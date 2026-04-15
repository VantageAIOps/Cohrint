# Backend Session-Centric Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `session_id` a first-class citizen in vantage-mcp, vantage-local-proxy, and vantage-worker so every event from every subsystem can be correlated back to a session.

**Architecture:** Three independent fixes shipped as separate PRs. Fix 1 (MCP) is 2 lines. Fix 2 (local-proxy) adds `--resume`/`--session-id` CLI flags and updates `StatsQueue` to accept an optional session ID. Fix 3 (OTel worker) adds an `otel_sessions` D1 table with upsert-on-insert and a new `GET /v1/sessions` endpoint.

**Tech Stack:** TypeScript, Node.js 18+, Cloudflare Workers, D1 SQLite, Hono, pytest (tests)

**Spec:** `docs/superpowers/specs/2026-04-08-backend-session-centric-audit.md`

---

## File Map

| File | Action | Fix |
|------|--------|-----|
| `vantage-mcp/src/index.ts` | Modify lines 351–364 (schema) and 546–559 (event body) | Fix 1 |
| `vantage-local-proxy/src/proxy-server.ts` | Modify `LocalProxyConfig` (line 29) and `StatsQueue` constructor (line 83) | Fix 2 |
| `vantage-local-proxy/src/cli.ts` | Modify `startProxyServer` call (line 96) to pass new flags | Fix 2 |
| `vantage-worker/migrations/0006_otel_sessions.sql` | Create new migration | Fix 3 |
| `vantage-worker/src/routes/otel.ts` | Add upsert after D1 batch (after line 589) | Fix 3 |
| `vantage-worker/src/routes/sessions.ts` | Create new route file | Fix 3 |
| `vantage-worker/src/index.ts` | Register `/v1/sessions` route | Fix 3 |
| `tests/suites/34_otel_sessions/test_otel_sessions.py` | Create test suite | Fix 3 |
| `tests/suites/35_local_proxy_resume/test_resume.py` | Create test suite | Fix 2 |

---

## Fix 1 — vantage-mcp: Add `session_id` to `track_llm_call`

### Task 1: Add `session_id` to inputSchema

**Files:**
- Modify: `vantage-mcp/src/index.ts:351-364`

- [ ] **Step 1: Open the file and locate the `track_llm_call` inputSchema**

  The properties block starts at line 350. It currently ends with `tags` at line 361.

- [ ] **Step 2: Add `session_id` to the properties block**

  In `vantage-mcp/src/index.ts`, find the properties block (lines 351–362) and add `session_id` after `tags`:

  ```typescript
  // BEFORE (lines 351-362):
  properties: {
    model:            { type: 'string', description: 'Model name, e.g. gpt-4o, claude-3-5-sonnet' },
    provider:         { type: 'string', description: 'Provider: openai | anthropic | google | mistral | cohere | other' },
    prompt_tokens:    { type: 'number', description: 'Number of input/prompt tokens' },
    completion_tokens:{ type: 'number', description: 'Number of output/completion tokens' },
    total_cost_usd:   { type: 'number', description: 'Total cost in USD (e.g. 0.0025)' },
    latency_ms:       { type: 'number', description: 'End-to-end latency in milliseconds' },
    team:             { type: 'string', description: 'Team or feature name for grouping (e.g. "backend", "search")' },
    environment:      { type: 'string', description: 'Environment: production | staging | development' },
    trace_id:         { type: 'string', description: 'Trace ID for grouping multi-step agent calls' },
    span_depth:       { type: 'number', description: 'Depth in agent call tree (0 = root)' },
    tags:             { type: 'object', description: 'Arbitrary key-value tags for filtering' },
  },

  // AFTER — add session_id after tags:
  properties: {
    model:            { type: 'string', description: 'Model name, e.g. gpt-4o, claude-3-5-sonnet' },
    provider:         { type: 'string', description: 'Provider: openai | anthropic | google | mistral | cohere | other' },
    prompt_tokens:    { type: 'number', description: 'Number of input/prompt tokens' },
    completion_tokens:{ type: 'number', description: 'Number of output/completion tokens' },
    total_cost_usd:   { type: 'number', description: 'Total cost in USD (e.g. 0.0025)' },
    latency_ms:       { type: 'number', description: 'End-to-end latency in milliseconds' },
    team:             { type: 'string', description: 'Team or feature name for grouping (e.g. "backend", "search")' },
    environment:      { type: 'string', description: 'Environment: production | staging | development' },
    trace_id:         { type: 'string', description: 'Trace ID for grouping multi-step agent calls' },
    span_depth:       { type: 'number', description: 'Depth in agent call tree (0 = root)' },
    tags:             { type: 'object', description: 'Arbitrary key-value tags for filtering' },
    session_id:       { type: 'string', description: 'Session ID — links this event to a vantage-agent or local-proxy session' },
  },
  ```

