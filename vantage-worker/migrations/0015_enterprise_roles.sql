-- VantageAI — Enterprise Roles + Budget Policy Enhancements
-- Adds superadmin + ceo roles to org_members
-- Extends budget_policies to support 'provider' scope
-- Adds business_unit field to cross_platform_usage + otel_events
-- Adds team to otel_sessions for live-feed team attribution

-- 1. Add business_unit to cross_platform_usage (already has cost_center; add business_unit)
ALTER TABLE cross_platform_usage ADD COLUMN business_unit TEXT;
CREATE INDEX IF NOT EXISTS idx_cpu_org_bu ON cross_platform_usage(org_id, business_unit) WHERE business_unit IS NOT NULL;

-- 2. Add business_unit to otel_events for live-feed team attribution
ALTER TABLE otel_events ADD COLUMN business_unit TEXT;
ALTER TABLE otel_events ADD COLUMN team TEXT;
ALTER TABLE otel_events ADD COLUMN agent_name TEXT;

-- 3. Add updated_at to budget_policies for optimistic concurrency
ALTER TABLE budget_policies ADD COLUMN updated_at TEXT DEFAULT (datetime('now'));

-- 4. Add provider_target to budget_policies for tool-scoped budgets
--    scope='provider' + scope_target='claude_code' means "Claude Code budget = $X/mo"
--    scope='team_provider' allows team + provider combo budget
ALTER TABLE budget_policies ADD COLUMN provider_target TEXT;

-- 5. Ensure index covers new scope types
CREATE INDEX IF NOT EXISTS idx_bp_org_scope ON budget_policies(org_id, scope, scope_target);

-- NOTE: org_members.role is TEXT with no CHECK constraint in SQLite.
-- New valid values: 'superadmin' | 'ceo' (in addition to existing 'admin'|'member'|'viewer')
-- Enforced at application layer in middleware/auth.ts
