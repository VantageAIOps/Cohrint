-- VantageAI Demo Org Seed Data
-- Run once: wrangler d1 execute vantageai-db --file=scripts/demo-seed.sql
-- Creates a fixed, constant demo org with read-only viewer key.
-- Demonstrates all major features: cost breakdown, teams, models, budget alert, semantic cache.
-- IMPORTANT: Replace the api_key_hash placeholder below with the real SHA-256 hash before running.

-- ── Org ──────────────────────────────────────────────────────────────────────
-- Demo org (delete+recreate for clean reset)
DELETE FROM org_members WHERE org_id = 'demo';
DELETE FROM events WHERE org_id = 'demo';
DELETE FROM budget_policies WHERE org_id = 'demo';
DELETE FROM orgs WHERE id = 'demo';

INSERT INTO orgs (id, api_key_hash, api_key_hint, name, email, plan, created_at)
VALUES (
  'demo',
  -- REPLACE: run `echo -n "<your_demo_api_key>" | openssl dgst -sha256` and paste the hash here
  '0000000000000000000000000000000000000000000000000000000000000000',
  'vnt_demo_vie...',
  'VantageAI Demo',
  'demo@vantageaiops.com',
  'team',
  unixepoch() - 30*86400
);

-- ── Viewer member key for demo button ────────────────────────────────────────
-- After running: create a viewer member key and update api_key_hash above.
-- wrangler d1 execute vantageai-db --command="
--   INSERT INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, created_at)
--   VALUES ('demo-viewer', 'demo', 'viewer@vantageaiops.com', 'Demo Viewer', 'viewer',
--     '<SHA256_OF_DEMO_KEY>', 'vnt_demo_vie...', unixepoch());"

-- ── Budget policy (backend team at 85% alert) ─────────────────────────────
INSERT INTO budget_policies (id, org_id, team, budget_usd, period, alert_threshold_pct, created_at)
VALUES ('bp-demo-backend', 'demo', 'backend', 500.00, 'monthly', 85, unixepoch() - 30*86400);

-- ── Events (fixed, constant — ~100 events over 30 days) ──────────────────
-- Teams: backend, ml-platform, product
-- Models: claude-sonnet-4-6, gpt-4o, gemini-2.0-flash, claude-haiku-4-5
-- ~20 duplicate calls (cache_hit=1) for semantic cache KPIs

-- Day 1 (30 days ago)
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-001','demo','anthropic','claude-sonnet-4-6',1200,450,0,1650,0.0054,1230,'backend','production',NULL,0,unixepoch()-30*86400),
('demo-002','demo','openai','gpt-4o',900,320,0,1220,0.0073,980,'ml-platform','production',NULL,0,unixepoch()-30*86400+3600),
('demo-003','demo','google','gemini-2.0-flash',750,280,0,1030,0.0002,540,'product','production',NULL,0,unixepoch()-30*86400+7200);

-- Day 3
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-004','demo','anthropic','claude-sonnet-4-6',1500,600,0,2100,0.0072,1450,'backend','production','a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4',0,unixepoch()-28*86400),
('demo-005','demo','anthropic','claude-haiku-4-5',400,180,0,580,0.0006,320,'product','production',NULL,0,unixepoch()-28*86400+1800),
('demo-006','demo','openai','gpt-4o',1100,400,0,1500,0.0088,1100,'ml-platform','production',NULL,0,unixepoch()-28*86400+3600),
-- Duplicate of demo-004 (cache_hit)
('demo-007','demo','anthropic','claude-sonnet-4-6',1500,600,0,2100,0.0072,1450,'backend','production','a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4',1,unixepoch()-28*86400+7200);

-- Day 5
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-008','demo','google','gemini-2.0-flash',600,220,0,820,0.0001,490,'product','production',NULL,0,unixepoch()-26*86400),
('demo-009','demo','anthropic','claude-sonnet-4-6',2000,800,400,2800,0.0096,1800,'backend','production','b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5',0,unixepoch()-26*86400+3600),
('demo-010','demo','openai','gpt-4o',1300,520,0,1820,0.0104,1250,'ml-platform','production',NULL,0,unixepoch()-26*86400+7200),
-- Duplicate
('demo-011','demo','anthropic','claude-sonnet-4-6',2000,800,400,2800,0.0096,1800,'backend','production','b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5',1,unixepoch()-26*86400+9000);