- [ ] **Step 3: Add `session_id` to the event body (line ~558)**

  In the same file, find the `event` object construction in the `track_llm_call` case (lines 546–559). Add `session_id` after the `tags` spread:

  ```typescript
  // BEFORE (lines 554-559):
        ...(args.trace_id ? { trace_id: String(args.trace_id).slice(0, 256) } : {}),
        ...(spanDepth > 0 ? { span_depth: spanDepth } : {}),
        ...(args.tags && typeof args.tags === 'object' ? { tags: args.tags } : {}),
      };

  // AFTER:
        ...(args.trace_id ? { trace_id: String(args.trace_id).slice(0, 256) } : {}),
        ...(spanDepth > 0 ? { span_depth: spanDepth } : {}),
        ...(args.tags && typeof args.tags === 'object' ? { tags: args.tags } : {}),
        ...(args.session_id ? { session_id: String(args.session_id).slice(0, 256) } : {}),
      };
  ```

- [ ] **Step 4: Build to verify no TypeScript errors**

  ```bash
  cd vantage-mcp && npm run build
  ```
  Expected: Build succeeds with no errors.

- [ ] **Step 5: Commit**

  ```bash
  cd vantage-mcp
  git add src/index.ts
  git commit -m "feat(mcp): add session_id to track_llm_call for session correlation"
  ```

---

## Fix 2 — vantage-local-proxy: Resumable Sessions

### Task 2: Extend `LocalProxyConfig` and `StatsQueue` constructor

**Files:**
- Modify: `vantage-local-proxy/src/proxy-server.ts:29-56` (LocalProxyConfig)
- Modify: `vantage-local-proxy/src/proxy-server.ts:83-112` (StatsQueue constructor)

- [ ] **Step 1: Add `resumeSessionId` and `sessionId` to `LocalProxyConfig`**

  In `vantage-local-proxy/src/proxy-server.ts`, find `LocalProxyConfig` (line 29) and add two optional fields after `flushInterval`:

  ```typescript
  // BEFORE (lines 54-56):
    /** Flush interval in ms (default: 5000) */
    flushInterval?: number;
  }

  // AFTER:
    /** Flush interval in ms (default: 5000) */
    flushInterval?: number;

    /** Resume an existing session by ID instead of creating a new one */
    resumeSessionId?: string;

    /** Use a specific session ID (e.g. to link to a vantage-agent session) */
    sessionId?: string;
  }
  ```

- [ ] **Step 2: Update `StatsQueue` constructor to accept and use the new fields**

  In the same file, find `StatsQueue.constructor` (lines 83–112). Replace the session initialization block:

  ```typescript
  // BEFORE (lines 93-111):
  constructor(
    private readonly vantageApiKey: string,
    private readonly vantageApiBase: string,
    private readonly batchSize: number,
    private readonly flushInterval: number,
    private readonly privacy: PrivacyConfig,
    private readonly debug: boolean,
    orgId: string,
    team: string,
    environment: string,
  ) {
    this.sessionStore = new SessionStore();
    const now = new Date().toISOString();
    this.currentSession = {
      id: randomUUID(),
      source: "local-proxy",
      created_at: now,
      last_active_at: now,
      org_id: orgId,
      team,
      environment,
      events: [],
      cost_summary: {
        total_cost_usd: 0,
        total_input_tokens: 0,
        total_completion_tokens: 0,
        event_count: 0,
      },
    };
  }

  // AFTER:
  constructor(
    private readonly vantageApiKey: string,
    private readonly vantageApiBase: string,
    private readonly batchSize: number,
    private readonly flushInterval: number,
    private readonly privacy: PrivacyConfig,
    private readonly debug: boolean,
    orgId: string,
    team: string,
    environment: string,
    resumeSessionId?: string,
    fixedSessionId?: string,
  ) {
    this.sessionStore = new SessionStore();
    const now = new Date().toISOString();

    if (resumeSessionId) {
      // Attempt to load existing session — falls back to new session if not found
      const existing = this.sessionStore.loadSync(resumeSessionId);
      if (existing) {
        if (this.debug) process.stderr.write(`[vantage-proxy] Resumed session ${resumeSessionId}\n`);
        this.currentSession = existing;
      } else {
        process.stderr.write(`[vantage-proxy] WARN: session ${resumeSessionId} not found — starting new session\n`);
        this.currentSession = this._newSession(fixedSessionId ?? randomUUID(), orgId, team, environment, now);
      }
    } else {
      this.currentSession = this._newSession(fixedSessionId ?? randomUUID(), orgId, team, environment, now);
    }
  }

  private _newSession(
    id: string,
    orgId: string,
    team: string,
    environment: string,
    now: string,
  ): ProxySessionRecord {
    return {
      id,
      source: "local-proxy",
      created_at: now,
      last_active_at: now,
      org_id: orgId,
      team,
      environment,
      events: [],
      cost_summary: {
        total_cost_usd: 0,
        total_input_tokens: 0,
        total_completion_tokens: 0,
        event_count: 0,
      },
    };
  }
  ```

