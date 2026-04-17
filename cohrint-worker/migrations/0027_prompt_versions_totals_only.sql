-- T005: Add total_prompt_tokens and total_completion_tokens columns so we
-- can compute averages on-read rather than in a read-modify-write.
-- The avg_* columns are kept for backward compat but deprecated.
ALTER TABLE prompt_versions ADD COLUMN total_prompt_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE prompt_versions ADD COLUMN total_completion_tokens INTEGER NOT NULL DEFAULT 0;

-- Backfill approximate values from existing avg columns
UPDATE prompt_versions
SET total_prompt_tokens = CAST(avg_prompt_tokens * total_calls AS INTEGER),
    total_completion_tokens = CAST(avg_completion_tokens * total_calls AS INTEGER)
WHERE total_calls > 0;
