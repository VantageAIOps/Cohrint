-- Track per-org dashboard version and opt-in upgrade timing
CREATE TABLE IF NOT EXISTS org_versions (
  org_id          TEXT    NOT NULL PRIMARY KEY REFERENCES orgs(id),
  current_version TEXT    NOT NULL DEFAULT 'v1.0.0',
  upgraded_at     INTEGER,                               -- unixepoch of last upgrade
  created_at      INTEGER NOT NULL DEFAULT (unixepoch())
);
