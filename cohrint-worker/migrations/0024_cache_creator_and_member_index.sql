-- 0024 — cache entry creator attribution + org_members (org_id, email) lookup index
--
-- Two small, complementary schema changes in one migration:
--
-- 1) semantic_cache_entries.created_by_member_id
--    0023 added team_id (nullable = org-wide scope). Without a stable creator
--    reference we cannot ever reconstruct team_id for historical entries, so
--    we track the authoring member from this point forward. Existing rows
--    keep team_id = NULL and created_by_member_id = NULL by design
--    (documented "org-wide scope, backward compatible" in 0023).
--
-- 2) idx_org_members_org_email
--    /v1/auth/session and /v1/auth/demo validate an API key by hash. Member
--    management (invite / revoke / update) then does lookups by (org_id, email)
--    to check for duplicates (auth.ts, teams.ts POST /:id/members). Without an
--    index this becomes a full scan on org_members per invite. An expression
--    on email (lower) is not portable in D1; rely on the app consistently
--    lowercasing email before bind (current behaviour in auth.ts/teams.ts).

ALTER TABLE semantic_cache_entries
  ADD COLUMN created_by_member_id TEXT REFERENCES org_members(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_org_members_org_email
  ON org_members(org_id, email);
