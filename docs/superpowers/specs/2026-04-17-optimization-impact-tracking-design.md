# Optimization Impact Tracking

**Date:** 2026-04-17  
**Branch:** feat/cost-forecasting-widget  
**Approach:** Lightweight multiplier overlay (Approach A) — no schema migration, uses existing `tags` JSON column

## Problem

Cohrint calculates optimization impact at request time but never persists it, aggregates it, or surfaces it as a customer-facing multiplier. Customers have no way to see "how much has Cohrint actually saved me?"

Hardcoded hints like "10-30% savings" exist in the MCP tool but are not per-customer calculated. Cache savings USD is computed in analytics but never shown as a multiplier (e.g., "10x").

## Goals

1. **Per-call multipliers in MCP responses** — developers see inline improvement factors after each optimization
2. **Cumulative dashboard widget for admins** — CTOs/admins see aggregate savings with 2x/5x/10x multipliers across their team

## Non-Goals

- New DB tables or schema migrations
- Retroactive recalculation of historical events (only new events get tagged)
- Recommendation uptake tracking or A/B testing

---

## Architecture

### 1. MCP Tool Changes (`cohrint-mcp/src/index.ts`)

#### `optimize_prompt` response

Add an `optimization_impact` block to every response alongside the compressed prompt:

```ts
optimization_impact: {
  improvement_factor: 2.8,          // original_cost / compressed_cost
  tokens_saved: 546,
  cost_before_usd: 0.00254,
  cost_after_usd: 0.00090,
  compression_ratio_pct: 64.5,
  model_switch_multiplier: 8.0,     // null if user is already on cheapest viable model
  combined_multiplier: 22.4         // compression × model_switch (or just compression if no switch)
}
```

Human-readable summary line prepended to response:
```
✦ Prompt optimized — 2.8x cheaper (64% fewer tokens, 546 tokens saved)
Tip: switch to claude-haiku-4-5 for another 8x savings (combined: 22x)
```

**Multiplier calculation:**
- `improvement_factor = original_cost / compressed_cost` using current model pricing
- `model_switch_multiplier = current_model_cost_per_token / cheapest_viable_model_cost_per_token`
- `combined_multiplier = improvement_factor × model_switch_multiplier`
- All costs computed from existing `MODEL_PRICING` map in `index.ts`

#### `analyze_tokens` response

Add `model_multipliers` array showing cost ratio of each model vs the cheapest:

```ts
model_multipliers: [
  { model: "claude-opus-4-7",   cost_usd: 0.01500, multiplier: "1x (baseline)" },
  { model: "claude-sonnet-4-6", cost_usd: 0.00300, multiplier: "5x cheaper" },
  { model: "claude-haiku-4-5",  cost_usd: 0.00025, multiplier: "60x cheaper" }
]
```

#### `get_recommendations` response

Add `estimated_multiplier` to each tip:

```ts
{ tip: "Enable prompt caching", estimated_multiplier: "10x", basis: "cache_read_vs_input_price" }
{ tip: "Compress prompts with optimize_prompt", estimated_multiplier: "2-3x", basis: "avg_compression_ratio" }
{ tip: "Switch to claude-haiku-4-5 for simple tasks", estimated_multiplier: "8-60x", basis: "model_price_ratio" }
```

---

### 2. Backend: Persist to `tags` column

#### `POST /v1/optimizer/compress` (`cohrint-worker/src/routes/optimizer.ts`)

When compress is called, store optimization metadata in the event's `tags` JSON (merged with any existing tags):

```json
{
  "optimization": {
    "type": "compress",
    "improvement_factor": 2.8,
    "tokens_saved": 546,
    "cost_before_usd": 0.00254,
    "cost_after_usd": 0.00090,
    "compression_ratio_pct": 64.5
  }
}
```

Cache hit events already write `cache_hit: 1` — no change needed there. Cache savings are computed from the existing `estimateCacheSavings()` function.

#### `GET /v1/optimizer/impact` (new endpoint)

Aggregates from `tags` column and existing `events`/`cross_platform_usage` tables. Requires Bearer auth (same pattern as all other routes).

**Response:**
```json
{
  "period": "2026-04",
  "avg_improvement_factor": 4.2,
  "total_tokens_saved": 1200000,
  "total_cost_saved_usd": 847.20,
  "by_type": {
    "compress":     { "avg_factor": 2.8,  "event_count": 312, "cost_saved_usd": 124.40 },
    "cache":        { "avg_factor": 10.0, "event_count": 891, "cost_saved_usd": 680.50 },
    "model_switch": { "avg_factor": 8.0,  "event_count": 44,  "cost_saved_usd": 42.30  }
  },
  "per_developer": [
    { "email": "alice@co", "avg_factor": 12.0, "cost_saved_usd": 42.0,  "opportunity_usd": null },
    { "email": "carol@co", "avg_factor": 1.1,  "cost_saved_usd": 2.0,   "opportunity_usd": 89.0 }
  ],
  "monthly_trend": [
    { "month": "2026-01", "avg_factor": 1.1 },
    { "month": "2026-02", "avg_factor": 1.8 },
    { "month": "2026-03", "avg_factor": 2.9 },
    { "month": "2026-04", "avg_factor": 4.2 }
  ]
}
```

