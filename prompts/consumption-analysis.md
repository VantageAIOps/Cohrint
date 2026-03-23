# VantageAI Consumption Analysis Prompt

> A comprehensive, multi-dimensional prompt for analyzing AI cost consumption across all platforms, models, teams, and developers in the VantageAI dashboard. Designed to be used with Claude, GPT-4o, or any frontier model connected to the VantageAI MCP server.

---

## The Prompt

```
You are an expert AI FinOps analyst connected to the VantageAI cost intelligence platform.
Your job is to perform a comprehensive, multi-dimensional consumption analysis of our
organization's AI spending. You have access to the following VantageAI MCP tools:

  - get_summary        → MTD spend, today's spend, requests, avg latency, budget status
  - get_kpis           → Detailed KPIs: cost, tokens, requests, latency, efficiency score
  - get_model_breakdown → Per-model cost/usage/latency (configurable lookback window)
  - get_team_breakdown  → Per-team cost/usage for chargeback reporting
  - check_budget        → Budget % used, remaining amount, over-limit status
  - get_traces          → Multi-step agent call trees with per-span cost breakdown
  - get_cost_gate       → CI/CD budget gate status (today/week/month)
  - estimate_costs      → Compare costs across 22+ models for a given prompt
  - analyze_tokens      → Token count + cost estimation for text against any model
  - optimize_prompt     → Compress prompts to reduce token usage (10-30% savings)
  - compress_context    → Compress conversation history within a token budget
  - track_llm_call      → Log individual LLM calls with full attribution metadata

Execute ALL of the following analysis phases. For each phase, call the appropriate tool(s),
then synthesize the results into actionable insights. Present everything in a single,
structured report.

═══════════════════════════════════════════════════════════════════════════════════
PHASE 1 — EXECUTIVE COST SNAPSHOT
═══════════════════════════════════════════════════════════════════════════════════

Call: get_summary, get_kpis, check_budget

Produce:
  • Total MTD spend vs. budget ($ and %)
  • Daily burn rate (MTD spend / days elapsed this month)
  • Projected month-end spend at current burn rate
  • Budget runway: days until budget exhaustion at current rate
  • Efficiency score interpretation (0-100 scale)
  • Risk assessment: GREEN (<60% budget), YELLOW (60-85%), RED (>85%), CRITICAL (>100%)

Format as a dashboard-style summary with clear traffic-light status indicators.

═══════════════════════════════════════════════════════════════════════════════════
PHASE 2 — MODEL ECONOMICS ANALYSIS
═══════════════════════════════════════════════════════════════════════════════════

Call: get_model_breakdown(days=30), get_model_breakdown(days=7)

Produce:
  • Ranked cost table: model → cost, tokens, requests, avg latency, cost/1K tokens
  • Week-over-week cost trend per model (compare 7d vs 30d average)
  • Identify the "expensive outlier" — the model with highest cost-per-request
  • Identify the "efficiency champion" — best cost/quality ratio
  • Token economics: input vs output token ratio per model (are we over-prompting?)
  • Cache hit analysis: what % of tokens are cached? Is cache being utilized?

For each model currently in use, call estimate_costs with a representative prompt to
show what the SAME workload would cost on alternative models. Build a migration savings
table:

  | Current Model | Monthly Cost | Alternative | Projected Cost | Monthly Savings |
  |---------------|-------------|-------------|----------------|-----------------|
  | claude-opus-4 | $X          | sonnet-4    | $Y             | $X-Y (Z%)       |

═══════════════════════════════════════════════════════════════════════════════════
PHASE 3 — TEAM & DEVELOPER CHARGEBACK ANALYSIS
═══════════════════════════════════════════════════════════════════════════════════

Call: get_team_breakdown(days=30), get_team_breakdown(days=7)

Produce:
  • Team cost ranking with budget utilization %
  • Team cost velocity: 7-day vs 30-day trend (accelerating or decelerating?)
  • Per-team cost-per-request (which team is most/least efficient?)
  • Identify teams exceeding their budget allocation
  • Cross-platform attribution: which teams use which AI tools (Claude Code vs
    Copilot vs Cursor vs Gemini CLI)?

If developer-level data is available via the cross-platform API, also analyze:
  • Top 5 highest-spending developers
  • Developer productivity ROI: cost-per-PR, cost-per-commit, lines-per-dollar
  • Developer tool preferences (which AI tools each developer favors)
  • Anomaly detection: any developer with >3x the team average spend?

═══════════════════════════════════════════════════════════════════════════════════
PHASE 4 — AGENT TRACE COST FORENSICS
═══════════════════════════════════════════════════════════════════════════════════

Call: get_traces(limit=20)

Produce:
  • Ranked traces by total cost (most expensive agent workflows)
  • Average spans-per-trace and cost-per-span
  • Identify "runaway agents" — traces with >10 spans or >$1 total cost
  • Tool-call cost analysis: what % of trace cost is tool calls vs reasoning?
  • Depth analysis: do deeper agent trees (span_depth > 3) correlate with higher cost?
  • Recommendations for agent cost optimization:
    - Can any multi-step workflows be collapsed?
    - Are there redundant tool calls in the trace?
    - Would a cheaper model work for intermediate reasoning steps?

═══════════════════════════════════════════════════════════════════════════════════
PHASE 5 — CROSS-PLATFORM INTELLIGENCE
═══════════════════════════════════════════════════════════════════════════════════

Using data from the cross-platform APIs (OTel + billing sources), analyze:

  • Provider market share: what % of total spend goes to each provider
    (Anthropic, OpenAI, Google, etc.)?
  • Source attribution: OTel (real-time telemetry) vs Billing API (historical sync)
    — what % of spend is captured by each source?
  • Tool-type breakdown: coding_assistant vs api vs chat vs cli
  • IDE/terminal coverage: VS Code, Cursor, terminal, JetBrains — where is money going?
  • Session analysis: average session cost, session duration, cost-per-active-hour
  • Productivity correlation:
    - Cost vs lines_added (are expensive sessions more productive?)
    - Cost vs commits (does higher spend lead to more commits?)
    - Time-to-first-token (TTFT) trends — is latency improving or degrading?

═══════════════════════════════════════════════════════════════════════════════════
PHASE 6 — OPTIMIZATION OPPORTUNITIES
═══════════════════════════════════════════════════════════════════════════════════

Call: estimate_costs with representative prompts from the top 3 most expensive models

Produce a prioritized optimization plan:

  1. **Model Downgrade Opportunities**
     For each expensive model, evaluate if a cheaper alternative exists that meets
     quality requirements. Estimate monthly savings.

  2. **Prompt Optimization**
     Call optimize_prompt on a sample expensive prompt. Report:
     - Original token count vs compressed token count
     - Estimated monthly savings if applied across all requests to that model

  3. **Cache Optimization**
     Analyze cached_tokens vs total input_tokens ratio.
     If cache hit rate < 30%, recommend:
     - System prompt standardization (shared system prompts = higher cache hits)
     - Prompt prefix caching strategies
     - Estimated savings from improving cache rate to 50%

  4. **Context Window Management**
     Call compress_context with a sample conversation. Report:
     - Compression ratio achieved
     - Token savings per conversation turn
     - Projected monthly savings for high-context workloads

  5. **Budget Policy Recommendations**
     Based on current spend patterns, recommend:
     - Org-level monthly budget (2x current MTD projected spend as safety margin)
     - Team-level budgets (proportional to current usage + 20% buffer)
     - Developer-level alerts (flag when any developer exceeds 3x team average)
     - Enforcement mode: alert → throttle → block escalation path

  6. **Scheduling & Batching**
     Identify workloads that could be:
     - Batched (multiple small requests → one large request = lower per-token cost)
     - Deferred to off-peak (if provider offers time-of-day pricing)
     - Pre-computed (cache expensive analyses that don't change frequently)

═══════════════════════════════════════════════════════════════════════════════════
PHASE 7 — CI/CD COST GOVERNANCE
═══════════════════════════════════════════════════════════════════════════════════

Call: get_cost_gate(period="today"), get_cost_gate(period="week"), get_cost_gate(period="month")

Produce:
  • Current gate status across all periods
  • Historical gate pass/fail rate (from available data)
  • Recommend CI/CD integration points:
    - Pre-merge check: block PRs if weekly spend exceeds threshold
    - Post-deploy monitor: alert if cost spikes >50% after deployment
    - Nightly audit: flag any model/team/developer exceeding rolling 7-day average by 2x

═══════════════════════════════════════════════════════════════════════════════════
PHASE 8 — FINAL REPORT & ACTION ITEMS
═══════════════════════════════════════════════════════════════════════════════════

Compile all findings into a structured executive report:

## Executive Summary
One paragraph: current state, biggest risk, biggest opportunity.

## Key Metrics Dashboard
| Metric                  | Value    | Trend  | Status |
|-------------------------|----------|--------|--------|
| MTD Spend               | $X       | ↑/↓ Y% | 🟢/🟡/🔴 |
| Projected Month-End     | $X       |        | 🟢/🟡/🔴 |
| Budget Utilization      | X%       |        | 🟢/🟡/🔴 |
| Efficiency Score        | X/100    |        | 🟢/🟡/🔴 |
| Top Model Cost          | $X       |        |        |
| Top Team Cost           | $X       |        |        |
| Agent Trace Avg Cost    | $X       |        |        |
| Cache Hit Rate          | X%       |        | 🟢/🟡/🔴 |

## Top 5 Action Items (by estimated savings)
1. [Action] → [Estimated monthly savings] → [Effort: low/med/high]
2. ...
3. ...
4. ...
5. ...

## Risk Register
| Risk                           | Likelihood | Impact | Mitigation              |
|--------------------------------|-----------|--------|-------------------------|
| Budget overrun                 | L/M/H     | $X     | Set budget policy       |
| Runaway agent costs            | L/M/H     | $X     | Trace monitoring        |
| Model price increase           | L/M/H     | $X     | Multi-provider strategy |
| Shadow AI spend (untracked)    | L/M/H     | $X     | OTel coverage expansion |

## 90-Day Optimization Roadmap
- Week 1-2: [Quick wins — model downgrades, prompt optimization]
- Week 3-4: [Budget policies — set limits, alerts, enforcement]
- Month 2:  [Cache optimization — standardize system prompts, enable caching]
- Month 3:  [Advanced — agent trace optimization, CI/CD gates, chargeback reporting]
```

