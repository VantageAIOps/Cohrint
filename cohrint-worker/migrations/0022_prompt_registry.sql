-- Prompt Registry MVP: versioned prompt templates with cost tracking

CREATE TABLE IF NOT EXISTS prompts (
  id          TEXT PRIMARY KEY,
  org_id      TEXT NOT NULL,
  name        TEXT NOT NULL,
  description TEXT,
  created_by  TEXT NOT NULL,  -- member email
  deleted_at  TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prompts_org
  ON prompts(org_id, deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompts_org_name
  ON prompts(org_id, name) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS prompt_versions (
  id          TEXT PRIMARY KEY,
  prompt_id   TEXT NOT NULL,
  version_num INTEGER NOT NULL,
  content     TEXT NOT NULL,            -- the prompt template text
  model       TEXT,                     -- intended model (NULL = model-agnostic)
  notes       TEXT,                     -- changelog / description
  total_calls       INTEGER NOT NULL DEFAULT 0,
  total_cost_usd    REAL NOT NULL DEFAULT 0,
  avg_cost_usd      REAL NOT NULL DEFAULT 0,
  avg_prompt_tokens INTEGER NOT NULL DEFAULT 0,
  avg_completion_tokens INTEGER NOT NULL DEFAULT 0,
  created_by  TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_prompt
  ON prompt_versions(prompt_id, version_num DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_versions_num
  ON prompt_versions(prompt_id, version_num);

-- Links LLM events (from SDK) to specific prompt versions for cost attribution
CREATE TABLE IF NOT EXISTS prompt_usage (
  id          TEXT PRIMARY KEY,
  version_id  TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  org_id      TEXT NOT NULL,
  cost_usd    REAL NOT NULL DEFAULT 0,
  prompt_tokens     INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (version_id) REFERENCES prompt_versions(id) ON DELETE CASCADE,
  FOREIGN KEY (org_id) REFERENCES orgs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_prompt_usage_version
  ON prompt_usage(version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prompt_usage_org
  ON prompt_usage(org_id, created_at DESC);