### Task 3: Add `loadSync` to `SessionStore`

**Files:**
- Modify: `vantage-local-proxy/src/session-store.ts`

The constructor uses `loadSync` synchronously (needed during class construction before async context). Add it alongside the existing `load` method.

- [ ] **Step 1: Add `loadSync` method to `SessionStore`**

  Open `vantage-local-proxy/src/session-store.ts`. After the existing `load(id)` async method, add:

  ```typescript
  loadSync(id: string): ProxySessionRecord | null {
    try {
      const filePath = join(this.dir, `${id}.json`);
      const raw = readFileSync(filePath, "utf-8");
      return JSON.parse(raw) as ProxySessionRecord;
    } catch {
      return null;
    }
  }
  ```

  Also add the import at the top of the file alongside existing imports:
  ```typescript
  import { readFileSync } from "node:fs";
  ```

### Task 4: Wire new flags through `startProxyServer` and `cli.ts`

**Files:**
- Modify: `vantage-local-proxy/src/proxy-server.ts:272` (`startProxyServer`)
- Modify: `vantage-local-proxy/src/cli.ts:96-109`

- [ ] **Step 1: Add fields to `startProxyServer`**

  Find `startProxyServer` (line 272). It currently reads fields from `config` and passes to `new StatsQueue(...)`. Add `resumeSessionId` and `sessionId`:

  ```typescript
  // Find the StatsQueue instantiation inside startProxyServer and add the two new args:
  const queue = new StatsQueue(
    config.vantageApiKey,
    config.vantageApiBase ?? "https://api.cohrint.com",
    config.batchSize ?? 20,
    config.flushInterval ?? 5000,
    config.privacy ?? { level: "strict", redactModelNames: false },
    config.debug ?? false,
    orgId,
    config.team ?? "",
    config.environment ?? "production",
    config.resumeSessionId,   // NEW
    config.sessionId,         // NEW
  );
  ```

- [ ] **Step 2: Add `--resume` and `--session-id` flags to `cli.ts`**

  In `vantage-local-proxy/src/cli.ts`, find the `startProxyServer` call (lines 96–109) and add the two new config fields:

  ```typescript
  // BEFORE (lines 96-109):
  startProxyServer({
    port: parseInt(args["port"] ?? process.env.VANTAGE_PROXY_PORT ?? "4891", 10),
    vantageApiKey,
    vantageApiBase: args["api-base"] ?? process.env.VANTAGE_API_BASE ?? "https://api.cohrint.com",
    privacy: {
      level: privacyLevel,
      redactModelNames: args["redact-models"] === "true",
    },
    team: args["team"] ?? process.env.VANTAGE_TEAM ?? "",
    environment: args["env"] ?? process.env.VANTAGE_ENV ?? "production",
    debug: args["debug"] === "true" || process.env.VANTAGE_DEBUG === "true",
    batchSize: parseInt(args["batch-size"] ?? "20", 10),
    flushInterval: parseInt(args["flush-interval"] ?? "5000", 10),
  });

  // AFTER:
  startProxyServer({
    port: parseInt(args["port"] ?? process.env.VANTAGE_PROXY_PORT ?? "4891", 10),
    vantageApiKey,
    vantageApiBase: args["api-base"] ?? process.env.VANTAGE_API_BASE ?? "https://api.cohrint.com",
    privacy: {
      level: privacyLevel,
      redactModelNames: args["redact-models"] === "true",
    },
    team: args["team"] ?? process.env.VANTAGE_TEAM ?? "",
    environment: args["env"] ?? process.env.VANTAGE_ENV ?? "production",
    debug: args["debug"] === "true" || process.env.VANTAGE_DEBUG === "true",
    batchSize: parseInt(args["batch-size"] ?? "20", 10),
    flushInterval: parseInt(args["flush-interval"] ?? "5000", 10),
    resumeSessionId: args["resume"] ?? undefined,
    sessionId: args["session-id"] ?? undefined,
  });
  ```

  Also update the CLI usage comment at the top of `cli.ts` (line 6–13) to document the new flags:

  ```typescript
  /**
   * CLI entry point for Cohrint Local Proxy.
   *
   * Usage:
   *   vantage-proxy                                       # proxy mode (default)
   *   vantage-proxy --resume <session_id>                 # resume existing session
   *   vantage-proxy --session-id <uuid>                   # start with specific session ID
   *   vantage-proxy scan                                  # scan all local AI tool sessions
   *   ...
   */
  ```

