-- VantageAI — Copilot Connections Table
-- Stores GitHub org + encrypted PAT for GitHub Copilot Metrics API polling.
-- The token itself is stored encrypted in KV (key: copilot:token:<org_id>:<github_org>).
-- This table only holds metadata so the cron can enumerate which orgs to poll.

CREATE TABLE IF NOT EXISTS copilot_connections (
  id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id          TEXT NOT NULL,
  github_org      TEXT NOT NULL,         -- e.g. 'acme-corp'
  kv_key          TEXT NOT NULL,         -- KV key where encrypted token is stored
  status          TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'error' | 'paused'
  last_synced_at  TEXT,                  -- datetime('now') format after each successful poll
  last_error      TEXT,                  -- last error message if status = 'error'
  created_at      TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(org_id, github_org)
);

CREATE INDEX IF NOT EXISTS idx_cc_org ON copilot_connections(org_id);
CREATE INDEX IF NOT EXISTS idx_cc_status ON copilot_connections(status, last_synced_at);
