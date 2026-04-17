# Dashboard UI Specification — Every Card, Every State

## Overview

The Cohrint dashboard (`app.html`) is a single-page application served from Cloudflare Pages. It loads data from `api.cohrint.com` via six parallel `apiFetch()` calls on mount. Every card is role-aware — members see team-scoped data, admins see org-wide data.

---

## Layout Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│  HEADER  Logo · Org Name · Role Badge · API Key hint · Logout           │
├─────────────────────────────────────────────────────────────────────────┤
│  NAV TABS                                                                │
│  Overview │ Analytics │ Models │ Traces │ [Integrations*] [Settings*]   │
│           │           │        │        │ [Audit Log*]   (*admin+ only) │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ KPI Card │ │ KPI Card │ │ KPI Card │ │ KPI Card │ │ KPI Card │    │
│  │ Today $  │ │  MTD $   │ │ Session  │ │  Tokens  │ │ Requests │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
│                                                                          │
│  ┌──────────┐ ┌──────────┐ ┌────────────────────────────────────────┐  │
│  │ Projected│ │  Budget  │ │                                        │  │
│  │Month-End │ │  Runway  │ │     Cost Over Time (Line Chart)        │  │
│  └──────────┘ └──────────┘ │     30-day daily cost breakdown        │  │
│                             │                                        │  │
│  ┌──────────┐ ┌──────────┐ └────────────────────────────────────────┘  │
│  │  Cache   │ │  Quality │                                              │
│  │ Hit Rate │ │  Score   │  ┌──────────────────────────────────────┐   │
│  └──────────┘ └──────────┘  │  Model Breakdown (Doughnut Chart)    │   │
│                              │  Top 5 models by spend               │   │
│                              └──────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tab 1 — Overview

### KPI Row 1 — Primary Cost Cards

---

#### Card: Today's Cost
```
┌─────────────────────────────┐
│  💰  Today's Cost           │
│                             │
│       $  47.82              │
│                             │
│  ▲ +12% vs yesterday        │
│  Source: /analytics/summary │
│  Field:  today_cost_usd     │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `today_cost_usd`

**What it shows:** Total LLM API spend since UTC midnight today. Resets at 00:00 UTC.

**States:**
- `$0.00` — No events today (new org or weekend)
- `$0.00–$10` — Green text
- `$10–$100` — Default (gray)
- `>$100` — Amber warning if approaching daily budget

**Update cadence:** Refreshed every 30 seconds via SSE stream or polling.

**Role scoping:** Members with `scope_team` set see only their team's today cost.

**Edge cases:**
- If `today_cost_usd` is null (no events ever), shows `—` not `$0.00`
- Tooltip: "Spend since 00:00 UTC. Updates in real-time."

---

#### Card: Month-to-Date (MTD) Cost
```
┌─────────────────────────────┐
│  📅  Month-to-Date          │
│                             │
│      $ 1,840.50             │
│                             │
│  36.8% of $5,000 budget     │
│  ████░░░░░░░░  Budget bar   │
│  Source: /analytics/summary │
│  Field:  mtd_cost_usd       │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `mtd_cost_usd`, `budget_usd`

**What it shows:** Cumulative spend from 1st of current month to now (UTC).

**Budget progress bar:**
- 0–50%: Green fill
- 50–75%: Amber fill
- 75–90%: Orange fill
- 90–100%: Red fill
- >100%: Red fill + "OVER BUDGET" badge

**States:**
- No budget set (`budget_usd = 0`): Bar hidden, just shows dollar amount
- Budget set: Shows "X% of $Y,000 budget" with progress bar

**Formula:** `budget_pct = (mtd_cost_usd / budget_usd) × 100`

---