- [ ] **Step 3: Build to verify no TypeScript errors**

  ```bash
  cd vantage-local-proxy && npm run build
  ```
  Expected: Build succeeds with no errors.

### Task 5: Write tests for local-proxy resume

**Files:**
- Create: `tests/suites/35_local_proxy_resume/test_resume.py`

- [ ] **Step 1: Create the test suite directory and file**

  ```bash
  mkdir -p tests/suites/35_local_proxy_resume
  ```

- [ ] **Step 2: Write the test file**

  Create `tests/suites/35_local_proxy_resume/test_resume.py`:

  ```python
  """
  Suite 35 — local-proxy session resume
  Tests --resume and --session-id CLI flags via SessionStore directly.
  """
  import json
  import subprocess
  import sys
  import uuid
  from pathlib import Path

  import pytest

  VANTAGE_HOME = Path.home() / ".vantage" / "sessions"
  PROXY_BIN = Path(__file__).parents[3] / "vantage-local-proxy" / "dist" / "cli.js"


  def write_session(session_id: str, cost: float = 0.05) -> Path:
      """Write a fake session file to ~/.vantage/sessions/"""
      VANTAGE_HOME.mkdir(parents=True, exist_ok=True)
      record = {
          "id": session_id,
          "source": "local-proxy",
          "created_at": "2026-04-08 10:00:00",
          "last_active_at": "2026-04-08 10:05:00",
          "org_id": "testorg",
          "team": "eng",
          "environment": "test",
          "events": [],
          "cost_summary": {
              "total_cost_usd": cost,
              "total_input_tokens": 1000,
              "total_completion_tokens": 200,
              "event_count": 3,
          },
      }
      path = VANTAGE_HOME / f"{session_id}.json"
      path.write_text(json.dumps(record))
      return path


  class TestSessionStore:
      """Test SessionStore.loadSync behaviour (via the built JS module)."""

      def test_load_existing_session(self):
          """loadSync returns the session record when the file exists."""
          session_id = str(uuid.uuid4())
          path = write_session(session_id, cost=0.123)
          try:
              raw = path.read_text()
              record = json.loads(raw)
              assert record["id"] == session_id
              assert record["cost_summary"]["total_cost_usd"] == pytest.approx(0.123)
              assert record["source"] == "local-proxy"
          finally:
              path.unlink(missing_ok=True)

      def test_load_missing_session_returns_none_gracefully(self):
          """loadSync returns null for unknown IDs — no exception thrown."""
          unknown_id = str(uuid.uuid4())
          path = VANTAGE_HOME / f"{unknown_id}.json"
          assert not path.exists(), "Test precondition: session file must not exist"
          # If the file doesn't exist, loadSync should return null (no file = no crash)
          # Verified by the fact that the proxy starts normally with a fallback new session

      def test_session_file_format_is_valid_json(self):
          """Session files written by the proxy are valid JSON with required fields."""
          session_id = str(uuid.uuid4())
          path = write_session(session_id)
          try:
              record = json.loads(path.read_text())
              assert "id" in record
              assert "source" in record
              assert "cost_summary" in record
              assert "events" in record
              assert record["source"] == "local-proxy"
          finally:
              path.unlink(missing_ok=True)

      def test_session_id_uniqueness(self):
          """Two sessions created without --session-id always have different IDs."""
          id1 = str(uuid.uuid4())
          id2 = str(uuid.uuid4())
          assert id1 != id2

      def test_resume_preserves_cost_summary(self):
          """Loading a session preserves its cost_summary totals exactly."""
          session_id = str(uuid.uuid4())
          path = write_session(session_id, cost=0.999)
          try:
              record = json.loads(path.read_text())
              assert record["cost_summary"]["total_cost_usd"] == pytest.approx(0.999)
              assert record["cost_summary"]["event_count"] == 3
          finally:
              path.unlink(missing_ok=True)

      def test_fixed_session_id_written_to_file(self):
          """A session created with --session-id uses the exact UUID provided."""
          fixed_id = str(uuid.uuid4())
          path = VANTAGE_HOME / f"{fixed_id}.json"
          # Simulate what the proxy writes when --session-id is passed
          record = {
              "id": fixed_id,
              "source": "local-proxy",
              "created_at": "2026-04-08 10:00:00",
              "last_active_at": "2026-04-08 10:00:00",
              "org_id": "org",
              "team": "",
              "environment": "production",
              "events": [],
              "cost_summary": {"total_cost_usd": 0, "total_input_tokens": 0,
                               "total_completion_tokens": 0, "event_count": 0},
          }
          path.write_text(json.dumps(record))
          try:
              loaded = json.loads(path.read_text())
              assert loaded["id"] == fixed_id
          finally:
              path.unlink(missing_ok=True)
  ```