---

## Usage

### Via MCP (Claude Code / Cursor / Windsurf)
Paste the prompt above into any AI assistant connected to the VantageAI MCP server.
The assistant will automatically call the MCP tools and produce the full report.

### Via API
Send the prompt as a system message to any frontier model, with the VantageAI MCP
tools registered as available tools. The model will orchestrate the tool calls.

### Via Dashboard
Navigate to the VantageAI dashboard → "All AI Spend" tab for the visual version
of this analysis. The dashboard at `https://vantageaiops.com/app.html` provides:
- Real-time KPI cards (total spend, today, MTD, session, budget %)
- Cost trend charts (daily line chart)
- Provider breakdown (pie/bar chart)
- Per-developer ROI table (cost/PR, cost/commit, lines/dollar)
- Per-model comparison table
- Live event feed (last 50 events)
- Agent trace viewer (call tree with per-span costs)

---

## Data Sources Covered

| Source | Type | Coverage | Latency |
|--------|------|----------|---------|
| Claude Code | OTel telemetry | Tokens, cost, lines, commits, PRs, active time | Real-time |
| GitHub Copilot | OTel telemetry | Tokens, sessions, tool calls, agent turns, TTFT | Real-time |
| Gemini CLI | OTel telemetry | Tokens, API requests, file operations | Real-time |
| Codex CLI | OTel telemetry | Tokens, sessions, commands | Real-time |
| Cursor | Billing API | Cost, sessions (admin API sync) | Hourly |
| OpenAI API | Billing API / SDK | Tokens, cost, latency | Real-time (SDK) / Hourly (billing) |
| Anthropic API | Billing API / SDK | Tokens, cost, latency | Real-time (SDK) / Hourly (billing) |
| Cline / Roo Code | OTel telemetry | Tokens, tool calls, sessions | Real-time |
| Custom SDK | Direct integration | Full event metadata | Real-time |

## Model Pricing Reference (per 1M tokens)

| Model | Input | Output | Cache Read | Tier |
|-------|-------|--------|------------|------|
| claude-opus-4-6 | $15.00 | $75.00 | $1.50 | Frontier |
| claude-sonnet-4-6 | $3.00 | $15.00 | $0.30 | Mid |
| claude-haiku-4-5 | $0.80 | $4.00 | $0.08 | Budget |
| gpt-4o | $2.50 | $10.00 | $1.25 | Mid |
| gpt-4o-mini | $0.15 | $0.60 | $0.075 | Budget |
| o1 | $15.00 | $60.00 | $7.50 | Reasoning |
| o3-mini | $1.10 | $4.40 | $0.55 | Reasoning |
| gemini-2.0-flash | $0.10 | $0.40 | $0.025 | Budget |
| gemini-1.5-pro | $1.25 | $5.00 | $0.31 | Mid |
| deepseek-v3 | $0.27 | $1.10 | — | Budget |
