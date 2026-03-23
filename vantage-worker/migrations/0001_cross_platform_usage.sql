-- VantageAI v2 — Cross-Platform Usage Table
-- Stores data from BOTH OTel telemetry (real-time) and billing API connectors (hourly)
-- Sources: Claude Code, Copilot Chat, Gemini CLI, Cursor Admin API, OpenAI Usage API, Anthropic Admin API

CREATE TABLE IF NOT EXISTS cross_platform_usage (
  id                    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id                TEXT NOT NULL,
  provider              TEXT NOT NULL,   -- 'claude_code' | 'copilot_chat' | 'gemini_cli' | 'codex_cli' | 'cline' | 'opencode' | 'kiro' | 'windsurf' | 'aider' | 'roo_code' | 'cursor' | 'openai_api' | 'anthropic_api' | 'custom_api'
  tool_type             TEXT NOT NULL,   -- 'coding_assistant' | 'api' | 'chat' | 'cli'
  source                TEXT NOT NULL DEFAULT 'billing_api',  -- 'otel' | 'billing_api' | 'sdk'
  developer_id          TEXT,            -- user.account_uuid (Claude), user.id (generic)
  developer_email       TEXT,            -- user.email from OTel or billing API
  team                  TEXT,            -- OTEL_RESOURCE_ATTRIBUTES team.id or billing API team
  cost_center           TEXT,            -- OTEL_RESOURCE_ATTRIBUTES cost_center
  model                 TEXT,            -- claude-sonnet-4-6, gpt-4o, gemini-2.0-flash, etc.
  input_tokens          INTEGER DEFAULT 0,
  output_tokens         INTEGER DEFAULT 0,
  cached_tokens         INTEGER DEFAULT 0,
  cache_creation_tokens INTEGER DEFAULT 0,
  total_requests        INTEGER DEFAULT 0,
  cost_usd              REAL NOT NULL DEFAULT 0,
  -- OTel-specific fields (null for billing API source)
  session_id            TEXT,            -- OTel session.id
  terminal_type         TEXT,            -- 'vscode' | 'cursor' | 'iTerm.app' | 'tmux'
  lines_added           INTEGER DEFAULT 0,
  lines_removed         INTEGER DEFAULT 0,
  commits               INTEGER DEFAULT 0,
  pull_requests         INTEGER DEFAULT 0,
  active_time_s         REAL DEFAULT 0,
  ttft_ms               REAL,
  latency_ms            REAL,
  -- Time range
  period_start          TEXT NOT NULL,   -- ISO 8601
  period_end            TEXT NOT NULL,   -- ISO 8601
  raw_data              TEXT,            -- JSON: original OTel payload or billing API response
  synced_at             TEXT DEFAULT (datetime('now')),
  created_at            TEXT DEFAULT (datetime('now'))
);

-- Per-developer queries (main dashboard use case)
CREATE INDEX IF NOT EXISTS idx_cpu_org_dev ON cross_platform_usage(org_id, developer_email, created_at DESC);

-- Per-provider aggregation
CREATE INDEX IF NOT EXISTS idx_cpu_org_provider ON cross_platform_usage(org_id, provider, created_at DESC);

-- OTel session correlation
CREATE INDEX IF NOT EXISTS idx_cpu_session ON cross_platform_usage(session_id) WHERE session_id IS NOT NULL;

-- Time-range queries for dashboards
CREATE INDEX IF NOT EXISTS idx_cpu_org_time ON cross_platform_usage(org_id, period_start DESC);

-- Source filtering (otel vs billing_api)
CREATE INDEX IF NOT EXISTS idx_cpu_source ON cross_platform_usage(org_id, source);

-- ── OTel Events Table (lightweight audit log) ───────────────────────────────
-- Stores all OTel log events (user_prompt, api_request, tool_result, api_error)
-- for debugging, audit trails, and detailed per-session analysis

CREATE TABLE IF NOT EXISTS otel_events (
  id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id            TEXT NOT NULL,
  provider          TEXT NOT NULL,
  session_id        TEXT,
  developer_email   TEXT,
  event_name        TEXT NOT NULL,    -- 'api_request' | 'tool_result' | 'user_prompt' | 'api_error'
  model             TEXT,
  cost_usd          REAL DEFAULT 0,
  tokens_in         INTEGER DEFAULT 0,
  tokens_out        INTEGER DEFAULT 0,
  duration_ms       REAL DEFAULT 0,
  timestamp         TEXT NOT NULL,
  raw_attrs         TEXT,             -- JSON: all OTel attributes
  created_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_oe_org_time ON otel_events(org_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_oe_session ON otel_events(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_oe_developer ON otel_events(org_id, developer_email, timestamp DESC);

-- ── Provider Connections Table ──────────────────────────────────────────────
-- Stores encrypted credentials for billing API connectors

CREATE TABLE IF NOT EXISTS provider_connections (
  id                    TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id                TEXT NOT NULL,
  provider              TEXT NOT NULL,   -- 'copilot' | 'cursor' | 'openai' | 'anthropic' | 'google'
  credentials           TEXT NOT NULL,   -- JSON: encrypted API keys/tokens
  status                TEXT DEFAULT 'pending',  -- 'pending' | 'active' | 'error' | 'expired'
  last_sync_at          TEXT,
  last_error            TEXT,
  sync_interval_minutes INTEGER DEFAULT 60,
  created_at            TEXT DEFAULT (datetime('now')),
  UNIQUE(org_id, provider)
);

-- ── Budget Policies Table ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS budget_policies (
  id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id              TEXT NOT NULL,
  scope               TEXT NOT NULL,    -- 'org' | 'team' | 'developer'
  scope_target        TEXT,             -- team name or developer email (null for org)
  monthly_limit_usd   REAL NOT NULL,
  alert_threshold_50  INTEGER DEFAULT 1,
  alert_threshold_80  INTEGER DEFAULT 1,
  alert_threshold_100 INTEGER DEFAULT 1,
  enforcement         TEXT DEFAULT 'alert',  -- 'alert' | 'throttle' | 'block'
  created_at          TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bp_org ON budget_policies(org_id);
