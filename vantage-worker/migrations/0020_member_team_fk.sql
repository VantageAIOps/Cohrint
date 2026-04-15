-- Migration 0020: Add team_id FK to org_members
-- team_id is NULL for standalone-team-account members.
-- For organization accounts, team_id points to teams(org_id, id).
-- scope_team (free-text) is preserved for backward compat.

ALTER TABLE org_members ADD COLUMN team_id TEXT
  REFERENCES teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_members_team
  ON org_members(team_id) WHERE team_id IS NOT NULL;
