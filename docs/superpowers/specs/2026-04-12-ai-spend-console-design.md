# AI Spend Console — Design Spec

**Goal:** Add a "Cross-Platform" tab to the Dashboard showing consolidated Copilot + Claude Code + Cursor + Gemini CLI spend with per-developer attribution, real-time feed, and a local test runner script.

**Architecture:** New Dashboard tab in `app.html` wired to existing `/v1/cross-platform/*` routes plus one new `/v1/cross-platform/trend` endpoint for the stacked daily chart. Live feed polls every 15s. Developer row opens a full-detail modal.

**Tech Stack:** Cloudflare Workers (Hono) + D1 SQLite, Chart.js, vanilla JS, Python pytest.

---

## 1. Backend — New Endpoint

**File:** `vantage-worker/src/routes/cross-platform.ts`

### `GET /v1/cross-platform/trend?days=N` (default 30)

Auth-gated (same middleware as all cross-platform routes). Query param `days` accepts 7, 30, or 90.

**SQL:**
```sql
SELECT DATE(period_start) AS day,
       provider,
       SUM(cost_usd) AS cost
FROM cross_platform_usage
WHERE org_id = ?
  AND period_start >= ?
GROUP BY day, provider
ORDER BY day ASC
```

Where `?` for period uses `sqliteDateSince(days)` (existing helper).

**Response shape:**
```json
{
  "period_days": 30,
  "days": ["2026-03-14", "2026-03-15", "..."],
  "providers": ["claude_code", "copilot_chat", "cursor", "gemini_cli"],
  "series": [
    { "provider": "claude_code", "data": [0.12, 0.34, 0.0, "..."] }
  ]
}
```

- `days` — sorted array of all calendar days in window that have data
- `providers` — deduplicated sorted list of providers seen in window
- `series` — one entry per provider; `data` array aligns 1:1 with `days`; missing days fill with `0`

**Registration:** Add route in `vantage-worker/src/index.ts` alongside existing `app.route('/v1/cross-platform', crossPlatformRouter)` (no change to router mount — add handler inside `cross-platform.ts`).

---

## 2. Frontend — Cross-Platform Tab

**File:** `vantage-final-v4/app.html`

### 2a. Nav

Add `cross-platform` to the Dashboard tab strip, after "Spend Analysis":
```html
<button class="tab-btn" data-tab="cross-platform" data-section="dashboard">Cross-Platform</button>
```

Add corresponding section div:
```html
<div id="section-cross-platform" class="tab-section" style="display:none">
  <!-- content below -->
</div>
```

### 2b. Section layout (top → bottom)

1. **Period selector** — `7d / 30d / 90d` buttons; active state styled; default `30`. Changing period calls `loadCrossplatform(period)`.
2. **KPI row** — 4 cards using `summary` response: Total Spend, Top Tool (name + share %), Active Developers, MTD Budget % (with colour: green <50%, orange 50–85%, red >85%).
3. **Charts row** — two side-by-side cards:
   - Left: stacked area chart (Chart.js) from `trend` response; one dataset per provider, colours: claude_code=#6366f1, copilot_chat=#06b6d4, cursor=#f59e0b, gemini_cli=#10b981, others=#8b5cf6.
   - Right: doughnut chart (Chart.js) from `summary.by_provider`; same colour map.
4. **Developer attribution table** — from `developers` response; columns: Developer (email), Tools (badge list), Spend, Commits, $/commit; sortable by Spend descending by default; click row → developer modal.
5. **Bottom row** — two side-by-side cards:
   - Left: Live feed — list of recent events from `live` response (provider, model, cost, timestamp); refreshes every 15s via `setInterval`; interval cleared when tab is switched away.
   - Right: Connected tools — from `connections` response; each row shows provider name, status dot (green=live, orange=warning, red=error, grey=not connected), last sync time; grey rows show "+ connect" link pointing to `#section-integrations`.

### 2c. Data loading

Function `loadCrossplatform(period)`:
- Fires 4 parallel `apiFetch` calls: `summary?days=period`, `developers?days=period`, `trend?days=period`, `connections`
- On success, renders each section independently (partial failures show inline error state per card, not full-page error)
- `connections` is only fetched once on first tab activation (not re-fetched on period change)