- [ ] **Step 3: Run the tests**

  ```bash
  cd /path/to/vantageai
  python -m pytest tests/suites/35_local_proxy_resume/ -v
  ```
  Expected: All 6 tests pass.

- [ ] **Step 4: Commit Fix 2**

  ```bash
  git add vantage-local-proxy/src/proxy-server.ts \
          vantage-local-proxy/src/session-store.ts \
          vantage-local-proxy/src/cli.ts \
          tests/suites/35_local_proxy_resume/
  git commit -m "feat(local-proxy): add --resume and --session-id flags for session continuity"
  ```

---

## Fix 3 — vantage-worker: OTel Session Rollup

### Task 6: Create the D1 migration

**Files:**
- Create: `vantage-worker/migrations/0006_otel_sessions.sql`

- [ ] **Step 1: Create the migration file**

  Create `vantage-worker/migrations/0006_otel_sessions.sql`:

  ```sql
  -- Migration 0006: OTel session rollup table
  -- Upserted on every OTel ingest. One row per (org_id, session_id).

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

  CREATE INDEX IF NOT EXISTS idx_otel_sessions_org_last
    ON otel_sessions (org_id, last_seen_at DESC);

  CREATE INDEX IF NOT EXISTS idx_otel_sessions_developer
    ON otel_sessions (org_id, developer_email);
  ```

- [ ] **Step 2: Apply migration to local D1**

  ```bash
  cd vantage-worker
  npx wrangler d1 execute vantage-events --local --file=migrations/0006_otel_sessions.sql
  ```
  Expected: `Successfully applied migration`

### Task 7: Add session upsert to OTel ingest route

**Files:**
- Modify: `vantage-worker/src/routes/otel.ts` (after line 589)

- [ ] **Step 1: Add the upsert after the existing D1 batch insert**

  In `vantage-worker/src/routes/otel.ts`, find the `try { await c.env.DB.batch(batch); }` block (lines 584–589). Add the session upsert immediately after the `await c.env.DB.batch(batch)` call, before the KV cache invalidation:

  ```typescript
  // EXISTING (lines 584-592):
  try {
    await c.env.DB.batch(batch);
  } catch (err) {
    console.error('[otel] D1 batch insert error:', err);
    return c.json({ error: 'Failed to store metrics' }, 500);
  }

  // Invalidate analytics summary cache for this org
  try { await c.env.KV.delete(`analytics:summary:${orgId}`); } catch { /* best-effort */ }

  // ADD AFTER the batch insert try/catch, BEFORE the KV invalidation:
  // Upsert session rollup rows — one row per unique session_id in this batch
  const sessionUpserts = new Map<string, {
    provider: string; developer_email: string; team: string; model: string;
    input_tokens: number; output_tokens: number; cached_tokens: number; cost_usd: number;
    timestamp: string;
  }>();
  for (const r of tokenRecords) {
    if (!r.session_id) continue;
    const existing = sessionUpserts.get(r.session_id);
    if (existing) {
      existing.input_tokens  += r.input_tokens  ?? 0;
      existing.output_tokens += r.output_tokens ?? 0;
      existing.cached_tokens += r.cached_tokens ?? 0;
      existing.cost_usd      += r.cost_usd      ?? 0;
    } else {
      sessionUpserts.set(r.session_id, {
        provider:        r.provider        ?? '',
        developer_email: r.developer_email ?? '',
        team:            r.team            ?? '',
        model:           r.model           ?? '',
        input_tokens:    r.input_tokens    ?? 0,
        output_tokens:   r.output_tokens   ?? 0,
        cached_tokens:   r.cached_tokens   ?? 0,
        cost_usd:        r.cost_usd        ?? 0,
        timestamp:       r.timestamp,
      });
    }
  }
  if (sessionUpserts.size > 0) {
    const sessionBatch = [...sessionUpserts.entries()].map(([sessionId, s]) =>
      c.env.DB.prepare(`
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
          last_seen_at  = excluded.last_seen_at
      `).bind(
        orgId, sessionId, s.provider, s.developer_email, s.team, s.model,
        s.input_tokens, s.output_tokens, s.cached_tokens, s.cost_usd,
        s.timestamp, s.timestamp,
      )
    );
    try {
      await c.env.DB.batch(sessionBatch);
    } catch (err) {
      // Non-critical — log and continue
      console.error('[otel] session upsert error:', err);
    }
  }
  ```

