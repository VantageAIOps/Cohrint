# AI Spend Console — Design Spec

**Goal:** Add a "Cross-Platform" tab to the Dashboard showing consolidated Copilot + Claude Code + Cursor + Gemini CLI spend with per-developer attribution, real-time feed, and a local test runner script.

**Architecture:** New Dashboard tab in `app.html` wired to existing `/v1/cross-platform/*` routes plus one new `/v1/cross-platform/trend` endpoint for the stacked daily chart. Cross-platform JS extracted to `cp-console.js` to keep `app.html` manageable. Live feed polls every 15s with jitter and backoff. Developer row opens a full-detail modal routed by internal `developer_id`.

**Tech Stack:** Cloudflare Workers (Hono) + D1 SQLite, Chart.js, vanilla JS, Python pytest.

---

## 1. Backend — New Endpoint + Validation Backfill

**File:** `vantage-worker/src/routes/crossplatform.ts`

### 1a. `GET /v1/cross-platform/trend?days=N`

Auth-gated (same middleware as all cross-platform routes).

**Parameter validation** — applied here and backfilled to all existing `?days=` routes in the same file:
```ts
const ALLOWED_DAYS = new Set([7, 30, 90]);
const rawDays = parseInt(c.req.query('days') ?? '30', 10);
if (!ALLOWED_DAYS.has(rawDays)) return c.json({ error: 'days must be 7, 30, or 90' }, 400);
const days = rawDays;
```

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

**Full calendar spine (not just days with data):** The handler generates all N calendar dates from today going back `days` days, then merges SQL results into that spine. Days with no data for a provider are filled with `0.0`. This ensures Chart.js always receives a continuous x-axis.

```ts
// Build full date spine
const spine: string[] = [];
for (let i = days - 1; i >= 0; i--) {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - i);
  spine.push(d.toISOString().slice(0, 10));
}

// Merge SQL rows into spine per provider
const providerSet = new Set(rows.map(r => r.provider));
const series = [...providerSet].sort().map(provider => ({
  provider,
  data: spine.map(day => {
    const row = rows.find(r => r.provider === provider && r.day === day);
    return row ? Number(row.cost) : 0.0;
  }),
}));
```

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

**Registration:** Add handler inside `crossplatform.ts` router — no change to `index.ts` mount.

### 1b. `GET /v1/cross-platform/developer/:id`

The existing `/developer/:email` endpoint is replaced by `/developer/:id` (internal `developer_id` UUID from `cross_platform_usage.developer_id`). This removes email from URL paths (browser history, logs, localStorage cache keys).

**Email validation removed** (no longer in path). Validate `id` is a UUID format:
```ts
const id = c.req.param('id');
if (!/^[0-9a-f-]{36}$/.test(id)) return c.json({ error: 'Invalid id' }, 400);
```

**Role check** — restrict to `owner` or `admin` role only (or allow members to query their own `developer_id`):
```ts
const member = c.get('member');
if (member.role !== 'owner' && member.role !== 'admin' && member.developer_id !== id) {
  return c.json({ error: 'Forbidden' }, 403);
}
```

### 1c. `GET /v1/cross-platform/live` — email redaction

For non-admin roles, redact `developer_email` in the live feed:
```ts
const isAdmin = member.role === 'owner' || member.role === 'admin';
events = events.map(e => ({
  ...e,
  developer_email: isAdmin ? e.developer_email : redactEmail(e.developer_email),
}));

function redactEmail(email: string): string {
  const [local, domain] = email.split('@');
  return local[0] + '***@' + domain;
}
```

---

## 2. Frontend — Cross-Platform Tab

**Files:**
- `vantage-final-v4/app.html` — nav tab + section shell + script tag
- `vantage-final-v4/cp-console.js` — all cross-platform JS (new file)

Extracting to `cp-console.js` keeps `app.html` from growing past ~3400 lines and sets a pattern for future tabs.

### 2a. app.html changes

**Nav tab** (after Spend Analysis tab):
```html
<button class="tab-btn" data-tab="cross-platform" data-section="dashboard">Cross-Platform</button>
```

**Section shell** (after spend-analysis section div):
```html
<div id="section-cross-platform" class="tab-section" style="display:none">
  <!-- period selector -->
  <div id="cp-period-bar" class="period-bar">
    <button class="period-btn active" data-days="7">7d</button>
    <button class="period-btn" data-days="30">30d</button>
    <button class="period-btn" data-days="90">90d</button>
  </div>
  <!-- KPI cards -->
  <div id="cp-kpis" class="kpi-grid"></div>
  <!-- charts row -->
  <div class="chart-row">
    <div class="card"><div class="card-title">Daily Spend by Tool</div><canvas id="cp-trend-canvas"></canvas><div id="cp-trend-error" class="card-error" style="display:none"></div></div>
    <div class="card"><div class="card-title">Tool Cost Share</div><canvas id="cp-donut-canvas"></canvas><div id="cp-donut-error" class="card-error" style="display:none"></div></div>
  </div>
  <!-- developer table -->
  <div class="card" id="cp-dev-card">
    <div class="card-title">Per-Developer Attribution</div>
    <div id="cp-dev-table"></div>
    <div id="cp-dev-error" class="card-error" style="display:none"></div>
  </div>
  <!-- bottom row -->
  <div class="chart-row">
    <div class="card"><div class="card-title">Live Feed <span id="cp-live-dot" class="live-dot">●</span></div><div id="cp-live-feed"></div></div>
    <div class="card"><div class="card-title">Connected Tools</div><div id="cp-connections"></div></div>
  </div>
</div>
```

