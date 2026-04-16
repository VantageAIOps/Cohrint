-- Add team_id to semantic_cache_entries for per-team cache isolation
-- Existing entries get NULL team_id (org-wide scope, backward compatible)

ALTER TABLE semantic_cache_entries ADD COLUMN team_id TEXT REFERENCES teams(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_semantic_cache_org_team_model
  ON semantic_cache_entries(org_id, team_id, model, created_at DESC);
