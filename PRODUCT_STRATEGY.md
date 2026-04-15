# Cohrint — Product Strategy v7.0
**The 10-Year War Room Plan: From LLM Cost Tracker → AI Spend Intelligence Layer → Bloomberg of AI**

**Author:** Aman Jain / Kamal Soft Pvt Ltd
**Date:** 2026-04-14
**Version:** 7.0 — P2 Milestone Complete + Full Platform Reality Update
**Stage:** Pre-Seed / 1-Man Army
**Critical Window:** 18 months

> **v7.0 Changes:** P2 milestone complete. All Copilot adapter, Datadog exporter, Benchmark system, Cross-Platform Console, Audit Log, Trust page, Report page fully shipped and live. Updated "What's Built" to reflect 18-table schema, 41 test suites, MCP v1.1.1, CLI rename to npx vantageai-cli, Python SDK v1.0.1. Competitive landscape rewritten for April 2026 — Cohrint now holds a unique cross-stack position no competitor covers. Task plan updated: P2 closed, P3 tasks reprioritized.

---

## Table of Contents

1. [Honest Diagnosis](#1-honest-diagnosis)
2. [The Existential Threat](#2-the-existential-threat)
3. [The Pivot — From Tool to Platform](#3-the-pivot--from-tool-to-platform)
4. [The 10-Year Defensible Moat](#4-the-10-year-defensible-moat)
5. [What We've Built](#5-whats-built)
6. [Gap Analysis — Critical Fixes](#6-gap-analysis--critical-fixes)
7. [Architecture — Vantage Intelligence Engine](#7-architecture--vantage-intelligence-engine)
8. [18-Month War Roadmap](#8-18-month-war-roadmap)
9. [Market Size and Competitive Landscape](#9-market-size-and-competitive-landscape)
10. [Financial Model](#10-financial-model)
11. [Sales Channels](#11-sales-channels)
12. [Automation Layer — n8n Workflows](#12-automation-layer--n8n-workflows)
13. [Task Plan — Week-by-Week Execution](#13-task-plan--week-by-week-execution)
14. [Research Canon](#14-research-canon)

---

## 1. Honest Diagnosis

You've built a genuinely powerful platform for a solo founder. The feature set now covers the entire AI coding spend stack — IDE tools, LLM APIs, agent frameworks — in a single dashboard with cross-company benchmark intelligence. No funded competitor does all of this. The P2 milestone is complete. The real work now is distribution.

> **"You are selling aspirin in a market that will shortly get free aspirin from the same companies selling the headache."**

The diagnosis from v6 still applies to the basic cost-visibility story. But the platform you've now shipped — Copilot billing adapter + Datadog exporter + anonymized benchmark system + cross-platform console — is structurally different from anything a provider can offer. The moat is real. The distribution is not there yet.

### What's Working

| Area | Signal |
|------|--------|
| OTel collector for AI coding tools | Genuinely unique. No competitor tracks Claude Code + Gemini CLI + Copilot + Cursor in one pipeline. |
| GitHub Copilot Metrics API adapter | First mover. GA API (Feb 2026). Competitors have not shipped this. |
| Anonymized benchmark system | k-anonymity, quarterly snapshots, percentile rankings. This is the data moat beginning to compound. |
| Cross-Platform Console | Full per-developer spend across OTel + Copilot billing + Datadog — no one else does this. |
| Datadog exporter | Meets customers where their monitoring already lives. Enterprise procurement unlock. |
| MCP server (12 tools in Claude Code, Cursor, Windsurf) | Right timing. Daily driver behavior. Developers love in-editor cost visibility. |
| Prompt optimizer (LLMLingua-based) | Concrete, measurable, demo-able. |
| CLI wrapper (npx vantageai-cli) | Transparent AI agent wrapper. Viral potential. |
| Trust page + privacy modes | Security architecture, 3 privacy modes, zero-interception positioning. Enterprise procurement differentiator. |
| Free tier: 50K events/month | Competitive with Langfuse. Low friction for early-stage teams. |

### What's Fragile

| Area | Problem |
|------|---------|
| Distribution | Platform is built. Nobody knows. Every week of no distribution is a week a funded competitor can catch up. |
| No social proof | Testimonials removed (good). Still no logos, no case studies, no named customers on the site. Enterprise sales stalls. |
| No paying customers yet | All metrics are product metrics. Revenue is the only signal that matters externally. |
| Brand name "Cohrint" | Trademark conflict risk. `cohrint.com` is clunky in enterprise sales conversations. |
| Palma.ai direct threat | Direct ICP competitor. Still pre-PMF but watch closely. |
| Benchmark data thin | k-anonymity floor of 5 orgs means most cohorts return 404 until more orgs opt in. Chicken-and-egg. |
| No semantic cache shipped | Helicone is exact-match only. Window to ship semantic cache before they move is still open but closing. |

---

## 2. The Existential Threat

OpenAI launched Usage Dashboard in Q4 2024. Anthropic Console has spend analytics. Google Cloud AI has cost monitoring. All free. All improving rapidly.

**Your "show costs" story has a 12-month shelf life max before providers make it redundant.**

The only response is to build what providers are structurally prevented from building: cross-provider, cross-company intelligence. A provider can never tell you a competitor is cheaper. That conflict of interest is permanent. It cannot be funded away.

The P2 milestone shipped the three features that create this permanent advantage: Copilot adapter (non-OTel tool coverage), Datadog exporter (meet-customers-where-they-are), and benchmark system (cross-company intelligence). The foundation is real. Now it needs to be marketed as such.

---

## 3. The Pivot — From Tool to Platform

The pivot is not about rebuilding. It's about reframing what exists and layering the right capabilities on top. Every feature you've built is still valid — the narrative and the target buyer need to shift.

```
Stage 1 · Now — Developer Tool
Token tracker, cost dashboard, prompt optimizer.
Target: individual developers. ACV: $0–99/mo.

     ↓

Stage 2 · Month 3–6 — Engineering Org Platform
Multi-tool consolidated spend, per-developer ROI, team budgets,
AI coding tool procurement dashboard.
Target: CTOs at 50–500 person companies. ACV: $5K–25K/yr.

     ↓

Stage 3 · Month 9–18 — AI Spend Intelligence Layer
Cross-company benchmarks, model quality intelligence, vendor
negotiation data, board-ready audit trails.
Target: CFOs, Procurement, VPs at 500+ companies. ACV: $50K–200K/yr.

     ↓

Stage 4 · Year 2–5 — Bloomberg of AI Pricing
The neutral market intelligence layer. Aggregated benchmarks across
1000s of companies. Pricing negotiation as a service. AI governance
compliance. The system of record for AI spend. ACV: $200K–1M/yr.
```

### The Structural Advantage

OpenAI cannot tell you Anthropic is cheaper. Anthropic cannot tell you Google outperforms on your workload. No provider will ever show you what other companies pay. **You are the only one structurally positioned to do this.** That conflict of interest is permanent.

### The Analogies to Study

| Company | What They Did | Outcome | Your Version |
|---------|---------------|---------|--------------|
| CloudHealth | Multi-cloud cost intelligence vs AWS/Azure/GCP | $500M VMware acquisition | Multi-model AI spend intelligence vs OpenAI/Anthropic/Google |
| Apptio | IT financial management, technology spend transparency | $1.94B IBM acquisition | AI financial management, model spend transparency + ROI |
| Bloomberg | Neutral market data terminal — banks can't provide this | $10B+ private company | AI model pricing terminal — providers can't provide this |
| Gartner | Tech procurement intelligence — vendors can't self-report | $5B+ public company | AI procurement intelligence — vendors can't self-report on ROI |

---

## 4. The 10-Year Defensible Moat

The real USP is not a feature. It's a data network effect that compounds with every new customer and becomes more valuable over time — exactly the opposite of every feature you currently have.

### Four Permanent Advantages

**1. Provider Conflict Lock-Out**
Providers are structurally prevented from offering cross-provider intelligence. CloudHealth survived AWS for 10 years on this same principle. AWS couldn't tell you Azure was cheaper — and they never will.

**2. Data Network Effect**
Company #500 makes the benchmark data 10x more valuable for companies #1–499. The more customers, the more accurate the pricing intelligence, the better the negotiation leverage. This compounds forever.

**3. Trusted Third Party**
When auditors, boards, and regulators ask "how do you govern AI spend?" — they won't accept a vendor dashboard. They'll need an independent system of record. You're building it now.

**4. Regulatory Inevitability**
EU AI Act, SOX-equivalent AI audit requirements, HIPAA AI governance — all coming. Compliance tools don't get ripped out. Vantage as the compliance layer is a 20-year contract, not a monthly subscription.

### 10-Year North Star

> **"Vantage is the Bloomberg Terminal of AI spend — the trusted, neutral intelligence layer that sits between enterprises and AI vendors, with the aggregated data that no single provider will ever have and the fiduciary position no provider can ever claim."**

---

## 5. What's Built

All items below are shipped and live at `cohrint.com` as of 2026-04-14.

### Infrastructure

| Layer | Tech | Status |
|-------|------|--------|
| API Worker | Cloudflare Workers + Hono | ✅ Live |
| Database | Cloudflare D1 (SQLite) — 18 tables, 14 migrations | ✅ Live |
| KV | Rate limiting (1,000 RPM per org), SSE broadcast, alert throttle, session tokens, AES-256-GCM secrets, idempotency locks | ✅ Live |
| Frontend | Cloudflare Pages — static HTML/CSS/JS + Chart.js | ✅ Live |
| Email | Resend API | ✅ Live |

### Database Schema (18 Tables)

| Table | Purpose |
|-------|---------|
| `events` | Core LLM call events — provider, model, tokens, cost_usd, team, trace_id, quality scores |
| `orgs` | Org accounts — plan, budget_usd, benchmark opt-in flag |
| `org_members` | RBAC — 6-level role hierarchy (owner/superadmin/ceo/admin/member/viewer), scope_team, api_key_hash |
| `sessions` | Auth session tokens — org_id, role, expires_at |
| `team_budgets` | Per-team budget limits |
| `alert_configs` | Slack webhook URLs, threshold triggers |
| `cross_platform_usage` | Normalized multi-tool spend — developer_id, tool_type, source, period dates |
| `otel_events` | Raw OpenTelemetry metrics/logs — developer.id, session_id, model, cost_usd |
| `provider_connections` | Connected external tool configs (Copilot, Datadog status) |
| `budget_policies` | Graduated alert thresholds (50%/75%/85%/100%) |
| `audit_events` | Admin action log — event_type, org_id, actor, created_at DESC index |
| `benchmark_cohorts` | Opt-in org cohort assignments — size_band, industry |
| `benchmark_snapshots` | Quarterly anonymized metrics — cost_per_dev_month, tokens_per_dev_month, cache_hit_rate per model |
| `benchmark_contributions` | Per-org snapshot source (org_id never in snapshots, only in contributions join table) |
| `copilot_connections` | Copilot token metadata — org_id, encrypted token KV key, last sync |
| `datadog_connections` | Datadog API key metadata — org_id, encrypted key KV key, site, last push |
| `platform_pageviews` | Anonymous landing page analytics |
| `platform_sessions` | Anonymous session-level analytics |

### Client Integrations

| Client | Package | Status |
|--------|---------|--------|
| Python SDK | `cohrint` v1.0.1 on PyPI | ✅ Live |
| TypeScript SDK | `cohrint` on npm | ✅ Live |
| MCP Server | `cohrint-mcp` v1.1.1 on npm — 12 tools | ✅ Live |
| CLI Agent | `npx vantageai-cli` — transparent AI agent wrapper | ✅ Live |
| Local Proxy | `vantage-local-proxy` — 3 privacy modes (strict/standard/relaxed) | ✅ Live |
| OTel OTLP | 1 env var → 10+ tools (Claude Code, Copilot, Cursor, Gemini CLI, Cline, Codex, Kiro, Windsurf, Continue, OpenCode) | ✅ Live |

### Core Feature Inventory

**Cost Visibility and Governance**
- [x] Unified cost dashboard — aggregate spend across all tools, teams, time ranges
- [x] Budget policy engine — graduated alerts at 50%, 75%, 85%, 100% per-team and per-org
- [x] Budget exceeded state — "Exceeded by $X" in red on dashboard KPI cards
- [x] Slack webhook delivery — budget alerts pushed on threshold breach + anomaly detection
- [x] CI/CD cost gate — `GET /v1/analytics/cost` designed for GitHub Actions
- [x] Real-time SSE stream — live cost events, SSE teardown on tab exit
- [x] RBAC — 6-level hierarchy (owner / superadmin / ceo / admin / member / viewer) + team-scoped data isolation + escalation guard
- [x] Audit log — full event stream of every admin API action, indexed by org_id + created_at DESC
- [x] Brute-force protection — 10 failed attempts per 5-minute window per IP
- [x] Rate limiting — 1,000 RPM per org via KV, returns 429 with Retry-After header

**Team and Developer Analytics**
- [x] Per-developer profiles (SHA-256 hashed user IDs for privacy)
- [x] Team breakdown — cost, volume, model mix by team
- [x] Model mix analytics — spend distribution across all models
- [x] Cross-platform summary — aggregated across OTel + Copilot billing + Datadog
- [x] Agent tracing — trace_id, parent_event_id, span_depth

**Cross-Platform Console (`/v1/cross-platform/*`)**
- [x] Per-developer spend table across all connected tools
- [x] Stacked trend chart — cost over time by tool type
- [x] Live feed — last 50 OTel events via SSE
- [x] Developer drill-down modal — per-tool breakdown for individual developer
- [x] Provider connection status panel
- [x] Endpoints: `/summary`, `/developers`, `/trend`, `/developer/:id`, `/live`, `/models`, `/connections`, `/budget`

**GitHub Copilot Metrics Adapter (`/v1/copilot/*`)**
- [x] Polls GitHub Copilot Metrics API (GA Feb 2026) — REST-based, no OTel required
- [x] Per-developer usage: seat costs ($19/user/month), suggestions accepted, active users
- [x] AES-256-GCM encrypted token storage in KV (never stored in D1)
- [x] Cron sync: Sundays UTC, idempotent upsert into `cross_platform_usage`
- [x] Endpoints: `POST /v1/copilot/connect`, `DELETE /v1/copilot/connect`, `GET /v1/copilot/status`

**Claude Code Integration (Stop Hook Tracking)**
- [x] Zero-config Stop hook — auto-tracks every Claude Code session
- [x] Three install channels: vantage-mcp setup, @cohrint/claude-code npm, manual install.sh
- [x] Client-side deduplication — ~/.claude/vantage-state.json (50K ID cap), server-side INSERT OR IGNORE
- [x] Dual-write architecture — events → /v1/events/batch (analytics) + /v1/otel/v1/metrics (cross-platform)
- [x] Cost calculation — mirrors worker pricing table, supports 12 models (Claude, GPT-4o, o1, o3-mini, Gemini)
- [x] Separate OTel AbortController — fire-and-forget OTel writes never block analytics uploads
- [x] Dashboard card — Settings → Integrations → Claude Code, shows active status, last event, session count
- [x] Integration status check — `/v1/analytics/summary?agent=claude-code` for setup verification

**Datadog Metrics Exporter (`/v1/datadog/*`)**
- [x] Pushes `vantage.ai.cost_usd` + `vantage.ai.tokens` gauge metrics to customer's own Datadog
- [x] Tags: provider, model, developer_id, org_id
- [x] AES-256-GCM encrypted API key storage in KV
- [x] KV-guarded idempotency — 23h TTL per calendar day per org
- [x] 5-site allowlist (datadoghq.com, datadoghq.eu, ddog-gov.com, us3/us5 regional)
- [x] Endpoints: `POST /v1/datadog/connect`, `DELETE /v1/datadog/connect`, `GET /v1/datadog/status`

**Anonymized Benchmark System (`/v1/benchmark/*`)**
- [x] Cross-company AI spend intelligence — opt-in per org
- [x] k-anonymity floor: cohort sample_size < 5 returns 404 (privacy protection)
- [x] Quarterly snapshots: cost_per_dev_month, tokens_per_dev_month, cache_hit_rate per model
- [x] Size bands: 1–10, 11–50, 51–200, 201–1000, 1000+ employees
- [x] N+1 query optimized: single INNER JOIN GROUP BY per metric
- [x] Percentile rankings: p25/p50/p75/p90 across cohort
- [x] Endpoints: `POST /v1/benchmark/contribute`, `GET /v1/benchmark/percentiles`, `GET /v1/benchmark/summary`

**OTel Collector v2 (`/v1/otel/v1/metrics`, `/v1/otel/v1/logs`)**
- [x] Receives OpenTelemetry metrics from any AI tool
- [x] Auto-cost estimation from token counts using MODEL_PRICES table
- [x] Stores in otel_events + cross_platform_usage tables
- [x] `developer.id` attribute extraction for per-developer tracking
- [x] Supports: Claude Code, Gemini CLI, VS Code Copilot, any OTel-compatible tool

**Audit Log (`/v1/audit/*`)**
- [x] Admin action tracking — invites, key rotations, config changes, budget updates
- [x] Indexed by org_id + created_at DESC
- [x] event_type column for categorization

**Quality and Waste Detection**
- [x] Semantic cache analytics — hit rate KPI, savings USD, duplicate call detection
- [x] LLM quality scores — hallucination, faithfulness, relevancy, consistency, toxicity, efficiency
- [x] Prompt hash dedup — SHA-256 identifies repeated queries across org
- [x] Token optimizer — LLMLingua-based prompt compression

**Auth System**
- [x] API keys (Bearer token)
- [x] Session cookies with recovery flow
- [x] RBAC — owner/superadmin/ceo/admin/member/viewer (6-level hierarchy)
- [x] Rate limiting on all auth endpoints

**MCP Server (12 tools in Claude Code, Cursor, Windsurf)**
`analyze_tokens`, `estimate_costs`, `get_summary`, `get_traces`, `get_model_breakdown`, `get_team_breakdown`, `get_kpis`, `get_recommendations`, `check_budget`, `compress_context`, `find_cheapest_model`, `optimize_prompt`

**Frontend Pages**
- [x] `app.html` — Dashboard SPA: real-time SSE, budget KPIs, team analytics, traces view, cross-platform tab
- [x] `index.html` — Marketing landing page
- [x] `signup.html` — Signup + pricing tiers including Enterprise
- [x] `trust.html` — Security architecture, privacy modes, compliance roadmap (SOC 2 planned Q3 2026, GDPR compliant)
- [x] `report.html` — "State of AI Coding Spend 2026" benchmark report, email-gated download, OG meta tags, mobile-responsive

**CI/CD and Testing**
- [x] GitHub Actions → Cloudflare Pages + Workers auto-deploy on merge to main
- [x] 41 test suites, 283+ checks — all hit live API, no mocking

---

## 6. Gap Analysis — Critical Fixes

_Updated 2026-04-14 based on P2 milestone completion and April 2026 competitive analysis._

### ✅ GAP 2 (CLOSED): Free Tier — 10K → 50K events/month
Worker enforces 50K (`FREE_TIER_LIMIT = 50_000` in events.ts). Frontend + docs updated (PR #54). **Note:** Langfuse also offers 50K/mo free — no moat here. The real advantage is OTel-native AI coding tool tracking, not the limit number.

### ✅ GAP 3 (CLOSED): No Consolidated AI Tool Billing Dashboard
AI Spend Console shipped (PR #51, merged 2026-04-12). Cross-Platform tab live with per-developer attribution, stacked trend chart, live feed, developer drill-down modal. Full `/v1/cross-platform/*` API surface.

### ✅ GAP 8 (CLOSED): No Copilot Metrics API Adapter
GitHub Copilot Metrics API went GA Feb 2026. Adapter shipped (PR #55, migration 0009): AES-256-GCM token storage, Sunday cron sync, `cross_platform_usage` upsert, `/v1/copilot/*` endpoints. Dashboard "Connected Tools" widget displays status.

### ✅ GAP 9 (CLOSED): No Category Claim — "AI Coding FinOps"
Report page shipped at `/report.html` — "State of AI Coding Spend 2026" with email-gated download. Trust page at `/trust.html` names the security and privacy positioning explicitly. Category claim is live.

---

### 🔴 GAP 1: No Cross-Company Intelligence Seeded (Critical)
Benchmark system is built and correct. But k-anonymity floor means most cohorts return 404 until 5+ orgs opt in. The data product doesn't activate until you have real orgs contributing. This is the current blocking constraint on the intelligence layer story.

**FIX:** Every onboarded org should be asked to opt in to benchmarks. Design partner CTOs are the seed. 5 orgs opt in = first real cohort data = benchmark dashboard activates. This is a GTM task, not an engineering task. Timeline: Month 1–2 (design partner outreach).

---

### 🔴 GAP 10: No Paying Customers (Critical)
Platform is real. Nobody is paying. Revenue is the signal that validates every other decision.

**FIX:** 5 design partner CTOs with free Enterprise access in exchange for feedback + logo rights. One paying customer at $99/mo is worth more than 10 more features right now. Timeline: This week.

---

### 🟠 GAP 4: No AI Gateway / Semantic Caching (Major)
Helicone's biggest practical advantage — proxy-based exact caching, fallbacks, routing. You're not in the call path for cost reduction, only observation. Helicone is exact-match only. Window to ship semantic cache is still open.

**FIX:** Build Semantic Cache Layer using Cloudflare Workers + Vectorize. Position as "AI-native caching" vs Helicone's "HTTP-level caching." Timeline: Month 2.

---

### 🟠 GAP 5: No Prompt Management / Versioning (Major)
Helicone, LangSmith both have this. Engineering teams want to version prompts, A/B test, track which version is cheaper.

**FIX:** Lightweight prompt registry with cost-per-version comparison. Timeline: Month 3–4.

---

### 🟡 GAP 6: Brand / Domain Fragmentation (Minor)
"Cohrint" trademark conflicts. `cohrint.com` is clunky for enterprise sales.

**FIX:** Decide domain by Month 1. Options: spendlens.ai, ailedger.com, modelbench.io, or commit to vantageai.com. Register and redirect.

---

### 🟡 GAP 7: No Social Proof for Enterprise (Minor)
Fictional testimonials removed (good). Still no logos, no case studies, no named customers. Enterprise sales stalls without this.

**FIX:** 3 real design partners with permission to use logo. Replace empty "design partners welcome" CTA with real quotes + GitHub handles.

---

## 7. Architecture — Vantage Intelligence Engine

### VIE — Full Event Flow

```
[SDK / CLI / OTel / MCP / Copilot API / Datadog Push]
         │
         ▼
[01 INGEST] — validate, auth, rate-limit (1K RPM/org via KV)
         │
         ▼
[02 NORMALIZE] — VantageEvent schema, provider detection, model canonicalization
         │
         ▼
[03 ENRICH] — live pricing injection (MODEL_PRICES), org context, developer attribution, team tagging
         │
         ▼
[04 SCORE] — efficiency score (0–100), prompt optimizer analysis, quality flag
         │
         ▼
[05 SEMANTIC CACHE CHECK] — Cloudflare Vectorize cosine similarity (default 0.92)
    cache HIT ────────────────────────────────► RETURN cached response + cost saved
    cache MISS ▼
         │
         ▼
[06 BENCHMARK] — compare to anonymized cohort percentiles (opt-in orgs only, k≥5)
         │
         ▼
[07 ALERT ENGINE] — Z-score anomaly, budget threshold, quality regression checks
    alert ────────────────────────────────────► Slack webhook / email (async)
         │
         ▼ waitUntil() — non-blocking async fan-out
[08 STORE] — D1 (events + otel_events + cross_platform_usage + audit_events)
         │
         ▼
[09 SERVE] — SSE push → dashboard | MCP tool response | API JSON
```

### Architecture Principle

> "Every token Vantage sees passes through the same pipeline. No event bypasses enrichment. No event skips benchmarking. The intelligence compounds because every event makes the model better."

### Backend Services

| Service | What It Runs | Provider | Monthly Cost |
|---------|-------------|----------|--------------|
| CF Workers | VIE ingest pipeline, OTel collector, Copilot/Datadog adapters, benchmark system | Cloudflare | $5–50/mo |
| CF Pages | Dashboard + landing page + trust + report pages | Cloudflare | Free → $20 |
| CF KV | Rate limiting, encrypted secrets (AES-256-GCM), idempotency locks, session tokens | Cloudflare | Included |
| CF Vectorize | Semantic cache embeddings (per org) — not yet shipped | Cloudflare | $0.05/1M queries |
| CF Workers AI | BGE embedding model for cache — not yet shipped | Cloudflare | $0.01/1K embed |
| D1 SQLite | Primary data store (18 tables, 14 migrations) | Cloudflare | Included |
| FastAPI / Render | LLM-as-judge quality scoring, prompt optimizer | Render | $25–85/mo |
| n8n / Railway | All automation workflows — not yet deployed | Railway | $5–15/mo |
| Resend | Transactional email | Resend | Free → $20 |
| Anthropic API | Quality scoring (Claude Sonnet), content gen | Anthropic | $100–300/mo |
| **Total (early stage)** | | | **~$300–600/mo** |

### Database Schema (18 Tables — Full Current State)

| Table | Key Fields | Notes |
|-------|-----------|-------|
| `events` | provider, model, tokens, cost_usd, team, trace_id, quality scores | INTEGER unix epoch timestamps |
| `orgs` | id, api_key_hash, plan, budget_usd, benchmark_opt_in | INTEGER unix epoch timestamps |
| `org_members` | role, scope_team, api_key_hash | INTEGER unix epoch timestamps |
| `sessions` | token, org_id, role, expires_at | INTEGER unix epoch timestamps |
| `team_budgets` | org_id, team, budget_usd | INTEGER unix epoch timestamps |
| `alert_configs` | slack_url, trigger thresholds | INTEGER unix epoch timestamps |
| `cross_platform_usage` | developer_id, tool_type, source, period_start, period_end | **TEXT 'YYYY-MM-DD HH:MM:SS'** (exception) |
| `otel_events` | provider, session_id, developer_email, model, cost_usd | TEXT timestamp field |
| `provider_connections` | org_id, provider, status | — |
| `budget_policies` | org_id, threshold_pct, action | — |
| `audit_events` | org_id, actor, event_type, payload, created_at | Indexed org_id + created_at DESC |
| `benchmark_cohorts` | org_id, size_band, industry, opt_in | size_bands: 1-10, 11-50, 51-200, 201-1000, 1000+ |
| `benchmark_snapshots` | cohort_id, period, metric, p25/p50/p75/p90 | k-anonymity enforced: sample_size ≥ 5 |
| `benchmark_contributions` | org_id, snapshot_id, contributed_at | Join table — org_id never in snapshot rows |
| `copilot_connections` | org_id, kv_key, last_sync | Encrypted token in KV, never D1 |
| `datadog_connections` | org_id, kv_key, site, last_push | Encrypted key in KV, never D1 |
| `platform_pageviews` | page, referrer, ts | Anonymous analytics |
| `platform_sessions` | session_id, pages_viewed, duration | Anonymous session analytics |

### Semantic Cache — Core Differentiator (Planned)

```typescript
// Cloudflare Workers + Vectorize
export async function checkSemanticCache(
  prompt: string, orgId: string, threshold = 0.92
): Promise<CacheHit | null> {
  // 1. Embed with Workers AI (bge-small-en)
  const { data } = await workersAI.run('@cf/baai/bge-small-en-v1.5', { text: [prompt] });
  // 2. Query org-scoped namespace
  const results = await vectorize.query(data[0], { topK: 1, namespace: orgId, returnMetadata: 'all' });
  if (!results.matches.length || results.matches[0].score < threshold) return null;
  // 3. Return cache hit + savings
  const best = results.matches[0];
  return { response: best.metadata.response, saved_usd: best.metadata.cost_usd, similarity_score: best.score };
}
```

> Ship this before Helicone does. They're exact-match only right now.

---

## 8. 18-Month War Roadmap

Every week counts. Only build what advances the data moat or the enterprise wedge.

### Phase 1 — Fix the Foundation (Weeks 1–6) ✅ COMPLETE

**Goal:** 500 active accounts, 5 design partner CTOs, $1K MRR, HN front page once.

| Task | Week | Effort | Status |
|------|------|--------|--------|
| Raise free tier to 50K OTel events/month | W1 | 2h | ✅ Done (PR #54) |
| Replace fake testimonials with honest CTA | W1 | 1h | ✅ Done (PR #55) |
| Add benchmark opt-in toggle to settings page | W1 | 4h | ✅ Done (PR #55) |
| Fix OTel developer.id attribute extraction | W1 | 2h | ✅ Done (PR #52) |
| Fix CI signup rate-limit duplicate block | W1 | 1h | ✅ Done (PR #53) |
| Add compliance/security page (trust.html) | W2 | 6h | ✅ Done (PR #55) |
| Build AI Spend Console MVP — cross-platform dashboard | W3–5 | 40h | ✅ Done (PR #51) |
| Build Copilot Metrics API adapter | W3–4 | 12h | ✅ Done (PR #55) |
| Add Enterprise tier to pricing page | W5 | 2h | ✅ Done (PR #55) |
| Publish "State of AI Coding Spend 2026" report page | W5 | 8h | ✅ Done (PR #55) |
| Email 20 CTOs at AI-heavy startups (design partner outreach) | W1 | 3h | ⬜ |
| Decide brand/domain — commit and register | W1 | 2h | ⬜ |
| Write + post Show HN (8am ET Tuesday/Wednesday) | W2 | 2.5h | ⬜ |
| Get 3 design partner CTOs onboarded | W4 | ongoing | ⬜ |
| Set up weekly Sunday execution review | W1+ | 1h/wk | ⬜ |

### Phase 2 — Build the Enterprise Wedge (Months 2–4)

**Goal:** 3 paying enterprise accounts ($1K–5K/yr), $5K MRR, benchmark report hits 2K shares.

- Semantic Cache Layer — Cloudflare Workers + Vectorize, configurable threshold, $ saved on dashboard
- Prompt Registry MVP — version, cost-compare, deploy via MCP
- First benchmark report: "State of AI Coding Tool Spend Q2 2026" — gate with email (data-driven, not placeholder)
- Seed benchmark data via 5 design partner orgs opting in
- Slack integration — spend alerts natively in Slack (already supports webhooks; native app is next)
- n8n automation deployment on Railway — onboarding drip + conversion workflows
- SOC2 prep with Vanta — start Month 3, target completion Month 7–8

### Phase 3 — Activate the Intelligence Layer (Months 5–8)

**Goal:** 10 enterprise accounts, $25K MRR, first $50K ACV deal, Series A narrative ready.

- Benchmark Dashboard — "Your cost/token vs industry median" across 6 model categories (data now available from Phase 2 seed)
- Vendor Negotiation Module — "Here's what similar companies paid at their last Copilot renewal"
- Quality-Adjusted Routing Engine — route by task type from historical quality + cost data
- AI Governance Report — auto-generate board-ready AI spend report (who spent what, which model, which outcome)
- Agent trace DAG visualization — graph view of multi-step agent sessions from OTel trace data
- Quarterly "AI Spend Index" — public report, PR strategy, builds brand authority
- SOC2 Type I certification

### Phase 4 — Become the Standard (Months 9–18)

**Goal:** $100K MRR, 50 enterprise accounts, system of record at 3 public companies.

- AI Procurement API — let Ramp, Brex, Coupa pull AI spend data directly
- Compliance Module — EU AI Act audit trail, HIPAA AI governance, auto-generated compliance reports
- Model Performance Index — public quality/cost ranking per task type (SEO + authority play)
- Raise seed/Series A — with 10+ enterprise customers + benchmark data from 500+ companies
- First BD hire — you build, they sell

---

## 9. Market Size and Competitive Landscape

### TAM / SAM / SOM

| Market | Size | Your Access |
|--------|------|-------------|
| Global AI/ML infrastructure spend | $150B+ by 2028 | TAM — too broad |
| LLM API spend (all companies) | $15–25B by 2027 | TAM — your upstream market |
| LLMOps / AI Observability tools | $2–4B by 2027 | SAM — current fight |
| AI coding tool spend (enterprise) | $8–12B by 2027 | SAM — your wedge |
| IT Financial Management (Apptio comp) | $4.5B | SOM — 5-year target |
| Initial serviceable market | ~$500M | Realistic SOM Y3–5 (10K companies × $50K ACV) |

### Competitive Landscape (April 2026)

| Dimension | Cohrint | Helicone | LangSmith | Langfuse | Datadog LLM Obs. | GitHub Copilot Analytics | Palma.ai |
|---|---|---|---|---|---|---|---|
| **Free tier** | 50K events/mo | 10K/mo | 5K traces/mo | 50K units/mo | None | Included w/ seat | Unknown |
| **Paid entry** | TBD | $20/seat/mo | $39/seat/mo | $29/mo flat | ~$120/day activation | $10–19/user/mo | Unknown |
| **OSS / self-host** | No | Yes (Apache 2.0) | No | Yes (MIT) | No | No | Unknown |
| **AI coding tool tracking** | **Yes — OTel native + Copilot REST** | No | No | No | Partial (no cost) | Own tool only | Yes (claimed) |
| **GitHub Copilot billing adapter** | **Yes — GA API, AES-encrypted** | No | No | No | No | Native only | Unknown |
| **Per-developer attribution (cross-tool)** | **Yes** | No | No | No | No | Own tool only | Yes (claimed) |
| **No proxy required** | **Yes** | No | No | No | N/A | N/A | Unknown |
| **MCP server** | **Yes (12 tools)** | No | No | No | Yes (different use) | No | Unknown |
| **CLI wrapper** | **Yes** | No | No | No | No | No | Unknown |
| **Privacy / strict mode** | **Yes (3 modes)** | No | No | No | No | No | Unknown |
| **Datadog exporter** | **Yes** | No | No | No | N/A | No | Unknown |
| **Anonymized benchmark data** | **Yes (k-anon, opt-in)** | No | No | No | No | No | Unknown |
| **Audit log** | **Yes** | Limited | Yes | Yes | Yes | No | Unknown |
| **Agent trace viz** | Partial | Yes | Yes | Yes (GA Nov 2025) | Yes | No | Unknown |
| **Eval framework** | No | Limited | Yes | Yes | No | No | Unknown |
| **Cross-provider spend** | Yes | Yes (proxy) | Yes | Yes | Yes (800+ models) | No | Yes (claimed) |

### Competitive Moat Comparison (April 2026)

| Competitor | Structural Weakness | Your Exploit |
|-----------|--------------------|-----------  |
| Helicone | Exact-match cache only. No AI coding tool OTel. No Copilot billing. No per-developer cross-tool attribution. Proxy = traffic interception risk for enterprise. | AI Spend Console + Copilot adapter + no-proxy architecture + privacy modes beats on all enterprise dimensions. |
| LangSmith | Deep LangChain coupling. Tracing-heavy, not cost-primary. No multi-tool procurement story. No Copilot. | Cost-first narrative. Non-LangChain teams are underserved. CTOs buying Copilot don't care about LangChain. |
| Langfuse | MIT OSS is a moat. Strong eval + prompt mgmt. No AI coding tool OTel. No CLI wrapper. No Copilot. | "Langfuse shows your LLM calls. Cohrint shows your AI coding bill." Different buyer: CTO vs ML engineer. |
| Datadog LLM | $15+/host explodes at scale. Observability focus, not cost intelligence. No AI coding tools. No Copilot attribution. | Purpose-built for AI spend. 10x cheaper. "Datadog is for infra, Vantage is for AI budgets." We push data to Datadog — we don't compete with it. |
| OpenAI Dashboard | Only shows OpenAI. Provider-biased. No cross-model comparison. No independence. | Multi-provider neutrality. "Would you let your bank audit itself?" |
| Anthropic Console | Same — single provider. No Copilot, no Cursor, no competitive intelligence. | You show the full picture. They show only their slice. CFOs need the full picture. |
| GitHub Copilot Analytics | Copilot only. No cross-tool. REST API (not OTel). No Cursor/Claude Code. | Copilot Metrics API is GA. We consume it, normalize it, show it alongside everything else. Their data feeds our moat. |
| Palma.ai | **Direct threat.** Identical ICP. Appears to be pre-PMF, limited marketing. | We've shipped: Copilot adapter, Datadog exporter, benchmark system, cross-platform console, MCP server — all production. Ship first, own the "AI Coding FinOps" category. |
| CloudZero / Apptio | Cloud cost focus. Not built for LLM/AI token economics. Expensive, slow to adapt. | AI-native from day one. These are your 5-year acquisition targets. |

### Why Cohrint Is the Only Full-Stack AI Coding Spend Platform

As of April 2026, Cohrint is the **only platform** that covers the complete AI coding spend stack in one dashboard:

1. **IDE tools** (GitHub Copilot) — via Copilot Metrics API adapter, per-developer, per-seat cost
2. **LLM APIs** (OpenAI, Anthropic, Google, Mistral, etc.) — via SDK + OTel collector, per-call tracking
3. **Agent frameworks** (LangChain, AutoGen, any OTel-compatible) — via OTLP endpoint, trace-level attribution
4. **Existing monitoring** (Datadog) — via exporter push, meets customers where they already are

No competitor covers all four. This is the cross-stack narrative that should lead every sales conversation.

---

## 10. Financial Model

### Unit Economics (Target)

| Tier | Price | Target | MRR | Gross Margin |
|------|-------|--------|-----|-------------|
| Free | $0 | Unlimited (acquisition) | $0 pipeline | — |
| Team $99/mo | $99 | 50 by Month 6 | $4,950 | ~85% |
| Business $499/mo | $499 | 20 by Month 9 | $9,980 | ~80% |
| Enterprise $2K–10K/mo | Custom | 5 by Month 12 | $20K–50K | ~75% |
| **Total Target M12** | | | **$35K–65K MRR** | ~80% |

### Monthly Burn (1-Man Army)

| Service | Cost |
|---------|------|
| Cloudflare Workers/Pages/D1/KV | $50–200/mo |
| Render (FastAPI quality scoring) | $25–85/mo |
| Anthropic API (quality scoring) | $100–300/mo |
| n8n on Railway (when deployed) | $5–15/mo |
| Domain + Email + Legal | $50/mo |
| Tools (Figma, Linear, etc.) | $50/mo |
| **Total** | **~$300–900/mo** |
| Break-even | 4–10 Team plan customers |
| Ramen profitable | ~$2K MRR |

### Revenue Milestones

| Milestone | Target |
|-----------|--------|
| Month 3 | $1K MRR — 10 Team customers |
| Month 6 | $5K MRR — mix Team + Business |
| Month 9 | $15K MRR — first enterprise deal |
| Month 12 | $35K MRR — fundable Series A story |
| Month 18 | $100K MRR — raise or profitable |
| Fundraise Goal | $1–3M Seed — hire BD + 1 eng |

---

## 11. Sales Channels

### Channel 1 — Hacker News (Week 1, Critical)

Post: **"Show HN: We built the only tool that shows per-developer ROI across all AI coding tools — Copilot + Claude Code + Cursor in one dashboard"**

Second post Month 2: **"Show HN: We analyzed $10M in AI coding tool spend — here's what we found"** (use benchmark data)

- One front-page post = 500–2000 sign-ups
- Reply to every comment personally for 48 hours
- Post 8–10am ET Tuesday or Wednesday

### Channel 2 — Cold Outreach to CTOs (Month 1, Critical)

Target: CTOs at startups paying for 3+ AI coding tools (Copilot + Cursor + Claude Code). Find via LinkedIn: "CTO" + "AI" + 50–200 employees.

Pitch: *"You're probably spending $30–60K/year on AI coding tools with zero data on which one actually moves the needle. We built the dashboard for that — including your Copilot billing, pulled directly from GitHub's API. 15 min demo?"*

Goal: 5 design partners in Month 1. Give free Enterprise access in exchange for feedback + logo rights.

### Channel 3 — Twitter/LinkedIn Thought Leadership (Ongoing)

- Post weekly: data-driven observations from anonymized usage data
- Twitter: developer audience. LinkedIn: CTOs/CFOs. Different angles, same data.
- Tag AI influencers when sharing benchmark data — they amplify free
- Build in public — weekly progress posts create accountability and attract early adopters

### Channel 4 — Quarterly Benchmark Report (Month 3 onward)

Publish "State of AI Coding Tool Spend — Q2 2026" quarterly using anonymized user data. Landing page at `/report.html` already live — drive traffic to it.

- Gate with email → enterprise sales list
- PR pitch to TechCrunch, The Information, Bloomberg Technology — they cover original AI spend data
- This is your most important content asset

### Channel 5 — Finance Tool Partnerships (Month 6+)

Ramp, Brex, Zip, Coupa track all company spend but have no AI intelligence layer.

Integration play: Vantage data flows into Ramp's AI spend category. Co-marketing to enterprise customers. These partnerships deliver high-ACV enterprise customers at zero acquisition cost.

### Channel 6 — SEO + Content Machine (Month 2+)

Target keywords: "Claude Code cost per developer", "GitHub Copilot ROI tracking", "AI tool spend dashboard", "LLM cost optimization"

- Comparison pages: "Vantage vs Helicone", "Vantage vs Datadog LLM" — rank fast for high-intent searches
- Weekly blog using anonymized data insights — original data ranks and gets linked

---

## 12. Automation Layer — n8n Workflows

Self-hosted n8n on Railway ($5/mo). All 7 core business automations — no code deployments to change them. **Not yet deployed — Month 2 priority.**

### Workflow 1 — New User Onboarding

Trigger: D1 webhook → INSERT on orgs

1. Wait 5 min → Send Email #1 (welcome + "install in 2 lines")
2. D+2: Check for first event → branch: no activity (activation email + Calendly) / has activity (first insights email with real top cost)
3. D+3: If company_size > 50 → send personal outreach from Aman for design partner
4. D+7: If still free → upgrade nudge with ROI proof

**Target metric:** Activation rate (first event within 24h) > 40%

### Workflow 2 — Real-Time Anomaly Alert

Trigger: CF Worker webhook when Z-score of 10-min spend > 3σ vs 30-day baseline

1. Enrich: which user/feature caused the spike? Top 3 expensive calls.
2. Build Slack Block Kit message: spike amount, % over baseline, top offending calls, one-click "investigate" link.
3. POST to org's Slack webhook + email to admin.
4. Log to audit_events table — prevent duplicate alerts within 30min.

**Enterprise impact:** "We caught a runaway agent before your invoice" = instant renewal.

### Workflow 3 — Weekly Benchmark Report

Trigger: Cron every Monday 6:00 AM IST, all opted-in orgs.

1. Compare last-7-days metrics vs cohort percentiles. Flag if moved >10% week-over-week.
2. Claude API: generate 3 personalized insight sentences for this org's delta.
3. Send "Your AI Spend Week in Review" — MTD cost, vs last week, vs cohort, savings opportunity.
4. If 3 consecutive unopens → switch to monthly cadence.

### Workflow 4 — Monthly Executive Report (Enterprise Only)

Trigger: Cron 1st of month 7:00 AM IST, Enterprise plan orgs.

1. Aggregate prior month: total spend, per-team, per-developer, cost/PR, model mix, cache savings, quality trend.
2. Claude Opus narrative: 3-paragraph CFO-facing executive summary with forward-looking recommendation.
3. Generate PDF → KV storage.
4. Send to org admin + configured CC emails. Slack post in #finance or #leadership.

**This feature gets Vantage invited to the board meeting.**

### Workflow 5 — Renewal Intelligence Alert

Trigger: Daily check on `provider_connections` + `copilot_connections` tables.

1. Find Copilot contracts renewing in 30/14/7 days (inferred from connection date).
2. Pull 90-day ROI data for that tool: spend, cost/dev/month, suggestions accepted, usage trend.
3. Claude: "Should this company renew Copilot? Give: renew/cancel/negotiate + one-sentence reason."
4. Send alert with recommendation to CTO: "Your Copilot renews in 14 days. Our recommendation: NEGOTIATE DOWN."

**This is the enterprise killer feature.** Being the tool that tells your CTO to cancel Copilot (with data) = they trust you forever.

### Workflow 6 — Public Benchmark Content Pipeline

Trigger: Cron every Friday 5:00 PM IST.

1. Pull most interesting delta from `benchmark_snapshots` (opted-in orgs, fully anonymized).
2. Claude: generate 280-char tweet + 500-word LinkedIn post about the stat.
3. Save to Notion content calendar. Status: "Draft — needs approval."
4. Slack DM Aman with Notion link.

**Goal:** 2x/week original data-backed posts with zero manual effort.

### Workflow 7 — Free → Paid Conversion Trigger

Trigger: KV counter → org hits 40,000 events (80% of 50K free tier).

1. Calculate total $ saved via optimizer + cache this month for this org.
2. Send ROI-first email: "You've used 80% of your free tier. Vantage has saved you $[X] this month. For $99/mo, unlimited tracking — that's [X/99]x ROI."
3. If no upgrade in 3 days → Slack Aman: "High-value free org near limit. Manual outreach opportunity."

**Rule:** Never "you're running out." Always "here's what you'd get."

---

## 13. Task Plan — Priority-Ordered Execution

_Reordered 2026-04-14 based on P2 completion, competitive analysis, and threat assessment. Tasks ordered by: (1) competitive urgency, (2) revenue impact, (3) effort. Completed tasks marked ✅._

---

### P0 — Done / Merged

| Task | Status | PR |
|------|--------|----|
| AI Spend Console MVP (Cross-Platform tab, /trend, per-dev attribution) | ✅ Merged | #51 |
| Fix OTel `developer.id` attribute extraction | ✅ Merged | #52 |
| Fix CI signup rate-limit duplicate block | ✅ Merged | #53 |
| Fix free tier copy: 10K → 50K events/month | ✅ Merged | #54 |
| P2 milestone: Copilot adapter, Datadog exporter, Benchmark system, Trust page, Report page, Enterprise pricing, Audit log | ✅ Merged | #55 |

---

### P1 — This Week (highest leverage, GTM focus)

- [ ] **Email 20 CTOs at AI-heavy startups** — Design partner outreach. Use Prompt #02. Frame around Copilot billing visibility — that's the new hook. 5 warm leads = the next 6 months of roadmap feedback. **3h.**
- [ ] **Write + post Show HN** — 8am ET Tuesday or Wednesday. Lead with cross-stack story: "only tool that covers Copilot + Claude Code + any LLM API in one dashboard." Use Prompt #05. **2.5h.**
- [ ] **Decide brand/domain** — Commit to vantageai.com or register spendlens.ai / ailedger.com. `cohrint.com` is a liability in enterprise sales. **2h.**
- [ ] **Seed benchmark data** — Manually opt in 3–5 early orgs (with permission). First cohort with k≥5 unlocks the entire benchmark story. **1h + outreach.**

---

### P2 — COMPLETE ✅

All P2 tasks shipped in PR #55 (merged 2026-04-14):
- [x] Copilot Metrics API adapter (backend + cron + KV encryption)
- [x] Datadog metrics exporter (push model + idempotency)
- [x] Anonymized benchmark system (schema + k-anonymity + percentiles)
- [x] Cross-Platform Console full implementation
- [x] Audit log (`/v1/audit/*`)
- [x] Trust page (`/trust.html`)
- [x] Report page (`/report.html`, email-gated)
- [x] Enterprise tier on pricing page
- [x] Benchmark opt-in toggle in org settings
- [x] Fake testimonials removed; honest design-partner CTA
- [x] Test suites 39–41 shipped

---

### P3 — Month 2 (build + GTM sprint)

- [ ] **Build semantic cache layer** — Cloudflare Workers + Vectorize. BGE embedding, configurable similarity threshold (default 0.92), $ saved on dashboard. Ship before Helicone moves to semantic matching. Use Prompt #03. **2 weeks.**
- [ ] **Get 3 design partner CTOs onboarded** — Cross-platform console + Copilot adapter is the hook. These are your first paying customers and your benchmark data seed. **ongoing.**
- [ ] **Deploy n8n on Railway** — Onboarding drip + trial conversion workflows (Workflow 1 + 7). **6h.**
- [ ] **Start SOC2 prep with Vanta** — Timeline: begin Month 3, target Type I at Month 7–8. **ongoing.**
- [ ] **LinkedIn/Twitter — 2x/week data-driven posts** — Use benchmark data + Cross-Platform Console screenshots. AI Coding FinOps category claim. **3h/wk.**
- [ ] **First $1K MRR milestone** — 10 Team plan customers at $99/mo. **milestone.**

---

### P4 — Month 3–4

- [ ] **Launch public benchmark dashboard** — email-gated, shows industry median cost/dev/month by tool and company size band. SEO + lead gen. **1 week.**
- [ ] **Publish first full benchmark report** — "State of AI Coding Spend Q2 2026" with real anonymized data from design partners. Use Prompt #04. PR strategy. **1 week.**
- [ ] **Prompt Registry MVP** — version prompts, cost-per-version comparison. Closes gap vs Helicone + LangSmith. **6 weeks.**
- [ ] **Agent trace DAG visualization** — Basic graph view of multi-step agent sessions from existing OTel trace data. Closes most visible gap vs Langfuse Agent Graph. **2 weeks.**
- [ ] **Finance tool BD outreach** — Ramp, Brex, Zip integration conversations. **M4.**

---

### P5 — Month 5–8

- [ ] **Vendor Negotiation Module** — "What similar companies paid at their last Copilot renewal." Powered by benchmark data from P3 seed. **M5.**
- [ ] **AI Governance Report auto-generation** — Board-ready audit trail. Regulatory inevitability play. **M6.**
- [ ] **Quarterly "AI Spend Index" public report** — PR + authority play. **M6.**
- [ ] **Series A narrative draft** — Use Prompt #09. **M6.**
- [ ] **SOC2 Type I certification** — **M7–8.**
- [ ] **Quality-Adjusted Routing Engine** — Route by task type from historical quality + cost data. **M7.**

---

### P6 — Month 9–18 (platform plays)

- [ ] **AI Procurement API** — Ramp, Brex, Coupa integration. **M9.**
- [ ] **Compliance Module** — EU AI Act audit trail, HIPAA AI governance. **M10.**
- [ ] **Model Performance Index** — Public quality/cost ranking per task type. SEO + authority. **M12.**
- [ ] **Raise seed/Series A** — With 10+ enterprise customers + benchmark data from 500+ companies. **M12–15.**
- [ ] **First BD hire** — You build, they sell. **M14.**

---

### Watch List (monitor monthly)

- **Palma.ai** — Direct ICP competitor. Check pricing page, LinkedIn hiring, funding announcements. If they raise, accelerate category-claiming content immediately.
- **Helicone** — Watch for semantic cache PR in helicone/helicone GitHub. Any ship = you have less time.
- **Copilot OTel parity** — github/copilot-cli issue #2471. When it ships, update OTel adapter to consume it natively alongside the REST API adapter.
- **Langfuse Agent Graph** — Benchmark against their agent viz for product parity decisions.
- **GitHub Copilot seat pricing** — Any change to $19/user/month changes the Copilot adapter cost model.

---

## 13. Technical Design Decisions

Architectural decisions and trade-offs made during V2 implementation. These are lessons learned from production deployment and should inform Phase 3 platform work.

### 1. AbortController Isolation for Fire-and-Forget Requests

**Decision:** OTel metrics emission must use its own `AbortController`, independent of the batch upload timer.

**Why:** The Claude Code hook performs a dual-write: POSTs to `/v1/events/batch` (for dashboard) and emits OTLP JSON to `/v1/otel/v1/metrics` (for cross-platform console). If a single `AbortController` is shared, and the batch upload is slow on the user's network, the abort timeout fires and cancels the OTel request as well. This caused silent data loss — OTel events never reached the cross-platform console.

**Implementation:** In vantage-track.js, the OTel fetch uses `new AbortController()` with a separate 5-second timeout. The batch upload uses a different controller. Both fire independently. If the OTel write fails, the batch upload still succeeds.

**Trade-off:** Two simultaneous network requests instead of one. Negligible overhead for a background process, huge reliability gain.

### 2. Agent-Scoped Analytics Without Per-Agent Caching

**Decision:** `/v1/analytics/summary?agent=<name>` filters all DB queries by `agent_name` and **bypasses KV cache entirely**.

**Why:** The analytics endpoint has a 5-minute KV cache for performance. But when a customer checks "is my Claude Code hook active?" via the dashboard, they want status **now**, not stale data. A shared KV cache would show "No Data" for 5 minutes after the first hook event, confusing users.

**Implementation:** The cache is only used if `?agent=` is not provided. Agent-filtered requests always hit D1, adding the clause `AND agent_name = ?` to every query.

**Trade-off:** O(n) DB hits for n status checks. In practice: 1–2 checks per setup, so negligible. Future: could use agent-specific cache keys (e.g., `analytics:summary:agent:claude-code`) if agents become high-frequency.

### 3. Dual-Write Architecture for Event Sources

**Decision:** Claude Code hook events are written to **both** `/v1/events/batch` (analytics pipeline) **and** `/v1/otel/v1/metrics` (cross-platform console).

**Why:** Cohrint has two independent event pipelines:
- **Analytics** (`events` table) powers the main dashboard, budgets, KPIs, team breakdowns
- **Cross-Platform** (`cross_platform_usage` + OTel) powers the unified developer spend view across all tools (Copilot, Cursor, Claude Code, Codeium)

If Claude Code only went to analytics, it would be invisible in the cross-platform console. Dual-write ensures one integration reaches both consumers.

**Implementation:** Fire two separate fetch calls after event collection. Each has its own error handling and timeout.

**Trade-off:** Client-side code duplication (hook must format data for both APIs). Future: server-side could accept either format and auto-distribute, but client-side duplication keeps the hook lightweight (zero dependencies).

### 4. Client-Side Deduplication + Server-Side INSERT OR IGNORE

**Decision:** The hook maintains `~/.claude/vantage-state.json` (capped at 50K event IDs) for client-side dedup, and the server uses `INSERT OR IGNORE` for a second layer.

**Why:** Network failures and retry logic in browsers/CLIs are unpredictable. A user runs a Claude Code session, the hook POSTs the event, the response gets lost, the SDK retries, and now the event is in the database twice. Two protections: (1) client remembers IDs and won't re-POST, (2) server has a unique constraint on event_id and ignores duplicates.

**Implementation:** After an HTTP 2xx response, event IDs are appended to `vantage-state.json`. On the next hook run, the hook loads this file and checks `uploadedIds.has(eventId)` before POSTing. Server uses `event_id` as a unique key.

**Trade-off:** State file grows unbounded, so it's capped at 50K entries (client-side). Beyond 50K, old IDs are dropped. This is acceptable because: (a) events are older than the last 6 months of usage, (b) retry windows are < 1 hour in practice, (c) server-side constraint is the true safeguard.

**Risk:** If state file is corrupted, the hook will re-upload old events. Mitigation: state file is JSON; hook safely catches parse errors and starts fresh.

### 5. Setup Subcommand Before MCP Transport Initialization

**Decision:** The `npx cohrint-mcp setup` subcommand must intercept `process.argv[2] === 'setup'` **before** `StdioServerTransport` is instantiated.

**Why:** The MCP server runs an infinite loop on stdin (MCP protocol). If the setup subcommand runs after the transport starts, stdin is consumed by the transport and the process won't exit cleanly. The user runs `npx cohrint-mcp setup` and it hangs indefinitely.

**Implementation:** In vantage-mcp/src/index.ts, the `main()` function checks `process.argv[2]` at the very top. If it's `'setup'`, it calls `runSetup()` synchronously and exits with `process.exit(0)` **before** creating the transport.

**Order:**
```
main()
  → check argv[2]
  → if 'setup': runSetup() → exit(0)
  → else: create StdioServerTransport + start loop
```

**Trade-off:** Setup code lives in the MCP package (not a separate CLI). This is fine because setup runs once; the MCP server itself runs continuously.

### 6. Zero Runtime Dependencies Constraint

**Decision:** All SDK/CLI packages (`vantage-mcp`, `@cohrint/claude-code`, `vantage-js-sdk`) must have **zero npm runtime dependencies**.

**Why:** (a) Security: fewer dependencies = fewer CVEs to patch. (b) Installation speed: no `npm install` recursion. (c) Compliance: easier auditing for regulated customers. (d) Bundling: tools like Claude Code might bundle the SDK; zero deps makes bundling trivial.

**Implementation:** Use only Node.js built-ins: `node:fs`, `node:os`, `node:path`, `node:url`, `node:crypto`, `node:https`. No axios, no node-fetch, just native fetch (Node 18+).

**Trade-off:** Some nice-to-haves are unavailable (auto-retry libraries, XML parsing). The hook implements its own exponential backoff and JSON parsing (trivial for telemetry).

**Exception:** Build tools (devDependencies) can have deps: esbuild, TypeScript, Vitest, etc. Only runtime code must be zero-dep.

---

## 14. Research Canon

Priority reading before each phase. Read in order of urgency.

| # | Document | Why It Matters | When to Read |
|---|----------|---------------|--------------|
| 01 | CloudHealth → VMware acquisition (TechCrunch, 2018) | Your best analog. How a cloud cost tool built a defensible moat despite AWS/Azure/GCP building native dashboards. Study their positioning shift from "cost tool" to "multi-cloud management platform." | Week 1 |
| 02 | Apptio S-1 / IBM acquisition docs (2019) | The ITFM/TBM market is your Stage 4 model. Enterprise sales motion and pricing are your 5-year template. | Month 2 |
| 03 | EU AI Act — Official Text (eur-lex.europa.eu) — Articles 13, 17, 26 | Creates mandatory audit and governance requirements. Vantage's governance module is a compliance product, not a nice-to-have. | Month 3 |
| 04 | Sequoia "AI's $600B Question" (2024) | The macro tailwind for Vantage — every CTO who read this is now asking "are we spending too much?" You're the tool that answers that. Reference in sales decks. | Week 1 |
| 05 | GitHub Copilot Productivity Research — Microsoft/MIT Study (2023) | Shows ~55% faster task completion. But measures productivity, not cost efficiency. That's the gap your product fills. | Week 2 |
| 06 | Helicone, LangSmith, Langfuse GitHub repos + changelogs | Watch weekly releases. Any semantic caching PR in helicone/helicone = you have less time. Set up GitHub notifications. | Ongoing |
| 07 | OpenTelemetry Semantic Conventions for GenAI (CNCF, 2024) | Your OTel collector should conform. Being a good citizen of the standard increases surface area dramatically. | Week 3 |
| 08 | a16z "The New Language Model Stack" (2023) | Every layer has a winner-take-most dynamic. You need to own your layer before a better-funded player does. | Month 1 |
| 09 | Chip Huyen — "AI Engineering" (2024 book) | Chapter on production LLM systems covers evaluation, cost management, observability architecture. Technical Bible for Phase 2 build. | Month 2 |
| 10 | Paul Graham — "Do Things That Don't Scale" (YC essay) | Your 5 design partner CTOs won't come from a landing page. They come from personal outreach. Permission to do the unscalable thing now. | Week 1 |

---

## Appendix: Claude Prompt Task Library

Use these directly in Claude sessions. Each is tuned for your specific build tasks.

**Prompt 01 — AI Spend Console PRD (Week 1)**
> You are a senior product manager at a B2B SaaS startup. Write a detailed PRD for an "AI Spend Console" — a dashboard consolidating spend across GitHub Copilot, Claude Code, Cursor, Gemini CLI, and Codeium. Target user: CTO at a 50–300 person engineering org. Include: user stories, core metrics (total spend, per-developer cost, cost per PR, cost per feature, tool comparison ROI), data model requirements, prioritized feature list for a 4-week MVP. Output as structured markdown.

**Prompt 02 — Cold Outreach Email Variants (Week 1)**
> Write 3 cold email variants targeting CTOs at AI-heavy startups (50–300 employees) paying for 3+ AI coding tools. Under 100 words. Lead with specific pain ($30–80K/year, zero ROI data). Hook on Copilot billing visibility — we pull directly from GitHub's API, no OTel required. Offer 15-min demo. End with yes/no question. Variants: (1) pain-led, (2) data-led (industry benchmark), (3) fear-of-waste. Subject lines for each. No buzzwords.

**Prompt 03 — Semantic Cache Architecture (Week 3)**
> Design a semantic caching system for LLM API calls on Cloudflare Workers + Vectorize. Requirements: embed prompts with bge-small-en, query Vectorize at configurable similarity threshold (default 0.92), return cached response if match, else forward + cache. Track hit rate, cost saved, latency delta per request in D1. Expose threshold as per-org config in Vantage dashboard. Write complete TypeScript Cloudflare Worker code with error handling, D1 schema, and cost-savings calculation function. Production-ready only.

**Prompt 04 — Benchmark Report First Draft (Month 2)**
> You are a data analyst at an AI infrastructure company. Write a "State of AI Coding Tool Spend — Q2 2026" report using this data: [INSERT AGGREGATE STATS]. Include: executive summary (3 bullets), 5–7 data-backed findings, per-developer cost benchmarks by company size, model usage trends, tool consolidation patterns, 3 actionable recommendations. Tone: authoritative but accessible. 1,500–2,000 words. Include 4 chart descriptions. Gate behind email capture.

**Prompt 05 — HN Launch Post (Week 2)**
> Write a "Show HN" post for Hacker News launching Vantage's AI Spend Console. No marketing language. Be technical and honest. Acknowledge Helicone. Explain the specific technical problem solved: we cover Copilot billing (via GitHub's Metrics API, no OTel required), Claude Code + Gemini CLI (via OTel OTLP), and any LLM API (via SDK) — all in one per-developer dashboard. Share one interesting finding from early data. 300–500 words. First-person builder voice. Include 3 talking points for comment replies about how this differs from Helicone.

**Prompt 06 — Enterprise Pricing Page Copy (Month 2)**
> Write copy for an Enterprise pricing tier. Product: Vantage AI — AI spend intelligence for engineering orgs. Target: CTOs and CFOs at 100+ person companies. Include: one-line value prop, 8–10 features with benefit-focused descriptions, ROI/compliance/security proof points, 2-sentence "who it's for," CTA. Price: custom/talk to sales. Tone: confident, executive-facing. No em-dashes. Max 400 words.

**Prompt 07 — SOC2 Prep Checklist (Month 4)**
> Create a SOC 2 Type I readiness checklist for an early-stage B2B SaaS with this stack: Cloudflare Workers/Pages/D1/KV, Render (FastAPI), Python SDK on PyPI. 1 full-time employee, 3 design partner customers. Cover all 5 Trust Service Criteria. For each: controls already in place given the stack, gaps to address, policies/documents to write, tools to use (Vanta/Drata), timeline. Prioritized action plan. Flag mandatory vs nice-to-have for $10K ACV enterprise deals.

**Prompt 08 — Anonymized Benchmark Schema (Month 2)**
> Design a D1 SQLite schema for collecting anonymized benchmark data from multiple enterprise customers. Requirements: opt-in only, no org identifiers in snapshot rows (bucketed cohorts by company size band and industry), metrics: avg cost/token by model, avg cost/dev/month, tool mix, cache hit rate, quality score by model and task type. Support percentile rankings (p25/p50/p75/p90) and quarterly snapshots. k-anonymity floor: cohort sample_size ≥ 5. Write complete SQL DDL with indexes and 3 example aggregate queries: (a) median cost/dev by company size, (b) model market share by industry, (c) p75 cost/token for Claude Sonnet.

**Prompt 09 — Series A Narrative (Month 6)**
> Write a Series A investor narrative for Vantage AI — the neutral AI spend intelligence layer for enterprise engineering orgs. Traction: $35K MRR, 15 enterprise customers, 500+ companies contributing anonymized benchmark data. Stack: Cloudflare, D1, FastAPI. Team: solo founder with prior SaaS experience. Cover: problem, insight (structural conflict of interest angle), solution, traction, market size ($8B AI coding tool → $50B AI spend governance), business model, why now (AI Act, multi-provider world, Copilot + Claude Code proliferation), ask ($2M seed / $8M Series A). Data-driven, not hype. Flag where specific metrics are needed.

**Prompt 10 — Weekly Execution Review (Recurring)**
> I am a solo founder building Vantage AI. Here is week [N] status: [PASTE completed tasks, blockers, metrics (MRR, signups, demos booked, features shipped)]. Review against north stars: 500 accounts by Month 3, 5 design partners by Month 2, $1K MRR by Month 3. Identify: (a) what I'm behind on and highest-leverage action to catch up, (b) what I should stop doing, (c) one specific thing to do in next 7 days for max impact. Direct. No fluff.

---

*Cohrint · War Room Strategy · Confidential · April 2026*
*P2 is complete. The platform is real. The only question left is distribution.*
*Every week you don't own your layer, a better-funded player gets closer to it.*

---

## 15. Competitive Analysis — palma.ai vs Cohrint (2026-04-15)

> **Why this section exists:** On 2026-04-15 we did a deep competitive teardown of palma.ai — the closest enterprise competitor in the AI governance/observability space. The findings informed a landing page revision, a hero copy change, and a 60-day product roadmap. Read this before any positioning conversation, pricing negotiation, or enterprise sales call.

---

### What palma.ai is (and isn't)

palma.ai is an **MCP protocol gateway** — a control plane that intercepts tool calls between AI agents and MCP servers before they execute. Their product answers the question: *"What are our agents allowed to do, and did they do it?"*

They are:
- Selling to **CISOs and compliance teams** — the buyer is security, not engineering
- 100% **sales-led** — no public pricing, every prospect books a demo
- Targeting **regulated industries** — fintech, automotive, defense — where "the agent did X" is a liability
- Positioned around **EU AI Act / DORA / NIST** compliance frameworks
- Members of the **Agentic AI Foundation** alongside Anthropic, OpenAI, Google — strong enterprise trust signal

They are **not** a FinOps tool. They track cost as a byproduct of governance, not as the primary product. They cannot tell you which model is most cost-efficient for a given quality threshold. They cannot forecast spend. They have no CI/CD integration. They have no self-serve tier.

---

### Where palma.ai is genuinely stronger than us

**1. Human-in-the-loop agent approvals**
palma can pause an agent mid-execution and require a human to approve a sensitive tool call (e.g., write to production database). We observe spend after the fact. For a CISO evaluating liability, "we stopped it" is categorically different from "we saw it cost $200." This is not our fight — we should not try to build a competing policy enforcement layer.

**2. Per-tool-call RBAC**
palma's access control operates at the tool level: "Agent X can read from Postgres but cannot write." Our RBAC is cost-data isolation only (team scoping, viewer roles). This is a meaningful gap for enterprise procurement where data governance reviewers ask "what can each agent actually do?"

**3. Compliance framework alignment**
EU AI Act (Articles 13/17/26), DORA, NIST AI RMF — palma has done the work of mapping their product to these frameworks. We have SOC 2 Type I in progress (Q3 2026) and a DPA/BAA offering. This is table stakes, not a differentiator. We need to either accelerate the compliance story or be explicit that we are the FinOps layer that complements a governance tool like palma.

**4. Sales credibility signals**
CEO previously built and sold infrastructure monitoring to Cisco. Agentic AI Foundation membership. Enterprise procurement teams recognize these patterns and weight them. We are earlier in building these signals.

---

### Where we are genuinely stronger

**1. Cost granularity mapped to business outcomes**
"Cost per PR merged," "cost per resolved ticket," "cost per feature shipped" — this is CFO/VP Eng language. palma tracks spend as a cost allocation byproduct. We make it the core product. No other competitor does outcome-level cost attribution.

**2. Self-serve PLG motion**
50K events free, 2-line SDK integration, MCP server for natural language queries in the IDE, running in 10 minutes without talking to sales. palma has zero self-serve. Every customer requires a sales cycle. Our PLG motion lets us land accounts they can never reach at their sales velocity.

**3. Token optimization = hard ROI**
We can show a measurable payback: "you spent $10K last month; our optimization recovered $4K of that." palma has no equivalent ROI mechanism. This is our strongest enterprise close argument — CFOs approve tools that pay for themselves.

**4. CI/CD cost gates**
Preventing runaway AI spend during CI test runs via GitHub Actions is a specific pain point we solve that nobody else has clearly articulated. A team that burns $1,200 on a CI run once will remember that pain. We are the only product with a documented solution.

**5. Privacy-first local proxy**
Prompts never leave the user's machine. This is a strong story for IP-sensitive organizations (law firms, defense contractors, financial institutions doing proprietary research). palma's on-prem story is about control plane deployment — it doesn't address prompt-level privacy.

**6. Live multi-model pricing intelligence**
24 LLM prices in real time. Model switch recommendations based on actual usage patterns. palma is deliberately model-agnostic — they cannot help you choose the cheapest appropriate model because their product treats all models as equivalent.

---

### Critical positioning insight — we are NOT direct competitors

palma owns: *"Control what your agents are allowed to do."*
We own: *"Know what your AI costs and whether it was worth it."*

These answer different questions for different buyers in the same organization. The CISO buys palma. The CFO or VP Eng buys Vantage. In a 200-person company, these are often different people with different budgets.

**The go-to-market implication:** We should land first via self-serve PLG (no procurement friction, $49/month Team tier), embed in the engineering team, generate ROI data, then position a palma conversation as a separate deal for the security team. This avoids head-on competition and lets us expand deal size. "palma and Vantage are complementary" is a true statement that helps both companies.

---

### Gaps neither of us covers — first-mover opportunities (60-day window)

**1. Cost forecasting**
"At current burn rate, Team A will exhaust their $5,000 budget in 11 days." Single aggregation on existing data. Neither palma nor Helicone/Langfuse/LangSmith have this. Makes the product sticky for engineering managers who check it daily. Should be on the main dashboard, not buried. Build time: ~1 week.

**2. Internal chargeback reporting**
A monthly PDF/CSV per team: cost center number, total AI spend, event count, model breakdown, cost-per-developer. The internal invoice for AI spend. Standard FinOps practice for cloud (every CloudHealth/Apptio customer uses this). Zero AI-specific tools offer it today. Opens VP Finance as an internal champion alongside VP Eng — doubles sponsor count per deal. Build time: ~2 weeks.

**3. Application-layer cost attribution**
Both us and palma track spend at the tool/infra layer. Neither gives a SaaS company the ability to say "our /summarize endpoint costs $0.08/call" or "customer ABC costs us $0.43/month in AI inference." This is the LLM equivalent of per-feature cloud cost attribution (Datadog APM does this for infra; nobody does it for LLM). Requires a thin SDK-level decorator pattern. Build time: ~4 weeks.

**4. Quality vs. cost tradeoff tooling**
We already track hallucination rate, faithfulness, and quality scores. We already have live model pricing. Nobody has connected these to answer: "Use GPT-4o for high-stakes requests, Haiku for low-stakes — here is the cost-per-quality-unit at each threshold." This becomes our unique positioning against Helicone and Langfuse who are pure observability. Build time: ~3 weeks.

**5. Vendor negotiation intelligence**
"At your current growth rate you qualify for Anthropic volume discounts in 6 weeks." Zero competitors touch this. Requires usage trend extrapolation + published volume tier thresholds. Very high enterprise value: a single conversation with an Anthropic account rep triggered by our insight could save a customer $20K/year — they remember who surfaced that. Build time: ~2 weeks.

**6. Compliance report generation**
Enterprise compliance teams need formatted audit reports for SOC 2 Type II / DORA evidence packages — not raw CSV exports. A "generate audit report" button that produces a formatted PDF with event counts, access log summary, anomaly incidents, and model usage by team would accelerate our SOC 2 story and is a concrete competitive moat in regulated industries.

---

### Landing page & positioning changes made (2026-04-15)

1. **Hero headline changed:** "Real-time cost visibility across every AI coding tool" → "Know what your AI bill will be before it arrives — and cut it." Rationale: the old headline is descriptive (what we do). The new headline is outcome-led (what the buyer feels). Enterprise buyers need to recognize their pain before they evaluate a solution.

2. **Capabilities cards revised:** Removed 5 cards that exposed core algorithm details (prompt optimizer internals, Z-score anomaly detection, exact rate-limit thresholds, SSE architecture, efficiency scorer methodology). Rewrote 11 cards to be outcome-focused. Engineering specifics are a competitive liability on a public page; outcomes are a sales asset.

3. **FAQ answers revised:** Removed "3 environment variables" OTel setup detail and CLI slash-command internals. Replaced with outcome-focused copy.

**Rule going forward:** Capabilities section should answer "what business problem does this solve?" not "how does it technically work?" The how is the moat. Keep it off the landing page.

---

### Recommended reading before enterprise sales calls

- Sequoia "AI's $600B Question" (2024) — macro tailwind context; every CTO who read this is asking "are we spending too much?"
- CloudHealth → VMware acquisition (2018) — closest analog to our trajectory; how a cloud cost tool built a defensible moat despite hyperscaler dashboards
- EU AI Act Articles 13, 17, 26 — palma's compliance narrative; understand it before a prospect asks "how do you compare to palma on EU AI Act?"