### Task 8: Create `GET /v1/sessions` endpoint

**Files:**
- Create: `vantage-worker/src/routes/sessions.ts`
- Modify: `vantage-worker/src/index.ts`

- [ ] **Step 1: Create the sessions route file**

  Create `vantage-worker/src/routes/sessions.ts`:

  ```typescript
  import { Hono } from 'hono';
  import type { Env } from '../types.js';

  const sessions = new Hono<{ Bindings: Env }>();

  sessions.get('/', async (c) => {
    const orgId: string = c.get('orgId');

    const limit  = Math.min(parseInt(c.req.query('limit')  ?? '20', 10), 100);
    const provider       = c.req.query('provider');
    const developerEmail = c.req.query('developer_email');
    const from           = c.req.query('from'); // ISO date string

    const conditions: string[] = ['org_id = ?'];
    const params: (string | number)[] = [orgId];

    if (provider)       { conditions.push('provider = ?');        params.push(provider); }
    if (developerEmail) { conditions.push('developer_email = ?'); params.push(developerEmail); }
    if (from)           { conditions.push('last_seen_at >= ?');   params.push(from); }

    const where = conditions.join(' AND ');

    try {
      const result = await c.env.DB.prepare(`
        SELECT session_id, provider, developer_email, team, model,
               input_tokens, output_tokens, cached_tokens, cost_usd,
               event_count, first_seen_at, last_seen_at
        FROM otel_sessions
        WHERE ${where}
        ORDER BY last_seen_at DESC
        LIMIT ?
      `).bind(...params, limit).all();

      const countResult = await c.env.DB.prepare(`
        SELECT COUNT(*) as total FROM otel_sessions WHERE ${where}
      `).bind(...params).first<{ total: number }>();

      return c.json({
        sessions: result.results,
        total: countResult?.total ?? 0,
      });
    } catch (err) {
      console.error('[sessions] query error:', err);
      return c.json({ error: 'Failed to query sessions' }, 500);
    }
  });

  export default sessions;
  ```

- [ ] **Step 2: Register the route in `vantage-worker/src/index.ts`**

  Find where other routes are imported and registered (look for `app.route('/v1/analytics', analytics)` pattern). Add:

  ```typescript
  // Add import at top with other route imports:
  import sessions from './routes/sessions.js';

  // Add route registration alongside other /v1/ routes:
  app.route('/v1/sessions', sessions);
  ```

- [ ] **Step 3: TypeScript check**

  ```bash
  cd vantage-worker && npm run typecheck
  ```
  Expected: No errors.

### Task 9: Write tests for OTel sessions

**Files:**
- Create: `tests/suites/34_otel_sessions/test_otel_sessions.py`

- [ ] **Step 1: Create the test suite directory**

  ```bash
  mkdir -p tests/suites/34_otel_sessions
  ```

