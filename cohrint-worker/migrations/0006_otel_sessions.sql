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