-- Day 7
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-012','demo','anthropic','claude-haiku-4-5',350,120,0,470,0.0004,280,'product','production',NULL,0,unixepoch()-24*86400),
('demo-013','demo','anthropic','claude-sonnet-4-6',1800,700,350,2500,0.0084,1650,'backend','production',NULL,0,unixepoch()-24*86400+3600),
('demo-014','demo','openai','gpt-4o',950,380,0,1330,0.0076,950,'ml-platform','production','c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6',0,unixepoch()-24*86400+7200),
-- Duplicate
('demo-015','demo','openai','gpt-4o',950,380,0,1330,0.0076,950,'ml-platform','production','c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6',1,unixepoch()-24*86400+9000);

-- Day 10
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-016','demo','anthropic','claude-sonnet-4-6',2500,1000,500,3500,0.012,2100,'backend','production',NULL,0,unixepoch()-21*86400),
('demo-017','demo','google','gemini-2.0-flash',1200,480,0,1680,0.0003,580,'product','production',NULL,0,unixepoch()-21*86400+3600),
('demo-018','demo','openai','gpt-4o',1600,640,0,2240,0.0128,1400,'ml-platform','production',NULL,0,unixepoch()-21*86400+7200),
('demo-019','demo','anthropic','claude-haiku-4-5',500,200,0,700,0.0008,350,'product','production',NULL,0,unixepoch()-21*86400+10800);

-- Day 13
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-020','demo','anthropic','claude-sonnet-4-6',1900,760,380,2660,0.0091,1750,'backend','production','d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1',0,unixepoch()-18*86400),
('demo-021','demo','openai','gpt-4o',1100,440,0,1540,0.0088,1080,'ml-platform','production',NULL,0,unixepoch()-18*86400+3600),
-- Duplicate
('demo-022','demo','anthropic','claude-sonnet-4-6',1900,760,380,2660,0.0091,1750,'backend','production','d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1',1,unixepoch()-18*86400+5400),
('demo-023','demo','google','gemini-2.0-flash',800,320,0,1120,0.0002,510,'product','production',NULL,0,unixepoch()-18*86400+7200);

-- Day 16
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-024','demo','anthropic','claude-sonnet-4-6',3000,1200,600,4200,0.0144,2400,'backend','production',NULL,0,unixepoch()-15*86400),
('demo-025','demo','openai','gpt-4o',1400,560,0,1960,0.0112,1300,'ml-platform','production','e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',0,unixepoch()-15*86400+3600),
-- Duplicate
('demo-026','demo','openai','gpt-4o',1400,560,0,1960,0.0112,1300,'ml-platform','production','e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',1,unixepoch()-15*86400+5400),
('demo-027','demo','anthropic','claude-haiku-4-5',600,240,0,840,0.001,380,'product','production',NULL,0,unixepoch()-15*86400+7200),
('demo-028','demo','google','gemini-2.0-flash',1000,400,0,1400,0.0003,530,'product','production',NULL,0,unixepoch()-15*86400+10800);

-- Day 19
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-029','demo','anthropic','claude-sonnet-4-6',2200,880,440,3080,0.0106,1950,'backend','production','f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3',0,unixepoch()-12*86400),
('demo-030','demo','openai','gpt-4o',1700,680,0,2380,0.0136,1550,'ml-platform','production',NULL,0,unixepoch()-12*86400+3600),
-- Duplicate
('demo-031','demo','anthropic','claude-sonnet-4-6',2200,880,440,3080,0.0106,1950,'backend','production','f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3',1,unixepoch()-12*86400+4800),
('demo-032','demo','anthropic','claude-haiku-4-5',450,180,0,630,0.0006,300,'product','production',NULL,0,unixepoch()-12*86400+7200),
('demo-033','demo','google','gemini-2.0-flash',900,360,0,1260,0.0002,510,'product','production',NULL,0,unixepoch()-12*86400+10800);

