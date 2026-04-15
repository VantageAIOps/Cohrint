-- Migration 0018: Add account_type to orgs
-- Existing orgs default to 'organization' — no data migration needed.

ALTER TABLE orgs ADD COLUMN account_type TEXT NOT NULL DEFAULT 'organization'
  CHECK(account_type IN ('individual', 'team', 'organization'));
