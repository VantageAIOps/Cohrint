-- Migration 0017: Add CHECK constraint on org_members.role
-- SQLite requires table recreation to add CHECK constraints

PRAGMA foreign_keys=OFF;

CREATE TABLE org_members_new (
  id            TEXT PRIMARY KEY,
  org_id        TEXT NOT NULL REFERENCES orgs(id),
  email         TEXT NOT NULL,
  name          TEXT,
  role          TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('owner','superadmin','ceo','admin','member','viewer')),
  api_key_hash  TEXT UNIQUE NOT NULL,
  api_key_hint  TEXT,
  scope_team    TEXT,
  created_at    INTEGER NOT NULL DEFAULT (unixepoch()),
  last_used_at  INTEGER DEFAULT NULL,
  UNIQUE(org_id, email)
);

INSERT INTO org_members_new SELECT * FROM org_members;

DROP TABLE org_members;
ALTER TABLE org_members_new RENAME TO org_members;

CREATE INDEX IF NOT EXISTS idx_members_org ON org_members (org_id);

PRAGMA foreign_keys=ON;
