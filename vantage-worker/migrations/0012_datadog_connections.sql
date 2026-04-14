-- VantageAI — Datadog Connections Table
-- Stores encrypted Datadog API key + site config per org.
-- The API key is AES-256-GCM encrypted (same HKDF pattern as copilot_connections)
-- and stored directly in this table (no KV indirection needed — key is org-scoped).

CREATE TABLE IF NOT EXISTS datadog_connections (
  id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
  org_id           TEXT NOT NULL UNIQUE,
  encrypted_api_key TEXT NOT NULL,           -- AES-256-GCM encrypted, base64
  datadog_site     TEXT NOT NULL DEFAULT 'datadoghq.com', -- datadoghq.com | datadoghq.eu | us3.datadoghq.com | us5.datadoghq.com | ap1.datadoghq.com
  status           TEXT NOT NULL DEFAULT 'active',        -- 'active' | 'error' | 'paused'
  last_synced_at   TEXT,                     -- datetime('now') format after each successful push
  last_error       TEXT,                     -- last error message when status = 'error'
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dc_org    ON datadog_connections(org_id);
CREATE INDEX IF NOT EXISTS idx_dc_status ON datadog_connections(status, last_synced_at);
