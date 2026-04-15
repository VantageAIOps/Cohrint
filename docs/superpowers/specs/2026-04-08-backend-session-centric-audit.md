# Backend Architecture Review — Session-Centric Integration Audit

**Date:** 2026-04-08  
**Status:** Approved — implementation pending  
**Scope:** vantage-mcp, vantage-local-proxy, vantage-worker (OTel)  
**Reference:** `2026-04-08-cli-multi-backend-cost-intelligence-design.md`

---

## Context

The `vantage-agent` Python CLI defines a session-centric model where every AI interaction belongs to a `VantageSession` (UUID, created_at, cost_summary, messages[]). The three Node/TypeScript subsystems — MCP, local-proxy, OTel worker — were built independently and do not align with this model. This spec documents the gaps found and the agreed fixes.

---

## Audit Findings

| Component | session_id present? | Gap |
|-----------|---------------------|-----|
| vantage-mcp | ❌ None | `track_llm_call` has no session_id field; events are unlinked |
| vantage-local-proxy | ✅ UUID per process | Session dies with process; no resume; can't link to agent session |
| OTel / vantage-worker | ✅ Extracted from `session.id` attribute | Stored in DB but never rolled up; no session-level aggregation |
| vantage-agent (Python) | ✅ Full model | Source of truth — defines session lifecycle correctly |

---

## Fix 1 — vantage-mcp: Add `session_id` to `track_llm_call`

### Problem
`track_llm_call` input schema has no `session_id` field. Events logged via MCP cannot be correlated with a `vantage-agent` session or `local-proxy` session.

### Change
**File:** `vantage-mcp/src/index.ts`

Add to `track_llm_call` inputSchema properties:
```typescript
session_id: { type: 'string', description: 'optional — link this event to a vantage-agent or local-proxy session' }
```

Add to event body constructed before `api('/v1/events', ...)`:
```typescript
...(args.session_id && { session_id: args.session_id }),
```

### Data Flow After Fix
```
vantage-agent creates session (UUID: abc-123)
  → user triggers MCP tool call in Claude Code
  → track_llm_call({ model, tokens, cost, session_id: "abc-123" })
  → POST /v1/events { ..., session_id: "abc-123" }
  → event stored with session lineage ✓
```

### Testing
- Existing MCP tests unchanged
- Add: `track_llm_call` with `session_id` → assert event body includes `session_id`
- Add: `track_llm_call` without `session_id` → assert no `session_id` key in body (backwards compat)

---

## Fix 2 — vantage-local-proxy: Resumable Sessions

### Problem
`ProxyServer` always calls `randomUUID()` at startup. There is no way to:
- Resume a session after a proxy restart
- Link a proxy session to a specific `vantage-agent` session ID

### Changes

**`cli.ts`** — add two new flags:
```
--resume <session_id>    Resume an existing proxy session by ID
--session-id <id>        Start with a caller-supplied session ID
```

**`proxy-server.ts`** — `ProxyServer` constructor accepts `resumeSessionId?: string` and `fixedSessionId?: string`:
```typescript
if (resumeSessionId) {
  const existing = await sessionStore.load(resumeSessionId);
  if (existing) {
    this.currentSession = existing;
  } else {
    warn(`Session ${resumeSessionId} not found — starting new session`);
    this.currentSession = createNewSession();
  }
} else if (fixedSessionId) {
  this.currentSession = createNewSession(fixedSessionId);
} else {
  this.currentSession = createNewSession(); // randomUUID() — today's behaviour
}
```

**`session-store.ts`** — `listAll()` already implemented (commit 4651ac9); used to validate ID before startup.

### Data Flow After Fix
```
# First run
vantageai-local-proxy --api-key crt_... --team eng
  → creates session abc-123
  → saves ~/.vantage/sessions/abc-123.json

# Crash / restart
vantageai-local-proxy --resume abc-123
  → loads session abc-123 from disk
  → new events append to existing session
  → cost_summary accumulates across runs ✓

# Linked to vantage-agent
vantageai-local-proxy --session-id <agent-session-id>
  → proxy events share session_id with agent session ✓
```

### Testing (new suite: `tests/suites/35_local_proxy_resume/`)
- `--resume <valid_id>` → session loaded, events appended, cost_summary accumulated
- `--resume <unknown_id>` → graceful fallback to new session, warning emitted
- `--session-id <custom>` → session created with exact UUID provided
- No flags → `randomUUID()` as before (regression test)

---

## Fix 3 — vantage-worker: OTel Session Rollup Table

