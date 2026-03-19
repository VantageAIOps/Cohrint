-- ─────────────────────────────────────────────────────────────────────────────
-- VantageAI D1 Schema — Cloudflare SQLite
-- Run: wrangler d1 execute vantage-events --file=schema.sql
-- ─────────────────────────────────────────────────────────────────────────────

-- Organisations & API keys
CREATE TABLE IF NOT EXISTS orgs (
  id            TEXT PRIMARY KEY,
  api_key_hash  TEXT UNIQUE NOT NULL,  -- SHA-256 hex of the raw key
  name          TEXT,
  plan          TEXT NOT NULL DEFAULT 'free',  -- free | starter | team | enterprise
  budget_usd    REAL NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Events (one row per LLM API call)
CREATE TABLE IF NOT EXISTS events (
  id                TEXT PRIMARY KEY,
  org_id            TEXT NOT NULL REFERENCES orgs(id),
  provider          TEXT NOT NULL DEFAULT '',
  model             TEXT NOT NULL DEFAULT '',
  prompt_tokens     INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cache_tokens      INTEGER NOT NULL DEFAULT 0,
  total_tokens      INTEGER NOT NULL DEFAULT 0,
  cost_usd          REAL    NOT NULL DEFAULT 0,
  latency_ms        INTEGER NOT NULL DEFAULT 0,
  -- Attribution
  team              TEXT,
  project           TEXT,
  user_id           TEXT,
  feature           TEXT,
  endpoint          TEXT,
  environment       TEXT NOT NULL DEFAULT 'production',
  -- Streaming
  is_streaming      INTEGER NOT NULL DEFAULT 0,  -- 0|1 boolean
  stream_chunks     INTEGER NOT NULL DEFAULT 0,
  -- Agent tracing
  trace_id          TEXT,
  parent_event_id   TEXT,
  agent_name        TEXT,
  span_depth        INTEGER NOT NULL DEFAULT 0,
  -- Quality scores (patched asynchronously)
  hallucination_score  REAL,
  faithfulness_score   REAL,
  relevancy_score      REAL,
  consistency_score    REAL,
  toxicity_score       REAL,
  efficiency_score     INTEGER,
  -- Extra
  tags              TEXT,       -- JSON object stored as text
  sdk_language      TEXT,       -- python | typescript | javascript | go | ruby
  sdk_version       TEXT,
  created_at        INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_events_org_time    ON events (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_org_model   ON events (org_id, model);
CREATE INDEX IF NOT EXISTS idx_events_org_team    ON events (org_id, team);
CREATE INDEX IF NOT EXISTS idx_events_trace       ON events (trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_created     ON events (created_at DESC);

-- Slack / Teams alert configs (one row per org)
CREATE TABLE IF NOT EXISTS alert_configs (
  org_id       TEXT PRIMARY KEY REFERENCES orgs(id),
  slack_url    TEXT,
  teams_url    TEXT,
  trigger_budget   INTEGER NOT NULL DEFAULT 1,  -- 0|1
  trigger_anomaly  INTEGER NOT NULL DEFAULT 1,
  trigger_daily    INTEGER NOT NULL DEFAULT 0,
  updated_at   INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Org members — each gets their own scoped API key
CREATE TABLE IF NOT EXISTS org_members (
  id            TEXT PRIMARY KEY,
  org_id        TEXT NOT NULL REFERENCES orgs(id),
  email         TEXT NOT NULL,
  name          TEXT,
  role          TEXT NOT NULL DEFAULT 'member',  -- admin | member | viewer
  api_key_hash  TEXT UNIQUE NOT NULL,
  api_key_hint  TEXT,
  scope_team    TEXT,    -- NULL = see all; 'backend' = scoped to that team only
  created_at    INTEGER NOT NULL DEFAULT (unixepoch()),
  UNIQUE(org_id, email)
);
CREATE INDEX IF NOT EXISTS idx_members_org ON org_members (org_id);

-- Per-team budgets (used in admin overview)
CREATE TABLE IF NOT EXISTS team_budgets (
  org_id     TEXT NOT NULL REFERENCES orgs(id),
  team       TEXT NOT NULL,
  budget_usd REAL NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  PRIMARY KEY (org_id, team)
);

-- Budget alerts log (avoid duplicate fires)
CREATE TABLE IF NOT EXISTS alert_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id     TEXT NOT NULL,
  alert_type TEXT NOT NULL,  -- budget_80 | budget_100 | anomaly | daily
  fired_at   INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS idx_alert_log_org ON alert_log (org_id, fired_at DESC);
