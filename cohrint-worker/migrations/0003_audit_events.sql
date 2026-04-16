-- Audit events log — tracks user actions for security & compliance
CREATE TABLE IF NOT EXISTS audit_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id       TEXT NOT NULL,
  actor_email  TEXT NOT NULL DEFAULT '',
  actor_role   TEXT NOT NULL DEFAULT '',
  action       TEXT NOT NULL,
  resource     TEXT NOT NULL DEFAULT '',
  detail       TEXT DEFAULT '',
  ip_address   TEXT DEFAULT '',
  user_agent   TEXT DEFAULT '',
  created_at   INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX IF NOT EXISTS idx_audit_org_time ON audit_events(org_id, created_at DESC);

-- Track last API key usage
ALTER TABLE org_members ADD COLUMN last_used_at INTEGER DEFAULT NULL;
