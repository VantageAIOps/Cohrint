# VantageAI — Developer Admin Guide
**Version 1.0 · March 2026 · INTERNAL — NOT FOR PUBLIC DISTRIBUTION**

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [System Architecture](#2-system-architecture)
3. [Database Schema & Data Model](#3-database-schema--data-model)
4. [Authentication & Authorization System](#4-authentication--authorization-system)
5. [Event Ingest Pipeline](#5-event-ingest-pipeline)
6. [Analytics Engine](#6-analytics-engine)
7. [Rate Limiting Algorithm](#7-rate-limiting-algorithm)
8. [Real-Time Streaming (SSE)](#8-real-time-streaming-sse)
9. [Alert System](#9-alert-system)
10. [Email Infrastructure](#10-email-infrastructure)
11. [Admin & Team Management](#11-admin--team-management)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Client Types & Integration Patterns](#13-client-types--integration-patterns)
14. [CI/CD & Deployment Pipeline](#14-cicd--deployment-pipeline)
15. [Test Infrastructure](#15-test-infrastructure)
16. [Security Model](#16-security-model)
17. [Business Algorithms — Current & Research-Backed Future](#17-business-algorithms--current--research-backed-future)
18. [Pricing & Plan Logic](#18-pricing--plan-logic)
19. [Operational Runbook](#19-operational-runbook)
20. [Research References & Reading List](#20-research-references--reading-list)
21. [MCP Server — Tools Reference & Examples](#21-mcp-server--tools-reference--examples)
22. [Local Proxy Gateway — Privacy-First LLM Tracking](#22-local-proxy-gateway--privacy-first-llm-tracking)
23. [Claude Code Auto-Tracking](#23-claude-code-auto-tracking)
24. [SDK Privacy Modes](#24-sdk-privacy-modes)
25. [Cross-Platform OTel Collector (v2)](#25-cross-platform-otel-collector-v2)
26. [VantageAI CLI — AI Agent Wrapper](#26-vantageai-cli--ai-agent-wrapper)
27. [Security & Governance](#27-security--governance)

---

## 1. Product Overview

VantageAI is an **AI cost intelligence and observability platform**. It gives engineering teams real-time visibility into LLM API spending, token efficiency, model performance, and output quality through a two-line SDK integration.

### What It Does (One Paragraph)
An application integrates the VantageAI SDK (Python or JS). Every LLM API call the app makes is transparently intercepted; the SDK extracts cost, token, latency, and metadata from the response and POSTs it to `api.vantageaiops.com`. The Worker stores it in D1 (SQLite). The dashboard (`app.html`) polls or streams from the same API to render charts, KPI cards, and team breakdowns. Admins set budgets, alerts fire via Slack when thresholds are crossed, and team members each get scoped keys so they see only their team's data.

### Technology Stack

| Layer | Technology | Why |
|---|---|---|
| API Worker | Cloudflare Workers + Hono | Edge-globally-distributed, zero cold starts, TypeScript |
| Database | Cloudflare D1 (SQLite) | Serverless SQLite, no infra, free tier sufficient for MVP |
| Cache/Pub-Sub | Cloudflare KV | Rate limiting counters, SSE broadcast, alert throttle, session tokens |
| Frontend | Cloudflare Pages | Static hosting, global CDN, auto-deploys from `main` |
| Email | Resend API | Transactional email, 3k/month free, custom domain |
| SDK (Python) | `vantageaiops` on PyPI | OpenAI + Anthropic proxy wrappers |
| SDK (JS) | `vantageaiops` on npm | OpenAI + Anthropic proxy wrappers, streaming support |
| MCP Server | `vantage-mcp/` | VS Code, Cursor, Windsurf integration |
| CI/CD | GitHub Actions | Deploy on push to `main`, test on every branch |

---

## 2. System Architecture

> **Interactive Diagram:** [System Architecture (UI + Backend + Infrastructure)](https://excalidraw.com/#json=92A4NZAtAZvzmUbVg_nd6,M0575eSAO8Eh8Eo3AVOPxg) — open in Excalidraw to explore the full UI layer, API worker middleware pipeline, and data storage topology.

### 2.1 High-Level Flow

```
SDK / Direct API call
        │
        ▼
  Bearer vnt_... token
  POST /v1/events
        │
        ▼
┌─────────────────────────────────┐
│     Cloudflare Worker           │
│   api.vantageaiops.com          │
│                                 │
│  corsMiddleware → authMiddleware│
│       → rate limiter (KV)       │
│       → route handler           │
│                                 │
│  events.ts → D1 INSERT          │
│           → KV broadcast        │
└──────────┬──────────────────────┘
           │
    ┌──────┴──────┐
    │             │
   D1            KV
(events,       (rl:, stream:,
 orgs,          sse:, slack:,
 sessions,      alert:, recover:)
 members,
 budgets,
 alerts)
           │
    ┌──────┴──────┐
    │             │
Dashboard     SSE stream
(polling       GET /v1/stream/:orgId
 /analytics)   (KV polling every 2s)
```

### 2.2 Request Lifecycle

Every authenticated request goes through this pipeline:

```
1. CORS preflight check (corsMiddleware)
   → Return 204 with CORS headers if OPTIONS

2. Auth resolution (authMiddleware)
   a. Cookie path:  vantage_session → sessions table → org_id, role, member_id
   b. Bearer path:  Authorization: Bearer vnt_... → SHA-256 hash → orgs or org_members table
   → Set context vars: orgId, role, scopeTeam, memberId

3. Rate limit check (KV, per-org, per-minute window)
   → key: rl:{orgId}:{minuteBucket}
   → RATE_LIMIT_RPM env var (default: 1000)
   → 429 + Retry-After header if exceeded

4. Role guard (adminOnly or viewer block)

5. Route handler business logic

6. D1 read/write

7. KV side-effects (broadcast, cache)
```

### 2.3 Infrastructure Bindings (wrangler.toml)

```toml
# Worker name
name = "vantageai-api"
routes = [{ pattern = "api.vantageaiops.com/*", zone_name = "vantageaiops.com" }]

# D1 SQLite — binding name only; actual database_id in wrangler.toml (not committed)
binding = "DB"

# KV Namespace — binding name only; actual namespace id in wrangler.toml (not committed)
binding = "KV"

# Env vars (non-secret)
ENVIRONMENT = "production"
ALLOWED_ORIGINS = "https://vantageaiops.com,https://www.vantageaiops.com,https://vantageai.pages.dev"
RATE_LIMIT_RPM = "1000"

# Secrets (set via: wrangler secret put)
RESEND_API_KEY   — email sending
```

> **Note:** `database_id` and KV `id` are in `wrangler.toml` which is gitignored. Retrieve them from the Cloudflare dashboard or via `wrangler d1 list` / `wrangler kv namespace list`.

---

## 3. Database Schema & Data Model

VantageAI uses Cloudflare D1 (SQLite). Six tables.

### 3.1 `orgs` — One row per organization (account owner)

```sql
CREATE TABLE orgs (
  id            TEXT PRIMARY KEY,     -- slug: "mycompany", "mycompany-a3f2"
  api_key_hash  TEXT NOT NULL,         -- SHA-256 of raw key (never store raw)
  api_key_hint  TEXT,                  -- "vnt_mycompa..." (first 12 chars + ...)
  name          TEXT,
  email         TEXT UNIQUE,
  plan          TEXT DEFAULT 'free',   -- 'free' | 'team' | 'enterprise'
  budget_usd    REAL DEFAULT 0,        -- monthly spend limit
  created_at    INTEGER               -- unix timestamp
);
```

**Key design decisions:**
- `id` is a human-readable slug derived from org name/email via `toSlug()`. If collision, append 3-char hex suffix.
- API key format: `vnt_{orgId}_{16-hex-random}`. The org_id is embedded for fast routing (extract without DB lookup).
- Only the SHA-256 hash is stored. The raw key is shown exactly once at signup.
- `budget_usd = 0` means no budget set (not zero budget).

### 3.2 `org_members` — Team members under an org

```sql
CREATE TABLE org_members (
  id            TEXT PRIMARY KEY,     -- 8-char hex random
  org_id        TEXT NOT NULL,        -- FK → orgs.id
  email         TEXT NOT NULL,
  name          TEXT,
  role          TEXT NOT NULL,        -- 'admin' | 'member' | 'viewer'
  api_key_hash  TEXT NOT NULL,
  api_key_hint  TEXT,
  scope_team    TEXT,                 -- NULL = see all; 'backend' = scoped
  created_at    INTEGER
);
```

**RBAC model:**
- `owner` — only in `orgs` table, full access, can rotate root key
- `admin` — in `org_members`, can invite/remove/rotate members
- `member` — can ingest events, read analytics
- `viewer` — read-only (403 on POST /events)
- `scope_team` — non-null means this member's analytics are filtered to only that team's data

### 3.3 `sessions` — HTTP-only cookie sessions

```sql
CREATE TABLE sessions (
  token       TEXT PRIMARY KEY,       -- 64-char hex (32 random bytes)
  org_id      TEXT NOT NULL,
  role        TEXT NOT NULL,
  member_id   TEXT,                   -- NULL for owner sessions
  expires_at  INTEGER NOT NULL        -- unix timestamp, 30-day TTL
);
```

Sessions are created when a user POSTs their API key to `/v1/auth/session`. The raw session token is set as an `HttpOnly; SameSite=Lax; Secure` cookie. It is validated on every authenticated request via a D1 lookup with expiry check.

### 3.4 `events` — Core data table (every LLM call)

```sql
CREATE TABLE events (
  id                  TEXT NOT NULL,     -- event_id from SDK/client
  org_id              TEXT NOT NULL,
  provider            TEXT,              -- 'openai', 'anthropic', 'google'
  model               TEXT,              -- 'gpt-4o', 'claude-3-5-sonnet', etc.
  prompt_tokens       INTEGER DEFAULT 0,
  completion_tokens   INTEGER DEFAULT 0,
  cache_tokens        INTEGER DEFAULT 0,
  total_tokens        INTEGER DEFAULT 0,
  cost_usd            REAL DEFAULT 0,    -- total cost for this call
  latency_ms          INTEGER DEFAULT 0,
  team                TEXT,              -- 'backend', 'frontend', 'data'
  project             TEXT,
  user_id             TEXT,
  feature             TEXT,              -- 'search', 'summarize', 'chat'
  endpoint            TEXT,
  environment         TEXT DEFAULT 'production',
  is_streaming        INTEGER DEFAULT 0, -- boolean
  stream_chunks       INTEGER DEFAULT 0,
  trace_id            TEXT,              -- for agent span grouping
  parent_event_id     TEXT,              -- parent span in agent trace
  agent_name          TEXT,
  span_depth          INTEGER DEFAULT 0,
  tags                TEXT,              -- JSON object
  sdk_language        TEXT,
  sdk_version         TEXT,
  -- Quality scores (written async by LLM judge)
  hallucination_score REAL,
  faithfulness_score  REAL,
  relevancy_score     REAL,
  consistency_score   REAL,
  toxicity_score      REAL,
  efficiency_score    REAL,
  created_at          INTEGER NOT NULL,  -- unix timestamp
  PRIMARY KEY (id, org_id)              -- composite PK (dedup per org)
);
```

**Design notes:**
- `INSERT OR IGNORE` on `(id, org_id)` — duplicate event_id per org is silently dropped (idempotent ingest).
- `cost_usd` stores the resolved cost (accepting both `total_cost_usd` and `cost_total_usd` field names for SDK compat).
- Quality scores are null at insert time; written back asynchronously via `PATCH /v1/events/:id/scores`.
- `trace_id` + `parent_event_id` + `span_depth` enable agent call graph reconstruction.

### 3.5 `team_budgets` — Per-team monthly limits

```sql
CREATE TABLE team_budgets (
  org_id      TEXT NOT NULL,
  team        TEXT NOT NULL,
  budget_usd  REAL NOT NULL,
  updated_at  INTEGER,
  PRIMARY KEY (org_id, team)
);
```

### 3.6 `alert_configs` — Slack webhook + trigger config

```sql
CREATE TABLE alert_configs (
  org_id          TEXT PRIMARY KEY,
  slack_url       TEXT,
  trigger_budget  INTEGER DEFAULT 1,   -- fire at 80% + 100%
  trigger_anomaly INTEGER DEFAULT 1,   -- fire on cost spike
  trigger_daily   INTEGER DEFAULT 0,   -- daily summary
  updated_at      INTEGER
);
```

---

## 4. Authentication & Authorization System

### 4.1 API Key Format

```
vnt_{orgId}_{16-hex-random}
 ^     ^          ^
 |     |          └── 16 bytes of crypto.getRandomValues() = 128 bits of entropy
 |     └───────────── org slug embedded (for fast routing)
 └─────────────────── VantageAI namespace prefix
```

**Storage:** Only `SHA-256(rawKey)` is stored. The raw key is shown once and never retrievable.

**Hint:** First 12 characters + `...` → `vnt_mycompa...`. Used in UI to identify which key is active.

### 4.2 Auth Middleware Flow

```
Request arrives
      │
      ├── Has Cookie: vantage_session=TOKEN ?
      │       │
      │       ├── YES → SELECT from sessions WHERE token=? AND expires_at > now()
      │       │           → If found: set orgId, role, memberId, scopeTeam
      │       │           → If not found: fall through to Bearer check
      │       │
      │       └── NO → continue
      │
      ├── Has Authorization: Bearer vnt_... ?
      │       │
      │       ├── YES → Extract orgId from key format (parts[1])
      │       │       → SHA-256 hash the key
      │       │       → Check orgs table (owner key)
      │       │       → If not found, check org_members table (member key)
      │       │       → If not found in prod → 401
      │       │       → If not found in dev → auto-create org (dev convenience)
      │       │
      │       └── NO → 401 "Missing or invalid API key"
      │
      └── Rate limit check → 429 if exceeded
```

### 4.3 Role Hierarchy

```
owner (org owner — in orgs table)
  └── admin (org_members, role='admin')
       └── member (org_members, role='member')
            └── viewer (org_members, role='viewer', read-only)
```

Role checks:
- **`adminOnly` guard:** `role === 'owner' || role === 'admin'` — applied to member management, admin overview, team budgets
- **`viewer` block:** `role === 'viewer'` → 403 on POST /events (inline guard, not middleware)
- **`owner` only:** POST /rotate (only owner can rotate the root key)

### 4.4 Session Security Properties

| Property | Value | Reason |
|---|---|---|
| Cookie flags | `HttpOnly; SameSite=Lax; Secure` | XSS protection, CSRF protection, HTTPS-only |
| `Domain` | `vantageaiops.com` (prod only) | Shared across `api.` and `app.` subdomains |
| TTL | 30 days | Balance UX vs. security; owner can rotate key to invalidate all sessions |
| Token entropy | 256 bits (32 random bytes → 64 hex chars) | Unguessable |
| Storage | D1 `sessions` table | Not in KV — D1 provides consistent expiry and deletion |

### 4.5 Key Recovery Flow

```
User requests recovery
        │
        ▼
POST /v1/auth/recover { email }
        │
        ├── Always returns 200 (don't leak email existence)
        │
        ├── If email exists in orgs:
        │     → Generate 48-char hex token (24 random bytes)
        │     → KV.put("recover:{token}", {orgId, type:'owner'}, TTL=3600s)
        │     → Build redeem URL: api.vantageaiops.com/v1/auth/recover/redeem?token=...
        │     → Send email via Resend (keyRecoveryEmail template)
        │
        └── If email exists in org_members:
              → Send email with hint only (no one-click redeem — admin resets member keys)

Email link clicked
        │
        ▼
GET /v1/auth/recover/redeem?token=TOKEN
        │
        ├── "Peek" at KV (don't delete — Gmail/Outlook scanners follow GETs)
        ├── If valid → redirect to /auth?confirm_token=TOKEN (confirmation page)
        └── If invalid → redirect to /auth?recovery_error=expired

User clicks "Get new key" button on /auth?confirm_token=TOKEN
        │
        ▼
POST /v1/auth/recover/redeem { token }
        │
        ├── KV.get("recover:{token}") → verify
        ├── KV.delete("recover:{token}") → consume (single-use)
        ├── Generate new key → hash → UPDATE orgs SET api_key_hash=?, api_key_hint=?
        └── Return { ok: true, api_key: newKey, hint }
```

**Critical design:** GET does not consume the token. Email scanners (Gmail, Outlook Safe Links) follow GET links automatically. If we consumed on GET, the user's recovery link would be dead by the time they click it. Only POST consumes.

---

## 5. Event Ingest Pipeline

### 5.1 Single Event: POST /v1/events

```
POST /v1/events
  Body: EventIn (see types.ts)

1. authMiddleware (cookie or Bearer)
2. Viewer role block (403 if viewer)
3. checkFreeTierLimit()
   → SELECT COUNT(*) FROM events WHERE org_id=? AND created_at >= start_of_month
   → If free plan AND count+1 > 10,000 → 429 with upgrade message
4. Field normalization (buildInsertStmt):
   → Accept both SDK field names (usage_prompt_tokens) and canonical names (prompt_tokens)
   → Accept both cost_total_usd and total_cost_usd
   → timestamp: use event timestamp if provided, else Date.now()
5. INSERT OR IGNORE INTO events (idempotent on event_id+org_id)
6. broadcastEvent() → KV.put("stream:{orgId}:latest", payload, TTL=60s)
7. Return 201 { ok: true, id: event_id }
```

### 5.2 Batch Event: POST /v1/events/batch

```
POST /v1/events/batch
  Body: { events: EventIn[], sdk_version?, sdk_language? }

1–3. Same as single (batch size check: max 500 events)
4. Build array of D1PreparedStatement via buildInsertStmt()
5. c.env.DB.batch(stmts) — D1 batch API (single round-trip)
6. broadcastEvent() for last event in batch
7. Return 201 { ok: true, accepted: N, failed: M }
```

### 5.3 EventIn Field Normalization

The SDK versions differ in field naming. The ingest handler accepts all variants:

| Canonical field | SDK aliases accepted |
|---|---|
| `event_id` | `id` |
| `prompt_tokens` | `usage_prompt_tokens` |
| `completion_tokens` | `usage_completion_tokens` |
| `cache_tokens` | `usage_cached_tokens`, `cache_tokens` |
| `total_tokens` | `usage_total_tokens` (or prompt+completion sum) |
| `total_cost_usd` | `cost_total_usd`, `cost_total_cost_usd`, `cost_usd` |

### 5.4 Free Tier Enforcement

```
FREE_TIER_LIMIT = 10,000 events/month

Algorithm:
  SELECT COUNT(*) FROM events
  WHERE org_id = ? AND created_at >= strftime('%s', 'now', 'start of month')

  if plan == 'free' AND current_count + new_events > 10000:
    return 429 {
      error: "Free tier limit reached",
      events_used: N,
      events_limit: 10000,
      upgrade_url: "https://vantageaiops.com/signup.html"
    }
```

`start of month` in SQLite epoch math avoids timezone ambiguity since all timestamps are UTC.

### 5.5 Quality Scores: PATCH /v1/events/:id/scores

Quality scores are written back asynchronously after an LLM judge evaluates the event:

```
PATCH /v1/events/{event_id}/scores
{
  hallucination_score: 0.12,   // 0-1 (lower = better)
  faithfulness_score:  0.95,   // 0-1 (higher = better)
  relevancy_score:     0.88,
  consistency_score:   0.91,
  toxicity_score:      0.01,
  efficiency_score:    72.0    // 0-100 composite
}

→ UPDATE events SET ... WHERE id=? AND org_id=?
```

The LLM judge (Claude Opus 4.6 as described in PRODUCT_STRATEGY.md) computes these offline and calls back. Current dashboard shows `efficiency_score` averaged across the period (default: 74 when no scores exist).

---

## 6. Analytics Engine

All analytics queries share a `teamScope()` helper that appends `AND e.team = ?` when the authenticated member has a `scope_team` set. This is the data isolation mechanism for scoped members.

### 6.1 Endpoint Map

| Endpoint | Time window | Primary aggregation |
|---|---|---|
| `GET /v1/analytics/summary` | today / 30-day MTD / last-30-min session | cost, tokens, requests, budget% |
| `GET /v1/analytics/kpis?period=N` | N days (max 365) | totals + averages + streaming count |
| `GET /v1/analytics/timeseries?period=N` | N days (max 365) | daily cost/tokens/requests |
| `GET /v1/analytics/models?period=N` | N days | per-model breakdown (top 25 by cost) |
| `GET /v1/analytics/teams?period=N` | N days | per-team cost + budget% |
| `GET /v1/analytics/traces?period=N` | N days (max 30) | agent trace summary (top 100) |
| `GET /v1/analytics/cost?period=N` | N days + today | CI cost gate (total + today) |

### 6.2 Summary Calculation Detail

```sql
-- today_cost_usd / today_tokens / today_requests (last 24h)
SELECT SUM(cost_usd), SUM(total_tokens), COUNT(*)
FROM events WHERE org_id=? AND created_at >= (now - 86400) [AND team=? if scoped]

-- mtd_cost_usd (calendar month-to-date, last 30 days approximation)
SELECT SUM(cost_usd)
FROM events WHERE org_id=? AND created_at >= (now - 30*86400)

-- session_cost_usd (last 30 minutes — "current session" feel)
SELECT SUM(cost_usd)
FROM events WHERE org_id=? AND created_at >= (now - 1800)

-- budget_pct
IF scoped: SELECT budget_usd FROM team_budgets WHERE org_id=? AND team=?
ELSE:      SELECT budget_usd FROM orgs WHERE id=?
pct = round((mtd_cost / budget) * 100)
```

### 6.3 Team Analytics with Budget Join

```sql
SELECT
  COALESCE(e.team, 'unassigned') AS team,
  SUM(e.cost_usd)                AS cost_usd,
  COALESCE(b.budget_usd, 0)      AS budget_usd,
  ROUND(SUM(e.cost_usd) / NULLIF(b.budget_usd,0) * 100, 1) AS budget_pct
FROM events e
LEFT JOIN team_budgets b ON b.org_id = e.org_id AND b.team = e.team
WHERE e.org_id=? AND e.created_at >= ?
GROUP BY e.team
ORDER BY cost_usd DESC
```

Note: Always qualify `e.team` with table alias to avoid ambiguity with `team_budgets.team` in the JOIN.

### 6.4 Agent Tracing

```sql
SELECT
  trace_id,
  MIN(agent_name)  AS name,         -- first agent name in trace
  COUNT(*)         AS spans,         -- number of LLM calls in trace
  SUM(cost_usd)    AS cost,
  SUM(latency_ms)  AS latency,
  MAX(CASE WHEN parent_event_id IS NULL THEN 1 ELSE 0 END) AS has_root,
  MIN(created_at)  AS started_at
FROM events
WHERE org_id=? AND trace_id IS NOT NULL
GROUP BY trace_id
ORDER BY started_at DESC
LIMIT 100
```

Spans with `parent_event_id IS NULL` are root spans (entry points of an agent workflow). `span_depth` tracks nesting level for tree reconstruction in the UI.

### 6.5 CI Cost Gate: GET /v1/analytics/cost

Designed to be called in CI pipelines to enforce cost budgets:

```bash
# In GitHub Actions:
COST=$(curl -s -H "Authorization: Bearer $VANTAGE_KEY" \
  "https://api.vantageaiops.com/v1/analytics/cost?period=1" \
  | jq '.today_cost_usd')
if (( $(echo "$COST > 10.0" | bc -l) )); then
  echo "❌ Cost exceeded $10 today — failing pipeline"
  exit 1
fi
```

Response: `{ total_cost_usd, today_cost_usd, period_days }`

---

## 7. Rate Limiting Algorithm

### 7.1 Token Bucket via KV (Per-Org, Per-Minute Window)

```typescript
async function checkRateLimit(kv: KVNamespace, orgId: string, limitRpm: number): Promise<boolean> {
  const key   = `rl:${orgId}:${Math.floor(Date.now() / 60_000)}`;  // minute bucket
  const raw   = await kv.get(key);
  const count = raw ? parseInt(raw, 10) : 0;
  if (count >= limitRpm) return false;
  kv.put(key, String(count + 1), { expirationTtl: 70 });           // 70s TTL (slightly > 60s)
  return true;
}
```

**Algorithm:** Fixed window counter (not sliding window). Each minute gets its own KV key. Key expires after 70 seconds (60s window + 10s buffer for clock skew).

**Characteristics:**
- `RATE_LIMIT_RPM = 1000` (configurable via env var)
- Rate limit is **per-org** (shared across all members of the same org)
- Headers on 429: `Retry-After` (seconds until next minute boundary), `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`
- No deduction on KV write failure — non-blocking `kv.put` (fire-and-forget, best-effort)

**Known tradeoff:** Fixed window allows a "burst at boundary" where a client can send 1000 requests at 11:59:59 and 1000 more at 12:00:01. For the SDK use case (background telemetry), this is acceptable. Future: implement sliding window in Durable Objects.

---

## 8. Real-Time Streaming (SSE)

### 8.1 Architecture: Polling-Over-SSE

Cloudflare Workers have a 30-second wall-clock limit. True persistent WebSocket connections are possible but require Durable Objects. Current design: **polling-over-SSE** — simulates real-time using short-lived connections that auto-reconnect.

```
┌─────────────────────────────────────────────┐
│  GET /v1/stream/:orgId?sse_token=XYZ        │
│                                             │
│  1. Validate sse_token (KV, one-time use)   │
│  2. Open TransformStream                    │
│  3. Background loop (25s max):              │
│     while (Date.now() < deadline) {         │
│       raw = KV.get("stream:{orgId}:latest") │
│       if raw.ts > lastTs:                   │
│         sendEvent(raw)                      │
│         lastTs = raw.ts                     │
│       else:                                 │
│         sendPing()                          │
│       await sleep(2000)                     │
│     }                                       │
│  4. writer.close() → client auto-reconnects │
└─────────────────────────────────────────────┘
```

### 8.2 SSE Token Security

The SSE endpoint can't use `Authorization` headers (browser `EventSource` API doesn't support custom headers). Two auth methods:

1. **`?sse_token=`** (dashboard/browser): 32-char hex token, stored in KV with 120s TTL. Generated in `GET /v1/auth/session`, returned as `sse_token`. One-time use (deleted on connect). This prevents replay attacks from URL logs.

2. **`?token=vnt_...`** (SDK/direct callers): Legacy bearer token in query param. Accepted without KV lookup (SDK use case, less sensitive than browser).

### 8.3 KV Broadcast Channel

When an event is ingested: `KV.put("stream:{orgId}:latest", payload, TTL=60s)`. The SSE loop polls this key every 2 seconds and sends the event if `ts` is newer than the last sent `ts`.

**Implication:** Only the *latest* event per org is buffered. High-frequency orgs (many events per second) will see sampling, not every event. This is intentional — the live stream is a "heartbeat" view, not a complete event feed.

---

## 9. Alert System

### 9.1 Budget Alert Algorithm

```typescript
// Called from event ingest after free-tier check
async function maybeSendBudgetAlert(db, kv, orgId, mtdCost, budgetUsd) {
  const pct = (mtdCost / budgetUsd) * 100;

  let alertType = null;
  if (pct >= 100) alertType = 'budget_100';
  else if (pct >= 80) alertType = 'budget_80';
  if (!alertType) return;

  // Throttle: one alert per type per hour
  const throttleKey = `alert:${orgId}:${alertType}`;
  if (await kv.get(throttleKey)) return;  // already sent recently

  // Get Slack webhook from KV cache (set when /v1/alerts/slack is called)
  const slackUrl = await kv.get(`slack:${orgId}`);
  if (!slackUrl) return;

  await sendSlackMessage(slackUrl, budgetAlertPayload);

  // Throttle for 1 hour
  await kv.put(throttleKey, '1', { expirationTtl: 3600 });
}
```

**Trigger thresholds:** 80% and 100% of monthly budget.

**Throttling:** KV key `alert:{orgId}:{budget_80|budget_100}` with 1-hour TTL prevents alert spam.

**Webhook caching:** When a Slack webhook is configured (`POST /v1/alerts/slack/:orgId`), the URL is written to both D1 (source of truth) and KV `slack:{orgId}` with 1-hour TTL. Alert sends read from KV for speed; if KV is empty (cache miss), the alert is silently skipped (acceptable — non-critical path).

### 9.2 Alert Config Persistence

```sql
INSERT INTO alert_configs (org_id, slack_url, trigger_budget, trigger_anomaly, trigger_daily, updated_at)
VALUES (?, ?, ?, ?, ?, unixepoch())
ON CONFLICT(org_id) DO UPDATE SET
  slack_url       = excluded.slack_url,
  trigger_budget  = excluded.trigger_budget,
  ...
```

Upsert pattern — calling `/v1/alerts/slack` again updates the existing config.

---

## 10. Email Infrastructure

### 10.1 Resend API Integration

Email is sent via [Resend](https://resend.com). The `RESEND_API_KEY` is stored as a Cloudflare Worker secret (`wrangler secret put RESEND_API_KEY`). If not set, all email calls are silently no-ops — the product works without email, you just don't get invite/recovery emails.

### 10.2 Sender Fallback

```typescript
const senders = [
  'VantageAI <noreply@vantageaiops.com>',    // custom domain (requires DNS verification)
  'VantageAI <onboarding@resend.dev>',       // Resend shared domain (always works)
];
for (const from of senders) {
  const res = await fetch('https://api.resend.com/emails', { ... body: { from, ... } });
  if (res.ok) return;
  const body = await res.json();
  if (body.name !== 'validation_error') return; // non-domain error → don't retry
  // Domain not verified → retry with shared sender
}
```

If the custom domain isn't verified in Resend, it falls back to `onboarding@resend.dev`. Free tier: 3,000 emails/month.

### 10.3 Email Templates

**`memberInviteEmail`** — sent when an admin invites a member:
- Shows org name, inviter email, role, scope (if set)
- Displays the raw API key in a styled code block (shown once)
- Warning box: "This key will not be shown again"
- CTA button → deep-link to dashboard with `?api_key=...&org=...` prefilled

**`keyRecoveryEmail`** — sent for account recovery:
- For **owners**: one-click redeem button → redirects to `/auth?confirm_token=TOKEN`. Only works once, expires in 1 hour.
- For **members**: shows hint + "ask your admin to reissue your key" message. No self-service key rotation for members.

---

## 11. Admin & Team Management

### 11.1 Member Invite Flow

```
POST /v1/auth/members (adminOnly)
{
  email: "alice@company.com",
  name: "Alice",
  role: "member",          // 'admin' | 'member' | 'viewer'
  scope_team: "backend"    // optional — scoped data access
}

1. Validate email format
2. Check for duplicate (409 if already a member)
3. Generate: memberId (8-char hex), rawKey (vnt_...), hash it
4. INSERT INTO org_members
5. Fire-and-forget email invite (c.executionCtx.waitUntil)
6. Return { member_id, api_key (shown once), hint, role, scope_team }
```

### 11.2 Key Rotation

Owner key rotation (`POST /v1/auth/rotate`):
- Generates new key, stores new hash in `orgs`
- Old key immediately invalid (no grace period)
- All sessions remain valid (sessions are independent of the key)
- Note in response: "Update it everywhere before closing this response"

Member key rotation (`POST /v1/auth/members/:id/rotate`, admin only):
- Same as owner rotation but targets `org_members` table
- Sends email to member with new key

### 11.3 Admin Overview

`GET /v1/admin/overview` returns a combined payload:
```json
{
  "org": { "id", "name", "email", "plan", "budget_usd", "budget_pct", "mtd_cost_usd", "events_this_month", "events_limit" },
  "totals": { "total_cost_usd", "total_tokens", "total_requests", "avg_latency_ms" },
  "teams": [ { "team", "cost_usd", "tokens", "requests", "budget_usd", "budget_pct" } ],
  "members": [ { "id", "email", "name", "role", "scope_team", "api_key_hint" } ],
  "period_days": 30
}
```

This single call powers the admin panel in the dashboard (avoids multiple round-trips).

---

## 12. Frontend Architecture

### 12.1 File Structure

```
vantage-final-v4/
├── index.html        — Landing page (SEO, hero, pricing)
├── app.html          — Main SPA dashboard (auth-gated)
├── auth.html         — Sign-in page
├── signup.html       — Signup page
├── docs.html         — API documentation
├── calculator.html   — Cost calculator tool
├── sw.js             — Service Worker (offline capability)
├── manifest.json     — PWA manifest
├── _headers          — Cloudflare Pages headers (CSP, cache)
└── _redirects        — URL routing rules
```

### 12.2 `app.html` — SPA Architecture

Single-file SPA. No build step, no bundler. Raw HTML/CSS/JavaScript.

**State management:** Global variables + localStorage
- `window.vantage_session` — cached session JSON
- `localStorage.getItem('vantage_api_key')` — persisted key
- `localStorage.getItem('vantage_theme')` — dark/light preference

**Navigation pattern:**
```javascript
function nav(view) {
  // Hide all .view sections
  document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
  // Show target
  document.getElementById(`view-${view}`).style.display = '';
  // Load data for that view
  loadView(view);
}
```

**Auth gate:** On load, reads `vantage_session` cookie via `GET /v1/auth/session`. If 401, redirects to `/auth`.

**Theme system:**
```javascript
// Inline script in <head> (before CSS loads — prevents flash):
(function(){
  var t = localStorage.getItem('vantage_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

// CSS:
:root { --bg: #0d1318; --tx: #e8ecf1; ... }
[data-theme="light"] { --bg: #f0f2f5; --tx: #0d1318; ... }
```

### 12.3 Security Headers (`_headers`)

```
# Global
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()

# app.html — no caching (contains live session state)
Cache-Control: no-cache, no-store, must-revalidate
Content-Security-Policy:
  default-src 'self' 'unsafe-inline' [fonts, CDN]
  connect-src 'self' https://api.vantageaiops.com wss://api.vantageaiops.com [cloudflare]
  img-src 'self' data:
  worker-src 'self'
```

`'unsafe-inline'` is required because the SPA uses inline `<script>` tags. Future: move to nonce-based CSP when build tooling is introduced.

---

## 13. Client Types & Integration Patterns

> **Interactive Diagram:** [SDK Architecture (Python + JavaScript)](https://excalidraw.com/#json=Tv6Kcu6jof1GZlHAFQMP2,DT4JGkvQJqxQ1EL2IoudbA) — open in Excalidraw to see how the SDK proxy wrappers intercept LLM calls, extract metadata, and POST events to the VantageAI API.

VantageAI serves four distinct client archetypes. Each has different integration patterns, auth needs, and data characteristics.

---

### 13.1 Client Type A: Python Backend Engineer

**Profile:** Uses OpenAI/Anthropic in a Python Flask/FastAPI app. Wants cost tracking with zero overhead.

**Integration:**
```python
# pip install vantageaiops
from vantageaiops import OpenAIProxy

client = OpenAIProxy(api_key="vnt_myorg_...")
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
# SDK silently posts event to api.vantageaiops.com/v1/events
```

**What the SDK does:**
1. Wraps the OpenAI/Anthropic client
2. Intercepts the response
3. Extracts tokens, cost (from pricing table), latency
4. POSTs to VantageAI API in a background thread (non-blocking)

**Auth:** Bearer key, set as env var `VANTAGE_API_KEY`

**Data characteristics:** High volume, regular cadence, automated (no human in loop)

**Dashboard views used:** Cost, Tokens, Models, Performance

---

### 13.2 Client Type B: TypeScript/Node.js Backend or Frontend

**Profile:** Node.js API using OpenAI SDK. May be building a chat product with many users.

**Integration:**
```typescript
// npm install vantageaiops
import { OpenAIProxy } from 'vantageaiops';

const client = new OpenAIProxy({ apiKey: 'vnt_myorg_...' });
const response = await client.chat.completions.create({ ... });
```

**Special capability:** Streaming support. The JS SDK intercepts SSE chunks from OpenAI's streaming API, counts tokens (or estimates from chunk count), and reports them.

**Team tagging pattern:**
```typescript
const client = new OpenAIProxy({
  apiKey: 'vnt_myorg_...',
  defaultTags: { team: 'frontend', feature: 'chat', user_id: userId }
});
```

---

### 13.3 Client Type C: AI Agent / Multi-Agent System

**Profile:** LangGraph, AutoGen, CrewAI, or custom agent framework. Each LLM call is a span in a larger workflow.

**Integration (direct API):**
```python
import requests, uuid

trace_id = str(uuid.uuid4())

# Root span
requests.post("https://api.vantageaiops.com/v1/events", json={
  "event_id": str(uuid.uuid4()),
  "provider": "anthropic",
  "model": "claude-3-5-sonnet-20241022",
  "total_cost_usd": 0.0045,
  "total_tokens": 1200,
  "latency_ms": 2340,
  "trace_id": trace_id,
  "parent_event_id": None,   # root span
  "agent_name": "ResearchAgent",
  "span_depth": 0,
  "team": "ai-platform"
}, headers={"Authorization": "Bearer vnt_..."})

# Child span
requests.post("https://api.vantageaiops.com/v1/events", json={
  "event_id": str(uuid.uuid4()),
  "trace_id": trace_id,
  "parent_event_id": parent_id,
  "agent_name": "SummarizerAgent",
  "span_depth": 1,
  ...
})
```

**Dashboard views used:** Traces view (group all spans by trace_id, show total cost per agent run)

**Key concern:** Multi-agent workflows can generate surprise invoices. Set team budget alerts at 80%.

---

### 13.4 Client Type D: VS Code / Cursor / AI Coding Tool (MCP Client)

**Profile:** Developer using an AI coding assistant. Every code completion, chat, or inline edit is an LLM call. VantageAI MCP server surfaces cost data directly in the IDE.

**How it works:**
```
VS Code / Cursor / Windsurf
    │
    └── runs vantage-mcp server as a local process
            │
            └── MCP tool calls → GET /v1/analytics/* (Bearer auth)
                              → renders cost summary inline in chat
```

**MCP server tools exposed:**
- `get_cost_summary` — today/MTD cost
- `get_model_breakdown` — cost by model
- `check_budget` — budget % used
- `list_recent_events` — last N events

**Auth:** API key stored in VS Code settings or `.env`, passed to MCP server on startup

**Integration uniqueness:** This client never ingests events directly (the AI coding tools don't expose their underlying LLM calls to user code). MCP is purely a **read path** — it reads analytics for events that were ingested by other clients (the app's own AI backend).

---

### 13.5 Client Type E: Team Admin (Dashboard User)

**Profile:** CTO, Head of Engineering, or DevOps lead. Uses the web dashboard to monitor cost, set budgets, manage team members, configure alerts.

**Auth:** Cookie-based session (logs in via `/auth` with API key → session cookie set)

**Workflows:**
1. **Morning dashboard review:** Check today_cost_usd, budget_pct, any anomalies
2. **Team management:** Invite new engineer, set `scope_team` so they only see their team's data
3. **Budget control:** `PUT /v1/admin/team-budgets/backend` to set $500/month cap
4. **Slack alert setup:** Configure webhook in Settings → Alerts
5. **Cost investigation:** Drill into Models view to see which model is driving cost

---

### 13.6 Client Type F: CI/CD Pipeline (Cost Gate)

**Profile:** GitHub Actions, GitLab CI, or Jenkins pipeline. Checks AI cost after a test run to fail the pipeline if cost exceeded a threshold.

**Integration:**
```yaml
- name: Check AI cost gate
  run: |
    COST=$(curl -sf -H "Authorization: Bearer $VANTAGE_KEY" \
      "https://api.vantageaiops.com/v1/analytics/cost?period=1" \
      | jq '.today_cost_usd')
    echo "Today's AI cost: $COST"
    python -c "import sys; sys.exit(1 if float('$COST') > 5.0 else 0)"
```

**Auth:** API key stored as CI secret

**Key insight:** This client never looks at the dashboard. It's a binary gate — pass or fail.

---

## 14. CI/CD & Deployment Pipeline

### 14.1 Branch Strategy

```
main (production)
  └── v1.0, v1.1 (version branches — working branches)
        └── v1.0/P001-fix-nav (feature branches)
  └── backup/v1.0 (immutable snapshot, never modified)
```

**Rule:** Cloudflare always deploys from `main`. Version branches are purely a testing layer. Feature branches merge → version branch → all tests pass → auto-create backup → manual PR approval to main → CF deploys.

### 14.2 Workflow Overview

| Workflow | Trigger | Action |
|---|---|---|
| `deploy.yml` | Push to `main` (frontend changes) | Wrangler Pages deploy with 4-attempt retry |
| `deploy-worker.yml` | Push to `main` (worker changes) | TypeScript check → Wrangler worker deploy |
| `ci-version.yml` | Push to `v[0-9]*` branches | Full test suite → backup branch → open PR to main |
| `ci-feature.yml` | Push to `v*/P*` feature branches | Fast smoke tests only |
| `ci-test.yml` | Post-deploy on main / after version pipeline | Full test validation |
| `repo-backup.yml` | Push to main + daily 03:00 UTC | Mirror to Amanjain98/Vantage-AI + ZIP artifact |
| `setup-branch-protection.yml` | Manual dispatch | Apply GitHub branch protection rules (uses ADMIN_PAT) |

### 14.3 Deploy Retry Logic

Cloudflare Pages API occasionally returns 504 Gateway Timeout. Both deploy workflows use exponential backoff:

```bash
MAX_ATTEMPTS=4; DELAY=30
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if npm run deploy; then exit 0; fi
  sleep $DELAY; DELAY=$((DELAY * 2))  # 30s → 60s → 120s
done
exit 1
```

### 14.4 Required GitHub Secrets

| Secret | Purpose | Where to Get |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | Deploy to Pages/Workers | Cloudflare Dashboard → API Tokens |
| `CLOUDFLARE_ACCOUNT_ID` | Identify CF account | Cloudflare Dashboard → Account ID |
| `BACKUP_REPO_TOKEN` | Push mirror to Amanjain98/Vantage-AI | GitHub → Settings → Developer settings → PAT (classic, repo scope) |
| `ADMIN_PAT` | Apply branch protection rules | GitHub → Settings → Developer settings → PAT (classic, repo + admin:repo_hook scope) |

---

## 15. Test Infrastructure

> **Interactive Diagram:** [Testing Framework (15 Suites + CI/CD)](https://excalidraw.com/#json=Otd993P-wGAX_4ANOAbUC,KQGCEnuRZvRTr5XPgey_jA) — open in Excalidraw to see all 15 test suites organized by category (Functional, Performance, Security, Integration) with CI/CD pipeline and test infrastructure.

### 15.1 New Directory Structure (Post-Restructure)

```
tests/
├── config/settings.py          — All URLs/secrets from env vars
├── infra/                      — Logging, reporting, metrics, cleanup
│   ├── structured_logger.py    — NDJSON structured logging
│   ├── reporter.py             — Test result aggregation + HTML/JSON report
│   ├── metrics_collector.py    — Per-endpoint latency percentiles
│   ├── log_viewer.py           — CLI log filter tool
│   └── cleanup.py              — Remove artifacts older than N days
├── helpers/
│   ├── api.py                  — API helpers (signup_api, fresh_account, etc.)
│   ├── browser.py              — Playwright factory + console error collector
│   ├── data.py                 — rand_email, rand_org, rand_name, rand_tag
│   └── output.py               — ok/fail/warn/info/section/chk (test output)
├── suites/
│   ├── 01_api/                 — Auth API + all 28 endpoints
│   ├── 02_ui/                  — Navigation, dashboard UI, auth UI
│   ├── 03_user_individual/     — Signup, signin, recovery, onboarding, settings
│   ├── 04_user_team/           — Members, access control
│   ├── 05_user_org/            — Org admin, budget
│   ├── 06_stress/              — Burst, edge cases, oversized payloads
│   ├── 07_load/                — Concurrent, sustained throughput
│   ├── 08_latency/             — p50/p95/p99 SLA enforcement
│   ├── 09_rate_limiting/       — 429 behavior, throttle headers, org isolation
│   ├── 10_security/            — CORS, auth bypass, injection, cross-org
│   ├── 11_integrations/        — Slack, Teams, mail alerts
│   ├── 12_mcp/                 — VS Code MCP client simulation
│   └── 13_dashboard/           — Full E2E dashboard reliance
└── run_suite.py                — Category-based test orchestrator
```

### 15.2 Test Execution in CI

```yaml
# api-tests job (no browser)
python tests/run_suite.py --no-browser --clean

# browser-tests job (Playwright)
python tests/run_suite.py --category 02_ui --category 13_dashboard

# stress-tests job (nightly / extended)
python tests/run_suite.py --category 06_stress --category 07_load --category 08_latency

# security-tests job
python tests/run_suite.py --security  # includes 09_rate_limiting + 10_security

# integration-tests (only when secrets set)
python tests/run_suite.py --integrations  # includes 11_integrations + 12_mcp
```

### 15.3 Key Test Invariants

Every test file:
1. Creates its own isolated accounts via `signup_api()` (no shared state)
2. Uses `rand_email()` / `rand_org()` for uniqueness
3. Exits 0 (pass) or 1 (fail)
4. Does not clean up test data (D1 is the authoritative store; test orgs accumulate)

### 15.4 SLA Targets (Suite 08)

| Endpoint | p50 target | p95 target | p99 target |
|---|---|---|---|
| GET /health | < 100ms | < 300ms | < 500ms |
| POST /session | < 300ms | < 800ms | < 1500ms |
| GET /analytics/summary | < 500ms | < 1200ms | < 2500ms |
| POST /events | < 200ms | < 600ms | < 1200ms |

---

## 16. Security Model

### 16.1 API Key Security

- **Never stored in plaintext.** Only SHA-256 hash in DB. Attack vector: hash collision (computationally infeasible with SHA-256).
- **Format encoding:** `vnt_{orgId}_{hex}` — the org_id in the key allows fast routing (extract before DB lookup) but doesn't reduce entropy (the 16-hex-random component provides 128 bits of entropy).
- **One-way:** There is no "decrypt the key" path. Forgotten = must rotate.
- **Rotation is instant:** No grace period for the old key (unless you implement one). Update before rotating.

### 16.2 Cross-Org Data Isolation

All D1 queries include `WHERE org_id = ?` bound to the authenticated org_id. There is no query that returns data across multiple orgs.

For scoped members, `teamScope()` appends `AND team = ?` to every analytics query. A viewer with `scope_team='backend'` can never see `team='frontend'` data — enforced at query layer, not application layer.

### 16.3 CORS Policy

```typescript
ALLOWED_ORIGINS = "https://vantageaiops.com,https://www.vantageaiops.com,https://vantageai.pages.dev"

// Pattern matching supports wildcard suffix: "https://*.vantageaiops.com"
const isAllowed = allowed.includes(origin) ||
  allowed.some(p => p.endsWith('*') && origin.startsWith(p.slice(0, -1)));
```

The response always echoes the origin (not `*`) when credentials are involved, because `Access-Control-Allow-Credentials: true` requires a specific origin.

For the SSE endpoint, `Access-Control-Allow-Origin: *` is used (no credentials in SSE).

### 16.4 Content Security Policy

`app.html` CSP (`_headers`):
```
default-src 'self' 'unsafe-inline' [trusted CDNs]
connect-src 'self' https://api.vantageaiops.com wss://api.vantageaiops.com
```

`'unsafe-inline'` is a known weakness. Mitigated by the strict `connect-src` (scripts can't exfiltrate data to unknown origins). Full mitigation requires moving to a build step with nonce-based CSP.

### 16.5 Session Cookie Security

```
Set-Cookie: vantage_session=TOKEN; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000; Secure; Domain=vantageaiops.com
```

- `HttpOnly` — not accessible to JavaScript (XSS protection)
- `SameSite=Lax` — not sent on cross-site POST requests (CSRF protection)
- `Secure` — HTTPS only (production only; omitted in dev/preview environments)
- `Domain=vantageaiops.com` — shared across `api.` and `www.` subdomains

---

## 16.5 Token Optimizer

VantageAI includes an integrated **AI Token Optimizer** that reduces LLM costs by compressing prompts before they are sent to providers.

### Architecture

```
vantage_optimizer/          # Core Python module
├── compressor.py           # PromptCompressor (LLMLingua) + SimpleCompressor (regex fallback)
├── context_manager.py      # Conversation context management + summarization
├── utils.py                # TokenCounter, cost estimation, clean_text()
└── config.py               # OptimizerConfig dataclass
```

### How It Works

1. **Prompt Compression**: Removes filler words, redundant phrases, and extra whitespace while preserving semantic meaning. Advanced mode uses LLMLingua for ML-based compression.
2. **Context Summarization**: Long conversation histories are automatically summarized — older messages are compressed while recent messages remain verbatim.
3. **Token-Aware Optimization**: Tracks tokens per message and enforces configurable limits.

### SDK Integration

```python
import vantage
vantage.init(api_key="vnt_...", enable_optimizer=True, compression_rate=0.5)

from vantage.proxy.openai_proxy import OpenAI
client = OpenAI(api_key="sk-...")
# All subsequent calls are automatically optimized
```

### API Endpoints (Worker)

| Endpoint | Method | Description |
|---|---|---|
| `/v1/optimizer/compress` | POST | Compress a prompt |
| `/v1/optimizer/analyze` | POST | Count tokens + estimate cost |
| `/v1/optimizer/estimate` | POST | Compare costs across models |
| `/v1/optimizer/stats` | GET | Optimizer usage statistics |

### MCP Tools

The MCP server exposes 4 optimizer tools: `optimize_prompt`, `analyze_tokens`, `estimate_costs`, `compress_context`.

### Dashboard

The "Token Optimizer" view in the dashboard provides an interactive prompt compressor, cost estimator, and optimization KPIs.

---

## 17. Business Algorithms — Current & Research-Backed Future

### 17.1 Currently Implemented

#### Fixed-Window Rate Limiting
Simple, fast, KV-based. See §7. Tradeoff: allows burst at minute boundaries.

#### Free-Tier Enforcement
Calendar-month event count. `strftime('%s', 'now', 'start of month')` in SQLite. Clean reset at month boundary.

#### Budget Alert Throttling
KV-based deduplication with 1-hour TTL. Prevents alert fatigue.

#### Cost Attribution
Tag-based: events carry `team`, `project`, `feature`, `user_id`. Analytics GROUP BY these dimensions. No ML required — pure aggregation.

#### Quality Scoring
Offline LLM-as-judge (Claude Opus 4.6). Scores 6 dimensions. Written back async via PATCH. Current dashboard shows `efficiency_score` average.

---

### 17.2 Algorithms to Build Next

#### A. Anomaly Detection — Cost Spike Alert

**Problem:** A team accidentally puts an agent in an infinite loop at 2am. $500 in 10 minutes.

**Algorithm:** Simple Z-score on rolling 7-day hourly cost:

```python
def is_anomaly(current_hour_cost, historical_costs):
    mean = statistics.mean(historical_costs)
    std  = statistics.stdev(historical_costs)
    z_score = (current_hour_cost - mean) / max(std, 0.001)
    return z_score > 3.0  # 3-sigma threshold
```

**Implementation:** Run as a Cloudflare Cron Trigger (Workers scheduled events). Query hourly cost from D1, compute Z-score, send alert if `z_score > 3`.

**Research:** See [Twitter's AnomalyDetection package](https://github.com/twitter/AnomalyDetection) — STL decomposition for seasonal time series. For simple hourly cost, Z-score is sufficient. For daily patterns (business hours vs. nights), use ARIMA or Holt-Winters.

#### B. Sliding Window Rate Limiter (Durable Objects)

**Problem:** Fixed-window allows 2x burst at minute boundaries.

**Algorithm:** Sliding window log using Durable Objects:

```typescript
// Durable Object: RateLimiter
// Stores timestamps of recent requests in memory
class RateLimiter {
  timestamps: number[] = [];

  check(orgId: string, limitRpm: number): boolean {
    const now = Date.now();
    const windowStart = now - 60_000;

    // Remove expired timestamps
    this.timestamps = this.timestamps.filter(t => t > windowStart);

    if (this.timestamps.length >= limitRpm) return false;
    this.timestamps.push(now);
    return true;
  }
}
```

**Research:** [Cloudflare Blog: Rate limiting with Durable Objects](https://blog.cloudflare.com/durable-objects-easy-fast-correct-choose-three/) — Durable Objects provide strongly-consistent, geographically-distributed state suitable for rate limiting.

#### C. Cost Forecasting (Predictive Budget Alerts)

**Problem:** Budget is 60% used with 20 days left in the month. Will we exceed it?

**Algorithm:** Linear regression on daily MTD cost:

```python
import numpy as np

def forecast_month_end(daily_costs: list[float]) -> float:
    """Given daily cost series, project end-of-month total."""
    days = np.arange(len(daily_costs))
    slope, intercept = np.polyfit(days, daily_costs, 1)
    remaining_days = 30 - len(daily_costs)
    forecasted_additional = max(0, slope * remaining_days + intercept * remaining_days)
    return sum(daily_costs) + forecasted_additional
```

**Alert:** If `forecast_month_end(daily_costs) > budget * 0.9`, send "projected to exceed budget by month end" alert.

**Research:** [Meta's Prophet](https://facebook.github.io/prophet/) — handles seasonality, holidays, trend changes. For AI cost, weekly seasonality (business days vs. weekends) is the dominant signal.

#### D. Model Recommendation Engine

**Problem:** Customer is paying $0.03/1k tokens on GPT-4o. Claude Haiku does the same task for $0.00025/1k tokens.

**Algorithm:** Task classification → model matching:

```
Input: model=gpt-4o, feature=summarization, avg_tokens=500, quality_score=0.82

Step 1: Cluster by task type (NLP: classify feature tag into task category)
  "summarization" → "extraction_task"

Step 2: Find cheaper models with comparable quality for same task:
  SELECT model, AVG(cost_usd/total_tokens), AVG(faithfulness_score)
  FROM events WHERE feature=? AND faithfulness_score > 0.75
  ORDER BY cost_usd/total_tokens ASC
  LIMIT 5

Step 3: Compute potential savings:
  current_cpt = $0.03/1k
  recommended_cpt = $0.0003/1k
  monthly_calls = 50,000
  savings = (0.03 - 0.0003) * 50000 / 1000 = $1,485/month

Output: "Consider claude-haiku-4-5 for summarization tasks — 100x cheaper, similar quality"
```

**Research:** [LLM-as-Judge paper (Zheng et al. 2023)](https://arxiv.org/abs/2306.05685) — MT-Bench benchmark methodology for comparing model quality on specific task types. Foundation for building a task-specific model leaderboard from your own data.

#### E. Prompt Efficiency Score

**Problem:** Developer is sending 5000-token prompts when 500 tokens would do. Detecting verbose/inefficient prompting.

**Algorithm:**

```
efficiency_score = (information_density) × (task_completion_rate) × (cost_ratio)

where:
  information_density  = completion_tokens / prompt_tokens  (higher = more efficient)
  task_completion_rate = faithfulness_score (did the model answer the question?)
  cost_ratio           = 1 - (actual_cost / max_expected_cost_for_this_model)

Normalized 0-100 composite.
```

**Research:** [Prompt Compression papers](https://arxiv.org/abs/2310.05736) — LLMLingua framework compresses prompts 3-20x while preserving task performance. Recommend this to users with low efficiency scores.

#### F. Multi-Tenant Cost Allocation (Chargeback)

**Problem:** SaaS company wants to charge each of their customers for AI costs they incurred.

**Algorithm:** Tag events with `user_id`, aggregate by `user_id`, expose per-user cost via API.

```sql
SELECT user_id, SUM(cost_usd) AS cost, COUNT(*) AS requests
FROM events WHERE org_id=? AND created_at >= ?
GROUP BY user_id
ORDER BY cost DESC
```

**Business model opportunity:** VantageAI becomes the billing engine for AI-first SaaS companies. They use VantageAI to measure and invoice their own customers for AI usage.

**Research:** [FinOps Foundation: AI Cost Attribution](https://www.finops.org/) — chargeback/showback methodologies from cloud FinOps adapted to AI APIs.

---

### 17.3 Advanced Future Research Areas

#### LLM Output Quality Evaluation at Scale

Currently: LLM-as-judge (single model evaluation). Future: ensemble judging (multiple models, take majority) to reduce judge bias.

**Papers to read:**
- [AlpacaEval: An Automatic Evaluator for Instruction-following Language Models](https://arxiv.org/abs/2404.04475)
- [Judging the Judges: Evaluating Alignment and Vulnerabilities in LLMs-as-Judges](https://arxiv.org/abs/2406.12624)

#### Token-Level Cost Attribution

Currently: event-level cost (total cost per API call). Future: prompt-level attribution (which part of the prompt is causing cost — system prompt, user message, context injection?).

**Research:** [TokenBudget: Aligning Budget Awareness with LLMs](https://arxiv.org/abs/2402.03940)

#### Predictive Scaling / Capacity Planning

For enterprise customers running self-hosted models (Llama on GPU): predict when they need to add more GPU capacity based on request volume trends.

**Research:** [AWARE: Autoregressive Workload-Aware Resource Estimation](https://arxiv.org/abs/2312.03562)

---

## 18. Pricing & Plan Logic

### 18.1 Current Plans

| Feature | Free | Team ($99/mo) | Enterprise (custom) |
|---|---|---|---|
| Events/month | 10,000 | Unlimited | Unlimited |
| Members | — | Up to 10 | Unlimited |
| Team scoping | — | ✓ | ✓ |
| Budget alerts | — | ✓ | ✓ |
| Slack alerts | — | ✓ | ✓ |
| SSE live stream | ✓ | ✓ | ✓ |
| API cost gate | ✓ | ✓ | ✓ |
| SLA | — | — | 99.9% uptime |
| Support | Community | Email | Dedicated |

### 18.2 Plan Enforcement in Code

**Free tier:** `checkFreeTierLimit()` in events.ts. Returns 429 with `upgrade_url` when exceeded.

**Plan field:** `orgs.plan` (default: `'free'`). Checked in `checkFreeTierLimit()` — non-free plans bypass the event count check.

**Upgrading a user:** Currently manual — update `orgs.plan = 'team'` in D1 directly. Future: Stripe webhook sets plan field.

### 18.3 Budget Logic

`orgs.budget_usd = 0` means "no budget set" (not zero budget — users can't set $0 budget deliberately in current UI). Budget percent shown in KPI card: `(mtd_cost / budget) * 100`. If `budget = 0`, budget_pct returns 0 (no gauge shown).

### 18.4 OTel Pricing Engine (Auto Cost Estimation)

When AI tools send only token counts via OTel (no explicit cost metric), VantageAI auto-calculates `cost_usd` using its internal pricing table. This is critical for tools like GitHub Copilot and Gemini CLI that emit token counts but not costs.

**Pricing Table** (maintained in `vantage-worker/src/routes/otel.ts` → `MODEL_PRICES`):

| Model | Input ($/1M) | Output ($/1M) | Cache ($/1M) |
|---|---|---|---|
| claude-opus-4-6 | $15.00 | $75.00 | $1.50 |
| claude-sonnet-4-6 | $3.00 | $15.00 | $0.30 |
| claude-haiku-4-5 | $0.80 | $4.00 | $0.08 |
| gpt-4o | $2.50 | $10.00 | $1.25 |
| gpt-4o-mini | $0.15 | $0.60 | $0.075 |
| o1 | $15.00 | $60.00 | $7.50 |
| o3-mini | $1.10 | $4.40 | $0.55 |
| gemini-2.0-flash | $0.10 | $0.40 | $0.025 |
| gemini-1.5-pro | $1.25 | $5.00 | $0.31 |
| gemini-1.5-flash | $0.075 | $0.30 | $0.018 |

**Cost Formula:**
```
cost_usd = (uncached_input / 1M) × input_price + (cached_input / 1M) × cache_price + (output / 1M) × output_price
```

**Fuzzy Matching:** If exact model name not in table, the engine tries substring matching (e.g., `claude-sonnet-4-6-20260301` matches `claude-sonnet-4-6`). Unknown models return `cost_usd = 0`.

**Precedence:** If a tool sends both token counts AND an explicit cost metric, the explicit cost takes precedence (auto-estimation only fills in when `cost_usd == 0`).

---

## 19. Operational Runbook

### 19.1 How to Deploy

```bash
# Deploy frontend
cd vantageai
npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai --branch=main

# Deploy worker
cd vantage-worker
npm run deploy  # runs: wrangler deploy

# Both with retry (in CI)
# → handled by deploy.yml and deploy-worker.yml GitHub Actions
```

### 19.2 D1 Database Operations

```bash
# Run SQL directly on production D1
npx wrangler d1 execute vantage-events --command "SELECT COUNT(*) FROM events"

# Run migration
npx wrangler d1 execute vantage-events --file ./migrations/0001_add_field.sql

# Backup (export to local file)
npx wrangler d1 export vantage-events --output backup.sql

# Check table sizes
npx wrangler d1 execute vantage-events --command \
  "SELECT name, COUNT(*) FROM sqlite_master GROUP BY name"
```

### 19.3 KV Operations

```bash
# List all keys with prefix
npx wrangler kv key list --namespace-id=65b5609ad5b747c9b416632a19529f24 --prefix="rl:"

# Get a value
npx wrangler kv key get --namespace-id=65b5609ad5b747c9b416632a19529f24 "slack:myorg"

# Delete a stuck rate limit key (unblock an org)
npx wrangler kv key delete --namespace-id=... "rl:myorg:$(date +%s | awk '{print int($1/60)}')"

# Delete a stuck alert throttle (re-enable alerts)
npx wrangler kv key delete --namespace-id=... "alert:myorg:budget_80"
```

### 19.4 Common Incidents

**Incident: Org hitting rate limit unexpectedly**
1. Identify org: `wrangler kv key list --prefix="rl:"` to see which org has high counts
2. Check their request pattern: `SELECT COUNT(*), created_at/60 AS min FROM events WHERE org_id=? GROUP BY min ORDER BY min DESC LIMIT 10`
3. Temporary unblock: delete their current minute's KV key
4. Long-term: increase `RATE_LIMIT_RPM` for their org (future: per-org rate limits)

**Incident: Deploy 504 timeout**
- The deploy workflows automatically retry 4 times with exponential backoff (30s → 60s → 120s)
- If all 4 fail: manual retry via GitHub Actions UI → "Re-run failed jobs"
- If persistent: Cloudflare status page at `cloudflarestatus.com`

**Incident: Email not sending**
1. Check `RESEND_API_KEY` is set: `wrangler secret list` (shows names, not values)
2. Check Resend dashboard for delivery failures
3. Verify `vantageaiops.com` domain is verified in Resend
4. If domain not verified: emails fallback to `onboarding@resend.dev` automatically

**Incident: Analytics showing wrong data**
1. Check if `scope_team` is set on the member's key (scoped members see filtered data)
2. Check event timestamps — events use client-provided timestamp if `timestamp` field is set
3. Check `org_id` in `events` table matches expected org

**Incident: Session not persisting**
1. Verify `Domain=vantageaiops.com` is set on cookie (production only)
2. Verify request is HTTPS (Secure cookie flag)
3. Check `sessions` table for expired session: `SELECT expires_at FROM sessions WHERE token=?`
4. Session expiry is 30 days from creation, not 30 days from last use

### 19.5 D1 Schema Migration Pattern

D1 doesn't have a migration framework built-in. Current pattern:

```bash
# Create migration file
cat > migrations/0002_add_anomaly_scores.sql << 'EOF'
ALTER TABLE events ADD COLUMN anomaly_score REAL DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_events_anomaly ON events(org_id, anomaly_score) WHERE anomaly_score IS NOT NULL;
EOF

# Apply
npx wrangler d1 execute vantage-events --file ./migrations/0002_add_anomaly_scores.sql
```

Always use `IF NOT EXISTS` and `IF NOT EXISTS` for safety. D1 has no rollback — test on preview first.

### 19.6 SQLite Date Format (Critical)

All date comparisons in cross-platform queries use SQLite-native format: `YYYY-MM-DD HH:MM:SS` (space separator, no T, no Z). This is because `datetime('now')` in SQLite produces this format.

**Common mistake:** Using ISO 8601 (`2026-03-24T00:00:00Z`) in WHERE clauses — this breaks string-based comparisons because `T` sorts differently than space.

**Helper functions** in `crossplatform.ts`:
- `sqliteDateSince(days)` — returns `YYYY-MM-DD HH:MM:SS` for N days ago
- `sqliteTodayStart()` — returns `YYYY-MM-DD 00:00:00` for today
- `sqliteMonthStart()` — returns `YYYY-MM-01 00:00:00` for current month

**When writing new queries:** Always use these helpers or `datetime('now')` — never construct ISO dates manually.

---

## 20. Research References & Reading List

### 20.1 Foundational Papers — LLM Observability & Evaluation

| Paper | Why Read | Link |
|---|---|---|
| **MT-Bench & Chatbot Arena** (Zheng et al., 2023) | Foundation for LLM-as-judge evaluation — how we should evaluate model output quality | [arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685) |
| **LLMLingua: Compressing Prompts** (Jiang et al., 2023) | Core technique for prompt efficiency score feature | [arxiv.org/abs/2310.05736](https://arxiv.org/abs/2310.05736) |
| **AlpacaEval** (Li et al., 2024) | Automatic instruction-following evaluator — better judge than GPT-4 alone | [arxiv.org/abs/2404.04475](https://arxiv.org/abs/2404.04475) |
| **Judging the Judges** (Panickssery et al., 2024) | Why single LLM judges are biased — ensemble judging methodology | [arxiv.org/abs/2406.12624](https://arxiv.org/abs/2406.12624) |
| **RAGAS: Automated Evaluation of RAG** (Es et al., 2023) | Framework for evaluating RAG quality — relevancy, faithfulness, context recall | [arxiv.org/abs/2309.15217](https://arxiv.org/abs/2309.15217) |

### 20.2 AI Cost & FinOps

| Resource | Why Read | Link |
|---|---|---|
| **FinOps Foundation — AI/ML Cost Management** | Industry standard for AI cost governance and chargeback methodology | [finops.org](https://www.finops.org/topic/ai-ml/) |
| **The Economics of Large Language Models** (a16z, 2024) | Cost structure of LLM inference, why costs are falling, what this means for pricing | Search: "a16z economics of LLMs" |
| **AWS re:Invent: AI FinOps** (2024) | Practical cost allocation techniques adapted from cloud FinOps | YouTube: AWS re:Invent 2024 AI FinOps |
| **Token Economics: Pricing LLM APIs** (Anthropic, 2024) | Why per-token pricing exists, how providers think about cost | Anthropic Docs: Pricing |
| **Building Reliable LLM Applications** (Chip Huyen, 2023) | Chapter on operational reliability and cost — excellent mental model | "AI Engineering" book by Chip Huyen |

### 20.3 Anomaly Detection & Time Series

| Resource | Why Read | Link |
|---|---|---|
| **Twitter AnomalyDetection** | Open-source STL + EGAD for time series anomalies — adapt for cost spike detection | [github.com/twitter/AnomalyDetection](https://github.com/twitter/AnomalyDetection) |
| **Facebook Prophet** | Production-grade forecasting with trend + seasonality — use for budget forecasting | [facebook.github.io/prophet](https://facebook.github.io/prophet/) |
| **ARIMA for AI Cost Forecasting** | Statistical approach to forecasting time-series cost data | [otexts.com/fpp3](https://otexts.com/fpp3/) — Forecasting: Principles and Practice |

### 20.4 Multi-Agent Systems & Tracing

| Resource | Why Read | Link |
|---|---|---|
| **LangSmith** (LangChain) | How they instrument agent traces — study their trace model for VantageAI Traces feature | [smith.langchain.com](https://smith.langchain.com) |
| **OpenTelemetry for LLMs** (OpenLLMetry) | Open standard for LLM spans — we should be compatible | [github.com/traceloop/openllmetry](https://github.com/traceloop/openllmetry) |
| **ReAct: Reasoning + Acting** (Yao et al., 2022) | Foundation paper for tool-using agents — understand what we're tracing | [arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629) |
| **HumanEval + SWE-Bench** | How to benchmark coding agent quality — relevant for IDE/MCP integration | [github.com/openai/human-eval](https://github.com/openai/human-eval) |

### 20.5 Infrastructure & Architecture

| Resource | Why Read | Link |
|---|---|---|
| **Cloudflare Workers docs** | Our runtime — Workers, D1, KV, Durable Objects | [developers.cloudflare.com/workers](https://developers.cloudflare.com/workers/) |
| **D1 vs. Turso vs. PlanetScale** | When to migrate D1 to a different edge database | [benchmark.turso.tech](https://benchmark.turso.tech) |
| **Durable Objects Deep Dive** | For sliding window rate limiting and real-time features | [blog.cloudflare.com/introducing-workers-durable-objects](https://blog.cloudflare.com/introducing-workers-durable-objects/) |
| **Hono.js docs** | Our API framework — routing, middleware, context | [hono.dev](https://hono.dev) |

### 20.6 Competitive Landscape — Study These

| Tool | What to Study | Why |
|---|---|---|
| **Helicone** | Their prompt caching analytics, gateway architecture | Direct competitor, strong data model |
| **LangSmith** | Trace visualization, evaluation framework | Best-in-class trace UI |
| **Weights & Biases (W&B)** | Their "Prompts" product, how ML teams adopt observability | Enterprise adoption playbook |
| **Datadog APM** | How they monetize observability at scale, pricing model evolution | Strategic pricing model |
| **OpenAI Usage Dashboard** | What developers see today — understand the gap we fill | Their own product is our TAM |

### 20.7 Video Resources

| Video | Platform | Why |
|---|---|---|
| **"LLMOps: The Future of AI in Production"** — Simon Willison | YouTube / PyCon | Practical view of what devs actually need from LLM tooling |
| **"Anthropic on Claude's cost-efficiency"** — Amanda Askell | YouTube | How Anthropic thinks about token efficiency — insight for pricing features |
| **"Building AI Products: Cost vs. Quality"** — a16z | YouTube | VC perspective on where AI cost intelligence fits in the stack |
| **"Scaling ML Systems"** — Chip Huyen (Stanford CS329S) | YouTube | Full course on ML systems including cost and observability |
| **"FinOps for AI"** — CloudFest 2024 | YouTube | Cloud cost practitioners adapting to AI — your enterprise customer's mindset |
| **"OpenTelemetry + LLMs"** — KubeCon 2024 | YouTube | How the observability community is standardizing on LLM tracing |

### 20.8 Communities & Newsletters to Follow

| Resource | Type | Focus |
|---|---|---|
| **The Batch** (deeplearning.ai) | Newsletter | AI industry news, practical ML |
| **LLM Observability Slack** (traceloop.com) | Community | OpenLLMetry users, LLM ops practitioners |
| **Latent Space podcast** | Podcast | AI engineering deep dives |
| **Simon Willison's Weblog** | Blog | Practical LLM use cases, prompt engineering |
| **FinOps Foundation** | Community | Cloud/AI cost management professionals |
| **MLOps.community** | Slack/Newsletter | ML practitioners, production AI |

---

## Quick Reference Card

### API Key Format
`vnt_{orgId}_{16-hex-random}` — 128-bit entropy, SHA-256 hashed for storage

### Role Hierarchy
`owner` > `admin` > `member` > `viewer`

### Free Tier
10,000 events/calendar-month per org

### Rate Limit
1,000 requests/minute/org (configurable via `RATE_LIMIT_RPM`)

### Session TTL
30 days from creation (not from last use)

### SSE Token TTL
120 seconds (one-time use, generated per `GET /v1/auth/session`)

### Recovery Token TTL
3,600 seconds (1 hour, single-use via POST only)

### Batch Max Size
500 events per `POST /v1/events/batch`

### Budget Alert Thresholds
80% and 100% of monthly budget, throttled to once per hour per threshold

### D1 Database ID
`a1301c2a-19bf-4fa3-8321-bba5e497de10`

### KV Namespace ID
`65b5609ad5b747c9b416632a19529f24`

### Workers Route
`api.vantageaiops.com/*` → zone `vantageaiops.com`

### SSE Architecture
Polling-over-SSE: 2s poll interval, 25s max connection, auto-reconnect

---

---

## 21. MCP Server — Tools Reference & Examples

The VantageAI MCP Server exposes all analytics and optimization tools to AI coding assistants (Claude Desktop, Cursor, Windsurf, VS Code Copilot, Cline). Once configured, your AI assistant can query costs, track calls, optimize prompts, and check budgets — all from natural language.

### 21.1 Setup

Add to your `.mcp.json` (Claude Desktop) or IDE MCP config:

```json
{
  "mcpServers": {
    "vantage": {
      "command": "npx",
      "args": ["-y", "vantageaiops-mcp"],
      "env": {
        "VANTAGE_API_KEY": "vnt_yourorg_abc123def456"
      }
    }
  }
}
```

**Environment variables:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VANTAGE_API_KEY` | Yes | — | Your Vantage API key (`vnt_...`) |
| `VANTAGE_API_BASE` | No | `https://api.vantageaiops.com` | Custom API endpoint |
| `VANTAGE_ORG` | No | Parsed from key | Override org ID |

### 21.2 Analytics Tools (require API key + real data)

#### `get_summary` — Quick cost overview

**When to use:** Start of any session to understand current spend status.

**Example prompt:**
> "How much have I spent on LLMs today?"

**What it returns:**

| Metric | Value |
|--------|-------|
| MTD Spend | $45.23 |
| Today Spend | $3.87 |
| Today Requests | 1,234 |
| Today Tokens | 2,450,000 |
| Session Spend (30 min) | $0.42 |
| Budget Used | 45.2% |

---

#### `get_kpis` — Detailed KPI metrics

**When to use:** Weekly reviews, standup prep, or when you need latency/efficiency data.

**Example prompt:**
> "Give me the full KPI breakdown for our AI usage"

**What it returns:** Total cost, total tokens, total requests, avg latency, efficiency score, streaming request count.

---

#### `get_model_breakdown` — Cost per model

**When to use:** Identify which models are costing the most, find optimization opportunities.

**Example prompts:**
> "Which model is our most expensive? Show me model breakdown for the last 7 days"

> "Compare GPT-4o vs Claude Sonnet costs this month"

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | number | 30 | Look-back window (1-365) |

**Sample output:**

| Model | Provider | Cost | Requests | Avg Latency |
|-------|----------|------|----------|-------------|
| gpt-4o | openai | $32.45 | 8,234 | 1,230ms |
| claude-sonnet-4-6 | anthropic | $12.18 | 3,456 | 890ms |
| gpt-4o-mini | openai | $0.87 | 15,678 | 340ms |

---

#### `get_team_breakdown` — Cost per team

**When to use:** Chargeback reporting, finding which team/feature drives the most spend.

**Example prompts:**
> "Show me cost breakdown by team for the last 30 days"

> "Which feature is burning through our budget?"

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `days` | number | 30 | Look-back window (1-365) |

---

#### `check_budget` — Budget status

**When to use:** Before launching expensive batch jobs, during sprint planning, or when you suspect overspend.

**Example prompts:**
> "Are we within budget this month?"

> "How much budget do we have left?"

**Sample output:**

| | |
|-|-|
| MTD Spend | $45.23 |
| Budget | $100.00 |
| Used | 45.2% |
| Remaining | $54.77 |

---

#### `get_traces` — Agent call traces

**When to use:** Debug multi-step agent workflows, find expensive agent chains.

**Example prompts:**
> "Show me the last 5 agent traces"

> "Which agent trace was most expensive?"

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | number | 10 | Number of traces (1-50) |

**Sample output:**

| Trace ID | Spans | Total Cost | Agent |
|----------|-------|------------|-------|
| abc123def456... | 4 spans | $0.0342 | code-review |
| fed987cba654... | 7 spans | $0.1205 | research-agent |

---

#### `get_cost_gate` — CI/CD budget gate

**When to use:** In CI pipelines before merging, automated budget checks.

**Example prompts:**
> "Run the cost gate check for today"

> "Can we merge? Check if we're within budget this week"

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `period` | string | `today` | `today`, `week`, or `month` |

**Sample output:**
```
🚦 CI Cost Gate — ✅ PASSED
Period: today | Spend: $3.87 | Budget: $50.00 | Status: Within budget
```

---

#### `track_llm_call` — Manual event logging

**When to use:** When your LLM calls aren't going through the SDK proxy (e.g., direct API calls, third-party tools).

**Example prompt:**
> "Track this: I just used GPT-4o, 1500 input tokens, 800 output tokens, cost $0.023, took 1200ms, team backend"

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | e.g., `gpt-4o`, `claude-sonnet-4-6` |
| `provider` | string | Yes | `openai`, `anthropic`, `google`, etc. |
| `prompt_tokens` | number | Yes | Input token count |
| `completion_tokens` | number | Yes | Output token count |
| `total_cost_usd` | number | Yes | Cost in USD |
| `latency_ms` | number | No | End-to-end latency |
| `team` | string | No | Team/feature name |
| `environment` | string | No | `production`, `staging`, `development` |
| `trace_id` | string | No | For grouping multi-step agent calls |
| `span_depth` | number | No | Depth in agent call tree (0 = root) |
| `tags` | object | No | Arbitrary key-value tags |

**Important:** This is the only MCP tool that writes data. All other tools are read-only.

---

### 21.3 Optimizer Tools (work offline — no API key needed)

These tools run entirely locally with no network calls. They're useful for reducing costs before making LLM calls.

#### `optimize_prompt` — Compress a prompt

**When to use:** Before sending a large prompt to an expensive model.

**Example prompt:**
> "Optimize this prompt for cost: 'I would like you to please analyze the following code and could you please provide suggestions for improvement. It is important to note that the code should be maintainable and readable. Please kindly review each function.'"

**What it does:**
1. Removes filler words ("I would like you to", "please kindly", "it is important to note")
2. Deduplicates repeated sentences
3. Compresses whitespace
4. Shows token savings and cost comparison
5. Suggests the cheapest model for the task

**Sample output:**

| Metric | Before | After | Saved |
|--------|--------|-------|-------|
| Tokens | 52 | 18 | 34 (65%) |
| Est. cost | $0.000260 | $0.000090 | $0.000170 |

---

#### `analyze_tokens` — Count tokens and estimate cost

**When to use:** Before deciding which model to use, or to understand why a call was expensive.

**Example prompts:**
> "How many tokens is this text and what would it cost on GPT-4o vs Claude?"

> "Analyze this prompt — how much would 500 output tokens cost?"

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | Yes | Text to analyze |
| `model` | string | No | Model to price against (default: `gpt-4o`) |
| `output_tokens` | number | No | Expected output tokens (default: same as input) |

---

#### `estimate_costs` — Compare costs across all models

**When to use:** Choosing the right model for a task, cost planning.

**Example prompt:**
> "Compare the cost of this prompt across all models: [paste your prompt]"

**What it returns:** Cost comparison across all 22 supported models (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral) sorted cheapest first, with savings vs most expensive.

---

#### `compress_context` — Fit conversation into token budget

**When to use:** Long conversations approaching context limits, before summarizing history.

**Example prompt:**
> "Compress this conversation to fit within 4000 tokens"

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `messages` | array | Yes | Array of `{role, content}` messages |
| `max_tokens` | number | No | Token budget (default: 4000) |

**What it does:** Keeps recent messages intact, summarizes/truncates older ones to fit within budget.

---

#### `find_cheapest_model` — Model recommendation

**When to use:** Choosing a model for a new feature or batch job.

**Example prompts:**
> "What's the cheapest frontier-tier model for 2000 input and 500 output tokens?"

> "Find me the cheapest Anthropic model for my use case"

**Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `input_tokens` | number | Yes | Expected input tokens |
| `output_tokens` | number | Yes | Expected output tokens |
| `tier` | string | No | `frontier`, `mid`, `budget`, `reasoning` |
| `provider` | string | No | Filter by provider |

---

### 21.4 MCP Workflow Examples

#### Daily Cost Check Workflow
```
You: "Good morning. How's our AI spend looking?"
→ MCP calls: get_summary
→ Returns: MTD $45, today $3.87, budget 45% used

You: "Which model is driving the most cost?"
→ MCP calls: get_model_breakdown (days=7)
→ Returns: GPT-4o at $32.45, then Claude Sonnet at $12.18

You: "Can we switch to a cheaper model for the search feature?"
→ MCP calls: find_cheapest_model (input_tokens=2000, output_tokens=500, tier=mid)
→ Returns: gpt-4o-mini at $0.0006 vs gpt-4o at $0.0100 — save 94%
```

#### Pre-Merge CI Gate Workflow
```
You: "I'm about to merge this PR. Are we within budget?"
→ MCP calls: get_cost_gate (period=today)
→ Returns: ✅ PASSED — $3.87 of $50 budget used

You: "What about for the week?"
→ MCP calls: get_cost_gate (period=week)
→ Returns: ⚠️ $42 of $50 — approaching limit
```

#### Prompt Optimization Workflow
```
You: "This prompt is too expensive. Optimize it: [paste 500-word prompt]"
→ MCP calls: optimize_prompt (prompt=..., model=gpt-4o)
→ Returns: 180 → 95 tokens (47% saving), optimized text, tips

You: "What would it cost across different models?"
→ MCP calls: estimate_costs (prompt=optimized_text)
→ Returns: Table of all 22 models sorted by cost

You: "Use gpt-4o-mini then. Track this call when it runs."
→ (SDK auto-tracks if using proxy, or user calls track_llm_call manually)
```

#### Agent Debugging Workflow
```
You: "My agent workflow is too expensive. Show me the traces."
→ MCP calls: get_traces (limit=5)
→ Returns: 5 traces with span count and total cost

You: "The research-agent trace with 7 spans costs $0.12. Break it down by team."
→ MCP calls: get_team_breakdown (days=1)
→ Returns: research team at $0.45 today, backend at $0.12
```

---

## 22. Local Proxy Gateway — Privacy-First LLM Tracking

### 22.1 The Problem

Traditional LLM observability requires routing API keys and prompts through a third-party server. This creates security concerns:
- Your LLM API keys pass through external infrastructure
- Your prompts (which may contain PII, business logic, code) are stored externally
- Compliance teams may block external data routing

### 22.2 The Solution: Local Proxy

The VantageAI Local Proxy runs **on the client's machine** (localhost). It:

1. Intercepts LLM API calls locally
2. Forwards them directly to OpenAI/Anthropic/Google using **your keys**
3. Extracts **only statistics** (tokens, cost, latency, model, status code)
4. Strips ALL sensitive data (prompts, responses, API keys)
5. Sends only anonymized stats to the VantageAI dashboard

```
Your App → localhost:4891 → Real LLM API (OpenAI/Anthropic)
                ↓
        Extract stats locally
                ↓
        Strip ALL sensitive data
                ↓
        Send ONLY numbers → api.vantageaiops.com/v1/events
```

### 22.3 What Stays Local vs What Is Sent

| Stays on your machine (NEVER sent) | Sent to VantageAI dashboard |
|---|---|
| Your LLM API keys (OpenAI, Anthropic, etc.) | Model name (e.g., `gpt-4o`) |
| Full prompt text and content | Provider (e.g., `openai`) |
| Full response text and content | Token counts (prompt, completion) |
| System prompts | Calculated cost in USD |
| PII, user data, business logic in prompts | Latency in milliseconds |
| | HTTP status code |
| | Team and environment tags |

### 22.4 Privacy Levels

| Level | Text | Prompt Hash | Use Case |
|-------|------|-------------|----------|
| `strict` (default) | No text at all | No | Maximum privacy, compliance-sensitive environments |
| `standard` | No text | SHA-256 hash (non-reversible) | Dedup detection without exposing content |
| `relaxed` | First 100 chars | Yes | Internal debugging (NOT for production) |

### 22.5 Setup & Usage

#### Install and run:
```bash
# Via npx (no install needed)
VANTAGE_API_KEY=vnt_yourorg_abc123 npx vantageai-local-proxy

# Or install globally
npm install -g vantageai-local-proxy
vantage-proxy --api-key vnt_yourorg_abc123 --privacy strict
```

#### Point your LLM client to the local proxy:

**OpenAI (Python):**
```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-real-key",          # stays local
    base_url="http://localhost:4891/v1"   # routes through local proxy
)

# Every call is now auto-tracked — stats only go to dashboard
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**OpenAI (JavaScript):**
```javascript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-your-real-key",             // stays local
  baseURL: "http://localhost:4891/v1",    // routes through local proxy
});

const response = await client.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "Hello!" }],
});
```

**Anthropic (Python):**
```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-ant-your-real-key",
    base_url="http://localhost:4891"
)

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}]
)
```

#### CLI Options:

| Flag | Env Var | Default | Description |
|------|---------|---------|-------------|
| `--api-key` | `VANTAGE_API_KEY` | — | Your Vantage key (required) |
| `--port` | `VANTAGE_PROXY_PORT` | `4891` | Local proxy port |
| `--privacy` | `VANTAGE_PRIVACY` | `strict` | Privacy level |
| `--team` | `VANTAGE_TEAM` | — | Team tag for all events |
| `--env` | `VANTAGE_ENV` | `production` | Environment tag |
| `--api-base` | `VANTAGE_API_BASE` | `https://api.vantageaiops.com` | Vantage API endpoint |
| `--debug` | `VANTAGE_DEBUG` | `false` | Enable debug logging |
| `--redact-models` | — | `false` | Redact model names to generic tiers |
| `--batch-size` | — | `20` | Stats batch size |
| `--flush-interval` | — | `5000` | Flush interval in ms |

#### Verify privacy:
```bash
# Check what data the proxy sends
curl http://localhost:4891/privacy

# Health check
curl http://localhost:4891/health
```

### 22.6 Security Guarantees

1. **API keys are never forwarded to VantageAI** — they're used locally to call the real LLM API
2. **Prompts/responses are sanitized immediately** — text is stripped before queuing, never lingers in memory
3. **The proxy validates its own output** — `assertNoSensitiveData()` checks for API key patterns in sanitized events
4. **No external dependencies for privacy logic** — sanitization runs entirely in-process
5. **Open source** — audit the `privacy.ts` file yourself

---

## 23. Claude Code Auto-Tracking

### 23.1 Overview

Claude Code writes every session to local JSONL files at `~/.claude/projects/{project-slug}/{session-uuid}.jsonl`. Each assistant message in these files contains the full token breakdown (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) and the model used.

The auto-tracking system uses two mechanisms:

1. **Stop hook** — a Node.js script registered in `~/.claude/settings.json` that runs after every Claude Code response, reads new turns from the JSONL file, and uploads them to `POST /v1/events/batch`.
2. **Backfill scan** — `vantage-proxy scan --tool claude-code --push` reads all historical JSONL sessions and uploads them in bulk.

Both use a shared dedup state file at `~/.claude/vantage-state.json` to prevent double-uploads.

### 23.2 JSONL File Format

**Path:** `~/.claude/projects/{slug}/{uuid}.jsonl`

**Slug algorithm:** Replace all non-alphanumeric characters with `-`. Example:
```
/Users/aman/Documents/my project  →  -Users-aman-Documents-my-project
```

**Assistant message entry (relevant fields):**
```json
{
  "type": "assistant",
  "uuid": "abc-123",
  "sessionId": "session-xyz",
  "timestamp": "2026-04-05T14:00:00.000Z",
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 3200,
      "output_tokens": 180,
      "cache_read_input_tokens": 6400,
      "cache_creation_input_tokens": 1100
    }
  }
}
```

### 23.3 Cost Calculation

Costs are calculated locally from the token breakdown:

| Token type | Field | Price basis |
|-----------|-------|------------|
| Regular input | `input_tokens` | Input price per 1M |
| Cache write | `cache_creation_input_tokens` | Cache price per 1M |
| Cache read | `cache_read_input_tokens` | Cache price per 1M |
| Output | `output_tokens` | Output price per 1M |

Pricing table (in `~/.claude/hooks/vantage-track.js`):
```javascript
'claude-opus-4-6':   { input: 15.00, output: 75.00, cache: 1.50 }
'claude-sonnet-4-6': { input:  3.00, output: 15.00, cache: 0.30 }
'claude-haiku-4-5':  { input:  0.80, output:  4.00, cache: 0.08 }
```

### 23.4 Stop Hook Implementation

**File:** `~/.claude/hooks/vantage-track.js`

**Registered in** `~/.claude/settings.json`:
```json
"hooks": {
  "Stop": [{
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": "VANTAGE_API_KEY=vnt_... node ~/.claude/hooks/vantage-track.js"
    }]
  }]
}
```

**Behavior:**
- Reads `~/.claude/vantage-state.json` to load already-uploaded event IDs
- Finds JSONL files in `~/.claude/projects/{cwd-slug}/`
- For each new assistant turn (not in state), builds an event and POSTs to `/v1/events/batch`
- 5-second fetch timeout — if API is slow, hook exits gracefully
- Dedup state is updated only after a successful `res.ok` response
- State file is trimmed to 50,000 most recent IDs to prevent unbounded growth
- **Always exits 0** — hook failures never break Claude Code

**Event shape sent to API:**
```json
{
  "event_id": "{sessionId}-{uuid}",
  "provider": "anthropic",
  "model": "claude-opus-4-6",
  "prompt_tokens": 4300,
  "completion_tokens": 180,
  "cache_tokens": 6400,
  "total_tokens": 4480,
  "total_cost_usd": 0.0842,
  "environment": "local",
  "agent_name": "claude-code",
  "timestamp": "2026-04-05T14:00:00.000Z",
  "tags": { "tool": "claude-code", "hook": "stop" }
}
```

### 23.5 Backfill Command

Upload all historical Claude Code sessions at once:

```bash
VANTAGE_API_KEY=vnt_your_key \
  npx vantageai-local-proxy scan --tool claude-code --push
```

**What it does:**
1. Scans all JSONL files under `~/.claude/projects/`
2. Loads `~/.claude/vantage-state.json` and skips already-uploaded event IDs
3. Sends new turns in batches of 500 to `POST /v1/events/batch`
4. Updates the state file after each successful batch

Running this command twice is safe — the dedup state ensures no event is uploaded twice.

### 23.6 Dedup State File

**Path:** `~/.claude/vantage-state.json`

**Format:**
```json
{
  "uploadedIds": ["sessionId-uuid", "sessionId-uuid-2", ...],
  "lastUploadAt": "2026-04-05T14:22:00.000Z"
}
```

**Limits:**
- Capped at 50,000 entries (oldest trimmed first)
- Shared between the Stop hook and the backfill scan command
- If file is corrupt or missing, the system starts fresh (may re-upload recent turns)

### 23.7 Data Flow

```
Claude Code response
        │
        ▼
~/.claude/projects/{slug}/{uuid}.jsonl   ← written by Claude Code
        │
        ▼
vantage-track.js (Stop hook)
  - reads new assistant turns
  - calculates cost locally
  - deduplicates via ~/.claude/vantage-state.json
        │
        ▼
POST /v1/events/batch                    ← only token counts + model + cost
        │
        ▼
D1 events table → /v1/analytics/* endpoints → Dashboard
```

**Privacy:** Prompt text, response text, and file contents never leave the machine. Only model name, token counts, calculated cost, and timestamp are sent.

---

## 24. SDK Privacy Modes

For teams using the JS/Python SDK directly (not the local proxy), the SDK now supports privacy modes that control what data is sent to VantageAI.

### 24.1 Configuration

```javascript
import { VantageClient, createOpenAIProxy } from "vantageaiops";
import OpenAI from "openai";

const vantage = new VantageClient({
  apiKey: "vnt_yourorg_abc123",
  privacy: "stats-only",   // ← NEW: no prompt/response text sent
});

const openai = createOpenAIProxy(new OpenAI({ apiKey: "sk-..." }), vantage);

// All calls auto-tracked with stats only — no text leaves the machine
const response = await openai.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "Sensitive business data here" }],
});
```

### 24.2 Privacy Modes

| Mode | `requestPreview` | `responsePreview` | `systemPreview` | `promptHash` | Use Case |
|------|-------------------|-------------------|-----------------|--------------|----------|
| `full` (default) | First 600 chars | First 600 chars | First 200 chars | Yes | Full observability, internal tools |
| `stats-only` | Stripped | Stripped | Stripped | Stripped | Maximum privacy, compliance |
| `hashed` | Stripped | Stripped | Stripped | SHA hash kept | Privacy + dedup detection |

### 24.3 Comparison: SDK Privacy vs Local Proxy

| Feature | SDK with `stats-only` | Local Proxy (`strict`) |
|---|---|---|
| Prompt text sent | No | No |
| API key sent to Vantage | No (Vantage key only) | No (Vantage key only) |
| Requires code changes | 1 line (`privacy: "stats-only"`) | 0 lines (just change `base_url`) |
| Works with all providers | OpenAI + Anthropic (via proxy wrappers) | Any provider (generic HTTP proxy) |
| Streaming support | Full | Pass-through (limited stats) |
| Runs as separate process | No (in-process) | Yes (localhost server) |

**Recommendation:** Use the **Local Proxy** for zero-code-change deployments and maximum isolation. Use **SDK privacy modes** when you already use the SDK and want fine-grained control.

---

## 25. Cross-Platform OTel Collector (v2)

### Overview

VantageAI v2 introduces a **4-layer architecture** for tracking ALL AI spending across an organization:

1. **Layer 1 — OTel Telemetry** (real-time): Receives live OpenTelemetry from 7+ AI coding tools
2. **Layer 2 — Local File Scanner** (near real-time): CLI agent reads tool session files from developer machines
3. **Layer 3 — Billing APIs** (hourly): Pulls from provider admin/billing APIs
4. **Layer 4 — Browser Extension** (real-time): Tracks web AI tools (ChatGPT, Claude Console, Gemini)

### OTel Collector Endpoint

**Endpoints:**
- `POST /v1/otel/v1/metrics` — OTLP metrics ingestion (HTTP/JSON)
- `POST /v1/otel/v1/logs` — OTLP event/log ingestion (HTTP/JSON)
- `POST /v1/otel/v1/traces` — OTLP traces (placeholder for future)

**Auth:** `Authorization: Bearer vnt_your_key` via `OTEL_EXPORTER_OTLP_HEADERS`

**Supported Tools (Native OTel):**

| Tool | `service.name` | Config | Key Metrics |
|---|---|---|---|
| Claude Code | `claude-code` | `CLAUDE_CODE_ENABLE_TELEMETRY=1` | Tokens, cost, commits, PRs, lines, active time |
| GitHub Copilot | `copilot-chat` | `github.copilot.chat.otel.enabled=true` | Tokens, TTFT, tool calls, sessions |
| Gemini CLI | `gemini-cli` | `telemetry.enabled=true` | Tokens (5 types), API calls, file ops |
| OpenAI Codex | `codex-cli` | `~/.codex/config.toml` | Tokens, cost, commits, lines |
| Cline | `cline` | `CLINE_OTEL_TELEMETRY_ENABLED=1` | Tokens, tool calls |
| OpenCode | `opencode` | OTel env vars | Tokens |
| Kiro | `kiro` | OTel env vars | LLM calls |

**Provider Detection:** `detectProvider()` in `otel.ts` matches `service.name` to determine provider. Falls back to `custom_api` for auto-instrumented OpenAI/Anthropic SDK calls.

**Metric Parsing:** The collector handles both Counter (Sum) and Histogram data points. Copilot uses histograms; Claude Code uses counters. Both are normalized into the same `cross_platform_usage` schema.

### Database Schema (D1)

**Tables added in migration `0001_cross_platform_usage.sql`:**

- `cross_platform_usage` — Unified schema for all sources (OTel + billing API + SDK). Key fields: `provider`, `source`, `developer_email`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `commits`, `pull_requests`, `lines_added`, `active_time_s`
- `otel_events` — Lightweight audit log of all OTel events (api_request, tool_result, user_prompt)
- `provider_connections` — Encrypted credentials for billing API connectors
- `budget_policies` — Per-org/team/developer budget rules with enforcement levels

### Cross-Platform API Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /v1/cross-platform/summary?days=N` | Total spend, by provider, budget status |
| `GET /v1/cross-platform/developers?days=N` | Per-developer table with ROI metrics |
| `GET /v1/cross-platform/developer/:email?days=N` | Drill-down: by provider, model, trend, productivity |
| `GET /v1/cross-platform/live?limit=N` | Latest OTel events (real-time feed) |
| `GET /v1/cross-platform/models?days=N` | Cost by model across all providers |
| `GET /v1/cross-platform/connections` | OTel source freshness + billing API status |
| `GET /v1/cross-platform/budget` | Budget policies + current spend |

### Org-Wide OTel Deployment

For enterprise admins deploying OTel across all developers:

1. **Create a VantageAI API key** in the dashboard
2. **Distribute via MDM** (for Claude Code):
   ```json
   {
     "env": {
       "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
       "OTEL_METRICS_EXPORTER": "otlp",
       "OTEL_LOGS_EXPORTER": "otlp",
       "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
       "OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vantageaiops.com/v1/otel",
       "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer vnt_ORG_KEY",
       "OTEL_RESOURCE_ATTRIBUTES": "team.id=TEAM,cost_center=CC"
     }
   }
   ```
3. **For Copilot**, distribute VS Code settings via Settings Sync or GPO
4. **For Gemini CLI**, distribute `~/.gemini/settings.json` via config management

### Dashboard Module

The dashboard (`app.html`) has been restructured to use **only real API data**. No fake/demo/synthetic data is generated.

**Sidebar layout:**
- **Core:** All AI Spend (LIVE), Cost Intelligence, Model Comparison, Agent Traces
- **Analytics:** Performance & Latency, Quality & Evaluation
- **Team:** Enterprise Reporting (gated for team/org plans), Team Members, Security & Governance
- **Tools:** Token Optimizer, Developer Experience, Settings, Account

**All AI Spend** is the default landing page and includes:
- 4 KPI cards (total spend, tokens, developers, budget %)
- Provider doughnut chart with breakdown rows
- Per-developer table with commits, PRs, lines, cost/PR
- Model cost breakdown
- Live OTel event feed (auto-refreshes every 30 seconds)
- Token efficiency: efficiency score, cache hit rate, token breakdown chart, optimization tips
- Data source connection status
- Dual-write to otel_events: OTel metrics with token/cost data are also inserted into the `otel_events` table, powering the `/live` feed

**Enterprise Reporting** (team/org plans only):
- Real data from `/v1/admin/overview`, `/v1/analytics/teams`, `/v1/cross-platform/developers`
- Team chargeback table with budget %, cost/request
- Developer spend table with ROI metrics (cost/PR, lines/$)
- Daily spend trend chart from `/v1/analytics/timeseries`
- Working CSV export for chargeback data
- Free/individual users see an upgrade prompt

**Modules with honest empty states** (no backend yet):
- Quality & Evaluation — requires quality scoring events (hallucination, faithfulness, etc.)
- AI Intelligence Layer — removed from sidebar (smart router not yet implemented)
- Performance percentiles (p50/p95/p99) — requires per-request latency tracking

## 26. Vantage Agent — Python AI Coding Agent

The `vantageai-agent` package (`vantageai-agent/`) is a standalone Python AI coding agent that calls the Anthropic API directly. It provides per-tool permissions, cost tracking, prompt optimization, and dashboard telemetry — no external CLI dependency required.

> **Note:** This replaces the previous `vantage-cli` TypeScript wrapper (deleted). All unique features have been ported to Python with full test parity.

**How it works:**
1. User types a prompt (REPL, one-shot, or pipe)
2. Classifier determines input type (prompt/command/structured/short-answer)
3. Optimizer compresses prompt (6-layer, <1ms, preserves code blocks)
4. Sends to Anthropic API with streaming
5. When model returns `tool_use` → permission check → local execution → `tool_result` → API continues
6. Repeats tool loop until model sends `end_turn`
7. Tracks cost from real API usage, sends telemetry to dashboard

**3 Modes:**
- **REPL**: `vantageai-agent` — interactive with `/commands`
- **One-shot**: `vantageai-agent "prompt"` — run and exit
- **Pipe**: `echo "prompt" | vantageai-agent` — scriptable

**REPL commands:**
- `/help` — show commands
- `/allow Tool` or `/allow all` — approve tools
- `/tools` — show tool approval status
- `/cost` — show session cost summary
- `/optimize on|off` — toggle prompt optimization
- `/model name` — switch model
- `/reset` — reset permissions, history, and cost
- `/quit` — exit (shows final cost)

**Per-tool permissions:**
- Safe tools auto-approved: Read, Glob, Grep
- Dangerous tools prompt user: Bash, Write, Edit
- User responds: `[y]es once / [a]lways / [n]o`
- Persisted to `~/.vantageai-agent/permissions.json`

**6 local tools:**
| Tool | Description |
|------|-------------|
| Bash | Shell commands with timeout |
| Read | Line-numbered file output |
| Write | Create/overwrite files (creates parent dirs) |
| Edit | Unique string replacement in files |
| Glob | File pattern matching |
| Grep | Regex content search |

**Prompt optimization (6 layers):**
1. Deduplicate sentences
2. Remove filler phrases (36 patterns)
3. Apply verbose rewrites (42 regex rules)
4. Strip filler words (25 words)
5. Collapse whitespace
6. Trim

Structured data (JSON, code blocks, URLs, high-symbol text) is auto-detected and skipped.

**Input classifier:**
- `prompt` — natural language (5+ words) → eligible for optimization
- `short-answer` — y/n, numbers, ≤2 words → pass through
- `vantage-command` — /cost, /opt-off, /exit-session → handle locally
- `agent-command` — /compact, /clear, @file, !cmd → agent-specific dispatch
- `structured` — JSON, code, URLs → skip optimizer
- `unknown` — empty input

**Multi-model pricing (15 models):**
| Provider | Models |
|----------|--------|
| Anthropic | claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 |
| OpenAI | gpt-4o, gpt-4o-mini, o1, o3-mini, gpt-3.5-turbo |
| Google | gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash |
| Other | llama-3.3-70b, mistral-large-latest, deepseek-chat, grok-2 |

- `calculate_cost(model, input, output, cached)` — exact USD with cache discounts
- `find_cheapest(model, input, output)` — cheaper alternative with savings %

**Recommendations engine (24 tips):**
- Agent-specific: Claude (6), Gemini (4), Codex (3), Aider (4), Cursor/ChatGPT (3)
- Universal: high cost alert, cost per prompt, large prompt, low cache (4)
- Priority sorted: critical → high → medium → low
- Dynamic placeholders: ${cost}, ${avg}, ${tokens}, ${pct}
- Inline tips with emoji: 🔴 critical, 🟡 high, 💡 medium

**Cost anomaly detection:**
- Warns when prompt cost exceeds 3x session average
- Minimum 2 prior prompts, minimum $0.001 average before flagging

**Dashboard telemetry:**
- Batched event sending via `httpx` to `/v1/events/batch`
- Configurable: batch size, flush interval, privacy mode
- Privacy modes: full, strict (strips agent name), anonymized, local-only
- Background timer for periodic flush

**Key files:**
| File | Purpose |
|------|---------|
| `cli.py` | REPL, one-shot, pipe modes, /commands |
| `api_client.py` | Anthropic API streaming + tool-use loop |
| `tools.py` | 6 local tool implementations |
| `permissions.py` | Per-tool approval with persistence |
| `cost_tracker.py` | Real token cost from API usage objects |
| `pricing.py` | 15-model pricing table, cheapest finder |
| `optimizer.py` | 6-layer prompt compression + structured data guard |
| `classifier.py` | Input classification + optimization pipeline |
| `recommendations.py` | 24 agent-specific tips engine |
| `anomaly.py` | Cost spike detection |
| `tracker.py` | Batched dashboard telemetry |
| `renderer.py` | Terminal output (streaming, tools, cost) |

### Feature Comparison: Previous TypeScript CLI vs Current Python Agent

| Feature | TS CLI (deleted) | Python Agent | Status |
|---------|-----------------|--------------|--------|
| Prompt optimizer (6 layers) | ✅ | ✅ | Ported |
| Structured data guard | ✅ | ✅ | Ported |
| Input classifier | ✅ | ✅ | Ported |
| Multi-model pricing (15) | ✅ | ✅ | Ported |
| Cheapest model finder | ✅ | ✅ | Ported |
| Cost anomaly detection | ✅ | ✅ | Ported |
| Dashboard telemetry | ✅ | ✅ | Ported |
| Recommendations (24 tips) | ✅ | ✅ | Ported |
| Agent name normalization | ✅ | ✅ | Ported |
| REPL + one-shot + pipe | ✅ | ✅ | Ported |
| Direct API execution | ❌ (wrapped CLI) | ✅ | **New** |
| Per-tool permissions | ❌ (relied on agent) | ✅ | **New** |
| Local tool execution | ❌ (delegated) | ✅ (6 tools) | **New** |
| Real API cost tracking | ❌ (estimated) | ✅ (from usage) | **New** |
| Agent adapter registry | ✅ (5 agents) | ❌ | Dropped |
| Session persistence | ✅ (~/.vantage/) | ❌ | Dropped |
| Setup wizard | ✅ | ❌ | Dropped |
| Event bus | ✅ | ❌ | Dropped |
| Claude config reading | ✅ | ❌ | Dropped |

**Dropped features rationale:** Python agent calls the Anthropic API directly — it doesn't wrap other CLI tools, so agent adapters, CLI config reading, session IDs, and the setup wizard are unnecessary.

### Test Coverage

**273 tests** across 11 test files (273 pass, 40 skip for live API):

| Test File | Tests | Covers |
|-----------|-------|--------|
| `test_integration.py` | 60 | Multi-turn, all 6 tools, permissions, cost, CLI, edge cases |
| `test_classifier.py` | 45 | Input classification (SS01-SS40), structured guard (CS01-CS08) |
| `test_rendering.py` | 43 | Text/tool/cost rendering, permission flow, API tool loop (mocked) |
| `test_tools.py` | 36 | Bash, Read, Write, Edit, Glob, Grep execution |
| `test_recommendations.py` | 30 | 24 tips, conditions, priorities, templates, formatting (R01-R30) |
| `test_optimizer.py` | 28 | 6-layer compression, dedup, filler, code preservation |
| `test_pricing.py` | 22 | 15 models, cache, cheapest, cross-provider (CL19-CL25) |
| `test_permissions.py` | 18 | Safe defaults, approve/deny, always/session, persistence |
| `test_cost_tracker.py` | 13 | Token recording, session accumulation, cache pricing |
| `test_tracker.py` | 11 | Batched telemetry, auto-flush, privacy, errors |
| `test_anomaly.py` | 7 | 3x threshold, min average, edge cases |

## 27. Security & Governance

### Audit Logging
All security-critical actions are logged to the `audit_events` table:
- Member invites, revocations, role changes
- API key rotations (owner and member)
- Budget policy changes

**Endpoint:** `GET /v1/admin/audit?limit=50` (owner/admin only)

**Table schema:**
- `org_id`, `actor_email`, `actor_role` — who did it
- `action` — what they did (member.invited, key.rotated, etc.)
- `resource`, `detail` — what was affected
- `ip_address`, `created_at` — when and where

### Security Overview API
`GET /v1/admin/security` returns:
- `audit_events_today` — count of audit events in last 24h
- `active_members` — count of org members + owner
- `plan` — current org plan (free/team/enterprise)
- `retention_days` — data retention based on plan (7/90/unlimited)
- `security_features` — API key hashing, session security, encryption, RBAC, rate limiting

### Dashboard
The Security & Governance view in `app.html` shows:
- Real-time KPIs from `/v1/admin/security` (no hardcoded values)
- API keys table from `/v1/admin/overview` (real member data)
- RBAC table with actual roles and permissions
- Audit log table from `/v1/admin/audit`
- Data retention policy based on actual plan
- Security features summary from API

### Test Coverage

- `tests/suites/17_otel/test_otel_collector.py` — 41 checks (auth, ingestion, API queries)
- `tests/suites/17_otel/test_otel_e2e.py` — 78 checks (multi-platform simulation, ROI metrics, edge cases)
- `tests/suites/18_sdk_privacy/test_sdk_privacy.py` — 50+ checks (privacy modes, pricing engine, date format, dual-write)
- `tests/suites/19_local_proxy/test_local_proxy.py` — 42+ checks (privacy engine, pricing accuracy, proxy integration, scanner coverage)
- `tests/suites/20_dashboard_real_data/test_dashboard_real_data.py` — 42+ checks (enterprise reporting, cost intelligence, no fake data, cross-platform integration)
- `vantageai-agent/tests/` — 273 checks across 11 files (optimizer, pricing, classifier, recommendations, permissions, tools, rendering, cost tracking, anomaly detection, telemetry, API tool loop)
- `tests/suites/22_landing_page/test_landing_page.py` — 41 checks (landing page content, v2 feature coverage, HTML structure)
- `tests/suites/23_security_governance/` — audit logging, security overview API, RBAC, data retention
- Total: **567+ checks** across suites covering OTel + cross-platform + privacy + pricing + dashboard + Python agent (273) + landing page + security & governance features

---

*Last updated: 7 April 2026 — v2.4 consolidated Python agent (vantage-cli deleted, all features ported to vantageai-agent). 273 agent tests + 294 backend tests = 567+ total checks.*

## CLI Agent Configuration

### Permission Persistence

Vantage Agent persists per-tool approvals:

```
~/.vantageai-agent/
├── permissions.json         # { "always_approved": ["Bash", "Write", "Edit"] }
```

**REPL commands:**
- `/allow Tool` — Approve a specific tool permanently
- `/allow all` — Approve all tools
- `/tools` — Show current approval status
- `/reset` — Clear permissions, history, and cost

### CLI Arguments

```
vantageai-agent                           # Start interactive REPL
vantageai-agent "fix the bug"             # One-shot mode
echo "fix the bug" | vantageai-agent      # Pipe mode
vantageai-agent --model claude-opus-4-6   # Use specific model
vantageai-agent --no-optimize             # Disable prompt optimization
vantageai-agent --api-key sk-ant-...      # Provide API key
vantageai-agent --vantage-key vnt_...     # Enable dashboard telemetry
vantageai-agent --debug                   # Enable debug output
```
