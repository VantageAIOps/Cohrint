-- T018: Raise default min_prompt_length from 10 → 100 for new orgs.
-- Rationale: embedding + vector query round-trip costs more than the LLM
-- call for cheap models on short prompts; caching is net-negative below ~100 chars.
-- Existing orgs keep their current setting unchanged.

UPDATE org_cache_config
SET min_prompt_length = 100
WHERE min_prompt_length = 10;