**CSS additions** (in `<style>` block):
```css
.card-error { color: #f87171; font-size: 12px; padding: 8px 0; }
```

**Script tag** (before closing `</body>`):
```html
<script src="/cp-console.js" defer></script>
```

### 2b. cp-console.js structure

```js
(function () {
  'use strict';

  // Chart instances — must be destroyed before re-creating
  let cpTrendChart = null;
  let cpDoughnutChart = null;
  let cpDevChart = null;  // developer modal mini-chart

  // Live poll state
  let cpLiveInterval = null;
  let cpLiveErrors = 0;
  let cpLivePaused = false;

  // Connections loaded flag — reset on every tab activation
  // (re-fetch is cheap; avoids stale state after Settings changes)

  // Period — persisted to localStorage
  const PERIOD_KEY = 'vantage_cp_period';
  function getSavedPeriod() { return parseInt(localStorage.getItem(PERIOD_KEY) || '30', 10); }
  function savePeriod(d) { localStorage.setItem(PERIOD_KEY, String(d)); }

  // Provider colour map
  const PROVIDER_COLORS = {
    claude_code: '#6366f1',
    copilot_chat: '#06b6d4',
    cursor: '#f59e0b',
    gemini_cli: '#10b981',
  };
  function providerColor(p) { return PROVIDER_COLORS[p] || '#8b5cf6'; }

  // ... renderCpKpis, renderCpTrend, renderCpDonut, renderCpDevTable,
  //     renderCpLiveFeed, renderCpConnections, openDevModal defined below
})();
```

### 2c. Data loading

`loadCrossplatform(period)` fires on tab activation and on period button click:
- 4 parallel `apiFetch` calls: `summary?days=period`, `developers?days=period`, `trend?days=period`, `live?limit=20`
- `connections` fetched on every tab activation (cheap query, avoids stale state)
- Each section renders independently; failures call `renderCardError(el, msg)` per card (not full-page error)
- `renderCardError(el, msg)`: sets `el.style.display = 'block'` and `el.textContent = '⚠ ' + msg`

### 2d. Chart.js stacked area (trend chart)

```js
function renderCpTrend(data) {
  if (cpTrendChart) { cpTrendChart.destroy(); cpTrendChart = null; }
  const ctx = document.getElementById('cp-trend-canvas').getContext('2d');
  cpTrendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.days,
      datasets: data.series.map(s => ({
        label: s.provider,
        data: s.data,
        borderColor: providerColor(s.provider),
        backgroundColor: providerColor(s.provider) + '33',
        fill: true,
        tension: 0.3,
      })),
    },
    options: {
      scales: {
        y: { stacked: true, beginAtZero: true },
        x: { ticks: { maxTicksLimit: 8 } },
      },
      plugins: { legend: { position: 'bottom' } },
      responsive: true,
    },
  });
}
```

Doughnut chart similarly destroys `cpDoughnutChart` before re-creating.

### 2e. Live feed polling

```js
function startCpLivePoll() {
  stopCpLivePoll();
  cpLiveErrors = 0;
  cpLivePaused = false;
  const jitter = Math.random() * 10000 - 5000; // ±5s
  function tick() {
    apiFetch('/v1/cross-platform/live?limit=20')
      .then(data => {
        cpLiveErrors = 0;
        renderCpLiveFeed(data);
      })
      .catch(() => {
        cpLiveErrors++;
        if (cpLiveErrors >= 3) {
          stopCpLivePoll();
          cpLivePaused = true;
          setTimeout(startCpLivePoll, 120000); // retry after 2 min
        }
      });
  }
  cpLiveInterval = setInterval(tick, 15000 + jitter);
}

function stopCpLivePoll() {
  if (cpLiveInterval) { clearInterval(cpLiveInterval); cpLiveInterval = null; }
}
```

`renderCpLiveFeed(data)` renders each event as a row: `provider | model | cost | timestamp`. If `data.is_stale === true`, shows a `⚠ stale` badge next to the Live dot.

### 2f. Developer detail modal

Developer table rows store `data-dev-id` (from `developers[].developer_id`) and `data-dev-email` attributes. Click calls `/v1/cross-platform/developer/:id`.

