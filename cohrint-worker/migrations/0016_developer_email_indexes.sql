-- VantageAI — Add developer_email to events + compound indexes for enterprise queries

-- 1. Add developer_email to events table (was missing; cross_platform_usage already has it)
ALTER TABLE events ADD COLUMN developer_email TEXT;
CREATE INDEX IF NOT EXISTS idx_events_org_dev_email ON events(org_id, developer_email) WHERE developer_email IS NOT NULL;

-- 2. Add business_unit to events table (missing from migration 0015 which only added to cross_platform_usage + otel_events)
ALTER TABLE events ADD COLUMN business_unit TEXT;
CREATE INDEX IF NOT EXISTS idx_events_org_bu ON events(org_id, business_unit) WHERE business_unit IS NOT NULL;

-- 3. Compound indexes for team+time queries (performance for 32-person org at scale)
CREATE INDEX IF NOT EXISTS idx_cpu_org_team_time ON cross_platform_usage(org_id, team, created_at);
CREATE INDEX IF NOT EXISTS idx_cpu_org_provider_time ON cross_platform_usage(org_id, provider, created_at);

-- 4. Index for active-developers query (last N seconds window)
CREATE INDEX IF NOT EXISTS idx_oe_org_ts ON otel_events(org_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_cpu_org_created ON cross_platform_usage(org_id, created_at);