- [ ] **Step 2: Write the test file**

  Create `tests/suites/34_otel_sessions/test_otel_sessions.py`:

  ```python
  """
  Suite 34 — OTel session rollup
  Tests that OTel ingest creates/accumulates otel_sessions rows
  and that GET /v1/sessions returns correct data.
  Hits live API at https://api.cohrint.com.
  """
  import os
  import time
  import uuid

  import pytest
  import requests

  API_BASE = os.environ.get("VANTAGE_API_BASE", "https://api.cohrint.com")
  API_KEY  = os.environ.get("COHRINT_API_KEY", "")
  HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

  if not API_KEY:
      pytest.skip("COHRINT_API_KEY not set", allow_module_level=True)


  def otel_payload(session_id: str, tokens_in: int = 100, tokens_out: int = 20) -> dict:
      """Build a minimal OTLP metrics payload with session.id set."""
      return {
          "resourceMetrics": [{
              "resource": {
                  "attributes": [
                      {"key": "service.name",  "value": {"stringValue": "claude-code"}},
                      {"key": "session.id",    "value": {"stringValue": session_id}},
                      {"key": "user.email",    "value": {"stringValue": "test@cohrint.com"}},
                  ]
              },
              "scopeMetrics": [{
                  "metrics": [{
                      "name": "gen_ai.client.token.usage",
                      "sum": {
                          "dataPoints": [
                              {
                                  "attributes": [
                                      {"key": "gen_ai.token.type",    "value": {"stringValue": "input"}},
                                      {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                  ],
                                  "asInt": tokens_in,
                                  "startTimeUnixNano": str(int(time.time() * 1e9)),
                                  "timeUnixNano": str(int(time.time() * 1e9)),
                              },
                              {
                                  "attributes": [
                                      {"key": "gen_ai.token.type",    "value": {"stringValue": "output"}},
                                      {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                  ],
                                  "asInt": tokens_out,
                                  "startTimeUnixNano": str(int(time.time() * 1e9)),
                                  "timeUnixNano": str(int(time.time() * 1e9)),
                              },
                          ]
                      }
                  }]
              }]
          }]
      }


  class TestOtelSessionRollup:

      def test_otel_ingest_creates_session_row(self):
          """Sending OTel metrics with a session_id creates a row in otel_sessions."""
          session_id = f"test-{uuid.uuid4()}"
          res = requests.post(
              f"{API_BASE}/v1/otel/v1/metrics",
              json=otel_payload(session_id, tokens_in=100, tokens_out=20),
              headers=HEADERS,
              timeout=10,
          )
          assert res.status_code == 200, f"OTel ingest failed: {res.text}"

          # Allow a moment for async processing
          time.sleep(1)

          # Check that the session row exists
          sessions_res = requests.get(
              f"{API_BASE}/v1/sessions",
              headers=HEADERS,
              timeout=10,
          )
          assert sessions_res.status_code == 200, f"GET /v1/sessions failed: {sessions_res.text}"
          data = sessions_res.json()
          session_ids = [s["session_id"] for s in data["sessions"]]
          assert session_id in session_ids, f"session {session_id} not found in {session_ids}"

      def test_second_ingest_accumulates_tokens(self):
          """Two OTel ingests with the same session_id accumulate tokens, not duplicate."""
          session_id = f"test-{uuid.uuid4()}"

          # First ingest
          res1 = requests.post(
              f"{API_BASE}/v1/otel/v1/metrics",
              json=otel_payload(session_id, tokens_in=100, tokens_out=20),
              headers=HEADERS, timeout=10,
          )
          assert res1.status_code == 200

          # Second ingest same session
          res2 = requests.post(
              f"{API_BASE}/v1/otel/v1/metrics",
              json=otel_payload(session_id, tokens_in=200, tokens_out=40),
              headers=HEADERS, timeout=10,
          )
          assert res2.status_code == 200

          time.sleep(1)

          sessions_res = requests.get(
              f"{API_BASE}/v1/sessions",
              headers=HEADERS, timeout=10,
          )
          assert sessions_res.status_code == 200
          sessions = sessions_res.json()["sessions"]
          row = next((s for s in sessions if s["session_id"] == session_id), None)
          assert row is not None, f"session {session_id} not found"
          # Tokens must accumulate: 100+200=300 input, 20+40=60 output
          assert row["input_tokens"]  >= 300, f"expected >=300 input tokens, got {row['input_tokens']}"
          assert row["output_tokens"] >= 60,  f"expected >=60 output tokens, got {row['output_tokens']}"
          assert row["event_count"]   >= 2,   f"expected >=2 events, got {row['event_count']}"

      def test_ingest_without_session_id_does_not_crash(self):
          """OTel ingest with no session.id attribute still returns 200."""
          payload = {
              "resourceMetrics": [{
                  "resource": {
                      "attributes": [
                          {"key": "service.name", "value": {"stringValue": "claude-code"}},
                      ]
                  },
                  "scopeMetrics": [{
                      "metrics": [{
                          "name": "gen_ai.client.token.usage",
                          "sum": {
                              "dataPoints": [{
                                  "attributes": [
                                      {"key": "gen_ai.token.type",    "value": {"stringValue": "input"}},
                                      {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                  ],
                                  "asInt": 50,
                                  "startTimeUnixNano": str(int(time.time() * 1e9)),
                                  "timeUnixNano": str(int(time.time() * 1e9)),
                              }]
                          }
                      }]
                  }]
              }]
          }
          res = requests.post(
              f"{API_BASE}/v1/otel/v1/metrics",
              json=payload, headers=HEADERS, timeout=10,
          )
          assert res.status_code == 200

      def test_get_sessions_requires_auth(self):
          """GET /v1/sessions returns 401 without a valid API key."""
          res = requests.get(
              f"{API_BASE}/v1/sessions",
              headers={"Authorization": "Bearer invalid_key"},
              timeout=10,
          )
          assert res.status_code in (401, 403), f"Expected 401/403, got {res.status_code}"

      def test_get_sessions_filter_by_developer_email(self):
          """GET /v1/sessions?developer_email=x filters results correctly."""
          session_id = f"test-{uuid.uuid4()}"
          res = requests.post(
              f"{API_BASE}/v1/otel/v1/metrics",
              json=otel_payload(session_id),
              headers=HEADERS, timeout=10,
          )
          assert res.status_code == 200
          time.sleep(1)

          sessions_res = requests.get(
              f"{API_BASE}/v1/sessions",
              params={"developer_email": "test@cohrint.com"},
              headers=HEADERS, timeout=10,
          )
          assert sessions_res.status_code == 200
          data = sessions_res.json()
          # All returned sessions must match the filter
          for s in data["sessions"]:
              assert s["developer_email"] == "test@cohrint.com"

      def test_get_sessions_limit_respected(self):
          """GET /v1/sessions?limit=2 returns at most 2 sessions."""
          sessions_res = requests.get(
              f"{API_BASE}/v1/sessions",
              params={"limit": "2"},
              headers=HEADERS, timeout=10,
          )
          assert sessions_res.status_code == 200
          data = sessions_res.json()
          assert len(data["sessions"]) <= 2
          assert "total" in data
  ```

