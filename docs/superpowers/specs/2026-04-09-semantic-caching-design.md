# Semantic Caching for track_llm_call — Design Spec

> **Status:** Approved for implementation
> **Date:** 2026-04-09
> **Scope:** `track_llm_call` MCP tool + Worker analytics + dashboard

---

## Problem

`track_llm_call` records every LLM call as a unique event. Currently:
1. The dashboard "Cache Savings" KPI card shows **zero always** — the `cache_tokens` column exists in D1 and OTel already populates it, but `GET /v1/analytics/kpis` never queries it.
2. There is **no detection of repeated/duplicate LLM calls** — if an agent sends the same prompt 10 times in a day, Cohrint has no way to flag that waste.
3. `track_llm_call` MCP schema exposes no `cache_tokens` parameter — agents cannot report provider-native cache reads.

---

## Option Analysis

### Option A — Exact-Match Dedup via `prompt_hash`
Add SHA-256 fingerprint field. Worker checks KV before insert; flags duplicate if same hash seen in last 24h. Returns warning to agent.

- **Infra needed:** D1 migration (2 new columns), KV key `phash:{orgId}:{hash}`
- **Complexity:** 5 story points
- **Value:** Proactive — agent gets real-time duplicate warning

### Option B — Fix Cache Analytics (surface existing `cache_tokens`)
Query and expose `cache_tokens` already in D1. Fix broken KPIs endpoint. Show real cache hit rate and savings USD. Add `cache_tokens` to `track_llm_call` MCP schema.

- **Infra needed:** Zero schema changes
- **Complexity:** 3 story points
- **Value:** Immediate — fixes broken dashboard card, zero friction

### Option C — Semantic Proxy (Workers AI + Vectorize)
Embed prompts, match semantically similar calls in Vectorize, serve cached responses.

- **Infra needed:** Vectorize + Workers AI (both paid, not yet provisioned)
- **Architectural problem:** `track_llm_call` is called *after* the LLM — cannot return a cached response. Would require a separate `check_cache` pre-call tool and fundamental agent workflow changes.
- **Complexity:** 20+ story points
- **Decision:** **Deferred.** Ship Phase 1 (A+B) first, validate duplicate rate, then revisit.

---

## Recommendation: Phase B then A (combined MVP)

**Phase 1 — Option B (3 SP, 1 day):** Fix analytics. Zero risk, immediate value.
**Phase 2 — Option A (5 SP, 2-3 days):** Add prompt_hash dedup. Proactive waste detection.

This matches PRODUCT_STRATEGY.md roadmap: "SHA-256 exact → Workers AI embeddings → Vectorize".

---

## Phase 1 — Cache Analytics Fix

### Files to Change

| File | Change |
|------|--------|
| `vantage-worker/src/routes/analytics.ts` | Add `cache_tokens`, `cache_savings_usd`, `cache_hit_rate_pct` to KPIs query |
| `vantage-worker/src/routes/otel.ts` | Extract `MODEL_PRICES` to `lib/pricing.ts` (reuse in analytics) |
| `vantage-worker/src/lib/pricing.ts` | **New file** — shared pricing table + `estimateCacheSavings()` helper |
| `vantage-mcp/src/index.ts` | Add `cache_tokens` param to `track_llm_call` schema; add cache fields to `get_kpis` output |

### KPIs Endpoint Change

`GET /v1/analytics/kpis` response adds:
```json
{
  "cache_tokens_total": 1420000,
  "cache_savings_usd": 1.23,
  "cache_hit_rate_pct": 34.2
}
```

**Savings formula:** Per model: `savings = (cached_tokens / 1e6) × (input_price - cache_read_price)`
Computed in TypeScript using `MODEL_PRICES` after the D1 query (because rate varies per model, not expressible in SQL alone).

Query addition to `analytics.ts` line ~116:
```sql
COALESCE(SUM(cache_tokens), 0)           AS total_cache_tokens,
GROUP_CONCAT(model || ':' || COALESCE(cache_tokens,0)) AS cache_by_model
```

### `track_llm_call` Schema Addition

```typescript
cache_tokens: {
  type: 'number',
  description: 'Tokens served from provider native cache (Anthropic/OpenAI prompt caching). Reduces billed cost.'
}
```

The field already passes through `EventIn` to D1 — just missing from the MCP input schema.

### Dashboard Fix

`app.html:1626` currently uses hardcoded `$2.70/MTok` (Claude-only). Replace with:
```js
var cacheSavingsUsd = kpis.cache_savings_usd || 0;
var cacheHitPct = kpis.cache_hit_rate_pct || 0;
```
Source: the new `get_kpis` response fields.

