-- ============================================================
-- Vantage AI — Full Database Schema
-- Run this in: Supabase Dashboard > SQL Editor
-- ============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── 1. Organisations ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organisations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'free',  -- free | starter | team | enterprise
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. Profiles ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
    id          UUID PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
    org_id      UUID REFERENCES organisations(id) ON DELETE SET NULL,
    role        TEXT NOT NULL DEFAULT 'member',  -- owner | admin | member | viewer
    name        TEXT,
    avatar_url  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── 3. API Keys ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id       UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    key_hash     TEXT UNIQUE NOT NULL,   -- SHA-256(raw_key)
    key_prefix   TEXT NOT NULL,          -- first 8 chars: "vnt_abc1"
    scopes       TEXT[] DEFAULT ARRAY['ingest'],
    environment  TEXT DEFAULT 'production',
    revoked      BOOLEAN DEFAULT FALSE,
    last_used_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    created_by   UUID REFERENCES auth.users
);

-- ── 4. AI Events (main fact table) ─────────────────────────
-- Stores every AI call captured by the SDK
CREATE TABLE IF NOT EXISTS ai_events (
    -- Identity
    event_id    TEXT PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL,
    org_id      TEXT NOT NULL,
    environment TEXT DEFAULT 'production',

    -- Request context
    provider    TEXT,
    model       TEXT,
    endpoint    TEXT,
    session_id  TEXT,
    user_id     TEXT,
    feature     TEXT,
    project     TEXT,
    team        TEXT,
    tags        JSONB DEFAULT '{}',

    -- Performance
    latency_ms  NUMERIC,
    ttft_ms     NUMERIC,
    status_code INTEGER DEFAULT 200,
    error       TEXT,

    -- Token usage
    usage_prompt_tokens         INTEGER DEFAULT 0,
    usage_completion_tokens     INTEGER DEFAULT 0,
    usage_total_tokens          INTEGER DEFAULT 0,
    usage_cached_tokens         INTEGER DEFAULT 0,
    usage_system_prompt_tokens  INTEGER DEFAULT 0,

    -- Cost
    cost_input_cost_usd         NUMERIC DEFAULT 0,
    cost_output_cost_usd        NUMERIC DEFAULT 0,
    cost_total_cost_usd         NUMERIC DEFAULT 0,
    cost_cheapest_model         TEXT,
    cost_cheapest_cost_usd      NUMERIC DEFAULT 0,
    cost_potential_saving_usd   NUMERIC DEFAULT 0,

    -- Quality metrics (populated async by Opus 4.6 evaluator)
    quality_hallucination_score     NUMERIC DEFAULT -1,
    quality_hallucination_type      TEXT,
    quality_hallucination_detail    TEXT,
    quality_coherence_score         NUMERIC DEFAULT -1,
    quality_relevance_score         NUMERIC DEFAULT -1,
    quality_completeness_score      NUMERIC DEFAULT -1,
    quality_factuality_score        NUMERIC DEFAULT -1,
    quality_toxicity_score          NUMERIC DEFAULT -1,
    quality_prompt_clarity_score    NUMERIC DEFAULT -1,
    quality_prompt_efficiency_score NUMERIC DEFAULT -1,
    quality_overall_quality         NUMERIC DEFAULT -1,
    quality_evaluated_by            TEXT,
    quality_eval_latency_ms         NUMERIC DEFAULT 0,

    -- Previews (truncated, for context)
    request_preview     TEXT,
    response_preview    TEXT,
    system_preview      TEXT,
    prompt_hash         TEXT,

    -- Metadata
    sdk_version TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ai_events_org_time  ON ai_events(org_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ai_events_model     ON ai_events(org_id, model);
CREATE INDEX IF NOT EXISTS idx_ai_events_team      ON ai_events(org_id, team);
CREATE INDEX IF NOT EXISTS idx_ai_events_project   ON ai_events(org_id, project);
CREATE INDEX IF NOT EXISTS idx_ai_events_feature   ON ai_events(org_id, feature);
CREATE INDEX IF NOT EXISTS idx_ai_events_halluc    ON ai_events(org_id, quality_hallucination_score) WHERE quality_hallucination_score >= 0;

-- ── 5. Daily Rollups (pre-aggregated for fast dashboard) ───
CREATE TABLE IF NOT EXISTS usage_daily (
    id               BIGSERIAL PRIMARY KEY,
    org_id           TEXT NOT NULL,
    date             DATE NOT NULL,
    model            TEXT,
    provider         TEXT,
    team             TEXT,
    project          TEXT,
    request_count    INTEGER DEFAULT 0,
    prompt_tokens    BIGINT  DEFAULT 0,
    completion_tokens BIGINT DEFAULT 0,
    total_cost_usd   NUMERIC DEFAULT 0,
    error_count      INTEGER DEFAULT 0,
    total_latency_ms NUMERIC DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, date, model, team, project)
);

CREATE INDEX IF NOT EXISTS idx_usage_daily_org ON usage_daily(org_id, date DESC);

-- ── 6. Budget Rules ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS budget_rules (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id          UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    scope           TEXT NOT NULL,  -- org | team | project | model
    scope_value     TEXT,           -- team name / project name / model name
    period          TEXT DEFAULT 'monthly',  -- daily | weekly | monthly
    limit_usd       NUMERIC NOT NULL,
    alert_at_pct    INTEGER DEFAULT 80,     -- alert when X% of budget used
    hard_limit      BOOLEAN DEFAULT FALSE,  -- block requests at limit
    enabled         BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    created_by      UUID REFERENCES auth.users
);

-- ── 7. Waitlist ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS waitlist (
    id         BIGSERIAL PRIMARY KEY,
    email      TEXT UNIQUE NOT NULL,
    company    TEXT,
    use_case   TEXT,
    source     TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Row Level Security ────────────────────────────────────
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys      ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_rules  ENABLE ROW LEVEL SECURITY;
-- ai_events uses org_id text (no FK) — RLS via backend service role

-- Profiles: users can read their own profile
CREATE POLICY "users_own_profile" ON profiles
    FOR ALL USING (id = auth.uid());

-- Organisations: members can read their org
CREATE POLICY "org_members_read" ON organisations
    FOR SELECT USING (
        id IN (SELECT org_id FROM profiles WHERE id = auth.uid())
    );

-- API Keys: org members can manage keys
CREATE POLICY "api_keys_by_org" ON api_keys
    FOR ALL USING (
        org_id IN (SELECT org_id FROM profiles WHERE id = auth.uid())
    );

-- ── Trigger: auto-create org on signup ────────────────────
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
    new_org_id UUID;
    user_name  TEXT;
BEGIN
    user_name := COALESCE(
        NEW.raw_user_meta_data->>'full_name',
        NEW.raw_user_meta_data->>'name',
        split_part(NEW.email, '@', 1)
    );

    -- Create organisation
    INSERT INTO organisations(name, slug)
    VALUES (
        user_name || '''s Workspace',
        lower(regexp_replace(user_name, '[^a-zA-Z0-9]', '-', 'g'))
            || '-' || substr(NEW.id::text, 1, 6)
    )
    RETURNING id INTO new_org_id;

    -- Create profile
    INSERT INTO profiles(id, org_id, role, name)
    VALUES (NEW.id, new_org_id, 'owner', user_name);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ── View: event summary per model per org ─────────────────
CREATE OR REPLACE VIEW model_stats AS
SELECT
    org_id,
    model,
    provider,
    COUNT(*)                                    AS request_count,
    SUM(usage_total_tokens)                     AS total_tokens,
    SUM(cost_total_cost_usd)                    AS total_cost_usd,
    AVG(latency_ms)                             AS avg_latency_ms,
    AVG(quality_overall_quality) FILTER (WHERE quality_overall_quality >= 0) AS avg_quality,
    AVG(quality_hallucination_score) FILTER (WHERE quality_hallucination_score >= 0) AS avg_hallucination,
    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) AS error_count
FROM ai_events
GROUP BY org_id, model, provider;

-- Done!
SELECT 'Vantage AI schema installed successfully' AS status;