**`opportunity_usd` calculation:** developers with `cache_hit_rate < 20%` and `total_cost > $1` get `cost * 0.15` as opportunity (reuses existing executive dashboard logic).

**SQL approach:** JSON extract on `tags` column using SQLite's `json_extract(tags, '$.optimization.improvement_factor')`. Monthly trend derives from `cache_savings_usd` + compress tag aggregates grouped by `strftime('%Y-%m', datetime(created_at, 'unixepoch'))`.

---

### 3. Dashboard Widget (`cohrint-frontend/app.html`)

New **"Optimization Impact"** section added to the existing dashboard, calling `GET /v1/optimizer/impact`. Three sub-panels stacked vertically:

#### Panel 1 — Hero metric card
- **Large numbers:** `avg_improvement_factorX` (lime green), `$total_cost_saved_usd` (sky blue), human-readable `total_tokens_saved` (pink)
- **Category badges:** `💡 Prompt compression: 2.8x` · `⚡ Prompt caching: 10x` · `🔀 Model switching: 8x`
- **Period label:** "Cohrint Optimization Impact · [month year]"

#### Panel 2 — Monthly trend chart
- Chart.js bar chart, `monthly_trend` data, x-axis = month labels, y-axis = `avg_factor`
- Latest month highlighted in lime green, prior months in muted green
- No tooltips needed — values shown as labels above bars

#### Panel 3 — Developer leaderboard
- Sorted by `avg_factor` descending
- Green badge for high-factor devs (`12x`), red badge for low-factor devs (`1.1x`)
- Red-highlighted row shows `↑ $89 opportunity` with inline tip (e.g., "using opus for tasks haiku handles")
- Limited to top 10 + bottom 3 (worst performers)

**Loading state:** skeleton placeholders matching panel heights. **Empty state:** "No optimization data yet — use `optimize_prompt` or enable prompt caching to start tracking."

---

### 4. Optimizer Algorithm Improvements (`cohrint-mcp/src/index.ts`)

Two additions to the existing 5-layer compression pipeline (currently lines 230-262):

**Layer 6 — Strip redundant wrapper tags:**
- Pattern: `<context>plain text</context>`, `<input>plain text</input>`, `<text>plain text</text>`
- If the tag contains only plain text (no nested XML/JSON), strip the tags, keep the content
- Do NOT strip semantic tags like `<system>`, `<assistant>`, `<tool_result>`

**Layer 7 — Deduplicate cross-turn instructions:**
- If the same constraint appears verbatim (or near-verbatim, 90%+ overlap) in both system prompt and user turn, keep only the system prompt copy
- Requires the caller to pass `system_prompt` separately — add optional `system_prompt` param to `optimize_prompt`

These improvements push average compression from ~10-30% toward ~30-50% for typical developer prompts.

---

## Data Flow

```
Developer uses optimize_prompt MCP tool
  → MCP computes improvement_factor, returns optimization_impact block
  → MCP calls POST /v1/optimizer/compress with tags.optimization payload
  → Worker stores tags in events table

Admin opens dashboard
  → Frontend calls GET /v1/optimizer/impact
  → Worker aggregates tags JSON + existing cache_savings_usd
  → Returns avg_factor, trend, per-developer breakdown
  → Dashboard renders hero card + chart + leaderboard
```

---

## Error Handling

- If `tags` JSON is malformed on insert, log and skip (don't fail the compress request)
- If `json_extract` returns null (old events without tags), exclude from averages
- If `/v1/optimizer/impact` returns empty data, dashboard shows empty state (no fake numbers)
- MCP multiplier calculation: if `cost_before = 0` (free tier / zero-cost model), set `improvement_factor = 1.0` and omit the multiplier display

---

## Testing

- New test suite `tests/suites/46_optimizer_impact/` covering:
  - `POST /v1/optimizer/compress` stores correct tags
  - `GET /v1/optimizer/impact` aggregates correctly from seeded events
  - `GET /v1/optimizer/impact` returns empty state for org with no optimization events
  - Per-developer opportunity calculation matches executive dashboard logic
- MCP tool unit tests: `improvement_factor` calculation with known token/cost values
- Use DA45 seed state (`tests/artifacts/da45_seed_state.json`) as base org

---

## Files to Change

| File | Change |
|------|--------|
| `cohrint-mcp/src/index.ts` | Add `optimization_impact` to `optimize_prompt`; `model_multipliers` to `analyze_tokens`; `estimated_multiplier` to `get_recommendations`; layers 6+7 to compression pipeline |
| `cohrint-worker/src/routes/optimizer.ts` | Persist `tags.optimization` on compress; add `GET /v1/optimizer/impact` |
| `cohrint-worker/src/index.ts` | Register new `/v1/optimizer/impact` route |
| `cohrint-frontend/app.html` | Add Optimization Impact section with 3 sub-panels |
| `tests/suites/46_optimizer_impact/` | New test suite (3-5 test files) |
