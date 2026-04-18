-- T008: Add composite indexes on events for per-org time-range scans.
-- Without these, every analytics query does a full table scan because
-- the PK is (id, org_id) and time predicates can't use it.
--
-- These three indexes cover the three most common WHERE patterns:
--   1. Basic org + time window (summary, kpis, timeseries)
--   2. Trace detail queries (trace_id lookup within org)
--   3. Team-scoped analytics (team dashboard)

CREATE INDEX IF NOT EXISTS idx_events_org_created
  ON events(org_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_org_trace
  ON events(org_id, trace_id, created_at);

CREATE INDEX IF NOT EXISTS idx_events_org_team_created
  ON events(org_id, team, created_at DESC);

ANALYZE events;
