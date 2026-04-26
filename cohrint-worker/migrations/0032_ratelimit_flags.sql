-- Migration 0032: Rate limiting control flags on orgs
-- is_test = 1        → skip rate limiting entirely (internal / test accounts)
-- rl_org_enabled = 1 → enable org-level rate limit in addition to per-key
--                       (premium accounts only; disabled by default)

ALTER TABLE orgs ADD COLUMN is_test        INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orgs ADD COLUMN rl_org_enabled INTEGER NOT NULL DEFAULT 0;
