-- Migration 0020: Add team_id to org_members
-- team_id is NULL for standalone-team-account members.
-- For organization accounts, team_id references the team within the same org.
--
-- NOTE: teams table has a composite PK (org_id, id) — team slugs like "backend"
-- are only unique per-org, not globally. A single-column FK on teams(id) would
-- be semantically broken. Cross-org integrity is enforced at the application
-- layer: every write validates WHERE id = ? AND org_id = ? before INSERT/UPDATE.
-- No DB-level FK is declared here to avoid a false sense of referential safety.

ALTER TABLE org_members ADD COLUMN team_id TEXT;

CREATE INDEX IF NOT EXISTS idx_members_team
  ON org_members(team_id) WHERE team_id IS NOT NULL;