#### Card: Session Cost (Last 30 min)
```
┌─────────────────────────────┐
│  ⚡  Session Cost           │
│                             │
│        $  3.24              │
│                             │
│  Last 30 minutes            │
│  Source: /analytics/summary │
│  Field:  session_cost_usd   │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `session_cost_usd`

**What it shows:** Cost of LLM calls in the last 30 minutes. Designed for developers to see real-time cost of their active coding session.

**Use case:** Developer running a long agent session can glance at this to see if they're burning money unexpectedly.

**States:**
- `$0.00` — No recent activity (idle)
- Updates every 30 seconds
- If `> $10` in 30 min: amber highlight (potential runaway)

---

#### Card: Total Tokens
```
┌─────────────────────────────┐
│  🔤  Total Tokens (MTD)     │
│                             │
│     12,847,392              │
│                             │
│  Prompt: 8.2M  Comp: 4.6M  │
│  Source: /analytics/kpis    │
│  Field:  total_tokens       │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/kpis?period=30` → `total_tokens`, `total_prompt_tokens`, `total_completion_tokens`

**What it shows:** Token consumption breakdown for the trailing 30 days.

**Sub-labels:** Prompt tokens vs Completion tokens. High prompt/completion ratio may indicate verbose system prompts costing money without value.

**Format:** Numbers >1M formatted as "12.8M", >1K as "12.8K"

---

#### Card: Total Requests
```
┌─────────────────────────────┐
│  📡  Total Requests (MTD)   │
│                             │
│        8,472                │
│                             │
│  Avg cost: $0.22 / request  │
│  Source: /analytics/kpis    │
│  Field:  total_requests     │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/kpis?period=30` → `total_requests`, computed avg

**What it shows:** Number of LLM API calls in the last 30 days.

**Sub-label:** `Avg cost per request = mtd_cost_usd / total_requests` — signals whether requests are cheap (high-volume batch) or expensive (long-context one-shots).

---

### KPI Row 2 — Forecast & Quality Cards

---

#### Card: Projected Month-End Cost (NEW — PR #70)
```
┌─────────────────────────────┐
│  📈  Projected Month-End    │
│                             │
│      $ 5,521.50             │
│                             │
│  +$521 over budget          │
│  Based on $184/day avg      │
│  Source: /analytics/summary │
│  Field: projected_month_end │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `projected_month_end_usd`, `daily_avg_cost_usd`

**What it shows:** If today's daily average spend continues for the rest of the month, this is the projected total.

**Formula (computed server-side):**
```
daily_avg = mtd_cost_usd / MAX(UTC_day_of_month, 1)
projected  = daily_avg × days_in_current_month
```

**Color coding:**
- Under budget: Green text
- Within 10% of budget: Amber text + "⚠ Approaching limit"
- Over budget: Red text + "+$X over budget" sub-label

**States:**
- Month is day 1: projection equals today's cost × days_in_month (high uncertainty)
- No budget set: Shows projection without "over/under" comparison, just the dollar amount
- `null` (no events this month): Shows `—`

**Tooltip:** "Projection based on $X/day average over the last N days. Assumes constant daily spend."

---

#### Card: Budget Runway (NEW — PR #70)
```
┌─────────────────────────────┐
│  🏃  Budget Runway          │
│                             │
│         17 days             │
│                             │
│  Budget exhausted Apr 27    │
│  At current $184/day pace   │
│  Source: /analytics/summary │
│  Field: days_until_budget_  │
│         exhausted           │
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `days_until_budget_exhausted`

**What it shows:** Days remaining before monthly budget is exhausted at the current daily spend rate.

**Formula:**
```
remaining = budget_usd - mtd_cost_usd
runway    = CEIL(remaining / daily_avg_cost_usd)
           → 0  if budget already exceeded
           → null if no budget set or daily_avg = 0
