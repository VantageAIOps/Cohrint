-- Supabase migration: initial schema (example)
-- Run via: supabase db push

-- API keys table (hashed)
CREATE TABLE IF NOT EXISTS api_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id text NOT NULL,
  key_hash text NOT NULL UNIQUE,
  name text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  revoked boolean NOT NULL DEFAULT false
);

-- AI events table (raw ingest)
CREATE TABLE IF NOT EXISTS ai_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id text NOT NULL,
  org_id text NOT NULL,
  timestamp double precision NOT NULL,
  provider text,
  model text,
  endpoint text,
  user_id text,
  team text,
  project text,
  cost_total_cost_usd double precision,
  quality_hallucination_score double precision,
  quality_overall_quality double precision
  -- add additional columns as needed
);
