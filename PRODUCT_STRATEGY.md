# VantageAI — Product Strategy v3.0
**March 23, 2026 — 4-Layer Architecture**

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Our Discovery](#2-our-discovery)
3. [4-Layer Architecture](#3-4-layer-architecture)
4. [Competitive Analysis](#4-competitive-analysis)
5. [v2 Sprint Plan (March 24 – April 6)](#5-v2-sprint-plan-march-24--april-6)
6. [Statistics Organizations Need](#6-statistics-organizations-need)
7. [CI/CD Pipeline](#7-cicd-pipeline)
8. [Sources & Research](#8-sources--research)

---

## 1. The Problem

Enterprise AI API spending: $3.5B → $8.4B in 6 months (late 2024 → mid 2025). Projected $15B by 2026. **50–90% is waste.** ([Source: LeanLM][s1])

> **No tool tracks what a company spends across Copilot + Cursor + Claude Code + ChatGPT + Gemini — all in one dashboard, per developer, per team, in real-time.**

Why existing tools fail:

| Problem | Evidence |
|---|---|
| **Shadow AI** — 98% of orgs have unsanctioned AI use | Harmonic Security: 665 AI tools across enterprises, only 40% official ([Source][s2]) |
| **Per-developer blind spot** — nobody knows what each dev costs | Copilot/Cursor charge per-token overages; bills are 2–5x subscription ([Source: TechCrunch][s3]) |
| **Multi-tool chaos** — avg enterprise uses 5+ AI tools | AI-native SaaS spend grew 108% YoY without governance ([Source: Zylo][s4]) |
| **Visibility without enforcement** — can see overruns, can't prevent them | Most 2026 deployments have dashboards but no budget controls ([Source: IDC][s5]) |
| **No ROI measurement** — CFOs can't justify AI spend | Gartner: AI governance spend hits $492M in 2026 ([Source][s6]) |

---

## 2. Our Discovery

### 7+ AI coding tools now export OpenTelemetry natively

| Tool | OTel Config | Key Live Metrics | Source |
|---|---|---|---|
| **Claude Code** | `CLAUDE_CODE_ENABLE_TELEMETRY=1` | Tokens, cost (USD), commits, PRs, lines-of-code, active time | [Official Docs][s7] |
| **GitHub Copilot** | `github.copilot.chat.otel.enabled=true` | Tokens, TTFT, tool calls, agent turns, sessions | [VS Code Docs][s8] |
| **Gemini CLI** | `telemetry.enabled=true` | Tokens (5 types), API calls, file ops, compression | [Gemini CLI Docs][s9] |
| **OpenAI Codex CLI** | `~/.codex/config.toml` | Tokens, cost, tool calls, sessions, lines modified | [Codex Docs][s10] |
| **Cline** | `CLINE_OTEL_TELEMETRY_ENABLED=1` | Token usage, tool calls, mode usage | [Cline Docs][s11] |
| **OpenCode** | OTel env vars | Tokens, tool execution | [GitHub][s12] |
| **Kiro** | OTel env vars | LLM calls, agent flows | [Dash0][s13] |

### Every AI coding tool stores session data in local files

| Tool | Local Path | Format | Source |
|---|---|---|---|
| **Claude Code** | `~/.claude/projects/{dir}/{uuid}.jsonl` | JSONL — full token/cost per message | [ccusage][s14] |
| **Codex CLI** | `~/.codex/sessions/` | JSON | [Tokscale][s15] |
| **Gemini CLI** | `~/.gemini/tmp/*/chats/*.json` | JSON | [Tokscale][s15] |
| **Cursor** | API sync via session token | CSV cache | [Tokscale][s15] |
| **Roo Code** | `~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks/` | JSON | [Tokscale][s15] |
| **OpenCode** | `~/.local/share/opencode/opencode.db` | SQLite | [Tokscale][s15] |
| **Amp** | `~/.local/share/amp/threads/` | JSON | [Tokscale][s15] |

### Billing APIs exist for aggregate/historical data

| Platform | API Endpoint | Data | Source |
|---|---|---|---|
| **GitHub Copilot** | `GET /orgs/{org}/settings/billing/usage` | Per-user premium requests, model, tokens, cost | [GitHub Docs][s16] |
| **Cursor** | `GET /teams/spend` | Per-developer spendCents, model, tokens | [Cursor Docs][s17] |
| **OpenAI** | `GET /v1/organization/usage/completions` | Per-API-key, model, tokens, daily costs | [OpenAI Cookbook][s18] |
| **Anthropic** | `GET /v1/organizations/cost_report` | Per-workspace, model, tokens, cost | [Anthropic Docs][s19] |
| **ChatGPT Enterprise** | Workspace Analytics + Compliance API | Per-user CSV export, adoption metrics | [OpenAI Help][s20] |

### Browser extensions can track web AI tools

| Platform | Method | Example | Source |
|---|---|---|---|
| **ChatGPT web** | Extension reads usage from page | QuotaMeter, ChatGPT Token Counter | [QuotaMeter][s21] |
| **Claude Console** | Extension reads token counts | Claude Usage Tracker | [Chrome Store][s22] |
| **Gemini web** | Extension reads usage | QuotaMeter | [QuotaMeter][s21] |

---

## 3. 4-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    VantageAI v2 Dashboard                        │
│    "Single pane of glass for ALL AI spending"                   │
│                                                                 │
│  LAYER 1: OTel Telemetry (REAL-TIME, per-request)     [P0]    │
│  Claude Code │ Copilot │ Gemini │ Codex │ Cline │ +5 more     │
│  Config: 1 env var per tool → point at our OTLP endpoint      │
│  ══════════════════════════════════════════════════════         │
│                                                                 │
│  LAYER 2: Local File Scanner (NEAR REAL-TIME)         [P1]    │
│  CLI agent reads ~/.claude/ │ ~/.codex/ │ ~/.gemini/ │ Cursor  │
│  Covers tools that don't have OTel or as backup/dedup source  │
│  ══════════════════════════════════════════════════════         │
│                                                                 │
│  LAYER 3: Billing APIs (HOURLY, aggregate)            [P2]    │
│  Copilot Billing │ Cursor Admin │ OpenAI Usage │ Anthropic    │
│  ChatGPT Enterprise │ Google Cloud Billing                     │
│  ══════════════════════════════════════════════════════         │
│                                                                 │
│  LAYER 4: Browser Extension (REAL-TIME, web tools)    [P3]    │
│  ChatGPT web │ Claude Console │ Gemini web                     │
│  ══════════════════════════════════════════════════════         │
│                                                                 │
│              ┌────────────────────────────────┐                 │
│              │  Unified Schema + Dedup Engine  │                 │
│              │  Per-developer, per-team,       │                 │
│              │  all sources merged             │                 │
│              └───────────────┬────────────────┘                 │
│                              │                                  │
│    ┌──────────┬──────────────┼──────────┬──────────┐            │
│    ▼          ▼              ▼          ▼          ▼            │
│  Dashboard  Developer     Budget    MCP Tools   CI/CD          │
│             Profiles      Policies  (IDE query) Gate           │
└─────────────────────────────────────────────────────────────────┘
```

### Complete Coverage Matrix

| Platform | L1 OTel | L2 Local Files | L3 Billing API | L4 Browser | **Total** |
|---|---|---|---|---|---|
| **Claude Code** | ✅ | ✅ | ✅ | — | **3 sources** |
| **Copilot Chat** | ✅ | — | ✅ | — | **2 sources** |
| **Gemini CLI** | ✅ | ✅ | ✅ | — | **3 sources** |
| **Codex CLI** | ✅ | ✅ | ✅ | — | **3 sources** |
| **Cline** | ✅ | ✅ | — | — | **2 sources** |
| **Cursor** | ❌ | ✅ | ✅ | — | **2 sources** |
| **ChatGPT web** | ❌ | ❌ | ✅ | ✅ | **2 sources** |
| **Claude Console** | ❌ | ❌ | ✅ | ✅ | **2 sources** |
| **Gemini web** | ❌ | ❌ | ✅ | ✅ | **2 sources** |
| **Custom API code** | ✅ | — | ✅ | — | **2 sources** |

**Current coverage:** OTel real-time tracking across 10+ tools (live).
**Roadmap:** Billing API connectors (Q2 2026), local file scanner + browser extension (Q3 2026).

---

## 4. Competitive Analysis

### Layer 1 Competitors (Proxy/SDK — SOLVED market)

| Tool | Approach | Pricing | Can Track AI Coding Tools? | Source |
|---|---|---|---|---|
| **Helicone** | Gateway proxy | Free / $79 Pro / $799 Team | ❌ Only proxied API calls | [helicone.ai][s23] |
| **Langfuse** | SDK wrapper + OTel | Free OSS / $59 Team | ❌ Only instrumented code | [langfuse.com][s24] |
| **Portkey** | LLM gateway | Free / $49 Team | ❌ Only gateway traffic | [portkey.ai][s25] |
| **LangSmith** | LangChain SDK | Free / $39+ | ❌ LangChain only | [langsmith.com][s26] |
| **Datadog LLM** | OTel + agent | $15+/host | Partial — OTel GenAI spans | [datadoghq.com][s27] |

**None of these can track Claude Code, Copilot, Cursor, Gemini CLI, or ChatGPT.**

### Layer 2 Competitors (New — Same Architecture Space)

| Tool | What It Does | Platforms | Limitations vs VantageAI |
|---|---|---|---|
| **AI Observer** ([GitHub][s28]) | Self-hosted OTel collector for AI coding tools. Go backend, DuckDB, React dashboard. | Claude Code, Gemini CLI, Codex CLI (3 only) | Local-only, no auth, no multi-user, no budget enforcement, no billing APIs, no browser extension, no MCP, 3 platforms only |
| **base14 Scout** ([Docs][s29]) | Cloud OTel platform with AI coding agent support. | Claude Code, Codex CLI, Gemini CLI | General observability platform (not AI-cost-focused), no billing API aggregation, no per-developer profiles, no budget enforcement, no local file scanning |
| **Tokscale** ([GitHub][s15]) | Rust CLI that scans local files from 16+ AI tools. Leaderboard. | 16+ tools via local files | CLI only (no web dashboard), no OTel collection, no billing APIs, no budget enforcement, no team/org management, no browser extension, gamification focus |
| **QuotaMeter** ([Site][s21]) | Browser extension + menu bar. Reads usage from AI tool websites. | Cursor, Claude, ChatGPT, Copilot, Gemini, OpenAI/Anthropic API | Individual developer only (no team/org), no OTel, no local file scanning, no billing APIs, no budget enforcement, browser-only, £5 one-time |
| **ccusage** ([GitHub][s14]) | CLI that reads Claude Code local JSONL files. | Claude Code + Codex CLI only | 2 platforms only, no dashboard, no OTel, no billing APIs, no team management |

### How VantageAI Differentiates From ALL of Them

| Capability | Helicone | AI Observer | Tokscale | QuotaMeter | **VantageAI v2** |
|---|---|---|---|---|---|
| **L1: OTel Collector** | ❌ proxy | ✅ (3 tools) | ❌ | ❌ | **✅ (10+ tools)** |
| **L2: Local File Scanner** | ❌ | ✅ (import) | ✅ (16 tools) | ❌ | **✅ (planned)** |
| **L3: Billing APIs** | ❌ | ❌ | ❌ | ❌ | **✅ (5 providers)** |
| **L4: Browser Extension** | ❌ | ❌ | ❌ | ✅ (7 tools) | **✅ (planned)** |
| **Multi-user / Org** | ✅ | ❌ | ❌ | ❌ | **✅** |
| **Budget enforcement** | Basic rate limit | ❌ | ❌ | ❌ | **✅ (graduated)** |
| **Per-developer profiles** | ❌ | ❌ | ❌ | ❌ | **✅** |
| **ROI: cost vs commits/PRs** | ❌ | ❌ | ❌ | ❌ | **✅** |
| **MCP tools (query from IDE)** | ❌ | ❌ | ❌ | ❌ | **✅ (12 tools)** |
| **CI/CD cost gate** | ❌ | ❌ | ❌ | ❌ | **✅** |
| **Enterprise (SSO, audit)** | $799/mo | ❌ | ❌ | ❌ | **✅** |
| **Dedup across sources** | N/A | ❌ | ❌ | ❌ | **✅** |

**VantageAI is the only product combining all 4 layers + org management + budget enforcement + MCP + CI/CD.**

---

## 5. v2 Sprint Plan (March 24 – April 6)

### Priority Order

| Priority | Layer | What | Days |
|---|---|---|---|
| **P0** | L1: OTel Collector | OTLP endpoint accepting 10+ AI tools | Day 1 (**DONE** — `otel.ts` built) |
| **P0** | Schema | `cross_platform_usage` + `otel_events` tables | Day 1 (**DONE** — migration built) |
| **P1** | L3: Billing APIs | Copilot + Cursor + OpenAI + Anthropic connectors | Days 2–5 |
| **P1** | API | `/v1/cross-platform/*` endpoints | Day 6 |
| **P2** | Dashboard | "All AI Spend" view + developer profiles | Days 7–8 |
| **P2** | Budget | Policy engine + alert cron | Day 9 |
| **P2** | MCP + Landing | Update MCP tools + landing page messaging | Day 10 |
| **P2** | VantageAI CLI | Terminal wrapper for AI agents — prompt optimization, cost tracking, dashboard push, anomaly detection. Distribution channel that puts VantageAI in front of every developer using Claude Code, Codex, Gemini CLI, or Aider. | Days 10–11 |
| **P3** | L2: Local Scanner | CLI agent for local file scanning (post-sprint) | Post-sprint |
| **P3** | L4: Browser Ext | Chrome extension for ChatGPT/Claude/Gemini web | Post-sprint |

### Day 1 Deliverables (DONE)

- **`vantage-worker/src/routes/otel.ts`** — OTLP HTTP/JSON collector
  - Detects 10+ platforms by `service.name`
  - Parses `claude_code.*`, `copilot_chat.*`, `gemini_cli.*`, `codex.*`, `cline.*`, `gen_ai.client.*` metrics
  - Handles both counter (Sum) and histogram data points
  - Auth via VantageAI API key in `Authorization` header
  - Batch inserts into D1
- **`vantage-worker/migrations/0001_cross_platform_usage.sql`** — D1 tables
  - `cross_platform_usage` — unified schema (OTel + billing API + SDK)
  - `otel_events` — lightweight event audit log
  - `provider_connections` — billing API credentials
  - `budget_policies` — enforcement rules
- **TypeScript: compiles clean. SQL: validates clean.**

### User Setup (1 env var per tool)

```bash
# Claude Code
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.vantageaiops.com/v1/otel
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer vnt_YOUR_KEY"
export CLAUDE_CODE_ENABLE_TELEMETRY=1

# Copilot (VS Code settings.json)
"github.copilot.chat.otel.enabled": true
"github.copilot.chat.otel.otlpEndpoint": "https://api.vantageaiops.com/v1/otel"

# Gemini CLI (~/.gemini/settings.json)
{ "telemetry": { "enabled": true, "useCollector": true,
  "otlpEndpoint": "https://api.vantageaiops.com/v1/otel" } }

# Codex CLI (~/.codex/config.toml)
[telemetry]
enabled = true
otlp_endpoint = "https://api.vantageaiops.com/v1/otel"
```

### Days 2–5: Billing API Connectors

| Day | Connector | API | Acceptance Criteria |
|---|---|---|---|
| 2 | GitHub Copilot | `GET /orgs/{org}/settings/billing/usage` | Per-user cost data in unified schema |
| 3 | Cursor | `GET /teams/spend` | Per-developer spendCents normalized |
| 4 | OpenAI | `GET /v1/organization/usage/completions` | Per-API-key usage + daily costs |
| 5 | Anthropic + Orchestrator | `GET /v1/organizations/cost_report` + cron scheduler | All 4 connectors running hourly |

### Days 6–10: Dashboard + Budget + Polish

| Day | Deliverable |
|---|---|
| 6 | REST endpoints: `/v1/cross-platform/summary`, `/developers`, `/teams`, `/connections`, `/budget` |
| 7 | Dashboard: "All AI Spend" module with provider breakdown, daily trend, developer table |
| 8 | Developer profile drill-down + provider onboarding settings page |
| 9 | Budget policies UI + hourly enforcement cron + email alerts |
| 10 | MCP tools updated + landing page rewrite + all tests green |

---

## 6. Statistics Organizations Need

### Tier 1 — Executive Dashboard (CFO/CTO)

| Metric | Source | Freshness |
|---|---|---|
| Total AI spend (all platforms) | L1 OTel + L3 Billing APIs | Hourly |
| Spend by provider (Copilot/Cursor/Claude/OpenAI) | Aggregated | Hourly |
| Spend vs budget | Budget policies table | Hourly |
| Cost per developer | Cross-platform per-dev | Daily |
| Cost trend (MoM) | Historical | Daily |
| AI ROI: cost vs commits/PRs/lines | OTel (Claude Code, Codex) | Weekly |

### Tier 2 — Engineering Manager

| Metric | Source | Freshness |
|---|---|---|
| Team spend breakdown | Cross-platform by team tag | Hourly |
| Cost per PR | AI spend ÷ PR count (OTel data) | Weekly |
| Model mix per team | OTel model attribute | Daily |
| Copilot acceptance rate vs cost | GitHub Copilot metrics API | Daily |
| Budget utilization % per team | Spend ÷ budget | Hourly |

### Tier 3 — Developer (MCP / Dashboard)

| Metric | Source | Freshness |
|---|---|---|
| My AI spend this month | Per-developer cross-platform | Hourly |
| My most expensive model | Per-dev model breakdown | Daily |
| Cost of this prompt (pre-flight) | MCP `analyze_tokens` tool | Real-time |
| Cheaper alternatives | MCP `estimate_costs` tool | Real-time |

### Industry Benchmarks

| Metric | Benchmark | Source |
|---|---|---|
| AI cost per developer per month | $200–800 | Industry avg 2026 ([Source][s30]) |
| Copilot PR time reduction | 9.6 days → 2.4 days (75%) | GitHub data ([Source][s31]) |
| Code acceptance rate | 88% retained | GitHub Copilot stats ([Source][s31]) |
| Build success rate with AI | +84% | GitHub data ([Source][s31]) |

---

## 7. CI/CD Pipeline

### Existing (11 workflows — all working)

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci-feature.yml` | Push to `v*/P*` | Fast smoke tests |
| `ci-version.yml` | Push to `v[0-9]*` | Full test suite + auto-backup + PR |
| `ci-pr-gate.yml` | PR to `main` | TypeScript + API + Cross-browser + MCP + **Connectors** + Preview |
| `ci-connectors.yml` | Push to `connectors/**` | TypeScript strict + secret scan + unit tests + schema validation |
| `cost-check.yml` | PR touching code | AI spend gate + **cross-platform budget warning** |
| `deploy.yml` | Push to `main` | Cloudflare Pages |
| `deploy-worker.yml` | Push to `main` | Cloudflare Workers |

### v2 Branch Strategy

```
main (production)
  ↑ PR (all checks must pass)
v2.0 (version branch)
  ↑ merge
v2.0/P001-otel-collector     ← Day 1 (DONE)
v2.0/P002-copilot-connector  ← Day 2
v2.0/P003-cursor-connector   ← Day 3
v2.0/P004-openai-connector   ← Day 4
v2.0/P005-anthropic-orch     ← Day 5
v2.0/P006-api-endpoints      ← Day 6
v2.0/P007-dashboard           ← Day 7
v2.0/P008-profiles-onboard   ← Day 8
v2.0/P009-budget-policies    ← Day 9
v2.0/P010-mcp-landing        ← Day 10
```

---

## 8. Sources & Research

All claims in this document are backed by verified sources:

### Market Data
- [s1]: [LLM Cost Optimization: Enterprises Overspend 50-90%](https://leanlm.ai/blog/llm-cost-optimization)
- [s2]: [Harmonic Security: 22M Enterprise AI Prompts](https://www.harmonic.security/resources/what-22-million-enterprise-ai-prompts-reveal-about-shadow-ai-in-2025)
- [s3]: [TechCrunch: AI Tokens as Signing Bonus](https://techcrunch.com/2026/03/21/are-ai-tokens-the-new-signing-bonus-or-just-a-cost-of-doing-business/)
- [s4]: [Zylo: 2026 SaaS Management Index](https://zylo.com/reports/2026-saas-management-index/)
- [s5]: [Solvimon: AI Billing Platforms](https://www.solvimon.com/blog/6-ai-billing-software-platforms-built-for-credits)
- [s6]: [Vectra: Shadow AI Governance](https://www.vectra.ai/topics/shadow-ai)

### OTel Telemetry (Verified Docs)
- [s7]: [Claude Code Monitoring — Official Docs](https://code.claude.com/docs/en/monitoring-usage)
- [s8]: [Copilot Chat OTel — VS Code Docs](https://code.visualstudio.com/docs/copilot/guides/monitoring-agents)
- [s9]: [Gemini CLI Telemetry — Official Docs](https://google-gemini.github.io/gemini-cli/docs/cli/telemetry.html)
- [s10]: [Codex CLI Config — OpenAI Docs](https://developers.openai.com/codex/config-advanced)
- [s11]: [Cline Telemetry — Docs](https://docs.cline.bot/more-info/telemetry)
- [s12]: [Dash0: New AI Integrations (OpenCode, Kiro)](https://www.dash0.com/changelog/new-ai-integrations-opencode-langchain-kagent-openlit-and-kiro)
- [s13]: [Dash0: Agent Skills](https://www.dash0.com/changelog/agent-skills-release)

### Local File Paths
- [s14]: [ccusage — Claude Code JSONL Parser](https://github.com/ryoppippi/ccusage)
- [s15]: [Tokscale — 16+ AI Tool Scanner](https://github.com/junhoyeo/tokscale)

### Billing APIs
- [s16]: [GitHub Copilot Billing API](https://docs.github.com/en/rest/billing/usage?apiVersion=2026-03-10)
- [s17]: [Cursor AI Code Tracking API](https://cursor.com/docs/account/teams/ai-code-tracking-api)
- [s18]: [OpenAI Usage API Cookbook](https://cookbook.openai.com/examples/completions_usage_api)
- [s19]: [Anthropic Usage & Cost API](https://platform.claude.com/docs/en/build-with-claude/usage-cost-api)
- [s20]: [ChatGPT Enterprise Workspace Analytics](https://help.openai.com/en/articles/10875114-user-analytics-for-chatgpt-enterprise-and-edu)

### Browser Extensions
- [s21]: [QuotaMeter — Track All AI Costs](https://www.quotameter.app/)
- [s22]: [Claude Usage Tracker Extension](https://chromewebstore.google.com/detail/claude-usage-tracker/knemcdpkggnbhpoaaagmjiigenifejfo)

### Competitors
- [s23]: [Helicone Gateway Docs](https://docs.helicone.ai/gateway/overview)
- [s24]: [Langfuse Docs](https://langfuse.com/docs)
- [s25]: [Portkey Docs](https://portkey.ai/docs)
- [s26]: [LangSmith Docs](https://docs.smith.langchain.com/)
- [s27]: [Datadog LLM Observability](https://www.datadoghq.com/blog/llm-otel-semantic-convention/)
- [s28]: [AI Observer — GitHub](https://github.com/tobilg/ai-observer)
- [s29]: [base14 Scout — Coding Agent Observability](https://docs.base14.io/blog/coding-agent-observability/)

### Industry Benchmarks
- [s30]: [AI Coding Tools Cost Analysis 2026](https://www.sitepoint.com/ai-coding-tools-cost-analysis-roi-calculator-2026/)
- [s31]: [GitHub Copilot Statistics 2026](https://www.getpanto.ai/blog/github-copilot-statistics)
- [s32]: [OpenAI Inference Cost Crisis](https://aiautomationglobal.com/blog/ai-inference-cost-crisis-openai-economics-2026)
- [s33]: [AI Agent Cost Optimization 2026](https://moltbook-ai.com/posts/ai-agent-cost-optimization-2026)
- [s34]: [Helicone Bug: Gateway Ignores Gemini Keys](https://github.com/helicone/helicone/issues/5561)
- [s35]: [JetStream $34M Seed for AI Governance](https://www.govinfosecurity.com/startup-jetstream-secures-34m-seed-round-for-ai-governance-a-30903)

---

---

## 9. Semantic Cache — Next Major Feature (v3.1)

### Why Semantic Caching

- 80% of companies miss AI cost forecasts by >25%
- Developers ask similar questions repeatedly across teams (error explanations, code patterns, boilerplate)
- LLM round-trips add 1-30 seconds; cache hits return in <100ms
- AI cost optimization market: **$5.03B (2025) → $13.52B (2029)**, CAGR 28%
- VentureBeat: semantic caching cuts LLM bills by up to 73% in ideal conditions; 40% median in production

### Competitive Position — Cache

| Platform | Semantic Cache | Local-First | CLI Wrapping | Our Advantage |
|----------|:---:|:---:|:---:|---|
| **VantageAI** | Planned | Yes | Yes (5+ agents) | Only local-first + multi-agent |
| Helicone | Yes | No | No | Cloud-only proxy |
| Portkey | Yes | No | No | Cloud-only gateway |
| LiteLLM | Yes | No | Proxy only | No CLI agent support |
| Braintrust | Limited | No | No | Eval-focused, not caching |

**Key differentiator:** VantageAI is the only platform offering **local-first semantic caching** for CLI AI tools. All competitors operate cloud-only proxies.

### How It Works

1. User prompt arrives at vantage-cli
2. Generate embedding vector (384-1536 dims) via Cloudflare Workers AI `bge-m3`
3. Query local cache (SQLite + cosine similarity) for nearest neighbors
4. If similarity ≥ threshold (default 0.95) → return cached response (cache hit)
5. If no match → forward to LLM, cache prompt embedding + response on return

### Architecture

```
Developer Machine                    VantageAI Cloud
+------------------+                +-------------------+
| vantage-cli      |                | CF Worker         |
|   ↓               |                |   ↓               |
| Local Cache       |  (optional)   | Shared Cache      |
| (SQLite + cosine) | ───────────→ | (Vectorize)       |
|   ↓               |   sync        |   ↓               |
| Cache HIT?        |                | Team-level cache  |
| Yes → return      |                | hit analytics     |
| No  → forward     |                +-------------------+
|   to LLM API      |
+------------------+
```

### Phased Rollout

| Phase | Scope | Timeline | Expected Hit Rate |
|-------|-------|----------|-------------------|
| **Phase 1: Exact Match (MVP)** | SHA-256 prompt hashing, local SQLite, zero new deps | 1-2 weeks | 5-15% |
| **Phase 2: Semantic Match** | Workers AI `bge-m3` embeddings, brute-force cosine, threshold tuning | 2-3 weeks | 15-30% |
| **Phase 3: Team Shared Cache** | Cloudflare Vectorize, new API endpoints, dashboard analytics | 3-4 weeks | 25-40% |
| **Phase 4: Advanced Tuning** | Per-category thresholds, model-version invalidation, cache warming | 4-6 weeks | 30-50% |

### Similarity Thresholds

| Threshold | Hit Rate | Risk | Use Case |
|-----------|----------|------|----------|
| 0.98 | 5-10% | Very low | Safety-critical |
| **0.95** | **15-25%** | **Low (default)** | **Code generation** |
| 0.90 | 25-40% | Medium | Customer support |
| 0.85 | 35-55% | High | Highly repetitive only |

### Privacy Design

| Mode | Local Cache | Server Cache |
|------|------------|-------------|
| `full` | Prompt + embedding + response | Embedding + metadata only |
| `anonymized` | Prompt + embedding + response | Embedding + metadata only |
| `strict` | Embedding + response only (no prompt stored) | Nothing sent |
| `local-only` | Embedding + response only | Nothing sent |

Embeddings are one-way transforms — prompts cannot be reconstructed from vectors. Server-side storage is privacy-safe.

### Storage Strategy

| Layer | Storage | Why |
|-------|---------|-----|
| **Local (vantage-cli)** | SQLite + BLOB vectors + JS cosine | Zero native deps; O(n) fine for <10K entries |
| **Server (shared)** | Cloudflare Vectorize + D1 metadata | ~$2/mo for 50K embeddings; native vector search |
| **Embedding model** | `bge-m3` via Workers AI | $0.012/M tokens — cheapest, multilingual |

### D1 Schema Addition

```sql
CREATE TABLE cache_analytics (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  team TEXT DEFAULT '',
  developer TEXT DEFAULT '',
  cache_hits INTEGER DEFAULT 0,
  cache_misses INTEGER DEFAULT 0,
  cost_saved_usd REAL DEFAULT 0,
  latency_saved_ms INTEGER DEFAULT 0,
  period TEXT NOT NULL,
  created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);
```

### Config Schema Addition

```typescript
cache: {
  enabled: boolean;              // default false (opt-in for v1)
  similarityThreshold: number;   // 0.85-0.99, default 0.95
  ttlSeconds: number;            // default 86400 (24h)
  maxEntries: number;            // default 10000
  strategy: "local" | "hybrid";  // default "local"
}
```

### New API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/cache/query` | POST | Send embedding, get cached response if match |
| `/v1/cache/store` | POST | Store new embedding + response metadata |
| `/v1/cache/stats` | GET | Cache hit rate, cost savings, per-team breakdown |

### Dashboard Metrics

| Metric | Value to User |
|--------|--------------|
| Cache hit rate (%) | "32% of your LLM calls served from cache" |
| Cost savings ($) | "$47.20 saved this month via caching" |
| Latency saved (s) | "14.2 hours of wait time saved" |
| Top cached queries | Your team's most repeated prompt patterns |
| Cache efficiency by model | "Opus cache saves 50x more than Flash" |

### ROI Estimate (10-dev team, 100 calls/dev/day)

| Metric | Value |
|--------|-------|
| Monthly LLM calls | 90,000 |
| Cache hit rate (25%) | 22,500 cached |
| Avg cost per call | $0.02 |
| **Monthly savings** | **$450** |
| Embedding cost | $0.54/mo |
| Vectorize cost | ~$2/mo |
| **Net ROI** | **99.6%** |

### Key Open-Source References

| Library | Notes |
|---------|-------|
| [GPTCache](https://github.com/zilliztech/GPTCache) | Most mature; LangChain integration |
| [LiteLLM Cache](https://docs.litellm.ai/docs/proxy/caching) | Redis/Qdrant semantic; production-ready |
| [LangChain Cache](https://python.langchain.com/docs/integrations/caches/) | RedisSemanticCache, GPTCache adapters |

### Embedding Model Comparison

| Model | Dims | Cost (Workers AI) | Best For |
|-------|------|-------------------|----------|
| `bge-small-en-v1.5` | 384 | $0.020/M tokens | High-volume, lower accuracy |
| `bge-base-en-v1.5` | 768 | $0.067/M tokens | Good balance |
| **`bge-m3`** | **1024** | **$0.012/M tokens** | **Cheapest, multilingual (recommended)** |
| `bge-large-en-v1.5` | 1536 | $0.204/M tokens | Highest accuracy |

---

*Last updated: 24 March 2026 (v3.1 — added semantic cache strategy, market analysis, phased rollout)*
*Sprint: March 24 – April 6, 2026*
*Next review: April 7, 2026 (post-sprint retro)*

## CLI Agent Integration Roadmap (v2.3+)

_Added: 2026-04-07_

### Problem Statement

The vantage CLI wraps AI coding agents (Claude, Gemini, Codex, Aider, ChatGPT) but has four integration gaps:

1. **Permission prompts invisible**: In one-shot REPL mode, agent stdout is piped for stream-json parsing — MCP tool permission prompts are auto-denied silently, never reaching the user
2. **Session state lost on restart**: `agentSessionIds` map lives in process memory only — closing the CLI loses all conversation context
3. **Incomplete live feed**: `ClaudeStreamRenderer` only handles `assistant` and `tool_result` events — misses `content_block_delta` (real-time streaming), `message_delta` (token counts), and `thinking_delta`
4. **Agent config silos**: Each agent has rich config/memory files (`~/.claude/settings.json`, `~/.gemini/settings.json`, `~/.codex/config.toml`) that vantage never reads — leading to hardcoded model assumptions and missed optimization opportunities

### Solution Architecture

#### P0 — Permission Mode Passthrough
- Add `permissionMode` and `allowedTools` to agent adapter config
- Claude: pass `--permission-mode` and `--allowedTools` flags in `buildCommand`/`buildContinueCommand`
- Codex: pass `--approval` mode flag
- Aider: already uses `--yes` (auto-accept)
- Configurable via `~/.vantage/config.json` per agent

#### P0 — Session Persistence
- Persist `agentSessionIds` to `~/.vantage/sessions/active.json` on every `agent:completed`
- On startup, restore map from `active.json` → enables cross-restart `--resume`
- Add `/reset` command to clear session state
- Append-only `history.jsonl` for cross-session cost tracking

#### P1 — Real-time Streaming
- Parse `content_block_delta` (type: `text_delta`) for character-by-character output
- Parse `message_delta` for real token counts (vs estimation from output length)
- Parse `content_block_start` with `tool_use` for "Using tool X..." before result
- Use `--include-partial-messages` flag for finer granularity

#### P1 — Agent Config Reading
- Read `~/.claude/settings.json` for actual model, MCP servers, permission mode
- Read `~/.codex/config.toml` for model, skills
- Read `~/.gemini/settings.json` for MCP config
- Auto-detect model changes → accurate cost calculation
- Read MCP server list → populate `--allowedTools` automatically

### Agent Config File Locations

| Agent | Config | Memory/Context | Settings |
|-------|--------|----------------|----------|
| Claude | `~/.claude/settings.json` | `~/.claude/projects/{slug}/memory/` | Permissions, plugins, hooks, model |
| Gemini | `~/.gemini/settings.json` | `~/.gemini/antigravity/` (protobuf) | MCP servers |
| Codex | `~/.codex/config.toml` | `~/.codex/sessions/` (JSONL) | Model, skills |
| Aider | `.aider.conf.yml` | Git history | Model, git integration |
| Cursor | `.cursorrules` | IDE-managed | Project rules |
| Windsurf | `.windsurfrules` | IDE-managed | Project rules |

### Claude Stream-JSON Event Types (Reference)

| Event | Currently Parsed | Purpose |
|-------|-----------------|---------|
| `system` | ✓ (session ID) | Session init |
| `assistant` | ✓ (text + tool_use) | Full message blocks |
| `tool_result` | ✓ (first 10 lines) | Tool output |
| `result` | ✓ (session ID) | Final result |
| `content_block_delta` | ✗ | Real-time text streaming |
| `message_delta` | ✗ | Token usage stats |
| `content_block_start` | ✗ | Tool use announcement |
| `thinking_delta` | ✗ | Extended thinking |
| `ping` | ✗ | Keepalive |

### Permission Behavior in Print Mode

Claude `-p` mode auto-denies unpermitted tools silently. No JSON event emitted. Solutions:
- `--permission-mode acceptEdits` — auto-approves file edits
- `--allowedTools "Bash(git:*),Read,Edit,Write,Glob,Grep"` — pre-approve specific tools
- `--permission-mode bypassPermissions` — skip all checks (power users only)