```

**Color coding (traffic light):**
- `> 14 days` — Green background: "On track"
- `8–14 days` — Amber background: "⚠ Monitor spend"
- `1–7 days` — Red background: "🔴 Budget critical"
- `= 0` — Red background + "BUDGET EXCEEDED" text
- `null` (no budget) — Gray: "No budget set — configure in Settings"

**Sub-label:** Computes and displays the calendar date: "Budget exhausted [Month Day]"

**Action link:** "Set budget →" links to Settings tab (admin+ only)

---

#### Card: Cache Hit Rate
```
┌─────────────────────────────┐
│  ⚡  Semantic Cache         │
│                             │
│       62% hit rate          │
│  ████████████░░░░░░░        │
│                             │
│  $1,971 saved this month    │
│  Source: /cache/stats       │
│  Field:  hit_rate,          │
│          total_savings_usd  │
└─────────────────────────────┘
```

**Data source:** `GET /v1/cache/stats` → `hit_rate`, `total_savings_usd`, `total_hits`, `total_misses`

**What it shows:** Percentage of prompts served from semantic cache (cosine similarity ≥ 0.92) vs forwarded to the LLM.

**Color coding:**
- `< 20%` — Gray (cache warming up or low prompt repetition)
- `20–50%` — Blue (good cache utilisation)
- `50–80%` — Green (excellent)
- `> 80%` — Gold (outstanding — highly repetitive workload)

**Sub-label:** `$X saved this month` — sum of `cost_usd` of all cache hits, showing actual dollar value.

**States:**
- Cache disabled (`enabled = false`): Shows "Cache disabled — enable in Settings"
- No entries yet: Shows "0% — cache warming up"
- Not enough data (<100 lookups): Shows "Insufficient data"

---

#### Card: Avg Quality Score
```
┌─────────────────────────────┐
│  ✅  Avg Quality Score      │
│                             │
│     0.87 / 1.00             │
│  ████████████████░░░        │
│                             │
│  Hallucination:  0.82 ⚠     │
│  Faithfulness:   0.91 ✓     │
│  Source: /analytics/summary │
│  Field:  hallucination_score│
└─────────────────────────────┘
```

**Data source:** `GET /v1/analytics/summary` → `hallucination_score` (org avg, 30-day trailing)

**What it shows:** Average quality score across all scored events this month. Lowest dimension shown as the "weakest link."

**Color coding:**
- `> 0.90` — Green: "High quality"
- `0.75–0.90` — Amber: "Acceptable"
- `< 0.75` — Red: "Quality issues detected"

**Sub-labels:** Shows the two most important dimensions — hallucination and faithfulness — with pass/warn icons.

**States:**
- No scored events: Shows "—" with "Quality scoring is async — scores appear within minutes of events"
- Only available for organisations using Cohrint quality scoring (requires events with responses)

**Action:** Clicking the card navigates to the Traces tab filtered by low hallucination score.

---

### Cost Over Time Chart

```
┌─────────────────────────────────────────────────────────┐
│  Cost Over Time (Last 30 Days)         [7d] [14d] [30d] │
│                                                          │
│  $300 ┤                    ╭─╮                          │
│  $250 ┤               ╭───╯ ╰─╮                        │
│  $200 ┤          ╭────╯       ╰────╮                   │
│  $150 ┤    ╭─────╯                 ╰──                  │
│  $100 ┤────╯                                            │
│   $50 ┤                                                 │
│    $0 └─────────────────────────────────────────────    │
│       Apr 1         Apr 15              Apr 30          │
│                                                          │
│  ● Daily cost   ○ 7-day rolling avg                     │
└─────────────────────────────────────────────────────────┘
```

**Data source:** `GET /v1/analytics/timeseries?period=30` → array of `{date, cost_usd, tokens, requests}`

**What it shows:** Daily spend as a line chart using Chart.js. Period selector (7/14/30 days) re-fetches.

**Chart elements:**
- Primary line: Daily `cost_usd` (solid blue)
- Secondary line: 7-day rolling average (dashed gray) — smooths out weekday/weekend variation
- X-axis: Date labels (every 5 days for 30-day view)
- Y-axis: Dollar amount, auto-scaled
- Hover tooltip: `Apr 17: $184.20 (↑12% vs 7-day avg)`

**Budget line:** If `budget_usd > 0`, draws a horizontal red dashed line at `budget_usd / days_in_month` (daily budget ceiling).

---

### Model Breakdown Doughnut Chart

```
┌──────────────────────────────────────┐
│  Spend by Model (Last 30 Days)       │
│                                      │
│         ╭──────────╮                 │
│       ╭─┤  $1,840  ├─╮              │
│  GPT-4o│ │  Total   │ │claude-opus  │
│  42%   │ ╰──────────╯ │  28%        │
│       ╰─────────────────╯            │
│                                      │
│  ● gpt-4o          $772 (42%)       │
│  ● claude-opus-4-6 $515 (28%)       │
│  ● claude-sonnet-4 $239 (13%)       │
│  ● gpt-4o-mini     $184 (10%)       │
│  ● gemini-pro      $130  (7%)       │
└──────────────────────────────────────┘
```

**Data source:** `GET /v1/analytics/models?period=30` → array of `{model, cost_usd, tokens, requests, pct}`

**What it shows:** Proportional spend per model as a doughnut chart. Centre shows total spend.

**Legend:** Each model listed with dollar amount and percentage. Top 5 shown; rest collapsed as "Other."

**Click interaction:** Clicking a model segment filters the timeseries chart to show only that model's spend over time.

---

## Tab 2 — Analytics

### Period Selector
```
┌────────────────────────────────────┐
│  Period: [7 days ▼]   Team: [All ▼]│
└────────────────────────────────────┘
```

All Analytics tab charts re-fetch with `?period=N` when period changes. Team dropdown (admin+) filters by team.

### KPI Summary Row
```
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Total    │ │ Total    │ │ Avg Cost │ │ Avg      │ │ Streaming│
│ Cost     │ │ Requests │ │ /Request │ │ Latency  │ │  Count   │
│ $2,840   │ │  12,472  │ │  $0.23   │ │  1,240ms │ │    3     │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
```

**Data source:** `GET /v1/analytics/kpis?period=N`

**Streaming count:** Number of currently open SSE connections — shows how many developers are live-streaming data right now.

### Timeseries Chart (Full)
Same as Overview but with period selector and toggles for cost/tokens/requests.

### Teams Table
```
┌────────────────────────────────────────────────────────────┐
│  Team Breakdown                                            │
├──────────────┬──────────┬──────────┬────────────┬────────┤
│  Team        │  Cost    │ Requests │ Budget Used│ Status │
├──────────────┼──────────┼──────────┼────────────┼────────┤
│  backend     │  $840    │  4,820   │  84%  ████ │  ⚠     │
│  frontend    │  $320    │  2,140   │  32%  ██   │  ✓     │
│  data-sci    │  $680    │  3,890   │  68%  ████ │  ✓     │
│  devops      │  $120    │    980   │  12%  █    │  ✓     │
└──────────────┴──────────┴──────────┴────────────┴────────┘
```

**Data source:** `GET /v1/analytics/teams?period=N`

**Budget Used column:** `(team_cost / team_budget) × 100`. Red if >80%, amber if >60%.

**Status column:** ✓ = under budget, ⚠ = >80% budget, 🔴 = over budget.

**Click row:** Opens team drill-down modal showing per-developer breakdown within that team.

---

## Tab 3 — Models

```
┌─────────────────────────────────────────────────────────────┐
│  Model Cost Breakdown                    Period: [30 days ▼] │
├──────────┬──────────┬──────────┬─────────┬─────────────────┤
│  Model   │  Cost    │ Requests │ Avg$/req│  Quality Avg    │
├──────────┼──────────┼──────────┼─────────┼─────────────────┤
│ gpt-4o   │  $772    │  4,289   │  $0.180 │ ✓ 0.94         │
│ claude-  │  $515    │  5,722   │  $0.090 │ ✓ 0.92         │
│ opus-4-6 │          │          │         │                 │
│ claude-  │  $239    │  6,640   │  $0.036 │ ✓ 0.91         │
│ sonnet-4 │          │          │         │                 │
│ gpt-4o-  │  $184    │ 23,000   │  $0.008 │ ○ —            │
│ mini     │          │          │         │                 │
│ gemini-  │  $130    │  4,333   │  $0.030 │ ✓ 0.89         │
│ pro      │          │          │         │                 │
└──────────┴──────────┴──────────┴─────────┴─────────────────┘
```

**Data source:** `GET /v1/analytics/models?period=N`

**Quality Avg column:** Average `hallucination_score` for that model over the period. `○ —` = no quality scores yet.

**Recommendation badge:** If a cheaper model exists with quality within 0.05 of the current model, shows "💡 Consider claude-haiku-4-5 ($0.001/req, 0.91 quality)"

**Sort:** Default by cost DESC. Clickable column headers for re-sort.

---

## Tab 4 — Traces

### Trace List
```
┌─────────────────────────────────────────────────────────────┐
│  Agent Traces                            Period: [7 days ▼] │
├───────────────┬──────┬─────────┬─────────┬─────────────────┤
│  Trace ID     │Spans │  Cost   │Latency  │  Started        │
├───────────────┼──────┼─────────┼─────────┼─────────────────┤
│ trace_a3f2... │  23  │  $4.20  │ 45min   │ Apr 17 14:23    │
│ trace_b891... │   8  │  $0.84  │  8min   │ Apr 17 12:05    │
│ trace_c44a... │   3  │  $0.12  │  2min   │ Apr 17 09:47    │
└───────────────┴──────┴─────────┴─────────┴─────────────────┘
```

**Data source:** `GET /v1/analytics/traces?period=N`

**Click row:** Expands to show the full DAG tree for that trace.

### Trace DAG Detail View
```
┌─────────────────────────────────────────────────────────────┐
│  Trace: trace_a3f2...    Total: $4.20    Duration: 45min    │
│                                                              │
│  ▼ 🤖 coding-agent (root)              $4.20   45min       │
│      ├─ 📄 read_file ×8               $0.08    2min        │
│      ├─ 🔍 analyze_code ×3            $0.54    8min        │
│      │    ├─ 💬 call_llm (gpt-4o)     $0.18    2.1min      │
│      │    ├─ 💬 call_llm (gpt-4o)     $0.18    2.3min      │
│      │    └─ 💬 call_llm (gpt-4o)     $0.18    1.9min      │
│      ├─ ✍️  write_tests ×4            $0.30    5min        │
│      └─ 💬 call_llm ×8 (gpt-4o)      $3.04   30min ← 72%  │
│                                                              │
│  ⚠️  8 call_llm spans using gpt-4o ($0.38/each avg)        │
│  💡 Switch to claude-haiku-4-5 → save ~$2.80/run           │
└─────────────────────────────────────────────────────────────┘
```

**Data source:** `GET /v1/analytics/traces/:traceId`

**Tree rendering:** Collapsible nodes. Each node shows: tool name, call count, cost, latency, model (if LLM call).

**Cost attribution bar:** Visual bar beside each node proportional to its % of total trace cost.

**Recommendation inline:** If any model has a cheaper equivalent with comparable quality, shows suggestion inline within the trace.

**RBAC:** Members see only their own traces (`developer_email` filter). Admins see all.

---

## Tab 5 — Integrations (admin+ only)

### Claude Code Card
```
┌─────────────────────────────────────────────┐
│  Claude Code                    ● ACTIVE     │
│                                              │
│  67,420 events tracked                       │
│  Last event: 2 minutes ago                  │
│  API Key: crt_myorg...  [Rotate key]        │
│                                              │
│  Setup: ~/.claude/settings.json ✓           │
│  Hook: PostToolUse Stop hook ✓              │
│                                              │
│  [View Claude Code events →]                 │
└─────────────────────────────────────────────┘
```

**Status logic:**
- `● ACTIVE` (green) — events received in last 24h via Stop hook
- `◎ SETUP` (amber) — API key valid but no events from Claude Code hook
- `○ NOT CONNECTED` (gray) — no events in last 7 days

**"Rotate key" button:** Calls `POST /v1/auth/rotate`, shows new key once (copy-on-click), updates hint.

**Setup validation:** Checks `~/.claude/settings.json` hook exists via a `GET /v1/analytics/summary?source=hook` probe.

---

### GitHub Copilot Card
```
┌─────────────────────────────────────────────┐
│  GitHub Copilot                 ● ACTIVE     │
│                                              │
│  Org: acme-corp                             │
│  140 seats tracked                          │
│  Last sync: Sun Apr 14 00:00 UTC            │
│  Next sync: Sun Apr 21 00:00 UTC            │
│                                             │
│  ┌────────────────────────────────────┐     │
│  │ Top 5 developers by acceptance %  │     │
│  │ alice: 84% · bob: 79% · carol: 71%│     │
│  └────────────────────────────────────┘     │
│                                              │
│  [Disconnect]  [View all developers →]      │
└─────────────────────────────────────────────┘
```

**Connect flow:**
1. Admin clicks "Connect GitHub Copilot"
2. Modal: enter GitHub Org name + Personal Access Token (PAT)
3. POST `/v1/copilot/connect` → PAT encrypted AES-256-GCM → stored in KV only
4. Card shows ACTIVE after first cron sync (Sunday UTC)

**States:**
- Not connected: "Connect GitHub Copilot" button + instructions
- Connected, pre-sync: "Waiting for first sync (Sunday UTC)"
- Connected, active: Shows sync status + developer stats

---

### Datadog Card
```
┌─────────────────────────────────────────────┐
│  Datadog Exporter               ● ACTIVE     │
│                                              │
│  Site: datadoghq.com                        │
│  Metrics pushed: vantage.ai.cost_usd        │
│                  vantage.ai.tokens          │
│  Last push: Apr 17 14:20 UTC               │
│  Events exported this month: 8,472          │
│                                              │
│  Tags: provider · model · team · developer  │
│                                              │
│  [View in Datadog ↗]  [Disconnect]         │
└─────────────────────────────────────────────┘
```

**Connect flow:**
1. Click "Connect Datadog"
2. Modal: select DD site (5 options), enter API key
3. POST `/v1/datadog/connect` → API key encrypted → stored
4. Cohrint pushes metrics to Datadog on each event batch

---

### OTel / Cross-Platform Card
```
┌─────────────────────────────────────────────┐
│  OpenTelemetry Collector        ● RECEIVING  │
│                                              │
│  Endpoint: api.cohrint.com/v1/otel/v1/logs  │
│  Events this month: 42,881                  │
│  Sources detected:                          │
│    Claude Code  ██████  31,420 events       │
│    Cursor       ████    8,240 events        │
│    Gemini CLI   ██      3,221 events        │
│                                              │
│  [Setup guide]  [View OTel events →]        │
└─────────────────────────────────────────────┘
```

**Source detection:** Infers source from OTel `service.name` attribute in incoming logs.

**Setup guide:** Shows copy-pasteable config for each tool (Claude Code, Cursor, Gemini CLI, etc.)

---

### Local Proxy Card
```
┌─────────────────────────────────────────────┐
│  Local Proxy Gateway            ○ NOT SET    │
│                                              │
│  Privacy mode: Standard (default)           │
│                                             │
│  Modes:                                     │
│  ○ Strict   — metadata only, no text       │
│  ● Standard — metadata + prompt hash       │
│  ○ Relaxed  — full text (for analysis)     │
│                                             │
│  [Change privacy mode]                      │
│  [Download local proxy →]                   │
└─────────────────────────────────────────────┘
```

**Privacy mode toggle:** `PATCH /v1/admin/settings` → `privacy_mode: 'strict'|'standard'|'relaxed'`

---

## Tab 6 — Settings (admin+ only)

### Organisation Settings
```
┌─────────────────────────────────────────────┐
│  Organisation                               │
│                                             │
│  Name:     Acme Corp          [Edit]        │
│  Plan:     Team               [Upgrade →]   │
│  Industry: Technology         [Edit]        │
│  Budget:   $5,000 / month     [Edit]        │
│                                             │
│  Benchmark opt-in:  ● Enabled  [Disable]    │
│  (Contribute to anonymised industry data)   │
└─────────────────────────────────────────────┘
```

### Semantic Cache Settings
```
┌─────────────────────────────────────────────┐
│  Semantic Cache Configuration               │
│                                             │
│  Status:        ● Enabled     [Disable]     │
│  Similarity:    0.92 ──●────── [0.85–0.99] │
│  Min length:    10 chars                    │
│  Max age:       30 days                     │
│                                             │
│  ℹ  Higher threshold = fewer hits,         │
│      less risk of wrong cached response.   │
│                                             │
│  [Save changes]                             │
└─────────────────────────────────────────────┘
```

**Threshold slider:** Live preview: "At 0.92, your current hit rate is 62%. At 0.85, estimated 74% (+12%, ~$380 more savings, small risk of inexact matches)."

### Team Budget Management
```
┌─────────────────────────────────────────────────────────┐
│  Team Budgets                          [Add team budget] │
├────────────────┬──────────────┬────────────────────────┤
│  Team          │  Budget/mo   │  Actions               │
├────────────────┼──────────────┼────────────────────────┤
│  backend       │  $1,000      │  [Edit] [Remove]       │
│  frontend      │  $1,000      │  [Edit] [Remove]       │
│  data-sci      │  $1,000      │  [Edit] [Remove]       │
│  devops        │  $1,000      │  [Edit] [Remove]       │
│  (org total)   │  $5,000      │  —                     │
└────────────────┴──────────────┴────────────────────────┘
```

### Alert Configuration
```
┌─────────────────────────────────────────────┐
│  Budget Alerts                              │
│                                             │
│  Slack webhook URL:                         │
│  https://hooks.slack.com/...  [Edit]        │
│                                             │
│  Alert thresholds:                          │
│  ☑  50% — "Halfway through budget"         │
│  ☑  75% — "75% budget used"                │
│  ☑  85% — "Budget warning"                 │
│  ☑ 100% — "Budget exhausted"               │
│  ☑  Anomaly alerts (Z-score > 3σ)          │
│                                             │
│  [Test alert]  [Save]                       │
└─────────────────────────────────────────────┘
```

### Member Management
```
┌───────────────────────────────────────────────────────────────┐
│  Team Members                              [Invite member +]   │
├──────────────────┬────────────┬────────────┬─────────────────┤
│  Email           │  Role      │  Team      │  Actions        │
├──────────────────┼────────────┼────────────┼─────────────────┤
│  alice@acme.com  │  admin     │  (all)     │  [Edit] [Remove]│
│  bob@acme.com    │  member    │  backend   │  [Edit] [Remove]│
│  carol@acme.com  │  member    │  frontend  │  [Edit] [Remove]│
│  dave@acme.com   │  viewer    │  (all)     │  [Edit] [Remove]│
│  cto@acme.com    │  ceo       │  (all)     │  [Edit] [Remove]│
└──────────────────┴────────────┴────────────┴─────────────────┘
```

**Invite flow:** Enter email + role + team → sends invite email via Resend → member receives link → sets password → gets scoped API key.

**Role constraints:** Admin cannot invite superadmin or owner roles.

**Scope team:** If set, member's API key only returns data for that team. NULL = sees all teams.

---

## Tab 7 — Audit Log (admin+ only)

```
┌─────────────────────────────────────────────────────────────────┐
│  Audit Log                    Filter: [All events ▼]  [Export] │
├────────────────┬──────────────┬────────────────────────────────┤
│  Timestamp     │  Actor       │  Action                        │
├────────────────┼──────────────┼────────────────────────────────┤
│ Apr 17 14:23   │ alice@acme   │ member_invited carol@acme.com  │
│ Apr 17 12:05   │ bob@acme     │ api_key_rotated (own key)      │
│ Apr 16 09:40   │ alice@acme   │ budget_updated $4000 → $5000   │
│ Apr 15 18:22   │ alice@acme   │ copilot_connected acme-corp    │
│ Apr 15 17:01   │ system       │ alert_fired 80% budget (Slack) │
│ Apr 14 10:33   │ alice@acme   │ cache_config_updated 0.88→0.92 │
└────────────────┴──────────────┴────────────────────────────────┘
```

**Data source:** `GET /v1/audit-log?limit=50&before=<timestamp>` — paginated, newest first.

**Infinite scroll:** "Load more" appends older entries using the `before` cursor.

**Export button:** Downloads filtered log as CSV (admin+ only).

**Immutability note:** Audit log is append-only. No admin can delete entries. This is shown in the UI: "This log is immutable and cannot be modified."

**Event types logged:**
- `member_invited` — actor, target email, role assigned
- `member_removed` — actor, target email
- `api_key_rotated` — actor, key hint (never full key)
- `budget_updated` — actor, old value, new value
- `role_changed` — actor, target, old role, new role
- `copilot_connected` / `copilot_disconnected` — actor, github_org
- `datadog_connected` / `datadog_disconnected` — actor, site
- `cache_config_updated` — actor, old/new threshold
- `alert_fired` — system, threshold, channel
- `auth_failed` — IP, reason (rate-limited to prevent log flooding)

---

## Tab 8 — Executive View (ceo+ only)

```
┌─────────────────────────────────────────────────────────────────┐
│  Executive Dashboard                         Last 30 days       │
│                                                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ Total AI Spend │  │ Cost per Dev   │  │  ROI Estimate  │   │
│  │   $18,420      │  │  $131/dev/mo   │  │   4.2× ROI     │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
│                                                                  │
│  Spend by Source                   Spend by Team                │
│  ┌──────────────────────────┐      ┌──────────────────────┐   │
│  │ LLM APIs      $12,840 70%│      │ backend    $7,200 39%│   │
│  │ Copilot        $2,660 14%│      │ data-sci   $5,400 29%│   │
│  │ Cursor (seats) $1,800 10%│      │ frontend   $3,600 20%│   │
│  │ Other          $1,120  6%│      │ devops     $2,220 12%│   │
│  └──────────────────────────┘      └──────────────────────┘   │
│                                                                  │
│  [Download Executive Report PDF]                                │
└─────────────────────────────────────────────────────────────────┘
```

**Data source:** `GET /v1/analytics/executive` → cross-source spend roll-up.

**Cost per Dev:** `total_spend / headcount` — requires org to have member count in settings.

**ROI Estimate:** Configurable formula: `(developers × avg_hourly_rate × hours_saved_per_dev) / total_ai_spend`. Default: 2h saved/dev/day × $75/hr × 22 working days.

**Download Report:** Generates PDF chargeback report per team (roadmap feature).

---

## Real-Time Indicator

```
┌──────────────────────────────────────────────┐
│  ● Live  3 connections   Last event: 14s ago  │
└──────────────────────────────────────────────┘
```

Shown in the header bar. Green dot pulses when SSE stream is receiving events. Shows count of active SSE connections across the org and timestamp of the most recent event.

**SSE flow:**
1. On load: `POST /v1/stream/:orgId` → returns SSE token (KV-stored, 120s TTL)
2. Dashboard opens SSE connection using token
3. Each new event triggers: KPI cards refresh, timeseries chart updates, streaming count increments

---

## Empty States

Each card has a defined empty state to avoid confusing blank UI:

| Card | Empty State Message |
|------|---------------------|
| Today's Cost | "No events today. Send your first event →" + link to docs |
| MTD Cost | "No events this month. Getting started guide →" |
| Cache Hit Rate | "Cache warming up. 0 lookups so far." |
| Quality Score | "No quality scores yet. Scores appear within minutes of events." |
| Traces | "No agent traces found. Add trace_id to your events →" |
| Models | "No model data yet. Events with model field will appear here." |
| Copilot | "Connect GitHub Copilot to see per-developer attribution →" |
| Audit Log | "No audit events. Admin actions will appear here automatically." |

---

## Loading States

All cards show a skeleton loader (gray animated placeholder) while data is fetching. The six `Promise.all()` fetches on load mean cards render simultaneously — no waterfall.

```javascript
// All 6 fetches fire in parallel
const [summary, kpis, timeseries, models, teams, cacheStats] =
  await Promise.all([
    apiFetch('/v1/analytics/summary'),
    apiFetch('/v1/analytics/kpis?period=30'),
    apiFetch('/v1/analytics/timeseries?period=30'),
    apiFetch('/v1/analytics/models?period=30'),
    apiFetch('/v1/analytics/teams?period=30'),
    apiFetch('/v1/cache/stats'),
  ])
```

---

## Error States

If an API call fails (401, 429, 5xx), the affected card shows:

```
┌─────────────────────────┐
│  ⚠  Failed to load      │
│  [Retry]                │
└─────────────────────────┘
```

- 401: Redirects to login page
- 429: Shows "Rate limited — retrying in 60s" with countdown
- 5xx: Shows "API error — [Retry]" button
- Network error: Shows "Check connection — [Retry]"