Live polling:
```js
let cpLiveInterval = null;

function startCpLivePoll() {
  stopCpLivePoll();
  cpLiveInterval = setInterval(() => {
    apiFetch('/v1/cross-platform/live?limit=20').then(renderCpLiveFeed);
  }, 15000);
}

function stopCpLivePoll() {
  if (cpLiveInterval) { clearInterval(cpLiveInterval); cpLiveInterval = null; }
}
```

Called on tab activation; `stopCpLivePoll()` called when switching away.

### 2d. Developer detail modal

Triggered by clicking any row in the developer table. Calls `/v1/cross-platform/developer/:email`.

Modal structure (3 sub-sections):
1. **By-tool cost table** — provider, cost, input tokens, output tokens
2. **Daily trend mini-chart** — line chart (Chart.js) from `daily_trend[]`; 280px tall
3. **Productivity stats** — commits, pull requests, lines added/removed, active time; displayed as a stat grid

Modal reuses existing modal infrastructure in `app.html` (same overlay + close pattern as invite/budget modals).

---

## 3. Test Runner Script

**File:** `scripts/run-tests.sh`

A bash script wrapping `python -m pytest` with ergonomic parameters for running specific suites or all tests.

### Usage

```bash
# Run all test suites
scripts/run-tests.sh

# Run a specific suite by name or number
scripts/run-tests.sh --suite 35_cross_platform_console
scripts/run-tests.sh --suite 35

# Run a specific test file within a suite
scripts/run-tests.sh --suite 35 --file test_trend

# Run a specific test function
scripts/run-tests.sh --suite 35 --file test_trend --test test_trend_7d_window

# Run multiple suites
scripts/run-tests.sh --suite 17_otel --suite 35_cross_platform_console

# Pass extra pytest flags (e.g. verbose, stop on first failure)
scripts/run-tests.sh --suite 35 -- -v -x
```

### Behaviour

- `--suite <name>` accepts partial match: `35` matches `35_cross_platform_console`; `otel` matches `17_otel`
- No `--suite` flag → runs the full active suite list from CLAUDE.md (suites 17–21, 32–35)
- `--file <name>` narrows to a single `.py` file within the matched suite (no `.py` extension needed)
- `--test <name>` maps to pytest `-k <name>`
- Arguments after `--` are passed through verbatim to pytest
- Prints the resolved `pytest` command before running it (so developers can see exactly what's executing)
- Exits with pytest's exit code (0 = pass, non-zero = fail)

---

## 4. Test Suite

**Directory:** `tests/suites/35_cross_platform_console/`

**Files:**
- `conftest.py` — reuses base_url, auth_headers fixtures from parent conftest; adds `trend_endpoint` fixture
- `test_trend.py` — 12 tests:
  - Response shape: `days`, `providers`, `series` keys present
  - `series[].data` length matches `days` length
  - Zero-fill: days with no data appear as `0.0` not missing
  - 7d, 30d, 90d windows return correct number of days
  - Unknown provider not in response
  - Auth required (401 without token)
  - Invalid `days` param returns 400
  - `period_days` in response matches requested param
- `test_console_frontend.py` — 10 contract tests:
  - `GET /v1/cross-platform/summary` returns `by_provider[]`, `total_cost_usd`, `budget`
  - `GET /v1/cross-platform/developers` returns `developers[]` with `by_provider[]` per entry
  - `GET /v1/cross-platform/developer/:email` returns `by_provider[]`, `daily_trend[]`, `productivity`
  - `GET /v1/cross-platform/live` returns `events[]` with `provider`, `model`, `cost_usd`, `timestamp`
  - `GET /v1/cross-platform/connections` returns `billing_connections[]`, `otel_sources[]`
  - All routes return 401 without auth

---

## 5. Out of Scope (v2)

- Server-sent events / WebSocket for live feed (polling is sufficient for MVP)
- Export to CSV
- Budget alert thresholds set from within the console tab (use existing Budgets & Alerts tab)
- Team-level grouping in developer table
