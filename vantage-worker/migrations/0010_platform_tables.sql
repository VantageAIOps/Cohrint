-- Platform tracking tables (pageviews + sessions)
-- Previously created inline via CREATE TABLE IF NOT EXISTS on each request.
-- Moved to migration to follow project conventions and avoid DDL in hot path.

CREATE TABLE IF NOT EXISTS platform_pageviews (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  page       TEXT,
  referrer   TEXT,
  created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS platform_sessions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id       TEXT,
  session_id   TEXT,
  duration_sec INTEGER DEFAULT 0,
  created_at   INTEGER NOT NULL DEFAULT (unixepoch())
);