---

## Phase 2 — Exact-Match Dedup Detection

### D1 Migration (`migrations/0007_prompt_hash.sql`)

```sql
ALTER TABLE events ADD COLUMN prompt_hash TEXT;
ALTER TABLE events ADD COLUMN cache_hit   INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_events_prompt_hash
  ON events(org_id, prompt_hash)
  WHERE prompt_hash IS NOT NULL;
```

### Files to Change

| File | Change |
|------|--------|
| `vantage-worker/src/types.ts` | Add `prompt_hash?: string`, `cache_hit?: number` to `EventIn` |
| `vantage-worker/src/routes/events.ts` | KV lookup before insert; KV write after; `cache_hit` in insert; `cache_warning` in response |
| `vantage-worker/src/routes/analytics.ts` | Add `duplicate_calls`, `wasted_cost_usd` to KPIs query |
| `vantage-mcp/src/index.ts` | Add `prompt_hash` to `track_llm_call` schema; parse `cache_warning` from response |

### KV Key Pattern

```
phash:{orgId}:{hash16}  →  { event_id, cost_usd, model, ts }
TTL: 86400s (24-hour rolling window)
```

### `POST /v1/events` Logic Addition

```
if body.prompt_hash:
  existing = KV.get(`phash:{orgId}:{hash}`)
  if existing:
    body.cache_hit = 1
    response.cache_warning = "Duplicate detected — identical prompt sent {N}m ago. Wasted: ${cost}"
  after insert:
    KV.put(`phash:{orgId}:{hash}`, { event_id, cost_usd, model, ts }, { expirationTtl: 86400 })
```

### `track_llm_call` New Parameter

```typescript
prompt_hash: {
  type: 'string',
  description: 'SHA-256 fingerprint of the prompt (first 16 hex chars). Compute: crypto.createHash("sha256").update(prompt).digest("hex").slice(0,16). Never send raw prompt text.'
}
```

### MCP Response Change

- No duplicate: `"✅ Tracked: {model} | {tokens}→{completionTokens} | ${cost}"`
- Duplicate: `"⚠️ Duplicate call detected — identical prompt sent {N}m ago. Wasted: ${wasted}. Consider caching the response client-side."`

### KPIs Query Addition

```sql
COALESCE(SUM(CASE WHEN cache_hit=1 THEN 1 ELSE 0 END), 0)         AS duplicate_calls,
COALESCE(SUM(CASE WHEN cache_hit=1 THEN cost_usd ELSE 0 END), 0)  AS wasted_cost_usd
```

---

## Phase 3 — Semantic Proxy (Deferred)

**Prerequisites before starting:**
1. Provision Vectorize + Workers AI bindings in `wrangler.toml`
2. Design `check_cache` pre-call MCP tool (separate from `track_llm_call`)
3. Validate duplicate call rate from Phase 2 data — if < 5%, skip Phase 3

**Rough design (for reference):**
- New MCP tool: `check_semantic_cache(prompt, model)` → `{ hit: bool, response?, similarity_score }`
- New MCP tool: `store_semantic_cache(prompt, response, model)` → void
- Vectorize namespace per org: `{orgId}-prompt-cache`
- Embedding model: `@cf/baai/bge-small-en-v1.5` (fastest, free tier friendly)
- Similarity threshold: 0.92 (tunable per org)

---

## Testing

### Phase 1 (Cache Analytics)
1. Send OTel payload with `cached_tokens: 500` for `claude-sonnet-4-6`
2. Call `GET /v1/analytics/kpis` — assert `cache_savings_usd > 0` and `cache_hit_rate_pct > 0`
3. Call MCP `get_kpis` — assert cache fields appear in Markdown table
4. Check dashboard "Cache Savings" card shows non-zero value

### Phase 2 (Dedup)
1. Compute `hash = sha256("explain caching").slice(0,16)`
2. POST `track_llm_call` with `prompt_hash: hash` — assert `cache_hit: false`
3. POST same hash again — assert `cache_hit: true`, response contains "Duplicate"
4. Query D1: `SELECT cache_hit FROM events WHERE prompt_hash = ?` → row 2 = 1
5. Call `get_kpis` — assert `wasted_cost_usd > 0`

### Test Suite
- New file: `tests/suites/36_semantic_cache/test_semantic_cache.py`
- Follows pattern from `tests/suites/17_otel/` (fixture-based, `chk()` + `assert`, poll-wait for D1 writes)
