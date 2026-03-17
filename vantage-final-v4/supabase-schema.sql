-- ============================================================
-- Vantage AI — Complete Supabase Schema
-- Project: oyljzpvwdfktrkeotmon
-- Run in: Supabase Dashboard → SQL Editor → New Query → Run All
-- ============================================================

-- ── 1. Organisations ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organisations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  slug        TEXT UNIQUE NOT NULL,
  plan        TEXT NOT NULL DEFAULT 'free'
                CHECK (plan IN ('free','team','enterprise')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. Profiles (extends Supabase auth.users) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  org_id      UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  full_name   TEXT,
  avatar_url  TEXT,
  role        TEXT NOT NULL DEFAULT 'member'
                CHECK (role IN ('owner','admin','member','viewer')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 3. API Keys ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name         TEXT NOT NULL DEFAULT 'Default key',
  key_prefix   TEXT NOT NULL,
  key_hash     TEXT NOT NULL UNIQUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at TIMESTAMPTZ,
  revoked      BOOLEAN NOT NULL DEFAULT false
);

-- ── 4. Usage events (daily rollup — full events go to ClickHouse) ─────────────
CREATE TABLE IF NOT EXISTS usage_daily (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id            UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  date              DATE NOT NULL,
  model             TEXT NOT NULL,
  provider          TEXT NOT NULL,
  request_count     INTEGER NOT NULL DEFAULT 0,
  prompt_tokens     BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  total_cost_usd    NUMERIC(14,8) NOT NULL DEFAULT 0,
  UNIQUE(org_id, date, model, provider)
);

-- ── 5. Budget rules ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS budget_rules (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id       UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  scope        TEXT NOT NULL DEFAULT 'org'
                CHECK (scope IN ('org','team','feature','model')),
  scope_value  TEXT,
  limit_usd    NUMERIC(12,2) NOT NULL,
  period       TEXT NOT NULL DEFAULT 'monthly'
                CHECK (period IN ('daily','weekly','monthly')),
  alert_pct    INTEGER NOT NULL DEFAULT 80,
  active       BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 6. Waitlist ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS waitlist (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT UNIQUE NOT NULL,
  name       TEXT,
  plan       TEXT DEFAULT 'free',
  source     TEXT DEFAULT 'website',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Row Level Security ─────────────────────────────────────────────────────────
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys       ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily    ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_rules   ENABLE ROW LEVEL SECURITY;
ALTER TABLE waitlist       ENABLE ROW LEVEL SECURITY;

-- Helper: get current user's org_id
CREATE OR REPLACE FUNCTION my_org_id()
RETURNS UUID LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT org_id FROM profiles WHERE id = auth.uid() LIMIT 1;
$$;

-- Profiles: own row only
CREATE POLICY "profiles_select" ON profiles FOR SELECT USING (id = auth.uid());
CREATE POLICY "profiles_update" ON profiles FOR UPDATE USING (id = auth.uid());

-- Organisations: members of the org
CREATE POLICY "orgs_select" ON organisations FOR SELECT USING (id = my_org_id());
CREATE POLICY "orgs_update" ON organisations FOR UPDATE
  USING (id = my_org_id()
    AND EXISTS (SELECT 1 FROM profiles WHERE id = auth.uid() AND role IN ('owner','admin')));

-- API keys: org members
CREATE POLICY "keys_select" ON api_keys FOR SELECT USING (org_id = my_org_id());
CREATE POLICY "keys_insert" ON api_keys FOR INSERT WITH CHECK (org_id = my_org_id());
CREATE POLICY "keys_update" ON api_keys FOR UPDATE USING (org_id = my_org_id());

-- Usage: org members
CREATE POLICY "usage_select" ON usage_daily FOR SELECT USING (org_id = my_org_id());
CREATE POLICY "usage_insert" ON usage_daily FOR INSERT WITH CHECK (org_id = my_org_id());

-- Budget: org members
CREATE POLICY "budget_select" ON budget_rules FOR SELECT USING (org_id = my_org_id());
CREATE POLICY "budget_all"    ON budget_rules FOR ALL    USING (org_id = my_org_id());

-- Waitlist: anyone can insert (public), only admins read
CREATE POLICY "waitlist_insert" ON waitlist FOR INSERT WITH CHECK (true);
CREATE POLICY "waitlist_select" ON waitlist FOR SELECT USING (auth.role() = 'service_role');

-- ── Auto-create org + profile on signup ───────────────────────────────────────
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  new_org_id  UUID;
  base_slug   TEXT;
  final_slug  TEXT;
  suffix      INT := 0;
BEGIN
  -- Build slug from email prefix
  base_slug := lower(regexp_replace(split_part(NEW.email, '@', 1), '[^a-z0-9]', '', 'g'));
  IF length(base_slug) < 3 THEN base_slug := 'org' || base_slug; END IF;
  final_slug := base_slug;

  -- Ensure slug is unique
  WHILE EXISTS (SELECT 1 FROM organisations WHERE slug = final_slug) LOOP
    suffix     := suffix + 1;
    final_slug := base_slug || suffix::text;
  END LOOP;

  -- Create organisation
  INSERT INTO organisations (name, slug)
  VALUES (
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email,'@',1)),
    final_slug
  )
  RETURNING id INTO new_org_id;

  -- Create profile
  INSERT INTO profiles (id, org_id, full_name, avatar_url, role)
  VALUES (
    NEW.id,
    new_org_id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email,'@',1)),
    NEW.raw_user_meta_data->>'avatar_url',
    'owner'
  );

  RETURN NEW;
END;
$$;

-- Attach trigger
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ── Indexes ────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_api_keys_hash    ON api_keys(key_hash)  WHERE NOT revoked;
CREATE INDEX IF NOT EXISTS idx_api_keys_org     ON api_keys(org_id);
CREATE INDEX IF NOT EXISTS idx_usage_org_date   ON usage_daily(org_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_profiles_org     ON profiles(org_id);

-- ── Supabase Auth: Configure in Dashboard → Auth → Settings ───────────────────
-- Site URL:       https://vantageai.aman-lpucse.workers.dev
-- Redirect URLs:  https://vantageai.aman-lpucse.workers.dev/app.html
--                 http://localhost:3000/app.html
--                 http://127.0.0.1:5500/app.html

-- ── Done ──────────────────────────────────────────────────────────────────────
SELECT 'Schema created successfully' AS status,
       (SELECT count(*) FROM information_schema.tables
        WHERE table_schema = 'public') AS table_count;
