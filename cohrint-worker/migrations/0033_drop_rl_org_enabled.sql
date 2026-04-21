-- Migration 0033: Drop rl_org_enabled — org-level rate limiting now driven by plan column
-- plan = 'free'  → per-key rate limiting only
-- plan != 'free' → per-key + org-level rate limiting (set via Stripe webhook when customer pays)

ALTER TABLE orgs DROP COLUMN rl_org_enabled;