-- Day 22 (last week — higher volume)
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-034','demo','anthropic','claude-sonnet-4-6',2800,1120,560,3920,0.0134,2250,'backend','production',NULL,0,unixepoch()-9*86400),
('demo-035','demo','openai','gpt-4o',1900,760,0,2660,0.0152,1700,'ml-platform','production',NULL,0,unixepoch()-9*86400+1800),
('demo-036','demo','anthropic','claude-sonnet-4-6',1600,640,320,2240,0.0077,1480,'backend','production','a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d5',0,unixepoch()-9*86400+3600),
-- Duplicate
('demo-037','demo','anthropic','claude-sonnet-4-6',1600,640,320,2240,0.0077,1480,'backend','production','a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d5',1,unixepoch()-9*86400+5000),
('demo-038','demo','google','gemini-2.0-flash',1100,440,0,1540,0.0003,550,'product','production',NULL,0,unixepoch()-9*86400+7200),
('demo-039','demo','anthropic','claude-haiku-4-5',700,280,0,980,0.0012,420,'product','production',NULL,0,unixepoch()-9*86400+9000),
('demo-040','demo','openai','gpt-4o',2100,840,0,2940,0.0168,1900,'ml-platform','production','b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e6',0,unixepoch()-9*86400+10800);

-- Day 25
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-041','demo','openai','gpt-4o',2100,840,0,2940,0.0168,1900,'ml-platform','production','b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e6',1,unixepoch()-6*86400),
('demo-042','demo','anthropic','claude-sonnet-4-6',3200,1280,640,4480,0.0154,2600,'backend','production',NULL,0,unixepoch()-6*86400+1800),
('demo-043','demo','anthropic','claude-sonnet-4-6',2400,960,480,3360,0.0115,2100,'backend','production',NULL,0,unixepoch()-6*86400+3600),
('demo-044','demo','google','gemini-2.0-flash',1300,520,0,1820,0.0004,570,'product','production',NULL,0,unixepoch()-6*86400+5400),
('demo-045','demo','anthropic','claude-haiku-4-5',550,220,0,770,0.0008,330,'product','production',NULL,0,unixepoch()-6*86400+7200),
('demo-046','demo','openai','gpt-4o',1800,720,0,2520,0.0144,1650,'ml-platform','production',NULL,0,unixepoch()-6*86400+9000);

-- Day 28 (recent — last 3 days)
INSERT OR IGNORE INTO events (id, org_id, provider, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, latency_ms, team, environment, prompt_hash, cache_hit, created_at) VALUES
('demo-047','demo','anthropic','claude-sonnet-4-6',2600,1040,520,3640,0.0125,2300,'backend','production','c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f7',0,unixepoch()-3*86400),
-- Duplicate
('demo-048','demo','anthropic','claude-sonnet-4-6',2600,1040,520,3640,0.0125,2300,'backend','production','c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f7',1,unixepoch()-3*86400+1800),
('demo-049','demo','openai','gpt-4o',2300,920,0,3220,0.0184,2050,'ml-platform','production',NULL,0,unixepoch()-3*86400+3600),
('demo-050','demo','google','gemini-2.0-flash',1500,600,0,2100,0.0005,580,'product','production',NULL,0,unixepoch()-3*86400+5400),
('demo-051','demo','anthropic','claude-haiku-4-5',800,320,0,1120,0.0014,460,'product','production',NULL,0,unixepoch()-3*86400+7200),
('demo-052','demo','anthropic','claude-sonnet-4-6',1800,720,360,2520,0.0086,1700,'backend','production',NULL,0,unixepoch()-86400),
('demo-053','demo','openai','gpt-4o',2000,800,0,2800,0.016,1850,'ml-platform','production',NULL,0,unixepoch()-86400+3600),
('demo-054','demo','google','gemini-2.0-flash',1200,480,0,1680,0.0004,560,'product','production',NULL,0,unixepoch()-86400+7200);