Modal 3 sub-sections:
1. **By-tool cost table** — provider, cost, input tokens, output tokens
2. **Daily trend mini-chart** — `type: 'line'` Chart.js, 200px height; destroys `cpDevChart` before re-creating
3. **Productivity stats** — commits, PRs, lines added/removed, active time as stat grid

Modal reuses existing overlay (`#modal-overlay`) and close pattern from `app.html`.

### 2g. Period selector

Default period read from `localStorage.getItem('vantage_cp_period') || 30`. On button click, save to `localStorage` and call `loadCrossplatform(newPeriod)`. Active button styled with `active` class.

---

## 3. Test Runner Script

**File:** `scripts/run-tests.sh`

### Usage

```bash
scripts/run-tests.sh                                     # all active suites
scripts/run-tests.sh --suite 35                          # partial match
scripts/run-tests.sh --suite 35_cross_platform_console   # exact match
scripts/run-tests.sh --suite 35 --file test_trend        # single file
scripts/run-tests.sh --suite 35 --file test_trend --test test_trend_7d_window  # single test
scripts/run-tests.sh --suite 17 --suite 35               # multiple suites
scripts/run-tests.sh --suite 35 -- -v -x                 # extra pytest flags
```

### Behaviour

- **Input validation** — `--suite`, `--file`, `--test` values validated against `^[a-zA-Z0-9_-]+$` before use; invalid values print error and exit 1
- **Partial match** — `--suite 35` matches directories under `tests/suites/` whose name contains `35`; if >1 match found, script errors: `"Ambiguous --suite '35': matches 35_foo, 35_bar. Be more specific."`
- **No `--suite`** — runs all active suites: 17, 18, 19, 20, 21, 32, 33, 34, 35
- **`--file`** — appended as `tests/suites/<suite>/<file>.py`; `.py` suffix added automatically if absent
- **`--test`** — passed as `pytest -k <test>`
- **Extra args** — everything after `--` appended as a bash array (never bare string interpolation)
- **Prints resolved command** before running (developer transparency)
- **Exits** with pytest exit code

### Implementation skeleton

```bash
#!/usr/bin/env bash
set -euo pipefail

SUITES=() FILES=() TEST_NAME="" EXTRA_ARGS=()
ALL_ACTIVE_SUITES=(17_otel 18_sdk_privacy 19_local_proxy 20_dashboard_real_data
                   21_vantage_cli 32_audit_log 33_frontend_contract 34_vega_chatbot
                   35_cross_platform_console)

validate_arg() {
  [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "Invalid arg: $1"; exit 1; }
}

# ... argument parsing loop

# Resolve suite names with partial match + ambiguity check
# Build pytest command as array
CMD=(python -m pytest)
# ... append paths, -k, extra args
echo "Running: ${CMD[*]}"
"${CMD[@]}"
```

---

## 4. Test Suite

**Directory:** `tests/suites/35_cross_platform_console/`

**Files:**
- `conftest.py` — inherits `base_url`, `auth_headers`, `admin_headers` from parent conftest; adds `trend_url` fixture
- `test_trend.py` — 12 tests:
  - Response contains `days`, `providers`, `series` keys
  - `series[i].data` length equals `len(days)` for all entries
  - Zero-fill: days with no activity appear as `0.0` (not absent)
  - Full calendar spine: response includes all N calendar days, not just days with data
  - `period_days` in response matches requested param
  - `days=7`, `days=30`, `days=90` all accepted
  - `days=91` returns 400 with `error` field
  - `days=abc` returns 400
  - `days=0` returns 400
  - No auth returns 401
  - Empty org returns `series: []`, `days` still fully populated
  - Unknown provider values do not appear in response
- `test_console_frontend.py` — 10 contract tests:
  - `GET /v1/cross-platform/summary` returns `by_provider[]`, `total_cost_usd`, `budget`
  - `GET /v1/cross-platform/developers` returns `developers[]` with `developer_id`, `by_provider[]` per entry
  - `GET /v1/cross-platform/developer/:id` returns `by_provider[]`, `daily_trend[]`, `productivity`; requires admin or self
  - `GET /v1/cross-platform/developer/:id` returns 403 for non-admin querying other user
  - `GET /v1/cross-platform/live` returns `events[]` with `provider`, `model`, `cost_usd`, `timestamp`, `is_stale`
  - `GET /v1/cross-platform/live` redacts `developer_email` for non-admin (`a***@...` format)
  - `GET /v1/cross-platform/connections` returns `billing_connections[]`, `otel_sources[]`
  - All routes return 401 without auth
  - `days=999` on any `?days=` route returns 400

---

## 5. Out of Scope (v2)

- Server-sent events / WebSocket for live feed (polling is sufficient for MVP)
- Export to CSV
- Budget alert thresholds set from within the console tab
- Team-level grouping in developer table
- Backfilling `developer_id` on historical rows that only have `developer_email`