### Problem
`session_id` is correctly extracted from OTel attributes and stored in `otel_events` and `cross_platform_usage`, but:
- No session-level summary exists
- Analytics queries cannot group by session
- No endpoint to list/query sessions

### Changes

**New D1 migration:**
```sql
CREATE TABLE IF NOT EXISTS otel_sessions (
  org_id          TEXT    NOT NULL,
  session_id      TEXT    NOT NULL,
  provider        TEXT,
  developer_email TEXT,
  team            TEXT,
  model           TEXT,
  input_tokens    INTEGER NOT NULL DEFAULT 0,
  output_tokens   INTEGER NOT NULL DEFAULT 0,
  cached_tokens   INTEGER NOT NULL DEFAULT 0,
  cost_usd        REAL    NOT NULL DEFAULT 0,
  event_count     INTEGER NOT NULL DEFAULT 0,
  first_seen_at   TEXT    NOT NULL,
  last_seen_at    TEXT    NOT NULL,
  PRIMARY KEY (org_id, session_id)
);
CREATE INDEX idx_otel_sessions_org_last ON otel_sessions (org_id, last_seen_at DESC);
CREATE INDEX idx_otel_sessions_developer ON otel_sessions (org_id, developer_email);
```

**`vantage-worker/src/routes/otel.ts`** — after inserting into `otel_events`, upsert session rollup:
```sql
INSERT INTO otel_sessions
  (org_id, session_id, provider, developer_email, team, model,
   input_tokens, output_tokens, cached_tokens, cost_usd, event_count,
   first_seen_at, last_seen_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
ON CONFLICT (org_id, session_id) DO UPDATE SET
  input_tokens  = input_tokens  + excluded.input_tokens,
  output_tokens = output_tokens + excluded.output_tokens,
  cached_tokens = cached_tokens + excluded.cached_tokens,
  cost_usd      = cost_usd      + excluded.cost_usd,
  event_count   = event_count   + 1,
  last_seen_at  = excluded.last_seen_at;
```

**New API endpoint:** `GET /v1/sessions`
```
Auth: Bearer crt_...
Query params:
  limit          integer  default 20, max 100
  provider       string   filter by provider
  developer_email string  filter by developer
  from           string   ISO date, filter by last_seen_at >=

Response:
{
  "sessions": [
    {
      "session_id": "abc-123",
      "provider": "claude-code",
      "developer_email": "aman@example.com",
      "model": "claude-sonnet-4-6",
      "input_tokens": 42000,
      "output_tokens": 8200,
      "cost_usd": 0.187,
      "event_count": 14,
      "first_seen_at": "2026-04-08 10:00:00",
      "last_seen_at":  "2026-04-08 10:43:11"
    }
  ],
  "total": 1
}
```

### Data Flow After Fix
```
Claude Code emits OTel metric (session.id = "abc-123")
  → POST /v1/otel/v1/metrics
  → insert into otel_events ✓ (existing)
  → upsert into otel_sessions (abc-123) ✓ (new)

Second metric arrives (same session)
  → otel_sessions row accumulates tokens + cost ✓

Dashboard / MCP calls GET /v1/sessions
  → returns per-session cost rollup ✓
```

### Testing (new suite: `tests/suites/34_otel_sessions/`)
- OTel ingest with session_id → `otel_sessions` row created
- Second ingest same session_id → row accumulated (not duplicated)
- Ingest without session_id → handled gracefully (row skipped or default session)
- `GET /v1/sessions` → returns correct rollup, auth required
- `GET /v1/sessions?developer_email=x` → filters correctly

---

## Implementation Order

1. **Fix 1** (MCP) — 2 lines, ship immediately, no migrations needed
2. **Fix 2** (local-proxy) — ~50 lines across 3 files, tests in suite 35
3. **Fix 3** (OTel worker) — migration + route change + new endpoint + tests in suite 34

Each fix is independent and can be PRed separately on its own branch.

---

## Files Touched Summary

| File | Fix |
|------|-----|
| `vantage-mcp/src/index.ts` | Fix 1 |
| `vantage-local-proxy/src/cli.ts` | Fix 2 |
| `vantage-local-proxy/src/proxy-server.ts` | Fix 2 |
| `vantage-local-proxy/src/session-store.ts` | Fix 2 (listAll already exists) |
| `vantage-worker/src/routes/otel.ts` | Fix 3 |
| `vantage-worker/migrations/XXXX_otel_sessions.sql` | Fix 3 |
| `vantage-worker/src/routes/sessions.ts` (new) | Fix 3 |
| `tests/suites/34_otel_sessions/` (new) | Fix 3 |
| `tests/suites/35_local_proxy_resume/` (new) | Fix 2 |
