-- ============================================================
-- VantageAI — ai_events table migration
-- Run AFTER supabase-schema.sql
-- Supabase Dashboard → SQL Editor → Run
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_events (
  -- Identity
  event_id     TEXT PRIMARY KEY,
  timestamp    DOUBLE PRECISION NOT NULL,
  org_id       UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  environment  TEXT NOT NULL DEFAULT 'production',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Request context
  provider     TEXT NOT NULL DEFAULT '',
  model        TEXT NOT NULL DEFAULT '',
  endpoint     TEXT NOT NULL DEFAULT '',
  session_id   TEXT NOT NULL DEFAULT '',
  user_id      TEXT NOT NULL DEFAULT '',
  feature      TEXT NOT NULL DEFAULT '',
  project      TEXT NOT NULL DEFAULT '',
  team         TEXT NOT NULL DEFAULT '',
  tags         JSONB NOT NULL DEFAULT '{}',

  -- Performance
  latency_ms   DOUBLE PRECISION NOT NULL DEFAULT 0,
  ttft_ms      DOUBLE PRECISION NOT NULL DEFAULT 0,
  status_code  INTEGER NOT NULL DEFAULT 200,
  error        TEXT,

  -- Token usage
  usage_prompt_tokens        INTEGER NOT NULL DEFAULT 0,
  usage_completion_tokens    INTEGER NOT NULL DEFAULT 0,
  usage_total_tokens         INTEGER NOT NULL DEFAULT 0,
  usage_cached_tokens        INTEGER NOT NULL DEFAULT 0,
  usage_system_prompt_tokens INTEGER NOT NULL DEFAULT 0,

  -- Cost (USD)
  cost_input_cost_usd        NUMERIC(14,8) NOT NULL DEFAULT 0,
  cost_output_cost_usd       NUMERIC(14,8) NOT NULL DEFAULT 0,
  cost_total_cost_usd        NUMERIC(14,8) NOT NULL DEFAULT 0,
  cost_cheapest_model        TEXT NOT NULL DEFAULT '',
  cost_cheapest_cost_usd     NUMERIC(14,8) NOT NULL DEFAULT 0,
  cost_potential_saving_usd  NUMERIC(14,8) NOT NULL DEFAULT 0,

  -- Quality (filled async by Claude Opus 4.6 judge — -1 = not yet evaluated)
  quality_hallucination_score     DOUBLE PRECISION DEFAULT -1,
  quality_hallucination_type      TEXT DEFAULT '',
  quality_hallucination_detail    TEXT DEFAULT '',
  quality_coherence_score         DOUBLE PRECISION DEFAULT -1,
  quality_relevance_score         DOUBLE PRECISION DEFAULT -1,
  quality_completeness_score      DOUBLE PRECISION DEFAULT -1,
  quality_factuality_score        DOUBLE PRECISION DEFAULT -1,
  quality_toxicity_score          DOUBLE PRECISION DEFAULT -1,
  quality_overall_quality         DOUBLE PRECISION DEFAULT -1,
  quality_prompt_clarity_score    DOUBLE PRECISION DEFAULT -1,
  quality_prompt_efficiency_score DOUBLE PRECISION DEFAULT -1,
  quality_evaluated_by            TEXT DEFAULT '',
  quality_eval_latency_ms         DOUBLE PRECISION DEFAULT 0,

  -- Request/response previews (truncated, for eval only)
  request_preview   TEXT DEFAULT '',
  response_preview  TEXT DEFAULT '',
  system_preview    TEXT DEFAULT '',
  prompt_hash       TEXT DEFAULT ''
);

-- ── Row Level Security ────────────────────────────────────────────────────────
ALTER TABLE ai_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "events_select" ON ai_events
  FOR SELECT USING (org_id = my_org_id());

-- Service role can insert (used by the ingest server)
CREATE POLICY "events_insert" ON ai_events
  FOR INSERT WITH CHECK (true);

CREATE POLICY "events_update" ON ai_events
  FOR UPDATE USING (true);  -- used by eval worker to write quality scores

-- ── Indexes for common dashboard queries ──────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_events_org_ts       ON ai_events(org_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_org_model    ON ai_events(org_id, model);
CREATE INDEX IF NOT EXISTS idx_events_org_team     ON ai_events(org_id, team);
CREATE INDEX IF NOT EXISTS idx_events_org_project  ON ai_events(org_id, project);
CREATE INDEX IF NOT EXISTS idx_events_org_feature  ON ai_events(org_id, feature);
CREATE INDEX IF NOT EXISTS idx_events_prompt_hash  ON ai_events(org_id, prompt_hash);
CREATE INDEX IF NOT EXISTS idx_events_hallucination ON ai_events(org_id, quality_hallucination_score)
  WHERE quality_hallucination_score >= 0;

-- ── Helper view: daily stats per model ────────────────────────────────────────
CREATE OR REPLACE VIEW v_daily_model_stats AS
SELECT
  org_id,
  DATE(to_timestamp(timestamp)) AS date,
  model,
  provider,
  team,
  project,
  COUNT(*)                                          AS request_count,
  SUM(usage_prompt_tokens)                          AS prompt_tokens,
  SUM(usage_completion_tokens)                      AS completion_tokens,
  SUM(usage_total_tokens)                           AS total_tokens,
  SUM(usage_cached_tokens)                          AS cached_tokens,
  SUM(cost_total_cost_usd)                          AS total_cost_usd,
  SUM(cost_potential_saving_usd)                    AS potential_savings_usd,
  AVG(latency_ms)                                   AS avg_latency_ms,
  PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS p50_latency,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99_latency,
  SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END)::FLOAT /
    NULLIF(COUNT(*),0) * 100                        AS error_rate_pct,
  AVG(CASE WHEN quality_overall_quality >= 0
      THEN quality_overall_quality END)             AS avg_quality,
  AVG(CASE WHEN quality_hallucination_score >= 0
      THEN quality_hallucination_score END)         AS avg_hallucination_score
FROM ai_events
GROUP BY 1,2,3,4,5,6;

-- ── Helper view: team summary ─────────────────────────────────────────────────
CREATE OR REPLACE VIEW v_team_summary AS
SELECT
  org_id,
  team,
  COUNT(*)                          AS total_requests,
  SUM(cost_total_cost_usd)          AS total_cost_usd,
  SUM(usage_total_tokens)           AS total_tokens,
  AVG(latency_ms)                   AS avg_latency_ms,
  AVG(quality_overall_quality)      AS avg_quality,
  AVG(quality_hallucination_score)  AS avg_hallucination,
  SUM(cost_potential_saving_usd)    AS potential_savings_usd,
  COUNT(DISTINCT model)             AS models_used,
  COUNT(DISTINCT project)           AS projects
FROM ai_events
GROUP BY 1,2;

-- ── Update usage_daily to include team/project ────────────────────────────────
ALTER TABLE usage_daily ADD COLUMN IF NOT EXISTS team    TEXT DEFAULT '';
ALTER TABLE usage_daily ADD COLUMN IF NOT EXISTS project TEXT DEFAULT '';
ALTER TABLE usage_daily ADD COLUMN IF NOT EXISTS error_count      INTEGER DEFAULT 0;
ALTER TABLE usage_daily ADD COLUMN IF NOT EXISTS total_latency_ms DOUBLE PRECISION DEFAULT 0;

-- ── Done ──────────────────────────────────────────────────────────────────────
SELECT 'ai_events table ready' AS status,
       (SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = 'ai_events') AS column_count;
