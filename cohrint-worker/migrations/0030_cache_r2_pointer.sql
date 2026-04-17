-- Release A: add nullable R2 pointer to semantic_cache_entries.
-- When CACHE_BUCKET is bound and R2 put succeeds, this column is set to
-- "cache/{orgId}/{entryId}" and response bodies are stored in R2.
-- D1 response_text remains the authoritative fallback during Release A.
--
-- Release B (later): stop writing response_text for new entries.
-- Release C (later): backfill old entries to R2, then drop response_text.
ALTER TABLE semantic_cache_entries ADD COLUMN response_r2_key TEXT;
