# Dashboard Redesign — Tool-Centric AI Coding Cost Intelligence

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current monolithic 14-view dashboard with a focused 7-view tool-centric dashboard. Agent tabs (Claude, Copilot, Cursor, Gemini) filter all data. Zero fake data. All API integrations preserved.

**Architecture:** Single-file `app.html` rewrite (no build step, Cloudflare Pages direct deploy). Same API endpoints, same auth flow (session cookie). New sidebar (7 items), tool tabs on overview, per-tool filtered views. Chart.js for charts. Dark theme with JetBrains Mono for data.

**Tech Stack:** HTML/CSS/JS (no framework), Chart.js 4.4.1, Cloudflare Pages

---

## Scope

**Views to build (7):**
1. **Overview** — tool tabs, KPIs, stacked spend chart, developer bars, tool comparison table, live feed
2. **Spend Analysis** — daily trend, cost by model, cost by team, budget status
3. **Model Pricing** — existing model comparison calculator (port as-is, already working)
4. **Members** — existing team members CRUD (port as-is, already working)
5. **Budgets & Alerts** — team budgets + Slack webhook config
6. **Settings** — API key, org config, theme toggle
7. **API Keys / Account** — profile, key rotation, plan info

**Views to remove (moved to P2-P3):**
- Quality & Evaluation, Agent Traces, AI Intelligence Layer, Performance & Latency, Token Optimizer, Developer Experience, Enterprise Reporting, Security & Governance, Token Analytics

**Critical API endpoints used:**
- `GET /v1/auth/session` — session + org info
- `GET /v1/cross-platform/summary?days=N` — KPIs, by_provider, budget
- `GET /v1/cross-platform/developers?days=N` — per-dev cost + providers
- `GET /v1/cross-platform/models?days=N` — per-model cost
- `GET /v1/cross-platform/live?limit=30` — live event feed
- `GET /v1/cross-platform/connections` — connected tools status
- `GET /v1/analytics/kpis?period=N` — aggregated stats
- `GET /v1/analytics/timeseries?period=N` — daily cost series
- `GET /v1/analytics/models?period=N` — model breakdown
- `GET /v1/analytics/teams?period=N` — team breakdown
- `GET /v1/admin/overview?period=N` — org overview (teams, members, budgets)
- `GET /v1/admin/team-budgets` — team budget list
- `PUT /v1/admin/team-budgets/:team` — set budget
- `GET /v1/auth/members` — member list
- `POST /v1/auth/members` — invite member
- `DELETE /v1/auth/members/:id` — revoke
- `POST /v1/auth/rotate` — rotate owner key
- `GET /v1/alerts/:orgId` — alert config
- `POST /v1/alerts/slack/:orgId` — save slack webhook
- `GET /v1/stream/:orgId?sse_token=X` — SSE live stream

**Test selectors to preserve (for backward compat where possible):**
- `#sidebar`, `.sidebar` — sidebar container
- `.kpi-grid`, `.kpi-card` — KPI elements
- `#main`, `.main` — main content area
- `button.sb-item` — sidebar buttons
- `#inp-key`, `#signin-btn` — auth page (unchanged)
- `canvas` elements for Chart.js
- `#theme-toggle` — theme toggle

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `vantage-final-v4/app.html` | Rewrite | Complete dashboard (HTML + CSS + JS in one file) |
| `tests/suites/20_dashboard_real_data/test_dashboard_real_data.py` | Rewrite | Updated checks for new views |
| `tests/suites/02_ui/test_dashboard_ui.py` | Update | New sidebar selectors, new view names |
| `tests/suites/02_ui/test_navigation.py` | Update | New sidebar nav items |
| `tests/suites/13_dashboard/test_dashboard_reliance.py` | Update | New sidebar text selectors |
| `tests/suites/15_cross_browser/test_visual_consistency.py` | Update | New element selectors |

---

## Task Decomposition

This is a single large file (app.html) that must be built incrementally. Each task adds a working section. The file compiles and runs after each task.

### Task 1: Skeleton — Layout, Sidebar, Auth, Theme

Build the app.html shell: `<head>`, CSS variables, sidebar (7 items), topbar, auth flow (session cookie login), theme toggle (dark/light), empty view containers.

**This task produces a working app** that authenticates, shows the sidebar, and switches between empty views.

### Task 2: Overview — KPIs + Tool Tabs

Wire the Overview view: tool tabs (All, per-provider), KPI cards (Total Spend, Costliest Tool, Active Devs, Budget). Fetch from `/v1/cross-platform/summary` and `/v1/analytics/kpis`. Filter KPIs by selected tool tab.

### Task 3: Overview — Stacked Spend Chart + Developer Bars

Add the stacked daily spend chart (Chart.js, data from `/v1/analytics/timeseries`) and per-developer cost bars (from `/v1/cross-platform/developers`). Both filter by tool tab.

### Task 4: Overview — Tool Comparison Table + Live Feed

Add the tool comparison table (from `/v1/cross-platform/summary` by_provider) and scrolling live event feed (from `/v1/cross-platform/live` + SSE stream). Table rows click to switch tool tab.

### Task 5: Spend Analysis View

Daily spend trend line chart, cost by model table, cost by team pie chart, budget status bar. All from existing analytics endpoints. Period selector (7d/30d/90d).

### Task 6: Model Pricing View

Port the existing model comparison calculator. This view is already fully working — copy the HTML structure, the PRICES data, the calculator logic. Minimal changes.

### Task 7: Members View

Port existing team members CRUD: member table, invite modal, key rotation, delete. Uses `/v1/auth/members` endpoints. Minimal changes from current.

### Task 8: Budgets & Alerts View

Team budgets table (add/edit/delete), org budget setting, Slack webhook config + test button. Uses `/v1/admin/team-budgets` and `/v1/alerts/slack` endpoints.

### Task 9: Settings & Account View

API key display/rotate, org ID, theme toggle, base URL config. Account profile (name, email, plan, usage). Session management (sign out).

### Task 10: Connected Tools Sidebar Widget + Polish

Add the "Connected Tools" widget at bottom of sidebar (from `/v1/cross-platform/connections`). Add keyboard shortcut hints, responsive mobile layout, loading states, error states, empty states.

### Task 11: Update Test Suites

Update all 6 test files to match new selectors, new sidebar items, new view names. Verify all checks pass. Add new checks for tool tabs.

### Task 12: Final Verification

Build, deploy preview, run all test suites, verify no fake data, verify all API integrations work.

---

## Implementation Notes

**Auth flow (preserve exactly):**
```javascript
// 1. Check for API key in URL params or localStorage
// 2. POST /v1/auth/session with api_key → get session cookie
// 3. GET /v1/auth/session → get org info, role, sse_token
// 4. All subsequent fetches use credentials: 'include'
```

**Tool tab filtering:**
The cross-platform endpoints return `by_provider` arrays. When a tool tab is selected, filter the data client-side by matching `provider` field. Provider names from API: `anthropic` (Claude), `openai` (Copilot/ChatGPT), `google` (Gemini), `cursor`, `windsurf`, etc.

**No fake data rule:**
- All KPI values come from API responses
- Empty states show "No data yet" messages, never placeholder numbers
- The demo/seed data toggle is removed entirely
- Charts show empty state if no data

**CSS architecture:**
- CSS variables for theming (dark + light)
- JetBrains Mono for data, DM Sans for UI text
- Mobile responsive (sidebar collapses)
- Smooth transitions on view/tab switches
