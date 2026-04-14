-- Schema fixes from audit of PR #55
-- 1. Drop the org_id column from platform_sessions — the public POST /session
--    endpoint intentionally never writes it (to prevent unauthenticated session
--    attribution spoofing). Keeping it causes silent schema drift where any
--    analytics query on platform_sessions.org_id returns all NULLs.
-- 2. Add session_id indexes on both platform tables — used in WHERE lookups
--    on every session event; without indexes these are full table scans.

ALTER TABLE platform_sessions DROP COLUMN org_id;

CREATE INDEX IF NOT EXISTS idx_platform_pageviews_session
  ON platform_pageviews(session_id);

CREATE INDEX IF NOT EXISTS idx_platform_sessions_session
  ON platform_sessions(session_id);

-- Also index copilot_connections lookup path used by the cron
CREATE INDEX IF NOT EXISTS idx_copilot_connections_org
  ON copilot_connections(org_id);

-- And datadog_connections
CREATE INDEX IF NOT EXISTS idx_datadog_connections_org
  ON datadog_connections(org_id);
