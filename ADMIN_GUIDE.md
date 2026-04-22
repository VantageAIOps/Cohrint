# Cohrint — Developer Admin Guide
**Version 2.1 · April 2026 · INTERNAL — NOT FOR PUBLIC DISTRIBUTION**

> **v2.1 Changes (2026-04-22):** Stage 1 routing system shipped (PR #87). Added Section 37: Intent Classifier + Model Router. Added Section 38: Routing Quality Sampling. Updated Section 25 (Local Proxy) to reflect v1.1.0 routing behaviour. Updated Section 6.1 endpoint map to include `GET /v1/analytics/savings`. Updated Section 1 (Product Overview) to describe routing.

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [System Architecture](#2-system-architecture)
3. [Database Schema & Data Model](#3-database-schema--data-model)
4. [Authentication & Authorization System](#4-authentication--authorization-system)
5. [Event Ingest Pipeline](#5-event-ingest-pipeline)
6. [Analytics Engine & Trace DAG](#6-analytics-engine--trace-dag)
7. [Semantic Cache Layer](#7-semantic-cache-layer)
8. [Prompt Registry](#8-prompt-registry)
9. [Public Benchmark Dashboard](#9-public-benchmark-dashboard)
10. [Rate Limiting Algorithm](#10-rate-limiting-algorithm)
11. [Real-Time Streaming (SSE)](#11-real-time-streaming-sse)
12. [Alert System](#12-alert-system)
13. [Email Infrastructure](#13-email-infrastructure)
14. [Admin & Team Management](#14-admin--team-management)
15. [Frontend Architecture & RBAC Guards (PR #67)](#15-frontend-architecture--rbac-guards-pr-67)
16. [Client Types & Integration Patterns](#16-client-types--integration-patterns)
17. [CI/CD & Deployment Pipeline](#17-cicd--deployment-pipeline)
18. [Test Infrastructure](#18-test-infrastructure)
19. [Security Model](#19-security-model)
20. [Business Algorithms — Current & Research-Backed Future](#20-business-algorithms--current--research-backed-future)
21. [Pricing & Plan Logic](#21-pricing--plan-logic)
22. [Operational Runbook](#22-operational-runbook)
23. [Research References & Reading List](#23-research-references--reading-list)
24. [MCP Server — Tools Reference & Examples](#24-mcp-server--tools-reference--examples)
25. [Local Proxy Gateway — Privacy-First LLM Tracking](#25-local-proxy-gateway--privacy-first-llm-tracking)
26. [Claude Code Auto-Tracking](#26-claude-code-auto-tracking)
27. [SDK Privacy Modes](#27-sdk-privacy-modes)
28. [Cross-Platform OTel Collector (v2)](#28-cross-platform-otel-collector-v2)
29. [Cohrint CLI — AI Agent Wrapper](#29-cohrint-cli--ai-agent-wrapper)
30. [Security & Governance](#30-security--governance)
31. [Claude Code Integration (Customer-Facing)](#31-claude-code-integration-customer-facing)
32. [GitHub Copilot Metrics Adapter](#32-github-copilot-metrics-adapter)
33. [Datadog Metrics Exporter](#33-datadog-metrics-exporter)
34. [Cross-Platform Console](#34-cross-platform-console)
35. [Audit Log](#35-audit-log)
36. [Quick Reference Card](#36-quick-reference-card)
37. [Intent Classifier + Model Router](#37-intent-classifier--model-router)
38. [Routing Quality Sampling](#38-routing-quality-sampling)
39. [Routing Savings API](#39-routing-savings-api)

---

## 1. Product Overview

Cohrint is an **AI cost intelligence and observability platform**. It gives engineering teams real-time visibility into LLM API spending, token efficiency, model performance, output quality, and cross-tool usage through a two-line SDK integration.

### What It Does (One Paragraph)

Cohrint is an **AI coding cost intelligence and routing platform**. The local proxy (`cohrint-local-proxy`) intercepts LLM API calls from Claude Code, Cursor, and Copilot; classifies the intent (autocomplete / generation / refactor / explanation) in <50ms; routes to the cheapest model that meets the quality bar; samples 1–5% of traffic against a premium model to detect quality drift; and publishes real-time savings data to the API. Applications can also integrate the SDK (Python or JS) directly — every LLM call is transparently intercepted, cost/token/latency extracted, and POSTed to `api.cohrint.com`. The Worker stores events in D1 (SQLite). The dashboard (`app.html`) streams from the same API to render charts, KPI cards, team breakdowns, and the Routing Savings card. The **Semantic Cache layer** intercepts prompts before they reach the LLM and returns cached responses for semantically equivalent prompts. The **Prompt Registry** lets admins version and A/B-compare prompt templates with per-version cost attribution. The **Benchmark Dashboard** surfaces anonymized industry percentile rankings (k-anonymity floor: 5 orgs). Admins set budgets; alerts fire via Slack when thresholds are crossed.

### Technology Stack

| Layer | Technology | Why |
|---|---|---|
| API Worker | Cloudflare Workers + Hono | Edge-globally-distributed, zero cold starts, TypeScript |
| Database | Cloudflare D1 (SQLite) | Serverless SQLite, no infra, free tier sufficient for MVP |
| Cache/Pub-Sub | Cloudflare KV | Rate limiting counters, SSE broadcast, alert throttle, session tokens |
| Vector Store | Cloudflare Vectorize | BGE-small-en-v1.5 (384-dim) embeddings for semantic cache |
| AI Inference | Cloudflare Workers AI | Embedding generation for semantic cache (`@cf/baai/bge-small-en-v1.5`) |
| Frontend | Cloudflare Pages | Static hosting, global CDN, auto-deploys from `main` |
| Email | Resend API | Transactional email, 3k/month free, custom domain |
| SDK (Python) | `cohrint` on PyPI | OpenAI + Anthropic proxy wrappers |
| SDK (JS) | `cohrint` on npm | OpenAI + Anthropic proxy wrappers, streaming support |
| MCP Server | `cohrint-mcp/` | VS Code, Cursor, Windsurf integration |
| CI/CD | GitHub Actions | Deploy on push to `main`, test on every branch |

---

## 2. System Architecture

### 2.1 High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                  │
│                                                                        │
│  Python SDK    JS SDK    MCP Server    CLI      Browser Dashboard     │
│  (cohrint)   (cohrint)  (cohrint-mcp) (cohrint-cli)  (app.html)      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │  HTTPS  Bearer crt_... / Cookie
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│              Cloudflare Worker  —  api.cohrint.com                   │
│                                                                        │
│  corsMiddleware → authMiddleware → rateLimiter → roleGuard            │
│                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │  events.ts   │  │ analytics.ts │  │  cache.ts    │               │
│  │  (ingest)    │  │  (query)     │  │  (semantic)  │               │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │
│         │                 │                  │                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │  prompts.ts  │  │benchmark.ts  │  │  auditlog.ts │               │
│  │  (registry)  │  │  (public)    │  │  (immutable) │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└───────────┬──────────────────────────────────────┬───────────────────┘
            │                                      │
    ┌───────┴────────┐                    ┌────────┴───────┐
    │  Cloudflare D1 │                    │  Cloudflare KV │
    │  (SQLite)      │                    │  (ephemeral)   │
    │                │                    │                │
    │  events        │                    │  rl:{org}:{min}│
    │  orgs          │                    │  stream:{org}  │
    │  org_members   │                    │  slack:{org}   │
    │  sessions      │                    │  alert:{org}   │
    │  prompts       │                    │  recover:{tok} │
    │  prompt_vers.  │                    │  copilot:token │
    │  semantic_cache│                    │  sse:{org}     │
    │  audit_events  │                    └────────────────┘
    │  benchmark_*   │
    │  cross_plat.   │           ┌────────────────────────┐
    │  otel_events   │           │  Cloudflare Vectorize  │
    └────────────────┘           │  (semantic embeddings) │
                                 │  namespace: org_id     │
                                 │  model: bge-small-en   │
                                 └────────────────────────┘
                                          ▲
                                 ┌────────┴───────┐
                                 │ Workers AI     │
                                 │ @cf/baai/bge-  │
                                 │ small-en-v1.5  │
                                 └────────────────┘
```

### 2.2 Request Lifecycle Sequence Diagram

```
Client                  Worker                    D1              KV
  │                       │                        │               │
  │──POST /v1/events──────▶│                        │               │
  │                       │                        │               │
  │                       │──corsMiddleware()──────▶│               │
  │                       │  ← 204 if OPTIONS       │               │
  │                       │                        │               │
  │                       │──authMiddleware()───────────────────────▶
  │                       │  1. parse Cookie header │               │
  │                       │  2. GET sessions WHERE  │               │
  │                       │     token=? expires>now─▶               │
  │                       │  OR SHA-256(Bearer key) │               │
  │                       │     GET orgs/members ───▶               │
  │                       │  set: orgId,role,scope  │               │
  │                       │                         │               │
  │                       │──checkRateLimit()────────────────────────▶
  │                       │  GET rl:{org}:{minute}  │     ┌─────────┤
  │                       │◀─ count (or 0)          │     │  count  │
  │                       │  PUT rl:{org}:{min} N+1 │     └─────────┘
  │                       │  ← 429 if >= RPM_LIMIT  │               │
  │                       │                         │               │
  │                       │──roleGuard()            │               │
  │                       │  viewer? → 403          │               │
  │                       │                         │               │
  │                       │──checkFreeTierLimit()───▶               │
  │                       │  COUNT events this month│               │
  │                       │  ← 429 if free + >50k   │               │
  │                       │                         │               │
  │                       │──INSERT OR IGNORE events▶               │
  │                       │                         │               │
  │                       │──broadcastEvent()────────────────────────▶
  │                       │  PUT stream:{org}:latest│     ┌─────────┤
  │                       │  TTL=60s                │     │ payload │
  │                       │                         │     └─────────┘
  │                       │──logAudit()─────────────▶               │
  │                       │  INSERT audit_events    │               │
  │◀──201 {ok,id}─────────│                         │               │
```

### 2.3 Infrastructure Bindings (wrangler.toml)

```toml
name = "vantageai-api"
routes = [{ pattern = "api.cohrint.com/*", zone_name = "cohrint.com" }]

[[d1_databases]]
binding = "DB"
# database_id in wrangler.toml (gitignored)

[[kv_namespaces]]
binding = "KV"
# id in wrangler.toml (gitignored)

[ai]
binding = "AI"          # Workers AI — used by semantic cache

[[vectorize]]
binding = "VECTORIZE"   # Vectorize index — used by semantic cache
# index_name in wrangler.toml (gitignored)

[vars]
ENVIRONMENT = "production"
ALLOWED_ORIGINS = "https://cohrint.com,https://www.cohrint.com,https://cohrint.pages.dev"
RATE_LIMIT_RPM = "1000"

# Secrets (set via: wrangler secret put <NAME>)
# RESEND_API_KEY           — email sending
# SUPERADMIN_SECRET        — /v1/superadmin/* gate
# VANTAGE_CI_SECRET        — bypass signup rate limiting in CI
# TOKEN_ENCRYPTION_SECRET  — AES-256-GCM key for Copilot PAT + Datadog key encryption
# DEMO_API_KEY             — viewer-scoped key used by POST /v1/auth/demo
```

> `database_id`, KV `id`, and Vectorize `index_name` are in `wrangler.toml` which is gitignored. Retrieve via `wrangler d1 list` / `wrangler kv namespace list` / `wrangler vectorize list`.

---

## 3. Database Schema & Data Model

Cohrint uses Cloudflare D1 (SQLite). **22 active tables** as of v2.0. New in v2.0: `semantic_cache_entries`, `org_cache_config`, `prompts`, `prompt_versions`, `prompt_usage`.

### CRITICAL: Date Column Type Divergence

**`created_at` is NOT consistent across tables.** Binding the wrong type causes SQLite to silently coerce to `0` — filters then match every row with no runtime error.

```
┌─────────────────────────────────────────────────────────────────────┐
│  INTEGER (unix epoch seconds)     TEXT (YYYY-MM-DD HH:MM:SS)        │
│  bind: Math.floor(Date.now()/1000)  bind: "2026-04-17 00:00:00"    │
│  default: unixepoch()             default: datetime('now')          │
│                                                                      │
│  events                           cross_platform_usage              │
│  orgs                             otel_events                       │
│  org_members                      benchmark_snapshots               │
│  alert_configs                    copilot_connections               │
│  team_budgets                     datadog_connections               │
│  sessions                         prompts                           │
│  alert_log                        prompt_versions                   │
│  platform_*                       prompt_usage                      │
│  audit_events                     semantic_cache_entries            │
│                                   org_cache_config                  │
└─────────────────────────────────────────────────────────────────────┘
```

Helper functions — use these, never raw date math:
- **INTEGER tables:** `sinceUnix(days)`, `todayUnix()` in `analytics.ts`
- **TEXT tables:** `sqliteDateSince(days)`, `sqliteTodayStart()`, `sqliteMonthStart()` in `crossplatform.ts`
- For INTEGER hour extraction: `strftime('%H', created_at, 'unixepoch')`
- Never use ISO 8601 `T`/`Z` format (`2026-03-24T00:00:00Z`) in TEXT WHERE clauses — `T` sorts differently than space.

### Database ERD (Abbreviated)

```
orgs ──────────────────────────────────────────────────────────────────┐
 │ id (PK)                                                              │
 │ api_key_hash, plan, budget_usd, benchmark_opt_in                     │
 │                                                                      │
 ├──── org_members                    ┌── sessions                     │
 │      id (PK)                       │    token (PK)                  │
 │      org_id (FK→orgs)              │    org_id (FK→orgs)            │
 │      role, scope_team, email       │    role, member_id, expires_at │
 │      api_key_hash                  └────────────────────────────────┤
 │                                                                      │
 ├──── events                                                           │
 │      (id, org_id) PK                                                 │
 │      provider, model, cost_usd                                       │
 │      trace_id, parent_event_id ◄── DAG edges                        │
 │      hallucination_score, ...                                        │
 │                                                                      │
 ├──── team_budgets                   ┌── alert_configs                │
 │      (org_id, team) PK             │    org_id (PK)                 │
 │      budget_usd                    │    slack_url, trigger_*        │
 │                                    └────────────────────────────────┤
 ├──── cross_platform_usage                                             │
 │      id (PK), org_id, source                                         │
 │      developer_email, model, cost_usd                                │
 │      created_at TEXT                                                 │
 │                                                                      │
 ├──── otel_events                                                      │
 │      id (PK), org_id, service_name                                   │
 │      created_at TEXT                                                 │
 │                                                                      │
 ├──── prompts                        ┌── prompt_versions              │
 │      id (PK), org_id               │    id (PK)                     │
 │      name UNIQUE, deleted_at       │    prompt_id (FK→prompts)      │
 │                                    │    version_num, content        │
 │                                    │    total_calls, avg_cost_usd   │
 │                                    └─── prompt_usage                │
 │                                          version_id (FK)            │
 │                                          event_id, cost_usd         │
 │                                                                      │
 ├──── semantic_cache_entries         ┌── org_cache_config             │
 │      id (PK), org_id, team_id      │    org_id (PK)                 │
 │      prompt_hash, model            │    enabled, similarity_thresh  │
 │      response_text, cost_usd       │    min_prompt_length           │
 │      hit_count, total_savings_usd  │    max_cache_age_days          │
 │      vectorize_id                  └────────────────────────────────┤
 │      created_at TEXT                                                 │
 │                                                                      │
 ├──── audit_events                                                     │
 │      id (PK), org_id, actor_id                                       │
 │      action, event_type, metadata                                    │
 │                                                                      │
 ├──── benchmark_cohorts ──────────── benchmark_snapshots              │
 │      id (PK)                        cohort_id (FK)                  │
 │      size_band, industry            quarter, metric_name            │
 │                                     p25/p50/p75/p90                 │
 │                                     sample_size (≥5 to be public)   │
 │                                  ── benchmark_contributions         │
 │                                     org_id, snapshot_id             │
 │                                                                      │
 ├──── copilot_connections            ┌── datadog_connections          │
 │      org_id (UNIQUE)               │    org_id (UNIQUE)             │
 │      github_org, status            │    dd_site                     │
 │      (token in KV only)            │    api_key_enc (AES-256-GCM)   │
 │                                    └────────────────────────────────┤
 └──── budget_policies                                                  │
        id (PK), org_id                                                 │
        scope, scope_value, budget_usd                                  │
        enforcement ('alert'|'block')                                   │
```

### 3.1 `orgs`

```sql
CREATE TABLE orgs (
  id            TEXT PRIMARY KEY,     -- slug: "mycompany-a3f2"
  api_key_hash  TEXT NOT NULL,        -- SHA-256 of raw key (never store raw)
  api_key_hint  TEXT,                 -- "crt_mycompa..." (first 12 chars + ...)
  name          TEXT,
  email         TEXT UNIQUE,
  plan          TEXT DEFAULT 'free',  -- 'free' | 'team' | 'enterprise'
  budget_usd    REAL DEFAULT 0,       -- monthly limit; 0 = not set
  benchmark_opt_in INTEGER NOT NULL DEFAULT 0,
  account_type  TEXT DEFAULT 'organization',
  industry      TEXT,                 -- 'tech'|'finance'|'healthcare'|'other'
  created_at    INTEGER               -- unix timestamp
);
```

### 3.2 `org_members`

```sql
CREATE TABLE org_members (
  id            TEXT PRIMARY KEY,     -- 8-char hex random
  org_id        TEXT NOT NULL,        -- FK → orgs.id
  email         TEXT NOT NULL,
  name          TEXT,
  role          TEXT NOT NULL,        -- 'superadmin'|'ceo'|'admin'|'member'|'viewer'
  api_key_hash  TEXT NOT NULL,
  api_key_hint  TEXT,
  scope_team    TEXT,                 -- NULL = see all; non-null = filtered to team
  team_id       TEXT,                 -- internal team assignment (for cache namespace)
  created_at    INTEGER
);
```

### 3.3 `sessions`

```sql
CREATE TABLE sessions (
  token       TEXT PRIMARY KEY,       -- 64-char hex (32 random bytes)
  org_id      TEXT NOT NULL,
  role        TEXT NOT NULL,
  member_id   TEXT,                   -- NULL for owner sessions
  expires_at  INTEGER NOT NULL        -- unix timestamp, 30-day TTL
);
```

### 3.4 `events` — Core data table

```sql
CREATE TABLE events (
  id                  TEXT NOT NULL,
  org_id              TEXT NOT NULL,
  provider            TEXT,
  model               TEXT,
  prompt_tokens       INTEGER DEFAULT 0,
  completion_tokens   INTEGER DEFAULT 0,
  cache_tokens        INTEGER DEFAULT 0,
  total_tokens        INTEGER DEFAULT 0,
  cost_usd            REAL DEFAULT 0,
  latency_ms          INTEGER DEFAULT 0,
  team                TEXT,
  project             TEXT,
  user_id             TEXT,
  feature             TEXT,
  endpoint            TEXT,
  environment         TEXT DEFAULT 'production',
  is_streaming        INTEGER DEFAULT 0,
  stream_chunks       INTEGER DEFAULT 0,
  trace_id            TEXT,              -- agent trace grouping
  parent_event_id     TEXT,              -- parent span → DAG edge
  agent_name          TEXT,
  span_depth          INTEGER DEFAULT 0,
  tags                TEXT,              -- JSON object
  sdk_language        TEXT,
  sdk_version         TEXT,
  hallucination_score REAL,
  faithfulness_score  REAL,
  relevancy_score     REAL,
  consistency_score   REAL,
  toxicity_score      REAL,
  efficiency_score    REAL,
  created_at          INTEGER NOT NULL,  -- unix timestamp
  prompt_hash         TEXT,
  cache_hit           INTEGER NOT NULL DEFAULT 0,
  developer_email     TEXT,
  PRIMARY KEY (id, org_id)               -- dedup per org (INSERT OR IGNORE)
);
```

### 3.5 `semantic_cache_entries` (new in v2.0)

```sql
CREATE TABLE semantic_cache_entries (
  id                TEXT PRIMARY KEY,   -- UUID = also vectorize_id
  org_id            TEXT NOT NULL,
  team_id           TEXT,               -- optional team namespace
  prompt_hash       TEXT NOT NULL,      -- SHA-256 or first 16 chars for dedup
  prompt_text       TEXT NOT NULL,      -- full prompt text
  model             TEXT NOT NULL,
  response_text     TEXT NOT NULL,      -- cached LLM response
  prompt_tokens     INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  cost_usd          REAL DEFAULT 0,     -- cost of original call (basis for savings)
  vectorize_id      TEXT,               -- Vectorize vector ID (matches id)
  hit_count         INTEGER DEFAULT 0,
  total_savings_usd REAL DEFAULT 0,
  last_hit_at       TEXT,               -- YYYY-MM-DD HH:MM:SS
  created_at        TEXT NOT NULL       -- YYYY-MM-DD HH:MM:SS
);
```

### 3.6 `org_cache_config` (new in v2.0)

```sql
CREATE TABLE org_cache_config (
  org_id               TEXT PRIMARY KEY,
  enabled              INTEGER DEFAULT 1,
  similarity_threshold REAL DEFAULT 0.92,   -- cosine similarity floor
  min_prompt_length    INTEGER DEFAULT 10,  -- chars; short prompts not cached
  max_cache_age_days   INTEGER DEFAULT 30,
  updated_at           TEXT                 -- YYYY-MM-DD HH:MM:SS
);
```

### 3.7 `prompts` + `prompt_versions` + `prompt_usage` (new in v2.0)

```sql
CREATE TABLE prompts (
  id          TEXT PRIMARY KEY,
  org_id      TEXT NOT NULL,
  name        TEXT NOT NULL,
  description TEXT,
  created_by  TEXT NOT NULL,      -- member email or 'owner'
  deleted_at  TEXT,               -- soft delete
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (org_id, name)           -- name unique per org
);

CREATE TABLE prompt_versions (
  id                  TEXT PRIMARY KEY,
  prompt_id           TEXT NOT NULL,    -- FK → prompts.id
  version_num         INTEGER NOT NULL, -- auto-incremented per prompt
  content             TEXT NOT NULL,    -- full prompt template text
  model               TEXT,             -- target model (nullable)
  notes               TEXT,
  created_by          TEXT NOT NULL,
  total_calls         INTEGER DEFAULT 0,
  total_cost_usd      REAL DEFAULT 0,
  avg_cost_usd        REAL DEFAULT 0,
  avg_prompt_tokens   INTEGER DEFAULT 0,
  avg_completion_tokens INTEGER DEFAULT 0,
  created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE prompt_usage (
  id                TEXT PRIMARY KEY,
  version_id        TEXT NOT NULL,     -- FK → prompt_versions.id
  event_id          TEXT NOT NULL,     -- FK → events.id
  org_id            TEXT NOT NULL,
  cost_usd          REAL DEFAULT 0,
  prompt_tokens     INTEGER DEFAULT 0,
  completion_tokens INTEGER DEFAULT 0,
  created_at        TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (version_id, event_id)        -- idempotent (INSERT OR IGNORE)
);
```

### 3.8 `cross_platform_usage`

```sql
CREATE TABLE cross_platform_usage (
  id              TEXT PRIMARY KEY,
  org_id          TEXT NOT NULL,
  source          TEXT NOT NULL,       -- 'otel'|'copilot'|'datadog'|'sdk'
  provider        TEXT,
  developer_id    TEXT,
  developer_email TEXT,
  model           TEXT,
  input_tokens    INTEGER DEFAULT 0,
  output_tokens   INTEGER DEFAULT 0,
  cache_tokens    INTEGER DEFAULT 0,
  cost_usd        REAL DEFAULT 0,
  commits         INTEGER DEFAULT 0,
  pull_requests   INTEGER DEFAULT 0,
  lines_added     INTEGER DEFAULT 0,
  active_time_s   INTEGER DEFAULT 0,
  period_date     TEXT,                -- YYYY-MM-DD
  created_at      TEXT                 -- YYYY-MM-DD HH:MM:SS
);
```

### 3.9 `benchmark_snapshots`

```sql
CREATE TABLE benchmark_snapshots (
  id           INTEGER PRIMARY KEY,
  cohort_id    INTEGER NOT NULL,   -- FK → benchmark_cohorts.id
  quarter      TEXT NOT NULL,      -- '2026-Q2'
  metric_name  TEXT NOT NULL,      -- 'cost_per_token'|'cost_per_dev_month'|'cache_hit_rate'
  model        TEXT,               -- NULL = all models
  sample_size  INTEGER DEFAULT 0,
  p25          REAL,
  p50          REAL,
  p75          REAL,
  p90          REAL,
  updated_at   TEXT,
  UNIQUE (cohort_id, quarter, metric_name, model)
);
```

### 3.10 Migration Registry

| File | Description |
|---|---|
| `0001_cross_platform_usage.sql` | `cross_platform_usage`, `otel_events`, `provider_connections`, `budget_policies` |
| `0003_audit_events.sql` | `audit_events` table |
| `0004_audit_event_type.sql` | `ALTER TABLE audit_events ADD COLUMN event_type TEXT` |
| `0005_otel_traces.sql` | `otel_traces` table |
| `0006_otel_sessions.sql` | `otel_sessions` table |
| `0007_prompt_hash.sql` | `ALTER TABLE events ADD COLUMN prompt_hash TEXT` + `cache_hit` |
| `0008_benchmark_opt_in.sql` | `ALTER TABLE orgs ADD COLUMN benchmark_opt_in INTEGER NOT NULL DEFAULT 0` |
| `0009_copilot_connections.sql` | `copilot_connections` table |
| `0010_platform_tables.sql` | `platform_pageviews`, `platform_sessions`, `benchmark_*` tables |
| `0011_benchmark_snapshots.sql` | Additional indexes on `benchmark_snapshots` |
| `0012_datadog_connections.sql` | `datadog_connections` table |
| `0013_schema_fixes.sql` | Additional indexes and fixes |
| `0014_drop_copilot_kv_key.sql` | Removes `kv_key` from `copilot_connections` (token KV-only) |
| `0015_semantic_cache.sql` | `semantic_cache_entries`, `org_cache_config` tables |
| `0016_prompt_registry.sql` | `prompts`, `prompt_versions`, `prompt_usage` tables |
| `0017_benchmark_metric_name.sql` | `ALTER TABLE benchmark_snapshots ADD COLUMN metric_name TEXT` + `p25/p50/p75/p90` |

---

## 4. Authentication & Authorization System

### 4.1 API Key Format

```
crt_{orgId}_{16-hex-random}
 ^     ^          ^
 |     |          └── 16 bytes crypto.getRandomValues() = 128 bits entropy
 |     └───────────── org slug (for fast routing — no DB lookup to extract orgId)
 └─────────────────── Cohrint namespace prefix
```

Only `SHA-256(rawKey)` is stored. Raw key shown exactly once. Forgotten = must rotate.

### 4.2 Auth Middleware Flow

```
Request arrives at authMiddleware
           │
           ▼
  Has Cookie: cohrint_session / __Host-cohrint_session / vantage_session ?
           │
     ┌─────┴──────┐
    YES           NO
     │             │
     ▼             ▼
  SELECT sessions  Has Authorization: Bearer crt_... / vnt_... ?
  WHERE token=?         │
  AND expires_at >      │
  unixepoch()    ┌──────┴───────┐
     │          YES             NO
     │           │               │
  Found?         ▼               ▼
  ┌──┴──┐   Extract orgId    logAuditRaw(auth.failed)
 YES    NO  from key (parts[1]) → 401
  │     │       │
  │   fall    SHA-256(key)
  │   through     │
  ▼             SELECT orgs WHERE api_key_hash=?
set ctx:          │
orgId,role,   Found (owner)?
scopeTeam,    ┌───┴───┐
memberId,    YES      NO → SELECT org_members WHERE api_key_hash=?
memberEmail   │              │
  │           ▼          Found? → set ctx from member row
  │      role='owner'        │
  │      scopeTeam=null      NO → logAuditRaw(auth.failed) → 401
  │
  ▼
checkRateLimit(KV, orgId, RPM)
  │
  ├── exceeded? → 429 + Retry-After header
  │
  └── ok → logAudit(auth.login) → next()
```

### 4.3 Role Hierarchy

```
  owner  ──────────────────────────── (in orgs table; cannot be demoted)
    │    privilege rank: 5
    ▼
  superadmin ─────────────────────── (org_members, rank 4)
    │    platform-wide; manages all orgs; full audit access
    ▼
  ceo ────────────────────────────── (org_members, rank 3)
    │    executive read; GET /v1/analytics/executive only
    ▼
  admin ──────────────────────────── (org_members, rank 2)
    │    invites/removes members; budgets; policies
    │    BLOCKED: cannot promote to superadmin/owner
    ▼
  member ─────────────────────────── (org_members, rank 1)
    │    ingest events; read analytics (team-scoped if scope_team set)
    ▼
  viewer ─────────────────────────── (org_members, rank 0)
       read-only; 403 on POST /v1/events and /v1/otel/*
```

**Guards (in `auth.ts`):**

| Guard | Minimum rank | Allowed roles |
|---|---|---|
| `adminOnly` | admin (2) | owner, superadmin, ceo, admin |
| `executiveOnly` | ceo (3) | owner, superadmin, ceo |
| `superadminOnly` | superadmin (4) | owner, superadmin |
| inline viewer block | — | all except viewer |

`hasRole(role, minimum)` uses `ROLE_RANK` lookup — always use this function, never compare role strings directly.

### 4.4 Session Security Properties

| Property | Value | Reason |
|---|---|---|
| Cookie flags | `HttpOnly; SameSite=Lax; Secure` | XSS, CSRF, HTTPS-only |
| Cookie name | `__Host-cohrint_session` (prod) | Origin-bound, no Domain= attr required |
| `Domain` | `cohrint.com` (prod only) | Shared across `api.` and `app.` |
| TTL | 30 days from creation (not last use) | Balance UX vs. security |
| Token entropy | 256 bits (32 random bytes → 64 hex) | Unguessable |
| Storage | D1 `sessions` table | Consistent expiry + deletion |

### 4.5 Key Recovery Flow

```
POST /v1/auth/recover { email }
  │
  ├── always returns 200 (never leak email existence)
  │
  ├── found in orgs table:
  │     generate 48-char hex token (24 random bytes)
  │     KV.put("recover:{token}", {orgId,'owner'}, TTL=3600s)
  │     email → one-click redeem link
  │
  └── found in org_members:
        email → hint only (admin must reissue member keys)

GET /v1/auth/recover/redeem?token=TOKEN
  ├── peek KV (don't delete — email scanners follow GETs)
  ├── valid → redirect /auth?confirm_token=TOKEN
  └── invalid → redirect /auth?recovery_error=expired

POST /v1/auth/recover/redeem { token }
  ├── KV.get → verify
  ├── KV.delete → consume (single-use)
  ├── generate new key → hash → UPDATE orgs
  └── return { ok, api_key, hint }
```

**Critical:** GET does not consume the token. Gmail/Outlook Safe Links follow GETs automatically. Only POST consumes.

---

## 5. Event Ingest Pipeline

### 5.1 Single Event Flow

```
POST /v1/events
       │
       ▼
authMiddleware (cookie or Bearer)
       │
       ▼
viewer block (403 if role='viewer')
       │
       ▼
checkFreeTierLimit()
  SELECT COUNT(*) FROM events
  WHERE org_id=? AND created_at >= strftime('%s','now','start of month')
  if plan='free' AND count+new > 50000 → 429
       │
       ▼
buildInsertStmt() — field normalization
  (see alias table below)
       │
       ▼
INSERT OR IGNORE INTO events
  (id, org_id) composite PK → duplicate silently dropped
       │
       ├──▶ broadcastEvent()
       │      KV.put("stream:{orgId}:latest", payload, TTL=60s)
       │
       ├──▶ logAudit() — async
       │
       └──▶ maybeSendBudgetAlert() — async
              check mtd_cost vs budget_usd
              fire Slack if 80% or 100%
       │
       ▼
201 { ok: true, id: event_id }
```

### 5.2 Field Normalization Aliases

| Canonical field | SDK aliases accepted |
|---|---|
| `event_id` | `id` |
| `prompt_tokens` | `usage_prompt_tokens` |
| `completion_tokens` | `usage_completion_tokens` |
| `cache_tokens` | `usage_cached_tokens`, `cache_tokens` |
| `total_tokens` | `usage_total_tokens` (or prompt+completion sum) |
| `total_cost_usd` | `cost_total_usd`, `cost_total_cost_usd`, `cost_usd` |

### 5.3 Batch Ingest: POST /v1/events/batch

- Max 500 events per request
- `c.env.DB.batch(stmts)` — single D1 round-trip
- `broadcastEvent()` on last event only
- Returns `{ ok, accepted: N, failed: M }`

### 5.4 Quality Scores: PATCH /v1/events/:id/scores

Written async by LLM judge (Claude Opus 4.6). Fields: `hallucination_score`, `faithfulness_score`, `relevancy_score`, `consistency_score`, `toxicity_score`, `efficiency_score`. All nullable at insert time.

---

## 6. Analytics Engine & Trace DAG

### 6.1 Endpoint Map

| Endpoint | Time window | Primary aggregation |
|---|---|---|
| `GET /v1/analytics/summary` | today / 30-day MTD / last-30-min session | cost, tokens, requests, budget% |
| `GET /v1/analytics/kpis?period=N` | N days (max 365) | totals + averages + streaming count |
| `GET /v1/analytics/timeseries?period=N` | N days (max 365) | daily cost/tokens/requests |
| `GET /v1/analytics/models?period=N` | N days | per-model breakdown (top 25 by cost) |
| `GET /v1/analytics/teams?period=N` | N days | per-team cost + budget% |
| `GET /v1/analytics/traces?period=N` | N days (max 30) | agent trace summaries (top 100) |
| `GET /v1/analytics/traces/:traceId` | — | full span DAG for one trace |
| `GET /v1/analytics/cost?period=N` | N days + today | CI cost gate |
| `GET /v1/analytics/executive` | 30 days | cross-source spend roll-up (ceo+) |
| `GET /v1/analytics/savings?period=N` | N days (default 30) | routing savings: total_savings_usd, routing_rate, by_intent[], by_model[] |

### 6.2 Agent Trace DAG

The `events` table stores a directed acyclic graph via `trace_id` + `parent_event_id` + `span_depth`. Two endpoints reconstruct the graph:

**`GET /v1/analytics/traces?period=N`** — trace index:
```sql
SELECT
  trace_id,
  MIN(agent_name)      AS name,
  COUNT(*)             AS spans,
  SUM(cost_usd)        AS cost,
  SUM(latency_ms)      AS latency,
  MAX(CASE WHEN parent_event_id IS NULL THEN 1 ELSE 0 END) AS has_root,
  MIN(created_at)      AS started_at
FROM events
WHERE org_id = ? AND trace_id IS NOT NULL AND created_at >= ?
GROUP BY trace_id
ORDER BY started_at DESC
LIMIT 100
```

**`GET /v1/analytics/traces/:traceId`** — full span tree (RBAC enforced):
```sql
SELECT
  event_id AS id, parent_event_id AS parent_id,
  agent_name, model, provider, feature,
  span_depth, prompt_tokens, completion_tokens,
  cache_tokens, cost_usd, latency_ms, created_at
FROM events
WHERE org_id = ? AND trace_id = ?
  [AND team = ? if scopeTeam]
  [AND developer_email = ? if role < admin]   -- non-admins see only their own spans
ORDER BY created_at ASC
```

**RBAC on trace detail:** Members below `admin` rank can only see spans where `developer_email` matches their own email. Admins see all spans in the trace.

**DAG reconstruction in frontend:**
```
spans returned ordered by created_at ASC
  │
  ▼
Build adjacency map: id → [children]
  root = spans where parent_id IS NULL
  │
  ▼
Recursive tree render: root → children → grandchildren
  span_depth provides visual indentation hint
```

### 6.3 DAG Sequence Diagram

```
Client (dashboard)          Worker                  D1
     │                         │                     │
     │─GET /analytics/traces──▶│                     │
     │                         │─SELECT trace summary▶│
     │◀─{ traces: [...] }──────│◀──────────────────── │
     │                         │                     │
     │─GET /traces/:traceId───▶│                     │
     │                         │  check role         │
     │                         │  isPrivileged?       │
     │                         │  ┌── YES: no devClause
     │                         │  └── NO:  AND developer_email=?
     │                         │─SELECT spans────────▶│
     │◀─{ spans: [...] }───────│◀──────────────────── │
     │                         │                     │
     │  Build DAG in JS        │                     │
     │  root = parent_id=null  │                     │
     │  children via Map       │                     │
     │  Render tree UI         │                     │
```

### 6.4 Team Scoping

`teamScope(scopeTeam)` appends `AND team = ?` to every analytics query when `scope_team` is non-null. Data isolation is enforced at the SQL layer, not application layer. A viewer with `scope_team='backend'` can never read `team='frontend'` events.

---

## 7. Semantic Cache Layer

New in v2.0. Uses Cloudflare Vectorize (cosine similarity) + Workers AI (BGE-small-en-v1.5, 384 dimensions) to serve cached LLM responses for semantically equivalent prompts.

### 7.1 Architecture

```
Application                   Worker (/v1/cache/*)        Vectorize + Workers AI
     │                               │                          │
     │──POST /v1/cache/lookup────────▶│                          │
     │  { prompt, model }            │                          │
     │                               │──getOrgCacheConfig()──▶D1│
     │                               │  enabled? min_length?    │
     │                               │                          │
     │                               │──embedText(prompt)───────▶
     │                               │  AI.run(bge-small-en)    │
     │                               │◀─ float[384] embedding───│
     │                               │                          │
     │                               │──VECTORIZE.query()───────▶
     │                               │  filter: {org_id, model} │
     │                               │  topK: 1                 │
     │                               │◀─ { id, score }──────────│
     │                               │                          │
     │                               │  score >= threshold?     │
     │                               │  ┌─YES──────────────────▶│
     │                               │  │  SELECT * FROM        │
     │                               │  │  semantic_cache_entries│
     │                               │  │  WHERE id=? org_id=?  │
     │                               │  │  check age_days       │
     │                               │  │  UPDATE hit_count+1   │
     │◀──{ hit:true, response }──────│  │  (waitUntil async)    │
     │                               │  └──────────────────────── │
     │                               │  NO → { hit:false, score }│
     │◀──{ hit:false }───────────────│                          │
```

### 7.2 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/cache/lookup` | any | Find cached response for prompt |
| `POST` | `/v1/cache/store` | any | Store prompt+response pair |
| `GET` | `/v1/cache/stats` | any | Hit rate + savings + recent entries |
| `PATCH` | `/v1/cache/config` | admin+ | Update org cache configuration |
| `DELETE` | `/v1/cache/entries/:id` | admin+ | Remove a specific cache entry |

### 7.3 Configuration Defaults

| Parameter | Default | Range | Description |
|---|---|---|---|
| `enabled` | `1` | 0/1 | Master on/off switch per org |
| `similarity_threshold` | `0.92` | 0.0–1.0 | Cosine similarity floor for a hit |
| `min_prompt_length` | `10` | chars | Prompts below this are not cached |
| `max_cache_age_days` | `30` | days | Entries older than this are evicted |

### 7.4 Cache Lookup Request/Response

```bash
# Lookup
curl -X POST https://api.cohrint.com/v1/cache/lookup \
  -H "Authorization: Bearer crt_..." \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize this document...", "model": "gpt-4o"}'

# Hit response
{
  "hit": true,
  "score": 0.9731,
  "response": "The document covers...",
  "prompt_tokens": 450,
  "completion_tokens": 120,
  "saved_usd": 0.00612,
  "cache_entry_id": "uuid-..."
}

# Miss response
{ "hit": false, "score": 0.8412 }

# Store
curl -X POST https://api.cohrint.com/v1/cache/store \
  -H "Authorization: Bearer crt_..." \
  -d '{
    "prompt": "Summarize this document...",
    "model": "gpt-4o",
    "response": "The document covers...",
    "prompt_tokens": 450,
    "completion_tokens": 120,
    "cost_usd": 0.00612,
    "prompt_hash": "sha256hexofprompt"
  }'
# → 201 { "stored": true, "cache_entry_id": "uuid-..." }
```

### 7.5 Duplicate Prevention

Before embedding+storing, the `store` endpoint checks for an exact-match via `prompt_hash`:
```sql
SELECT id FROM semantic_cache_entries
WHERE org_id = ? AND prompt_hash = ? AND model = ?
```
If found, returns `{ stored: false, reason: 'duplicate', cache_entry_id }` without hitting Vectorize.

### 7.6 Team Namespace Isolation

When the authenticated member has `scopeTeam` set, `team_id` is included in both the Vectorize metadata filter and the D1 WHERE clause. A scoped member for `team='backend'` cannot retrieve a cache entry stored by `team='frontend'`, even if the prompt is identical and semantically equivalent. This is enforced at both the Vectorize query layer (metadata filter) and the D1 fetch layer (re-checked in SQL).

### 7.7 Stale Entry Eviction

On a hit, the handler checks entry age:
```sql
SELECT (julianday('now') - julianday(created_at)) AS age_days
FROM semantic_cache_entries WHERE id = ?
```
If `age_days > max_cache_age_days`, the entry is evicted asynchronously via `waitUntil`:
1. `VECTORIZE.deleteByIds([id])` — remove from vector index
2. `DELETE FROM semantic_cache_entries WHERE id = ?` — remove from D1

Returns `{ hit: false, reason: 'entry_expired' }`.

---

## 8. Prompt Registry

New in v2.0. Version-controlled prompt templates with per-version cost tracking and A/B comparison.

### 8.1 RBAC

| Operation | Required role |
|---|---|
| List prompts (`GET /v1/prompts`) | any authenticated |
| Get prompt + versions (`GET /v1/prompts/:id`) | any authenticated |
| Get version analytics comparison | any authenticated |
| Create prompt (`POST /v1/prompts`) | admin+ |
| Update prompt name/description | admin+ |
| Soft delete prompt | admin+ |
| Add new version | admin+ |
| Get single version (full content) | admin+ |
| Record usage (`POST /v1/prompts/usage`) | any authenticated (SDK) |

### 8.2 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/v1/prompts` | any | List all (with version count + total cost) |
| `POST` | `/v1/prompts` | admin | Create prompt (optionally with first version inline) |
| `GET` | `/v1/prompts/:id` | any | Get prompt + version list (200-char preview) |
| `PATCH` | `/v1/prompts/:id` | admin | Update name/description |
| `DELETE` | `/v1/prompts/:id` | admin | Soft delete (`deleted_at = now()`) |
| `POST` | `/v1/prompts/:id/versions` | admin | Add new version (auto-increments `version_num`) |
| `GET` | `/v1/prompts/:id/versions/:vId` | admin | Get full version content + stats |
| `POST` | `/v1/prompts/usage` | any | Record LLM event attribution to version |
| `GET` | `/v1/prompts/analytics/comparison` | any | Cost comparison across all versions |

### 8.3 Version Comparison Flow

```
GET /v1/prompts/analytics/comparison?prompt_id=uuid
           │
           ▼
  Verify prompt ownership (org_id check)
           │
           ▼
  SELECT all versions ORDER BY version_num ASC
  (returns content_preview first 100 chars + stats)
           │
           ▼
  Compute cost_delta_pct between consecutive versions:
    delta = ((v_n.avg_cost - v_{n-1}.avg_cost) / v_{n-1}.avg_cost) * 100
    null for version 1 (no prior)
           │
           ▼
  Response: { prompt, versions: [{...v, cost_delta_pct}] }
```

```
Version comparison example:

v1  avg_cost=$0.0050  total_calls=1000   cost_delta_pct=null
v2  avg_cost=$0.0032  total_calls=800    cost_delta_pct=-36.0  ← 36% cheaper
v3  avg_cost=$0.0041  total_calls=200    cost_delta_pct=+28.1  ← regression
```

### 8.4 SDK Attribution Flow

```
SDK (Python/JS)                  Worker
     │                               │
     │  1. LLM call completes        │
     │     cost_usd, tokens known    │
     │                               │
     │──POST /v1/prompts/usage──────▶│
     │  { version_id, event_id,      │
     │    cost_usd, prompt_tokens,   │
     │    completion_tokens }        │
     │                               │
     │                        verify version belongs to org
     │                               │
     │                        D1.batch([
     │                          INSERT OR IGNORE prompt_usage,
     │                          UPDATE prompt_versions SET
     │                            total_calls = total_calls + 1,
     │                            avg_cost_usd = rolling avg
     │                        ])
     │◀──201 { recorded: true }──────│
```

Rolling average formula:
```
new_total_calls = old_total_calls + 1
new_total_cost  = old_total_cost + cost_usd
new_avg_cost    = new_total_cost / new_total_calls
new_avg_prompt  = (old_avg_prompt * old_calls + new_tokens) / new_calls
```

---

## 9. Public Benchmark Dashboard

### 9.1 Overview

Anonymized industry benchmarks. Orgs opt in via `benchmark_opt_in = 1`. No org identifiers in public endpoints. k-anonymity floor: cohorts with `sample_size < 5` return 404.

### 9.2 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/benchmark/contribute` | admin/owner | Compute + upsert quarterly snapshot |
| `GET` | `/v1/benchmark/percentiles` | **public** | p25/p50/p75/p90 by metric+model |
| `GET` | `/v1/benchmark/summary` | **public** | Available metric+model combos with sample sizes |

### 9.3 Metrics Tracked

| Metric | Formula | Unit |
|---|---|---|
| `cost_per_token` | `SUM(cost_usd) / SUM(input+output tokens)` | USD per token |
| `cost_per_dev_month` | `(SUM(cost_usd) / COUNT(DISTINCT developer_email)) / 3` | USD/dev/month |
| `cache_hit_rate` | `SUM(cached_tokens) / SUM(gross_tokens)` | 0.0–1.0 |

### 9.4 k-Anonymity Data Flow

```
syncBenchmarkContributions() — cron, Sundays UTC only
           │
           ▼
  SELECT orgs WHERE benchmark_opt_in = 1
           │
    For each org:
           │
           ▼
  computeAndUpsertContribution(db, orgId)
    │
    ├── verify opt_in = 1
    │
    ├── sizeBand(memberCount)  →  '1-10'|'11-50'|'51-200'|'201-1000'|'1000+'
    │
    ├── ensureCohort(band, industry)  →  cohort_id
    │
    ├── query cross_platform_usage for quarter date range
    │   (TEXT dates: "YYYY-QN" → month start/end strings)
    │
    ├── compute metrics: cost_per_token, cost_per_dev_month, cache_hit_rate
    │
    └── For each metric:
          │
          ├── UPSERT benchmark_snapshots (sample_size starts 0)
          │
          ├── INSERT OR IGNORE benchmark_contributions (org_id, snapshot_id)
          │
          ├── Re-aggregate ALL contributing orgs' values via JOIN
          │   (avoids storing individual org values — only percentiles stored)
          │
          ├── percentiles([sorted values]) → p25, p50, p75, p90
          │
          └── UPDATE benchmark_snapshots SET p25/p50/p75/p90, sample_size


GET /v1/benchmark/percentiles?metric=cost_per_token&model=gpt-4o
           │
           ▼
  SELECT weighted percentiles FROM benchmark_snapshots
  WHERE metric_name=? AND COALESCE(model,'')=COALESCE(?,'')
    AND sample_size >= 5                ← k-anonymity floor
  GROUP BY quarter
  HAVING MIN(sample_size) >= 5          ← all cohorts must pass
  ORDER BY quarter DESC LIMIT 1

  total_sample < 5? → 404 "Insufficient data"
```

### 9.5 Cohort Size Bands

| Band | Member count |
|---|---|
| `1-10` | ≤ 10 |
| `11-50` | 11–50 |
| `51-200` | 51–200 |
| `201-1000` | 201–1000 |
| `1000+` | > 1000 |

### 9.6 Manual Contribution Trigger

```bash
curl -X POST https://api.cohrint.com/v1/benchmark/contribute \
  -H "Authorization: Bearer crt_..." \
# Response: { "ok": true }
# or { "ok": false, "reason": "not_opted_in" | "no_usage_data" }
```

Restricted to `owner` or `admin` to prevent member-triggered O(N contributors) re-aggregation.

---

## 10. Rate Limiting Algorithm

### 10.1 Upstash Redis — Fixed-Window Counter via HTTP Pipeline

Rate limiting moved from Cloudflare KV to **Upstash Redis** (free tier: 10K commands/day).
KV was hitting its 1,000 write/day free-tier limit under normal OTel traffic.

**Storage:** `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` worker secrets.

**Two tiers controlled by `orgs` table columns:**

| Column | Value | Behaviour |
|---|---|---|
| `is_test` | `1` | Skip rate limiting entirely — 0 Redis commands |
| `is_test` | `0` (default) | Apply rate limiting |
| `plan` | `'free'` (default) | Per-key limiting only — 2 Redis commands/request |
| `plan` | anything else | Per-key + org-level limiting — 4 Redis commands/request |

**Algorithm — INCR + EXPIRE pipeline (1 HTTP round-trip):**

```
bucket = floor(now / 60_000)   // 1-minute window

// Always (non-test accounts):
INCR  rl:key:{apiKey[0..8]}:{bucket}   → keyCount
EXPIRE rl:key:{apiKey[0..8]}:{bucket} 70

// Premium only (plan != 'free'):
INCR  rl:org:{orgId}:{bucket}          → orgCount
EXPIRE rl:org:{orgId}:{bucket} 70

if keyCount > RATE_LIMIT_RPM → 429
if orgCount > RATE_LIMIT_RPM * 5 → 429
```

- Default: `RATE_LIMIT_RPM = 1000` (env var in wrangler.toml)
- 429 response includes: `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`
- Upstash failure → allow through (graceful degradation)

### 10.2 Operational Runbook

**Mark an account as internal/test (skip rate limiting):**
```sql
UPDATE orgs SET is_test=1 WHERE id='<org-id>';
```

**Upgrade a paying customer to premium rate limiting:**
```sql
UPDATE orgs SET plan='pro' WHERE id='<org-id>';
```
> `plan` is the single source of truth for payment status. When Stripe integration is added,
> the webhook handler updates `plan` automatically on `invoice.paid` / `customer.subscription.deleted`.

**Downgrade / cancel:**
```sql
UPDATE orgs SET plan='free' WHERE id='<org-id>';
```

**Check current flags for an org:**
```sql
SELECT id, plan, is_test FROM orgs WHERE id='<org-id>';
```

---

## 11. Real-Time Streaming (SSE)

### 11.1 Polling-Over-SSE Architecture

Workers have a 30s wall-clock limit. True persistent WebSocket requires Durable Objects. Current design simulates real-time via short-lived SSE connections that auto-reconnect.

```
Client (browser)              Worker                       KV
     │                           │                          │
     │──GET /v1/stream/:orgId────▶│                          │
     │  ?sse_token=XYZ           │                          │
     │                           │─validate sse_token───────▶
     │                           │  (one-time use, 120s TTL)│
     │                           │─delete sse_token─────────▶
     │                           │                          │
     │                           │  Open TransformStream    │
     │                           │  deadline = now + 25s    │
     │                           │                          │
     │                           │  LOOP every 2s:          │
     │                           │─GET stream:{orgId}:latest▶
     │                           │◀─ payload or null ───────│
     │                           │                          │
     │                           │  if ts > lastTs:         │
     │◀──data: {event json}──────│    writer.write(event)   │
     │                           │  else:                   │
     │◀──: ping ─────────────────│    writer.write(ping)    │
     │                           │                          │
     │                           │  END LOOP at deadline    │
     │                           │─writer.close()           │
     │  [auto-reconnect]         │                          │
```

### 11.2 SSE Token Security

Browser `EventSource` API does not support custom headers. Two auth methods:

1. `?sse_token=` — 32-char hex, KV TTL=120s, one-time use (prevents replay from URL logs). Generated in `GET /v1/auth/session`.
2. `?token=crt_...` — legacy bearer in query param (SDK/direct callers).

---

## 12. Alert System

### 12.1 Budget Alert Algorithm

```typescript
async function maybeSendBudgetAlert(db, kv, orgId, mtdCost, budgetUsd) {
  const pct = (mtdCost / budgetUsd) * 100;

  let alertType: string | null = null;
  if (pct >= 100) alertType = 'budget_100';
  else if (pct >= 80) alertType = 'budget_80';
  if (!alertType) return;

  // Throttle: one alert per type per hour
  const throttleKey = `alert:${orgId}:${alertType}`;
  if (await kv.get(throttleKey)) return;

  const slackUrl = await kv.get(`slack:${orgId}`);
  if (!slackUrl) return;   // webhook not configured

  await sendSlackMessage(slackUrl, budgetAlertPayload);
  await kv.put(throttleKey, '1', { expirationTtl: 3600 });
}
```

Thresholds: 80% and 100%. Throttled to once per hour per threshold via KV. Webhook URL cached in KV from D1 on configuration.

---

## 13. Email Infrastructure

Sent via Resend (`RESEND_API_KEY` secret). Silent no-op if key not set.

### 13.1 Sender Fallback

```typescript
const senders = [
  'Cohrint <noreply@cohrint.com>',      // custom domain (requires DNS verification)
  'Cohrint <onboarding@resend.dev>',    // Resend shared domain (always works)
];
// Retries with shared sender if domain not verified (validation_error only)
```

### 13.2 Email Templates

**`memberInviteEmail`** — admin invites member; shows org, role, scope, raw API key (once), CTA to dashboard.

**`keyRecoveryEmail`** — owner: one-click redeem (expires 1h); member: hint only + "ask admin".

---

## 14. Admin & Team Management

### 14.1 Member Invite Flow

```
POST /v1/auth/members (adminOnly)
{ email, name, role, scope_team? }
  │
  ├── validate email format
  ├── 409 if already a member
  ├── generate memberId (8-char hex), rawKey, hash
  ├── INSERT INTO org_members
  ├── waitUntil: send invite email
  └── return { member_id, api_key (once), hint, role, scope_team }
```

Escalation guard: admins cannot invite to `superadmin` or `owner` roles.

### 14.2 Key Rotation

- **Owner:** `POST /v1/auth/rotate` (owner only) — instant, old key dead immediately, sessions survive
- **Member:** `POST /v1/auth/members/:id/rotate` (admin+) — targets member by `member_id` field, sends email

### 14.3 Admin Overview Payload

`GET /v1/admin/overview` returns combined payload powering the admin panel:
```json
{
  "org": { "id", "name", "email", "plan", "budget_usd", "budget_pct", "mtd_cost_usd" },
  "totals": { "total_cost_usd", "total_tokens", "total_requests", "avg_latency_ms" },
  "teams": [{ "team", "cost_usd", "budget_usd", "budget_pct" }],
  "members": [{ "id", "email", "name", "role", "scope_team", "hallucination_score" }],
  "period_days": 30
}
```

**New in v2.0:** `members` array includes per-developer `hallucination_score` (average across their events for the period).

### 14.4 Budget Policies CRUD

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/v1/admin/budget-policies` | admin+ | List all policies |
| `POST` | `/v1/admin/budget-policies` | admin+ | Create policy |
| `PUT` | `/v1/admin/budget-policies/:id` | admin+ | Update budget/period/enforcement |
| `DELETE` | `/v1/admin/budget-policies/:id` | admin+ | Remove policy |

`enforcement: "block"` → `POST /v1/events` returns 429 when scope budget exceeded.

---

## 15. Frontend Architecture & RBAC Guards (PR #67)

### 15.1 File Structure

```
cohrint-frontend/
├── index.html        — Landing page
├── app.html          — Main SPA dashboard (auth-gated)
├── auth.html         — Sign-in
├── signup.html       — Signup
├── docs.html         — API documentation
├── calculator.html   — Cost calculator
├── sw.js             — Service Worker (offline)
├── manifest.json     — PWA manifest
├── _headers          — Cloudflare Pages headers (CSP, cache control)
└── _redirects        — URL routing rules
```

### 15.2 Navigation Pattern

```javascript
function nav(view) {
  // RBAC gate added in PR #67:
  if (view === 'integrations' && userRole === 'member') {
    return nav('overview');   // non-admin redirected to overview
  }
  document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
  document.getElementById(`view-${view}`).style.display = '';
  loadView(view);
}
```

### 15.3 RBAC Guards Shipped in PR #67

The following UI elements are gated by role. Applying them at the frontend is a UX guard only — the API enforces the same restrictions on the backend.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Tab / Card                    Minimum Role    PR #67 change        │
├─────────────────────────────────────────────────────────────────────┤
│  Cross-Platform tab            admin+          Added role gate       │
│  Cost per Developer card       admin+          Hidden from member    │
│  Budgets & Alerts tab          admin+          Hidden from member    │
│  Integrations view (nav)       admin+          nav() guard added     │
│  Per-developer hallucination   admin+          New column in members │
└─────────────────────────────────────────────────────────────────────┘
```

**State machine for tab visibility:**

```
User logs in
     │
     ▼
GET /v1/auth/session → role
     │
     ├── role ∈ {owner, superadmin, ceo, admin}
     │     │
     │     ├── show: All tabs including Cross-Platform, Integrations
     │     ├── show: Cost per Developer card in Overview
     │     ├── show: Budgets & Alerts tab
     │     └── show: Per-developer hallucination in members table
     │
     └── role ∈ {member, viewer}
           │
           ├── hide: Cross-Platform tab (display:none)
           ├── hide: Cost per Developer card
           ├── hide: Budgets & Alerts tab
           ├── nav('integrations') → redirected to nav('overview')
           └── members table omits hallucination_score column
```

### 15.4 Theme System

```javascript
// Inline <head> script (before CSS — prevents flash):
(function(){
  var t = localStorage.getItem('vantage_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();
```

### 15.5 Security Headers (`_headers`)

```
# All pages
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()

# app.html — no caching
Cache-Control: no-cache, no-store, must-revalidate
Content-Security-Policy:
  default-src 'self' 'unsafe-inline' [CDNs]
  connect-src 'self' https://api.cohrint.com wss://api.cohrint.com
  img-src 'self' data:
```

`'unsafe-inline'` required due to inline `<script>` blocks. Mitigated by strict `connect-src`.

---

## 16. Client Types & Integration Patterns

### 16.1 Python Backend

```python
# pip install cohrint
from cohrint import OpenAIProxy
client = OpenAIProxy(api_key="crt_myorg_...")
response = client.chat.completions.create(model="gpt-4o", messages=[...])
# SDK silently posts event in background thread
```

### 16.2 TypeScript/Node.js

```typescript
import { OpenAIProxy } from 'cohrint';
const client = new OpenAIProxy({
  apiKey: 'crt_myorg_...',
  defaultTags: { team: 'frontend', feature: 'chat', user_id: userId }
});
```

### 16.3 AI Agent / Multi-Agent (Trace DAG)

```python
import requests, uuid
trace_id = str(uuid.uuid4())

# Root span (parent_event_id=None, span_depth=0)
root_id = str(uuid.uuid4())
requests.post("https://api.cohrint.com/v1/events", json={
  "event_id": root_id,
  "trace_id": trace_id, "parent_event_id": None,
  "agent_name": "ResearchAgent", "span_depth": 0,
  ...
}, headers={"Authorization": "Bearer crt_..."})

# Child span (parent_event_id=root_id, span_depth=1)
requests.post("https://api.cohrint.com/v1/events", json={
  "event_id": str(uuid.uuid4()),
  "trace_id": trace_id, "parent_event_id": root_id,
  "agent_name": "SummarizerAgent", "span_depth": 1,
  ...
})
```

### 16.4 MCP (IDE Integration)

Read-only analytics path. Never ingests events. MCP tools: `get_summary`, `get_model_breakdown`, `check_budget`, `get_traces`, `track_llm_call`, `optimize_prompt`.

### 16.5 CI/CD Cost Gate

```yaml
- name: Check AI cost gate
  run: |
    COST=$(curl -sf -H "Authorization: Bearer $VANTAGE_KEY" \
      "https://api.cohrint.com/v1/analytics/cost?period=1" | jq '.today_cost_usd')
    python -c "import sys; sys.exit(1 if float('$COST') > 5.0 else 0)"
```

---

## 17. CI/CD & Deployment Pipeline

### 17.1 Branch Strategy

```
main (production — CF deploys from here)
  └── fix/*, feat/*, v[0-9]* (working branches)
        └── v1.0/P001-fix-nav (feature branches)
  └── backup/v1.0 (immutable snapshots)
```

### 17.2 Workflow Overview

| Workflow | Trigger | Action |
|---|---|---|
| `deploy.yml` | Push to `main` (frontend) | Wrangler Pages deploy (4-attempt retry) |
| `deploy-worker.yml` | Push to `main` (worker) | TypeScript check → Wrangler worker deploy |
| `ci-version.yml` | Push to `v[0-9]*` | Full test suite → backup branch → PR to main |
| `ci-feature.yml` | Push to `v*/P*` | Fast smoke tests only |
| `ci-test.yml` | Post-deploy on main | Full test validation |
| `repo-backup.yml` | Push to main + daily 03:00 UTC | Mirror + ZIP artifact |

### 17.3 Deploy Retry Logic

```bash
MAX_ATTEMPTS=4; DELAY=30
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if npm run deploy; then exit 0; fi
  sleep $DELAY; DELAY=$((DELAY * 2))   # 30 → 60 → 120s
done; exit 1
```

### 17.4 Active Test Suites

| Suite | Directory | Coverage |
|---|---|---|
| 32 | `32_audit_log` | Audit event creation, pagination, role guard |
| 33 | `33_frontend_contract` | API shape contract for all frontend endpoints |
| 34 | `34_vega_chatbot` | Chatbot/recommendations widget API |
| 35 | `35_cross_platform_console` | Cross-platform console (8 endpoints) |
| 36 | `36_semantic_cache` | Cache hit/miss, threshold, dedup, team isolation |
| 37 | `37_all_dashboard_cards` | All dashboard card data shapes |
| 38 | `38_security_hardening` | OWASP top-10, injection, CORS |
| 39 | `39_copilot_adapter` | Copilot connect/disconnect/sync |
| 40 | `40_benchmark` | Contribute, percentiles, k-anonymity floor |
| 41 | `41_datadog_exporter` | Datadog connect, encrypt/decrypt, sync |
| 45 | `45_dashboard_api_coverage` | Full dashboard API coverage (seed state DA45) |
| 51 | `51_playwright_rbac` | Playwright + API role visibility (49 checks) |

---

## 18. Test Infrastructure

### 18.1 Directory Structure

```
tests/
├── config/settings.py          — All URLs/secrets from env vars
├── infra/
│   ├── structured_logger.py    — NDJSON structured logging
│   ├── reporter.py             — Result aggregation + HTML/JSON report
│   ├── metrics_collector.py    — Per-endpoint latency percentiles
│   └── cleanup.py              — Remove artifacts older than N days
├── helpers/
│   ├── api.py                  — signup_api, fresh_account
│   ├── browser.py              — Playwright factory + console error collector
│   ├── data.py                 — rand_email, rand_org, rand_name
│   └── output.py               — ok/fail/warn/info/section/chk
├── suites/
│   ├── 01_api/ … 13_dashboard/ — Legacy suites
│   ├── 17_otel/ … 21_vantage_cli/
│   └── 32_audit_log/ … 51_playwright_rbac/
└── artifacts/
    ├── da45_seed_state.json    — Persistent DA45 test accounts (gitignored)
    └── da45_credentials.txt   — Human login cards
```

### 18.2 DA45 Seed State

Persistent test accounts — always load before creating new accounts for dashboard/API tests:
```python
state = json.loads(Path("tests/artifacts/da45_seed_state.json").read_text())
admin_key    = state["admin"]["api_key"]
member_key   = state["member"]["api_key"]
ceo_key      = state["ceo"]["api_key"]
superadmin_key = state["superadmin"]["api_key"]
```

Re-seed if needed: `python tests/suites/45_dashboard_api_coverage/seed.py --force`

### 18.3 SLA Targets (Suite 08)

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| GET /health | < 100ms | < 300ms | < 500ms |
| POST /session | < 300ms | < 800ms | < 1500ms |
| GET /analytics/summary | < 500ms | < 1200ms | < 2500ms |
| POST /events | < 200ms | < 600ms | < 1200ms |

---

## 19. Security Model

### 19.1 API Key Security

- Never stored in plaintext. Only SHA-256 hash in DB.
- `crt_{orgId}_{16-hex-random}` — orgId embedded for fast routing, 128 bits entropy in random segment.
- One-way: no decrypt path. Forgotten = rotate.
- Rotation is instant. No grace period for old key.

### 19.2 Cross-Org Data Isolation

All D1 queries include `WHERE org_id = ?` bound to authenticated orgId. No cross-org query exists. For scoped members, `teamScope()` appends `AND team = ?` at the SQL layer.

### 19.3 Sensitive Credential Storage

| Secret | Storage | Encryption |
|---|---|---|
| Owner/member API keys | D1 (hash only) | SHA-256 (one-way) |
| Session tokens | D1 | 256-bit random, no encryption needed |
| Recovery tokens | KV (TTL=3600s) | 192-bit random |
| SSE tokens | KV (TTL=120s) | 256-bit random |
| GitHub Copilot PAT | KV only (never D1) | AES-256-GCM (`TOKEN_ENCRYPTION_SECRET`) |
| Datadog API key | D1 (`api_key_enc` + `api_key_iv`) | AES-256-GCM |

### 19.4 CORS Policy

```typescript
ALLOWED_ORIGINS = "https://cohrint.com,https://www.cohrint.com,https://cohrint.pages.dev"
// Wildcard suffix supported: "https://*.cohrint.com"
// Always echoes specific origin (not *) when credentials involved
// SSE endpoint uses * (no credentials)
```

### 19.5 Frontend Security Notes

- Chart.js CDN: SRI hash enforced (`integrity="sha384-..."`) — CDN compromise cannot execute unsigned JS
- `apiFetch` not exposed on `window` — external scripts use one-time `window.__cpRegister` callback
- `api_base` validated against allowlist (`api.cohrint.com`, `localhost`)
- All dynamic DOM writes use `textContent` — no `innerHTML` anywhere

### 19.6 Audit Log Coverage

Every authenticated request writes to `audit_events` (async via `waitUntil`):
- `auth.login` — every successful auth (session + key paths)
- `auth.failed` — every failed auth attempt (logged with IP)
- `admin.*` — member invite, remove, key rotate, budget change
- `key.rotated`, `member.invited`, `member.removed`, `budget.changed`
- Exception: `GET /v1/audit-log` itself is NOT logged (prevents offset pagination drift)

---

## 20. Business Algorithms — Current & Research-Backed Future

### 20.1 Currently Implemented

**Fixed-Window Rate Limiting** — KV-based, per-org, per-minute. Burst at boundary tradeoff acceptable for telemetry use case.

**Free-Tier Enforcement** — Calendar-month event count via `strftime('%s','now','start of month')`.

**Budget Alert Throttling** — KV TTL=1h deduplication per alert type.

**Cost Attribution** — Tag-based GROUP BY. No ML. Pure aggregation.

**Quality Scoring** — Claude Opus 4.6 LLM-as-judge, async, 6 dimensions.

**Semantic Cache Similarity** — BGE-small-en-v1.5 cosine similarity, 0.92 default threshold.

**Benchmark Percentiles** — Weighted percentile interpolation across contributing orgs, p25/p50/p75/p90.

### 20.2 Algorithms to Build Next

#### A. Anomaly Detection — Cost Spike Alert

```python
def is_anomaly(current_hour_cost, historical_costs):
    mean = statistics.mean(historical_costs)
    std  = statistics.stdev(historical_costs)
    z_score = (current_hour_cost - mean) / max(std, 0.001)
    return z_score > 3.0  # 3-sigma threshold
```

Run as Cloudflare Cron Trigger. Query hourly cost from D1, compute Z-score, Slack alert if triggered.

#### B. Sliding Window Rate Limiter (Durable Objects)

Current fixed-window allows 2x burst. Durable Objects provide strongly-consistent sliding window log.

#### C. Cost Forecasting

Linear regression on daily MTD cost → project end-of-month total → alert if projected > 90% of budget.

#### D. Model Recommendation Engine

Cluster by task type (`feature` tag) → find cheaper models with comparable `faithfulness_score` → compute monthly savings.

---

## 21. Pricing & Plan Logic

### 21.1 Plans

| Feature | Free | Team ($99/mo) | Enterprise |
|---|---|---|---|
| Events/month | 50,000 | Unlimited | Unlimited |
| Members | — | Up to 10 | Unlimited |
| Team scoping | — | ✓ | ✓ |
| Budget alerts | — | ✓ | ✓ |
| Semantic cache | — | ✓ | ✓ |
| Prompt registry | — | ✓ | ✓ |
| Benchmark access | — | ✓ | ✓ |
| SSE live stream | ✓ | ✓ | ✓ |
| API cost gate | ✓ | ✓ | ✓ |
| SLA | — | — | 99.9% |

### 21.2 OTel Pricing Table (auto cost estimation)

When tools send only token counts (no explicit cost), Cohrint auto-calculates `cost_usd`:

| Model | Input ($/1M) | Output ($/1M) | Cache ($/1M) |
|---|---|---|---|
| claude-opus-4-6 | $15.00 | $75.00 | $1.50 |
| claude-sonnet-4-6 | $3.00 | $15.00 | $0.30 |
| claude-haiku-4-5 | $0.80 | $4.00 | $0.08 |
| gpt-4o | $2.50 | $10.00 | $1.25 |
| gpt-4o-mini | $0.15 | $0.60 | $0.075 |
| o1 | $15.00 | $60.00 | $7.50 |
| o3-mini | $1.10 | $4.40 | $0.55 |
| gemini-2.0-flash | $0.10 | $0.40 | $0.025 |
| gemini-1.5-pro | $1.25 | $5.00 | $0.31 |
| gemini-1.5-flash | $0.075 | $0.30 | $0.018 |

Formula: `cost = (uncached_input/1M × input_price) + (cached_input/1M × cache_price) + (output/1M × output_price)`

Fuzzy matching: `claude-sonnet-4-6-20260301` matches `claude-sonnet-4-6`. Unknown models: `cost_usd = 0`.

---

## 22. Operational Runbook

### 22.1 Deploy

```bash
# Frontend
npx wrangler pages deploy ./cohrint-frontend --project-name=cohrint --branch=main

# Worker
cd cohrint-worker && npm run deploy   # wrangler deploy
```

### 22.2 D1 Operations

```bash
# Query production
npx wrangler d1 execute vantage-events --command "SELECT COUNT(*) FROM events"

# Run migration
npx wrangler d1 execute vantage-events --file ./migrations/0017_benchmark_metric_name.sql

# Backup
npx wrangler d1 export vantage-events --output backup-$(date +%Y%m%d).sql
```

### 22.3 KV Operations

```bash
# Delete stuck rate limit key (unblock org)
npx wrangler kv key delete --namespace-id=... "rl:myorg:$(date +%s | awk '{print int($1/60)}')"

# Delete stuck alert throttle (re-enable alerts)
npx wrangler kv key delete --namespace-id=... "alert:myorg:budget_80"

# Check Slack webhook cached
npx wrangler kv key get --namespace-id=... "slack:myorg"
```

### 22.4 Common Incidents

**Analytics showing wrong data / returning all rows:**
- Almost always a date type mismatch. Check column type in schema.
- `events.created_at` is INTEGER — must bind unix seconds, not ISO text.
- `cross_platform_usage.created_at` is TEXT — must bind `"YYYY-MM-DD HH:MM:SS"`.
- Commit `b1fcc6f` caused this across all analytics routes; partially reverted in fix branches.

**Org hitting rate limit unexpectedly:**
1. `wrangler kv key list --prefix="rl:{orgId}"` — see current count
2. Check event pattern: `SELECT COUNT(*), created_at/60 AS min FROM events WHERE org_id=? GROUP BY min ORDER BY min DESC LIMIT 10`
3. Delete current-minute KV key to unblock
4. Long-term: increase `RATE_LIMIT_RPM` (future: per-org limits)

**Semantic cache not hitting:**
1. Check `org_cache_config.enabled = 1` for the org
2. Check `similarity_threshold` — may be too high (try lowering to 0.85 for testing)
3. Check Workers AI binding in `wrangler.toml` — `[ai]` block required
4. Check Vectorize index exists: `wrangler vectorize list`
5. Ensure prompt length >= `min_prompt_length` (default 10 chars)

**Benchmark contribute returning no_usage_data:**
1. Verify `benchmark_opt_in = 1` in orgs table
2. Verify `cross_platform_usage` has rows for the current quarter with `developer_email IS NOT NULL`
3. Quarter range uses TEXT dates — verify `created_at` is stored as `YYYY-MM-DD HH:MM:SS`

**Deploy 504 timeout:**
- Workflows retry 4 times with exponential backoff (30 → 60 → 120s)
- Manual retry: GitHub Actions UI → "Re-run failed jobs"
- Persistent: check `cloudflarestatus.com`

**Session not persisting:**
1. Verify `Domain=cohrint.com` on cookie (production only)
2. Check `sessions` table: `SELECT expires_at FROM sessions WHERE token=?`
3. 30-day TTL from creation, not from last use

### 22.5 D1 Schema Migration Pattern

```bash
cat > cohrint-worker/migrations/0018_my_change.sql << 'EOF'
ALTER TABLE events ADD COLUMN new_field TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_events_new ON events(org_id, new_field) WHERE new_field IS NOT NULL;
EOF

# Test on preview first
npx wrangler d1 execute vantage-events-preview --file ./cohrint-worker/migrations/0018_my_change.sql

# Apply to production
npx wrangler d1 execute vantage-events --file ./cohrint-worker/migrations/0018_my_change.sql
```

Always use `IF NOT EXISTS`. D1 has no rollback — preview first.

---

## 23. Research References & Reading List

### 23.1 LLM Observability & Evaluation

| Paper | Why | Link |
|---|---|---|
| MT-Bench & Chatbot Arena (Zheng et al. 2023) | Foundation for LLM-as-judge evaluation | arxiv.org/abs/2306.05685 |
| LLMLingua: Compressing Prompts (Jiang et al. 2023) | Prompt efficiency score feature | arxiv.org/abs/2310.05736 |
| AlpacaEval (Li et al. 2024) | Better judge than GPT-4 alone | arxiv.org/abs/2404.04475 |
| Judging the Judges (Panickssery et al. 2024) | Why ensemble judging matters | arxiv.org/abs/2406.12624 |
| RAGAS: Automated RAG Evaluation (Es et al. 2023) | Relevancy, faithfulness, recall | arxiv.org/abs/2309.15217 |

### 23.2 Infrastructure

| Resource | Link |
|---|---|
| Cloudflare Vectorize docs | developers.cloudflare.com/vectorize |
| Cloudflare Workers AI | developers.cloudflare.com/workers-ai |
| Hono.js | hono.dev |
| Durable Objects (for future sliding window RL) | developers.cloudflare.com/durable-objects |

### 23.3 Competitive Landscape

| Tool | What to Study |
|---|---|
| Helicone | Gateway architecture, prompt caching analytics |
| LangSmith | Trace visualization, evaluation framework |
| Weights & Biases | Enterprise adoption playbook for observability |
| Datadog APM | Observability monetization at scale |

---

## 24. MCP Server — Tools Reference & Examples

### 24.1 Setup

```json
{
  "mcpServers": {
    "vantage": {
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": { "COHRINT_API_KEY": "crt_yourorg_abc123..." }
    }
  }
}
```

### 24.2 Available Tools

| Tool | Description |
|---|---|
| `get_summary` | Today/MTD cost overview |
| `get_kpis` | KPI totals for N days |
| `get_model_breakdown` | Cost by model |
| `get_team_breakdown` | Cost by team |
| `check_budget` | Budget % used |
| `get_traces` | Recent agent traces |
| `track_llm_call` | Post an event directly |
| `optimize_prompt` | Compress a prompt |
| `analyze_tokens` | Count tokens + estimate cost |
| `estimate_costs` | Compare across models |
| `compress_context` | Summarize conversation history |
| `find_cheapest_model` | Model recommendation |
| `get_recommendations` | Optimization suggestions |

---

## 25. Local Proxy Gateway — Privacy-First LLM Tracking

The local proxy (`cohrint-local-proxy/`) runs as a local HTTP server that intercepts LLM API calls. In `strict` mode, prompts and responses never leave the user's machine — only token counts and costs are forwarded to Cohrint.

**Privacy modes:** `strict` (hash only), `hashed` (SHA-256 of prompt), `standard` (full metadata).

**Port:** `7878` by default. Configure `OPENAI_API_BASE=http://localhost:7878/openai` to route calls through it.

---

## 26. Claude Code Auto-Tracking

A `PostToolUse` hook in VS Code / Claude Code automatically posts events to Cohrint after every LLM tool use. The hook (`vantage-track.js`) extracts token counts and cost from the tool response and POSTs to `/v1/events` with `agent_name='claude-code'`.

**Setup:** Add hook to `.claude/settings.json`:
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": ".*",
      "hooks": [{ "type": "command", "command": "node ~/.claude/vantage-track.js" }]
    }]
  }
}
```

**Verification:** `GET /v1/analytics/summary?agent=claude-code` returns last event timestamp.

---

## 27. SDK Privacy Modes

| Mode | What's sent | Stored |
|---|---|---|
| `standard` | Full metadata (no prompt text by default) | All fields |
| `hashed` | `prompt_hash` = SHA-256(prompt) | Hash only |
| `strict` | No prompt data at all | `prompt_hash=null` |

Configure: `cohrint.init(api_key="...", privacy_mode="strict")`

---

## 28. Cross-Platform OTel Collector (v2)

`POST /v1/otel/v1/metrics` and `/v1/otel/v1/logs` accept OpenTelemetry-format payloads from any tool. The handler extracts token + cost metrics and writes to `cross_platform_usage` and `otel_events` (both TEXT date columns).

Auto-cost-estimation applies when `cost_usd == 0` — pricing table lookup by model name with fuzzy substring matching.

**Agent filter:** `GET /v1/analytics/summary?agent=otel-collector` checks OTel-sourced events specifically.

---

## 29. Cohrint CLI — AI Agent Wrapper

`cohrint-cli/` wraps any AI CLI tool and tracks every call:

```bash
# Install
npm install -g cohrint-cli

# Use
COHRINT_API_KEY=crt_... cohrint run -- claude "explain this code"
```

Posts `POST /v1/events` after each wrapped command completes, capturing tokens, cost, latency, and exit code.

---

## 30. Security & Governance

### 30.1 Superadmin Routes

`/v1/superadmin/*` requires the `SUPERADMIN_SECRET` header in addition to normal auth. Used for cross-org operations (platform admin panel). Never exposed in the public docs.

### 30.2 Token Encryption

Both Copilot PAT and Datadog API key are encrypted with AES-256-GCM using `TOKEN_ENCRYPTION_SECRET`. This secret **throws on Worker startup if missing** — no silent fallback. Set via `wrangler secret put TOKEN_ENCRYPTION_SECRET`.

Copilot token stored in KV only (`copilot:token:{orgId}:{githubOrg}`), never in D1.
Datadog key stored in D1 as `api_key_enc` (ciphertext hex) + `api_key_iv` (GCM IV hex).

---

## 31. Claude Code Integration (Customer-Facing)

The Claude Code tab in the dashboard guides users through installing the PostToolUse hook. The "Check Setup" button calls `GET /v1/analytics/summary?agent=claude-code` — if `last_event_at` is recent, setup is confirmed active without being affected by other event streams.

---

## 32. GitHub Copilot Metrics Adapter

### 32.1 Architecture

```
Cron (Sundays UTC)
       │
       ▼
copilot.ts: syncCopilotMetrics(env)
       │
       ├── SELECT copilot_connections WHERE status='active'
       │
       └── For each connection:
             │
             ├── KV.get("copilot:token:{orgId}:{githubOrg}")
             │   → AES-256-GCM decrypt using TOKEN_ENCRYPTION_SECRET
             │
             ├── GitHub Copilot Metrics API
             │   GET /orgs/{github_org}/copilot/metrics
             │   Authorization: Bearer {decrypted_PAT}
             │
             ├── Map response → cross_platform_usage rows
             │   source='copilot', provider='github_copilot'
             │
             ├── INSERT OR IGNORE INTO cross_platform_usage
             │
             └── UPDATE copilot_connections SET last_sync=now()
```

### 32.2 Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/copilot/connect` | admin+ | Store encrypted PAT, set status=active |
| `DELETE` | `/v1/copilot/disconnect` | admin+ | Delete connection + KV token |
| `POST` | `/v1/copilot/sync` | admin+ | Manual sync trigger |
| `GET` | `/v1/copilot/status` | any | Connection status + last_sync |

---

## 33. Datadog Metrics Exporter

Exports `cross_platform_usage` data to Datadog as custom metrics. Runs daily.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/datadog/connect` | admin+ | Store encrypted DD API key |
| `DELETE` | `/v1/datadog/disconnect` | admin+ | Remove connection |
| `POST` | `/v1/datadog/sync` | admin+ | Manual sync |
| `GET` | `/v1/datadog/status` | any | Status + last_sync |

Datadog key encrypted with AES-256-GCM (same `TOKEN_ENCRYPTION_SECRET`). Stored in D1 as `api_key_enc` + `api_key_iv`.

---

## 34. Cross-Platform Console

**RBAC: admin+ only (PR #67).** The Cross-Platform tab and Cost per Developer card are hidden from `member` and `viewer` roles at both the frontend nav level and the API level (`GET /v1/cross-platform/*` enforces `adminOnly`).

| Endpoint | Description |
|---|---|
| `GET /v1/cross-platform/summary` | Spend roll-up across all sources |
| `GET /v1/cross-platform/developers` | Per-developer cost breakdown |
| `GET /v1/cross-platform/models` | Cost by model across sources |
| `GET /v1/cross-platform/live` | Recent cross-platform events |
| `GET /v1/cross-platform/budget` | Cross-platform budget status |

All cross-platform queries use TEXT date columns (`cross_platform_usage.created_at`). Use `sqliteDateSince()` / `sqliteMonthStart()` helpers.

---

## 35. Audit Log

### 35.1 Architecture

```
Any authenticated write request
          │
          ▼
  logAudit(c, { event_type, event_name, resource_type, metadata })
          │
          ▼  (c.executionCtx.waitUntil — non-blocking)
  INSERT INTO audit_events (
    id, org_id, actor_id, actor_email,
    action, target_id, target_type,
    metadata (JSON), event_type,
    created_at (TEXT datetime('now'))
  )
```

`audit_events.created_at` is TEXT (`datetime('now')`) — NOT INTEGER. Paginate with `WHERE created_at < ?` using ISO `YYYY-MM-DD HH:MM:SS` strings.

### 35.2 Audit Log API

```
GET /v1/audit-log?limit=50&before=2026-04-17+00:00:00
```

- Requires `adminOnly`
- Sorted DESC by `created_at`
- Cursor-based pagination via `before` param (offset pagination would drift due to new writes)
- This endpoint itself is NOT logged (prevents pagination drift)

### 35.3 Common Action Types

| action | event_type | Trigger |
|---|---|---|
| `auth.login` | `auth` | Every successful auth |
| `auth.failed` | `auth` | Failed key or session |
| `member.invited` | `admin` | Admin invites member |
| `member.removed` | `admin` | Admin removes member |
| `key.rotated` | `admin` | Key rotation |
| `budget.changed` | `billing` | Budget policy update |
| `cache.cleared` | `admin` | Admin deletes cache entry |
| `prompt.created` | `admin` | New prompt in registry |
| `prompt.deleted` | `admin` | Soft delete |

---

## 36. Quick Reference Card

### API Key Format
`crt_{orgId}_{16-hex-random}` — 128-bit entropy, SHA-256 hashed for storage

### Role Hierarchy
`owner(5)` > `superadmin(4)` > `ceo(3)` > `admin(2)` > `member(1)` > `viewer(0)`

### RBAC Guards
- `adminOnly` → rank ≥ 2 (owner/superadmin/ceo/admin)
- `executiveOnly` → rank ≥ 3 (owner/superadmin/ceo)
- `superadminOnly` → rank ≥ 4 (owner/superadmin)

### Free Tier
50,000 events/calendar-month per org

### Rate Limit
1,000 requests/minute/org (env: `RATE_LIMIT_RPM`)

### Session TTL
30 days from creation (not from last use)

### SSE Token TTL
120 seconds, one-time use

### Recovery Token TTL
3,600 seconds (1 hour), single-use via POST only

### Batch Max Size
500 events per `POST /v1/events/batch`

### Budget Alert Thresholds
80% and 100%, throttled once/hour/threshold via KV

### Semantic Cache Defaults
threshold=0.92, min_length=10, max_age=30d, model=bge-small-en-v1.5 (384-dim)

### Benchmark k-Anonymity Floor
`sample_size >= 5` required for public percentile data

### D1 Database
Name: `vantage-events` | ID: `a1301c2a-19bf-4fa3-8321-bba5e497de10`

### KV Namespace ID
`65b5609ad5b747c9b416632a19529f24`

### Workers Route
`api.cohrint.com/*` → zone `cohrint.com`

### Production URLs
API: `https://api.cohrint.com` | Dashboard: `https://cohrint.com`

### Required Wrangler Secrets
- `RESEND_API_KEY` — email
- `TOKEN_ENCRYPTION_SECRET` — AES-256-GCM (throws on startup if missing)
- `SUPERADMIN_SECRET` — `/v1/superadmin/*` gate
- `VANTAGE_CI_SECRET` — bypass signup rate limiting in CI
- `DEMO_API_KEY` — viewer-scoped demo key

### All D1 Tables (22)
`orgs`, `org_members`, `sessions`, `events`, `team_budgets`, `alert_configs`,
`cross_platform_usage`, `otel_events`, `otel_traces`, `otel_sessions`,
`provider_connections`, `budget_policies`, `audit_events`,
`copilot_connections`, `datadog_connections`,
`benchmark_cohorts`, `benchmark_snapshots`, `benchmark_contributions`,
`platform_pageviews`, `platform_sessions`,
`semantic_cache_entries`, `org_cache_config`,
`prompts`, `prompt_versions`, `prompt_usage`

### Cron Schedule
- Benchmark sync + Copilot metrics: Sundays UTC
- Datadog export: Daily UTC

### Date Type Matrix (critical)
- INTEGER tables: bind `Math.floor(Date.now()/1000)` or `unixepoch()`
- TEXT tables: bind `"YYYY-MM-DD HH:MM:SS"` or `datetime('now')`
- Wrong bind = silent full-table scan (no error)

---

## 37. Intent Classifier + Model Router

**File:** `cohrint-local-proxy/src/intent-classifier.ts` and `cohrint-local-proxy/src/routing-config.ts`

**Stage:** Stage 1 core (shipped PR #87)

### 37.1 Intent Classification

Rule-based, zero latency — no API calls. Classifies every LLM request into one of four coding intents:

| Intent | Detection Logic |
|--------|----------------|
| `autocomplete` | Prompt token count < 40 AND no sentence-ending punctuation in last message |
| `refactor` | Pattern keywords: refactor, rewrite, improve, optimize, simplify, clean, restructure |
| `generation` | Pattern keywords: write, create, generate, implement, build, code, add, scaffold |
| `explanation` | Pattern keywords: explain, describe, what is/are/does, how does/do/can, why does/is |

Scoring: count pattern matches across all message content + system prompt. Precedence when tied: refactor > generation > explanation > autocomplete.

```typescript
export function classifyIntent(messages: Message[], system?: string): CodingIntent
```

### 37.2 Routing Decision

`routingDecision(requestedModel, intent)` applies these rules:

| Intent | Candidate models (cheapest first) | Premium model | Sample rate |
|--------|----------------------------------|---------------|-------------|
| autocomplete | gemini-2.0-flash, gpt-4o-mini, claude-haiku-4-5 | gpt-4o | 5% |
| explanation | gpt-4o-mini, gemini-2.0-flash, claude-haiku-4-5 | claude-sonnet-4-6 | 3% |
| generation | gpt-4o-mini, claude-haiku-4-5, gemini-1.5-flash | gpt-4o | 4% |
| refactor | gpt-4o-mini, claude-haiku-4-5, gemini-1.5-pro | claude-sonnet-4-6 | 5% |

Selection: first candidate whose provider is configured in the local proxy config. Returns `reason`:
- `cost_optimization` — routed to a cheaper model
- `same_model` — cheapest candidate is already the requested model
- `no_cheaper_candidate` — no configured provider matches the candidate list

Routing only applies to non-streaming requests. Streaming requests always use the original model.

### 37.3 Event Tagging

Routing metadata is appended to event tags before sending to the API:

```json
{
  "routing": {
    "original_model": "claude-sonnet-4-6",
    "routed_model": "gpt-4o-mini",
    "intent": "generation",
    "reason": "cost_optimization",
    "savings_usd": 0.0042
  }
}
```

The `GET /v1/analytics/savings` endpoint queries these tags via `json_extract(tags,'$.routing.savings_usd')`.

---

## 38. Routing Quality Sampling

**File:** `cohrint-local-proxy/src/proxy-server.ts` — `runQualitySample()` function

### 38.1 Purpose

Quality drift detection: 1–5% of routed requests (where the model was downgraded) are silently re-sent to the premium model. The premium model's response is discarded. Quality scores from both calls (once the LLM judge runs) are compared to detect when the cheaper model is underperforming.

### 38.2 Implementation

- Fire-and-forget: `void runQualitySample(...)` — never blocks the main request path
- Uses its own AbortController with 30s timeout (longer than main request to ensure completion)
- Sends to the same upstream provider endpoint using the premium model name
- Does NOT stream — always uses `stream: false` regardless of original request
- Event ID is tagged with `"quality_sample": true` to distinguish in analytics

### 38.3 Fallback Behaviour

When the routed model returns 429 or 5xx:
1. Log routing failure to event tags
2. Retry original request with the original (user-requested) model
3. Record `fallback: true` in routing metadata
4. Quality sampling is skipped for fallback calls

---

## 39. Routing Savings API

**Endpoint:** `GET /v1/analytics/savings?period=N` (default N=30 days)

**Auth:** Bearer token or session cookie (member+ role)

**Response schema:**

```typescript
{
  period_days: number,
  total_events: number,
  routed_events: number,
  routing_rate: number,          // 0–1
  total_savings_usd: number,
  by_intent: Array<{
    intent: string,
    count: number,
    savings_usd: number
  }>,
  by_model: Array<{
    original_model: string,
    routed_model: string,
    count: number,
    savings_usd: number
  }>
}
```

**D1 queries:** Three batched queries using `json_extract(tags,'$.routing.savings_usd')` and `json_extract(tags,'$.routing.reason')`. Time filter uses `sinceUnix(period)` (INTEGER unixepoch — `events` table).

**Dashboard:** Routing Savings KPI card in `app.html` (id=`kpiRoutingSavings`) renders total saved, rerouted count, and routing rate %. Falls back to "No routing yet — install local proxy" when `routed_events === 0`.
