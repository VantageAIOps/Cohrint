-- Phase 2: Exact-match duplicate detection
-- Adds prompt_hash (SHA-256 fingerprint, first 16 hex chars) and cache_hit flag to events.

ALTER TABLE events ADD COLUMN prompt_hash TEXT;
ALTER TABLE events ADD COLUMN cache_hit   INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_events_prompt_hash
  ON events(org_id, prompt_hash)
  WHERE prompt_hash IS NOT NULL;
