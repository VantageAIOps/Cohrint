-- Daily rollup: pre-aggregated events per (org, day, model, team)
-- Consumer upserts atomically via INSERT ... ON CONFLICT DO UPDATE
CREATE TABLE IF NOT EXISTS events_daily_rollup (
  org_id        TEXT    NOT NULL,
  date_unix_day INTEGER NOT NULL,  -- Unix timestamp of UTC midnight for the day
  model         TEXT    NOT NULL,
  provider      TEXT    NOT NULL DEFAULT '',
  team          TEXT    NOT NULL DEFAULT '',
  cost_usd      REAL    NOT NULL DEFAULT 0,
  prompt_tokens    INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cache_tokens     INTEGER NOT NULL DEFAULT 0,
  total_tokens     INTEGER NOT NULL DEFAULT 0,
  requests         INTEGER NOT NULL DEFAULT 0,
  cache_hits       INTEGER NOT NULL DEFAULT 0,
  latency_ms_sum   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (org_id, date_unix_day, model, team)
);
CREATE INDEX IF NOT EXISTS idx_rollup_org_date ON events_daily_rollup(org_id, date_unix_day DESC);