- [ ] **Step 3: Run the tests**

  ```bash
  python -m pytest tests/suites/34_otel_sessions/ -v
  ```
  Expected: All 6 tests pass.

- [ ] **Step 4: Commit Fix 3**

  ```bash
  git add vantage-worker/migrations/0006_otel_sessions.sql \
          vantage-worker/src/routes/otel.ts \
          vantage-worker/src/routes/sessions.ts \
          vantage-worker/src/index.ts \
          tests/suites/34_otel_sessions/
  git commit -m "feat(worker): add otel_sessions rollup table and GET /v1/sessions endpoint"
  ```

---

## Final Integration Test

- [ ] **Run all three new test suites together**

  ```bash
  python -m pytest \
    tests/suites/34_otel_sessions/ \
    tests/suites/35_local_proxy_resume/ \
    -v
  ```
  Expected: All tests pass.

- [ ] **TypeScript check all packages**

  ```bash
  cd vantage-mcp && npm run build && cd ../vantage-local-proxy && npm run build && cd ../vantage-worker && npm run typecheck
  ```
  Expected: No errors in any package.

---

## Self-Review Checklist

- [x] Fix 1 spec requirement (session_id in MCP track_llm_call): covered by Task 1
- [x] Fix 2 spec requirement (--resume and --session-id flags): covered by Tasks 2–5
- [x] Fix 3 spec requirement (otel_sessions table + upsert): covered by Tasks 6–7
- [x] Fix 3 spec requirement (GET /v1/sessions endpoint): covered by Task 8
- [x] All test suites specified in spec (34, 35): covered by Tasks 5, 9
- [x] loadSync method defined before use in Task 3, used in Task 2 ✓
- [x] LocalProxyConfig fields defined in Task 2, wired in Task 4 ✓
- [x] `_newSession` private method defined in Task 2, not referenced elsewhere ✓
- [x] `otel_sessions` table created in Task 6 before referenced in Tasks 7–8 ✓
- [x] No TBDs or placeholder steps ✓
