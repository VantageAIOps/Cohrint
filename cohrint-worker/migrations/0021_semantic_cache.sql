-- Semantic cache: vector-similarity-based LLM response caching
-- Requires Vectorize index: wrangler vectorize create cohrint-semantic-cache --dimensions=384 --metric=cosine

-- Stores cached LLM responses keyed by their Vectorize embedding ID
CREATE TABLE IF NOT EXISTS semantic_cache_entries (
  id            TEXT PRIMARY KEY,
  org_id        TEXT NOT NULL,
  prompt_hash   TEXT NOT NULL,           -- SHA-256 first 16 chars (dedup with events.prompt_hash)
  prompt_text   TEXT NOT NULL,           -- stored for re-embedding on threshold change
  model         TEXT NOT NULL,           -- model the response was generated for
  response_text TEXT NOT NULL,           -- cached LLM response
  prompt_tokens   INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd      REAL NOT NULL DEFAULT 0, -- cost of the original call
  vectorize_id  TEXT,                    -- ID in Vectorize index
  hit_count     INTEGER NOT NULL DEFAULT 0,
  total_savings_usd REAL NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  last_hit_at   TEXT,
  FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_semantic_cache_org_model
  ON semantic_cache_entries(org_id, model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_cache_hash
  ON semantic_cache_entries(org_id, prompt_hash);

-- Per-org cache configuration
CREATE TABLE IF NOT EXISTS org_cache_config (
  org_id              TEXT PRIMARY KEY,
  enabled             INTEGER NOT NULL DEFAULT 1,
  similarity_threshold REAL NOT NULL DEFAULT 0.92,  -- cosine similarity floor [0,1]
  min_prompt_length   INTEGER NOT NULL DEFAULT 10,   -- ignore very short prompts
  max_cache_age_days  INTEGER NOT NULL DEFAULT 30,   -- auto-expire old entries
  created_at          TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE
);
