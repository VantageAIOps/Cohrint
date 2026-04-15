-- Migration 0019: teams table for sub-teams within organization accounts

CREATE TABLE IF NOT EXISTS teams (
  id         TEXT NOT NULL,                              -- slug, e.g. "backend"
  org_id     TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  created_at INTEGER NOT NULL DEFAULT (unixepoch()),
  updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
  deleted_at INTEGER,                                    -- soft delete
  PRIMARY KEY (org_id, id)
);

CREATE INDEX IF NOT EXISTS idx_teams_org ON teams(org_id) WHERE deleted_at IS NULL;
