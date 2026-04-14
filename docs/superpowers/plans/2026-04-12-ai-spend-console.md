# AI Spend Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Cross-Platform" Dashboard tab showing consolidated AI tool spend with per-developer attribution, real-time live feed, and a local test runner script.

**Architecture:** One new backend endpoint (`/trend`) plus targeted changes to existing routes in `crossplatform.ts`. Frontend extracted into a new `cp-console.js` file to avoid bloating `app.html`. All data flows through existing `apiFetch` exposed as `window.apiFetch`. Tests hit the live API — no mocking.

**Tech Stack:** Cloudflare Workers (Hono) + D1 SQLite, Chart.js 4.4.1, vanilla JS (ES5-compatible IIFE), Python 3.11 pytest, bash.

---

## File Map

| Action | File | What changes |
|--------|------|--------------|
| Modify | `vantage-worker/src/routes/crossplatform.ts` | Add `validateDays()` + `redactEmail()`; add `/trend`; update `/developers`; replace `/developer/:email` with `/developer/:id`; add email redaction to `/live` |
| Modify | `vantage-final-v4/app.html` | Expose `window.apiFetch`; add nav tab; add section shell + modal HTML; add `.card-error` CSS; add `<script src="/cp-console.js">` |
| Create | `vantage-final-v4/cp-console.js` | All cross-platform tab JS |
| Create | `tests/suites/35_cross_platform_console/conftest.py` | Seeded account fixture |
| Create | `tests/suites/35_cross_platform_console/test_trend.py` | 12 tests for `/trend` |
| Create | `tests/suites/35_cross_platform_console/test_console_frontend.py` | 10 contract tests |
| Create | `scripts/run-tests.sh` | Local test runner with partial match + validation |

**HTML rendering convention:** `cp-console.js` builds DOM strings using an `esc()` function that escapes `& < > "` before any value is inserted into HTML. All user-sourced data (emails, provider names, model names) must go through `esc()`. This is the same pattern used throughout `app.html`.

---

## Task 1: Backend — `days` Validation + `/trend` Endpoint

**Files:**
- Modify: `vantage-worker/src/routes/crossplatform.ts`

### Steps

- [ ] **Step 1: Run typecheck to establish a clean baseline**

```bash
cd vantage-worker && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 2: Add `validateDays` and `redactEmail` helpers after `sqliteMonthStart` (after line 45)**

```typescript
const ALLOWED_DAYS = new Set([7, 30, 90]);

/**
 * Returns parsed days if valid (7, 30, or 90).
 * Throws a non-number sentinel so callers can return 400.
 */
function validateDays(raw: string | undefined): number {
  const n = parseInt(raw ?? '30', 10);
  if (!ALLOWED_DAYS.has(n)) throw new Error('invalid_days');
  return n;
}

/** Redacts `user@domain.com` to `u***@domain.com` for non-admin roles. */
function redactEmail(email: string | null): string | null {
  if (!email) return null;
  const at = email.indexOf('@');
  if (at < 1) return '***';
  return email[0] + '***' + email.slice(at);
}
```

- [ ] **Step 3: Add `/trend` handler — insert before the `/summary` route (before `// ── GET /summary`)**

```typescript
// ── GET /trend — daily cost per provider for stacked area chart ───────────

crossplatform.get('/trend', async (c) => {
  const orgId = c.get('orgId');
  let days: number;
  try {
    days = validateDays(c.req.query('days'));
  } catch {
    return c.json({ error: 'days must be 7, 30, or 90' }, 400);
  }
  const since = sqliteDateSince(days);

  const rows = await c.env.DB.prepare(`
    SELECT DATE(period_start) AS day,
           provider,
           COALESCE(SUM(cost_usd), 0) AS cost
    FROM cross_platform_usage
    WHERE org_id = ? AND period_start >= ?
    GROUP BY DATE(period_start), provider
    ORDER BY day ASC
  `).bind(orgId, since).all<{ day: string; provider: string; cost: number }>();

  // Build the full N-day calendar spine regardless of whether every day has
  // data. This ensures Chart.js always receives a continuous x-axis.
  const spine: string[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - i);
    spine.push(d.toISOString().slice(0, 10));
  }

  const data = rows.results ?? [];
  const providerSet = new Set(data.map(r => r.provider));
  const providers = [...providerSet].sort();

  const series = providers.map(provider => ({
    provider,
    data: spine.map(day => {
      const row = data.find(r => r.provider === provider && r.day === day);
      return row ? Number(row.cost) : 0.0;
    }),
  }));

  return c.json({ period_days: days, days: spine, providers, series });
});
```

- [ ] **Step 4: Run typecheck — must pass**

```bash
cd vantage-worker && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add vantage-worker/src/routes/crossplatform.ts
git commit -m "feat(api): add /v1/cross-platform/trend with full calendar spine"
```

---

## Task 2: Backend — `/developers` + `/developer/:id` Migration

**Files:**
- Modify: `vantage-worker/src/routes/crossplatform.ts`

### Steps

- [ ] **Step 1: Backfill `validateDays` to `/summary`, `/developers`, `/models`**

In each of these three handlers, replace the unsafe days line:
```typescript
// BEFORE (appears in /summary ~line 51, /developers ~line 148, /models ~line 310):
const days = parseInt(c.req.query('days') ?? '30', 10) || 30;

// AFTER (identical replacement for all three):
let days: number;
try {
  days = validateDays(c.req.query('days'));
} catch {
  return c.json({ error: 'days must be 7, 30, or 90' }, 400);
}
```

- [ ] **Step 2: Update `/developers` query — add `developer_id`, filter NULLs**

Replace the SQL inside `/developers` handler (lines 151–169):

```typescript
  const developers = await c.env.DB.prepare(`
    SELECT
      developer_id,
      developer_email,
      COALESCE(SUM(cost_usd), 0)       AS total_cost,
      COALESCE(SUM(input_tokens), 0)    AS input_tokens,
      COALESCE(SUM(output_tokens), 0)   AS output_tokens,
      COALESCE(SUM(commits), 0)         AS commits,
      COALESCE(SUM(pull_requests), 0)   AS pull_requests,
      COALESCE(SUM(lines_added), 0)     AS lines_added,
      COALESCE(SUM(lines_removed), 0)   AS lines_removed,
      COALESCE(SUM(active_time_s), 0)   AS active_time_s,
      COUNT(DISTINCT provider)          AS providers_used,
      GROUP_CONCAT(DISTINCT provider)   AS providers,
      COUNT(*)                          AS records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
      AND developer_email IS NOT NULL
      AND developer_id IS NOT NULL
    GROUP BY developer_id, developer_email
    ORDER BY total_cost DESC
  `).bind(orgId, since).all();
```

Also update the `byProviderRows` query to group by `developer_id` as well:
```typescript
    GROUP BY developer_id, developer_email, provider
    ORDER BY developer_email, cost DESC
```

`developer_id` propagates automatically via the spread `...d` in `devList.map`.

- [ ] **Step 3: Replace `/developer/:email` handler entirely**

Delete lines 207–265 (`// ── GET /developer/:email` through the closing `});`) and replace with:

```typescript
// ── GET /developer/:id — single developer drill-down (admin/owner only) ──────

crossplatform.get('/developer/:id', async (c) => {
  const orgId = c.get('orgId');
  const role   = c.get('role');

  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Forbidden' }, 403);
  }

  const id = c.req.param('id');
  // UUID v4 format: 8-4-4-4-12 hex chars
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)) {
    return c.json({ error: 'Invalid id' }, 400);
  }

  let days: number;
  try {
    days = validateDays(c.req.query('days'));
  } catch {
    return c.json({ error: 'days must be 7, 30, or 90' }, 400);
  }
  const since = sqliteDateSince(days);

  const byProvider = await c.env.DB.prepare(`
    SELECT provider,
      COALESCE(SUM(cost_usd), 0)       AS cost,
      COALESCE(SUM(input_tokens), 0)   AS input_tokens,
      COALESCE(SUM(output_tokens), 0)  AS output_tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_id = ? AND created_at >= ?
    GROUP BY provider ORDER BY cost DESC
  `).bind(orgId, id, since).all();

  const byModel = await c.env.DB.prepare(`
    SELECT model,
      COALESCE(SUM(cost_usd), 0)                    AS cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_id = ? AND created_at >= ? AND model IS NOT NULL
    GROUP BY model ORDER BY cost DESC LIMIT 10
  `).bind(orgId, id, since).all();

  const daily = await c.env.DB.prepare(`
    SELECT DATE(created_at) AS day,
      COALESCE(SUM(cost_usd), 0)                    AS cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_id = ? AND created_at >= ?
    GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 30
  `).bind(orgId, id, since).all();

  const productivity = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(commits), 0)       AS commits,
      COALESCE(SUM(pull_requests), 0) AS pull_requests,
      COALESCE(SUM(lines_added), 0)   AS lines_added,
      COALESCE(SUM(lines_removed), 0) AS lines_removed,
      COALESCE(SUM(active_time_s), 0) AS active_time_s
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_id = ? AND created_at >= ?
  `).bind(orgId, id, since).first();

  // Fetch email for display — not stored in the URL
  const meta = await c.env.DB.prepare(`
    SELECT developer_email FROM cross_platform_usage
    WHERE org_id = ? AND developer_id = ? LIMIT 1
  `).bind(orgId, id).first<{ developer_email: string }>();

  return c.json({
    developer_id:    id,
    developer_email: meta?.developer_email ?? null,
    period_days:     days,
    by_provider:     byProvider.results,
    by_model:        byModel.results,
    daily_trend:     daily.results,
    productivity,
  });
});
```

- [ ] **Step 4: Update the file header comment (lines 10)**

Change:
```
 *   GET /v1/cross-platform/developer/:email — single developer drill-down
```
to:
```
 *   GET /v1/cross-platform/trend          — daily cost per provider (stacked chart)
 *   GET /v1/cross-platform/developer/:id  — single developer drill-down (admin/owner)
```

- [ ] **Step 5: Run typecheck**

```bash
cd vantage-worker && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
git add vantage-worker/src/routes/crossplatform.ts
git commit -m "feat(api): /developer/:id replaces :email, developer_id in /developers, days validation backfill"
```

---

## Task 3: Backend — `/live` Email Redaction

**Files:**
- Modify: `vantage-worker/src/routes/crossplatform.ts`

### Steps

- [ ] **Step 1: Update `/live` handler — add role check and redact emails**

Inside the `/live` handler (line 269), after `const orgId = c.get('orgId');` add:

```typescript
  const role    = c.get('role');
  const isAdmin = role === 'owner' || role === 'admin';
```

Replace the first `return c.json(...)` (fresh events, line ~285):
```typescript
  if (recent.results && recent.results.length > 0) {
    const events = (recent.results as any[]).map(e => ({
      ...e,
      developer_email: isAdmin ? e.developer_email : redactEmail(e.developer_email),
    }));
    return c.json({ events, is_stale: false });
  }
```

Replace the fallback `return c.json(...)` (line ~299):
```typescript
  const events = (fallback.results ?? [] as any[]).map((e: any) => ({
    ...e,
    developer_email: isAdmin ? e.developer_email : redactEmail(e.developer_email),
  }));
  return c.json({
    events,
    is_stale: true,
    message: 'No activity in the last 5 minutes — showing most recent events',
  });
```

- [ ] **Step 2: Run typecheck**

```bash
cd vantage-worker && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add vantage-worker/src/routes/crossplatform.ts
git commit -m "feat(api): redact developer_email in /live for non-admin roles"
```

---

## Task 4: Frontend — app.html Structural Changes

**Files:**
- Modify: `vantage-final-v4/app.html`

### Steps

- [ ] **Step 1: Expose `apiFetch` as `window.apiFetch`**

Find `function apiFetch(` (around line 1461). After the closing `}` of the function body, add:

```javascript
  window.apiFetch = apiFetch;
```

This is inside the outer IIFE so it does not pollute the global scope in any other way.

- [ ] **Step 2: Add `.card-error` CSS**

Find `</style>` (the closing tag before `</head>`). Insert before it:

```css
.card-error{color:#f87171;font-size:12px;padding:8px 0;display:none}
```

- [ ] **Step 3: Add Cross-Platform nav button**

Find the Dashboard section in the sidebar (contains buttons with `data-section="dashboard"`). After the last such button (Spend Analysis), add:

```html
<button class="sb-item" onclick="nav('cross-platform', this)" data-section="dashboard">Cross-Platform</button>
```

- [ ] **Step 4: Add section shell and developer modal**

Find `</div><!-- end dashboard views -->` or the closing of the last dashboard view div. Insert after the spend-analysis view closing tag:

```html
<!-- ── Cross-Platform tab ─────────────────────────────────────────────── -->
<div id="view-cross-platform" class="view" style="display:none">

  <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:16px">
    <button class="period-btn cp-period active" data-days="7">7d</button>
    <button class="period-btn cp-period" data-days="30">30d</button>
    <button class="period-btn cp-period" data-days="90">90d</button>
  </div>

  <div id="cp-kpis" class="kpi-grid" style="margin-bottom:16px"></div>

  <div class="grid-2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-title">Daily Spend by Tool</div>
      <canvas id="cp-trend-canvas" height="180"></canvas>
      <div id="cp-trend-error" class="card-error"></div>
    </div>
    <div class="card">
      <div class="card-title">Tool Cost Share</div>
      <canvas id="cp-donut-canvas" height="180"></canvas>
      <div id="cp-donut-error" class="card-error"></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-title">
      Per-Developer Attribution
      <span style="font-size:11px;opacity:.5;font-weight:400"> — click row for full detail</span>
    </div>
    <div id="cp-dev-table"></div>
    <div id="cp-dev-error" class="card-error"></div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        Live Feed
        <span id="cp-live-dot" style="color:#4ade80;font-size:10px;margin-left:4px">&#9679;</span>
      </div>
      <div id="cp-live-feed"></div>
    </div>
    <div class="card">
      <div class="card-title">Connected Tools</div>
      <div id="cp-connections"></div>
    </div>
  </div>

</div>
<!-- ── Developer detail modal ──────────────────────────────────────────── -->
<div id="devDetailModal" class="modal-overlay" style="display:none" role="dialog" aria-modal="true">
  <div class="modal-content" style="max-width:600px;width:100%">
    <button class="modal-close" onclick="closeModal('devDetailModal')" aria-label="Close">&times;</button>
    <h3 id="devDetailTitle" style="margin-bottom:16px"></h3>
    <div id="devDetailBody"></div>
  </div>
</div>
```

- [ ] **Step 5: Wire tab lifecycle in `nav()` function**

Find `function nav(` in `app.html`. Inside it, after the existing show/hide section logic, add:

```javascript
  if (id === 'cross-platform') {
    if (window.cpConsoleInit) window.cpConsoleInit();
  } else {
    if (window.cpConsoleDestroy) window.cpConsoleDestroy();
  }
```

- [ ] **Step 6: Add `<script>` tag**

Find `<script src="/widget/chatbot.js"></script>` near the end of `</body>`. After it add:

```html
<script src="/cp-console.js" defer></script>
```

- [ ] **Step 7: Open in browser and confirm no console errors**

Navigate to Dashboard. Check DevTools console. No errors on load. Cross-Platform tab button should appear in sidebar.

- [ ] **Step 8: Commit**

```bash
git add vantage-final-v4/app.html
git commit -m "feat(ui): add Cross-Platform tab shell, modal element, nav wiring to app.html"
```

---

## Task 5: Frontend — cp-console.js Core (Loading, KPIs, Charts)

**Files:**
- Create: `vantage-final-v4/cp-console.js`

**Security note:** All user-sourced values (provider names, emails, model names) are passed through `esc()` before being inserted into HTML strings. The `esc()` function escapes `& < > "`. This is the same pattern used throughout `app.html`.

### Steps

- [ ] **Step 1: Create `vantage-final-v4/cp-console.js` with the full skeleton**

```javascript
/**
 * cp-console.js — Cross-Platform AI Spend Console tab
 * Depends on: window.apiFetch (exposed by app.html), Chart.js (loaded in app.html head)
 *
 * Security: all values inserted into HTML pass through esc() which encodes & < > "
 */
(function () {
  'use strict';

  // Chart instances — destroyed before re-creating on each data refresh
  var cpTrendChart    = null;
  var cpDoughnutChart = null;
  var cpDevChart      = null;

  // Live poll
  var cpLiveInterval = null;
  var cpLiveErrors   = 0;

  // Period persistence
  var PERIOD_KEY = 'vantage_cp_period';
  function getSavedPeriod() {
    var v = parseInt(localStorage.getItem(PERIOD_KEY) || '30', 10);
    return [7, 30, 90].indexOf(v) >= 0 ? v : 30;
  }
  function savePeriod(d) { localStorage.setItem(PERIOD_KEY, String(d)); }

  // Provider colour map
  var COLORS = { claude_code: '#6366f1', copilot_chat: '#06b6d4', cursor: '#f59e0b', gemini_cli: '#10b981' };
  function pc(p) { return COLORS[p] || '#8b5cf6'; }

  // HTML-escape user-sourced values before inserting into DOM strings
  function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function fmt2(n) { return n != null ? Number(n).toFixed(2) : '0.00'; }

  // Show/hide per-card error banners
  function showCardError(elId, msg) {
    var el = document.getElementById(elId);
    if (!el) return;
    el.style.display = 'block';
    el.textContent = '\u26A0 ' + msg;
  }
  function clearCardError(elId) {
    var el = document.getElementById(elId);
    if (el) { el.style.display = 'none'; el.textContent = ''; }
  }

  // ── KPI cards ─────────────────────────────────────────────────────────────
  function renderCpKpis(summary) {
    var el = document.getElementById('cp-kpis');
    if (!el) return;
    var budget = summary.budget || {};
    var pct = budget.budget_pct != null ? Math.round(budget.budget_pct) : null;
    var pctColor = pct == null ? '' : pct >= 85 ? '#f87171' : pct >= 50 ? '#fb923c' : '#4ade80';
    var top = (summary.by_provider || [])[0] || {};
    var share = summary.total_cost_usd > 0 && top.cost
      ? Math.round(top.cost / summary.total_cost_usd * 100) + '%' : '';

    var cards = [
      kpiHtml('Total Spend', '$' + fmt2(summary.total_cost_usd)),
      kpiHtml('Top Tool', esc(top.provider || '\u2014') + (share ? ' <small style="opacity:.5">' + share + '</small>' : '')),
      kpiHtml('Active Devs', String(summary.active_developers || '\u2014')),
      kpiHtml('MTD Budget', pct != null
        ? '<span style="color:' + pctColor + '">' + pct + '%</span>'
        : '\u2014'),
    ];

    // Use textContent-safe wrapper — inject pre-built HTML into container
    el.textContent = '';
    var tmp = document.createElement('div');
    tmp.style.display = 'contents';
    // NOTE: cards[] contains only esc()-sanitized user values and static markup
    tmp.innerHTML = cards.join('');
    el.appendChild(tmp);
  }

  function kpiHtml(label, value) {
    return '<div class="kpi-card"><div class="kpi-label">' + label +
      '</div><div class="kpi-value">' + value + '</div></div>';
  }

  // ── Trend chart ───────────────────────────────────────────────────────────
  function renderCpTrend(data) {
    clearCardError('cp-trend-error');
    var canvas = document.getElementById('cp-trend-canvas');
    if (!canvas) return;
    if (cpTrendChart) { cpTrendChart.destroy(); cpTrendChart = null; }

    cpTrendChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: data.days,
        datasets: (data.series || []).map(function (s) {
          return {
            label: s.provider,
            data: s.data,
            borderColor: pc(s.provider),
            backgroundColor: pc(s.provider) + '33',
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          };
        }),
      },
      options: {
        responsive: true,
        scales: {
          y: {
            stacked: true,
            beginAtZero: true,
            ticks: { callback: function (v) { return '$' + Number(v).toFixed(2); } },
          },
          x: { ticks: { maxTicksLimit: 8 } },
        },
        plugins: { legend: { position: 'bottom' } },
        interaction: { mode: 'index' },
      },
    });
  }

  // ── Doughnut chart ────────────────────────────────────────────────────────
  function renderCpDonut(summary) {
    clearCardError('cp-donut-error');
    var canvas = document.getElementById('cp-donut-canvas');
    if (!canvas) return;
    if (cpDoughnutChart) { cpDoughnutChart.destroy(); cpDoughnutChart = null; }

    var items = summary.by_provider || [];
    cpDoughnutChart = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: items.map(function (p) { return p.provider; }),
        datasets: [{
          data: items.map(function (p) { return p.cost; }),
          backgroundColor: items.map(function (p) { return pc(p.provider); }),
          borderWidth: 1,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { callbacks: { label: function (ctx) { return ' $' + ctx.parsed.toFixed(2); } } },
        },
      },
    });
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadCrossplatform(period) {
    savePeriod(period);
    updatePeriodButtons(period);

    window.apiFetch('/v1/cross-platform/summary?days=' + period)
      .then(function (d) { renderCpKpis(d); renderCpDonut(d); })
      .catch(function (e) { showCardError('cp-donut-error', 'Load failed: ' + esc(e.message)); });

    window.apiFetch('/v1/cross-platform/trend?days=' + period)
      .then(renderCpTrend)
      .catch(function (e) { showCardError('cp-trend-error', 'Load failed: ' + esc(e.message)); });

    window.apiFetch('/v1/cross-platform/developers?days=' + period)
      .then(function (d) { renderCpDevTable(d.developers || []); })
      .catch(function (e) { showCardError('cp-dev-error', 'Load failed: ' + esc(e.message)); });

    window.apiFetch('/v1/cross-platform/connections')
      .then(renderCpConnections)
      .catch(function () {
        var el = document.getElementById('cp-connections');
        if (el) el.textContent = 'Failed to load connections.';
      });
  }

  function updatePeriodButtons(period) {
    document.querySelectorAll('.cp-period').forEach(function (btn) {
      btn.classList.toggle('active', parseInt(btn.dataset.days, 10) === period);
    });
  }

  // ── Tab lifecycle (called by app.html nav()) ──────────────────────────────
  window.cpConsoleInit = function () {
    loadCrossplatform(getSavedPeriod());
    startCpLivePoll();
  };
  window.cpConsoleDestroy = function () {
    stopCpLivePoll();
  };

  // ── Period button wiring ──────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.cp-period').forEach(function (btn) {
      btn.addEventListener('click', function () {
        loadCrossplatform(parseInt(btn.dataset.days, 10));
      });
    });

    // Close developer modal on overlay click
    var modal = document.getElementById('devDetailModal');
    if (modal) {
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal('devDetailModal');
      });
    }
  });

  // ── Developer table ───────────────────────────────────────────────────────
  function renderCpDevTable(devs) {
    clearCardError('cp-dev-error');
    var el = document.getElementById('cp-dev-table');
    if (!el) return;

    if (!devs.length) {
      el.textContent = 'No developer data for this period.';
      return;
    }

    // Build table using DOM API — header row via createElement
    var table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse';

    var thead = table.createTHead();
    var hrow  = thead.insertRow();
    ['Developer', 'Tools', 'Spend', 'Commits', '$/commit'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:4px 6px;text-align:left;font-size:10px;opacity:.5;font-weight:500;border-bottom:1px solid rgba(255,255,255,.08)';
      hrow.appendChild(th);
    });

    var tbody = table.createTBody();
    devs.forEach(function (d) {
      var row = tbody.insertRow();
      var hasId = !!d.developer_id;
      if (hasId) {
        row.dataset.devId    = d.developer_id;
        row.dataset.devEmail = d.developer_email || '';
        row.className = 'cp-dev-row';
        row.style.cursor = 'pointer';
      } else {
        row.title = 'Install vantage-agent to enable drill-down';
        row.style.opacity = '0.6';
      }

      // Developer email cell
      var emailTd = row.insertCell();
      emailTd.textContent = d.developer_email || d.developer_id || '—';
      emailTd.style.cssText = 'padding:7px 6px;font-size:12px';

      // Tools badges cell
      var toolsTd = row.insertCell();
      toolsTd.style.cssText = 'padding:7px 6px';
      (d.providers || []).forEach(function (p) {
        var badge = document.createElement('span');
        badge.textContent = p.replace(/_/g, ' ');
        badge.style.cssText = 'font-size:10px;background:' + pc(p) + '22;color:' + pc(p) + ';padding:1px 6px;border-radius:4px;margin-right:3px';
        toolsTd.appendChild(badge);
      });

      // Spend cell
      var spendTd = row.insertCell();
      spendTd.textContent = '$' + fmt2(d.total_cost);
      spendTd.style.cssText = 'padding:7px 6px;font-size:12px;color:#4ade80';

      // Commits cell
      var commitsTd = row.insertCell();
      commitsTd.textContent = String(d.commits || 0);
      commitsTd.style.cssText = 'padding:7px 6px;font-size:12px;opacity:.7';

      // $/commit cell
      var costTd = row.insertCell();
      costTd.textContent = d.cost_per_commit != null ? '$' + d.cost_per_commit.toFixed(2) : '—';
      costTd.style.cssText = 'padding:7px 6px;font-size:12px;opacity:.7';
    });

    el.textContent = '';
    el.appendChild(table);

    // Wire click handlers for rows that have a developer_id
    el.querySelectorAll('.cp-dev-row').forEach(function (row) {
      row.addEventListener('click', function () {
        openDevModal(row.dataset.devId, row.dataset.devEmail);
      });
    });
  }

  // ── Developer detail modal ────────────────────────────────────────────────
  function openDevModal(devId, devEmail) {
    var modal = document.getElementById('devDetailModal');
    var title = document.getElementById('devDetailTitle');
    var body  = document.getElementById('devDetailBody');
    if (!modal || !title || !body) return;

    title.textContent = devEmail || devId;
    body.textContent  = 'Loading\u2026';
    modal.style.display = 'flex';

    window.apiFetch('/v1/cross-platform/developer/' + encodeURIComponent(devId))
      .then(function (data) { renderDevModalBody(body, data); })
      .catch(function (e) {
        body.textContent = '\u26A0 ' + (e.message || 'Failed to load');
      });
  }

  function renderDevModalBody(body, data) {
    body.textContent = '';

    // 1. By-tool cost table
    var table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse;margin-bottom:16px';
    var thead = table.createTHead();
    var hrow  = thead.insertRow();
    ['Tool', 'Spend', 'Input tokens', 'Output tokens'].forEach(function (h) {
      var th = document.createElement('th');
      th.textContent = h;
      th.style.cssText = 'padding:4px 8px;text-align:left;font-size:10px;opacity:.5;font-weight:500;border-bottom:1px solid rgba(255,255,255,.08)';
      hrow.appendChild(th);
    });
    var tbody = table.createTBody();
    (data.by_provider || []).forEach(function (p) {
      var row = tbody.insertRow();
      [p.provider, '$' + fmt2(p.cost), String(p.input_tokens || 0), String(p.output_tokens || 0)]
        .forEach(function (val, i) {
          var td = row.insertCell();
          td.textContent = val;
          td.style.cssText = 'padding:6px 8px;font-size:12px' + (i === 1 ? ';color:#4ade80' : ';opacity:.8');
        });
    });
    body.appendChild(table);

    // 2. Daily trend chart
    var chartTitle = document.createElement('div');
    chartTitle.className = 'card-title';
    chartTitle.textContent = 'Daily Trend';
    chartTitle.style.marginBottom = '8px';
    body.appendChild(chartTitle);

    var canvas = document.createElement('canvas');
    canvas.id = 'cp-dev-chart-canvas';
    canvas.height = 120;
    body.appendChild(canvas);

    if (data.daily_trend && data.daily_trend.length) {
      if (cpDevChart) { cpDevChart.destroy(); cpDevChart = null; }
      var trend = data.daily_trend.slice().reverse();
      cpDevChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: trend.map(function (t) { return t.day; }),
          datasets: [{
            label: 'Spend',
            data: trend.map(function (t) { return t.cost; }),
            borderColor: '#6366f1',
            backgroundColor: '#6366f133',
            fill: true,
            tension: 0.3,
            pointRadius: 2,
          }],
        },
        options: {
          responsive: true,
          scales: {
            y: { beginAtZero: true, ticks: { callback: function (v) { return '$' + Number(v).toFixed(2); } } },
            x: { ticks: { maxTicksLimit: 6 } },
          },
          plugins: { legend: { display: false } },
        },
      });
    }

    // 3. Productivity stats
    var prod = data.productivity || {};
    var prodGrid = document.createElement('div');
    prodGrid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px';
    [
      ['Commits',       prod.commits],
      ['Pull Requests', prod.pull_requests],
      ['Lines Added',   prod.lines_added],
      ['Lines Removed', prod.lines_removed],
      ['Active Time',   prod.active_time_s != null ? Math.round(prod.active_time_s / 60) + 'm' : null],
    ].forEach(function (item) {
      var box = document.createElement('div');
      box.style.cssText = 'background:rgba(255,255,255,.04);border-radius:8px;padding:10px;text-align:center';
      var lbl = document.createElement('div');
      lbl.textContent = item[0];
      lbl.style.cssText = 'font-size:10px;opacity:.5;margin-bottom:4px';
      var val = document.createElement('div');
      val.textContent = item[1] != null ? String(item[1]) : '—';
      val.style.cssText = 'font-size:18px;font-weight:600';
      box.appendChild(lbl);
      box.appendChild(val);
      prodGrid.appendChild(box);
    });
    body.appendChild(prodGrid);
  }

  // ── Live feed ─────────────────────────────────────────────────────────────
  function renderCpLiveFeed(data) {
    var el  = document.getElementById('cp-live-feed');
    var dot = document.getElementById('cp-live-dot');
    if (!el) return;

    if (dot) dot.style.color = data.is_stale ? '#fb923c' : '#4ade80';

    var events = data.events || [];
    el.textContent = '';

    if (!events.length) {
      var empty = document.createElement('p');
      empty.textContent = 'No activity yet.';
      empty.style.cssText = 'font-size:12px;opacity:.4;padding:8px 0';
      el.appendChild(empty);
      return;
    }

    events.slice(0, 15).forEach(function (e) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:11px';

      var left = document.createElement('span');
      left.textContent = (e.provider || '') + ' \u00b7 ' + (e.model || '');
      left.style.opacity = '0.8';

      var cost = document.createElement('span');
      cost.textContent = '$' + fmt2(e.cost_usd);
      cost.style.color = '#4ade80';

      var ts = document.createElement('span');
      ts.textContent = e.timestamp ? String(e.timestamp).slice(11, 19) : '';
      ts.style.opacity = '0.4';

      row.appendChild(left);
      row.appendChild(cost);
      row.appendChild(ts);
      el.appendChild(row);
    });

    if (data.is_stale) {
      var staleNote = document.createElement('p');
      staleNote.textContent = '\u26A0 stale — no activity in last 5 min';
      staleNote.style.cssText = 'font-size:10px;color:#fb923c;margin-top:4px';
      el.appendChild(staleNote);
    }
  }

  // ── Live poll ─────────────────────────────────────────────────────────────
  function startCpLivePoll() {
    stopCpLivePoll();
    cpLiveErrors = 0;
    var jitter = Math.random() * 10000 - 5000;

    function tick() {
      window.apiFetch('/v1/cross-platform/live?limit=15')
        .then(function (data) {
          cpLiveErrors = 0;
          renderCpLiveFeed(data);
        })
        .catch(function () {
          cpLiveErrors++;
          if (cpLiveErrors >= 3) {
            stopCpLivePoll();
            setTimeout(startCpLivePoll, 120000);
          }
        });
    }

    tick(); // fire immediately; don't wait 15s for first update
    cpLiveInterval = setInterval(tick, 15000 + jitter);
  }

  function stopCpLivePoll() {
    if (cpLiveInterval) { clearInterval(cpLiveInterval); cpLiveInterval = null; }
  }

  // ── Connections ───────────────────────────────────────────────────────────
  function renderCpConnections(data) {
    var el = document.getElementById('cp-connections');
    if (!el) return;
    el.textContent = '';

    var billing = data.billing_connections || [];
    var otel    = data.otel_sources || [];

    if (!billing.length && !otel.length) {
      var p = document.createElement('p');
      p.style.cssText = 'font-size:12px;opacity:.4';
      var txt = document.createTextNode('No tools connected. ');
      var link = document.createElement('a');
      link.href = '#';
      link.textContent = 'Add a tool';
      link.onclick = function (e) { e.preventDefault(); if (window.nav) nav('integrations', link); };
      p.appendChild(txt);
      p.appendChild(link);
      el.appendChild(p);
      return;
    }

    function addRow(providerName, statusColor, syncTime) {
      var row = document.createElement('div');
      row.style.cssText = 'display:flex;justify-content:space-between;padding:5px 0;font-size:12px';
      var left = document.createElement('span');
      var dot = document.createElement('span');
      dot.textContent = '\u25cf ';
      dot.style.color = statusColor;
      left.appendChild(dot);
      left.appendChild(document.createTextNode(providerName));
      var right = document.createElement('span');
      right.textContent = syncTime || '—';
      right.style.opacity = '0.5';
      row.appendChild(left);
      row.appendChild(right);
      el.appendChild(row);
    }

    billing.forEach(function (c) {
      var color = c.status === 'active' ? '#4ade80' : c.status === 'error' ? '#f87171' : '#fb923c';
      var sync  = c.last_sync_at ? String(c.last_sync_at).slice(0, 16).replace('T', ' ') : '';
      addRow(c.provider, color, sync);
    });
    otel.forEach(function (o) {
      var t = o.last_data_at ? String(o.last_data_at).slice(0, 16).replace('T', ' ') : '';
      addRow(o.provider + ' (OTel)', '#4ade80', t);
    });
  }

})();
```

- [ ] **Step 2: Navigate to Cross-Platform tab in browser**

Open the dashboard, click Cross-Platform. Check DevTools console — no errors. KPI cards, chart canvases, and table container should all render (data may be empty in test env). Live feed should start polling (visible in Network tab).

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/cp-console.js
git commit -m "feat(ui): cp-console.js — full Cross-Platform tab implementation"
```

---

## Task 6: Test Runner Script

**Files:**
- Create: `scripts/run-tests.sh`

### Steps

- [ ] **Step 1: Create `scripts/run-tests.sh`**

```bash
#!/usr/bin/env bash
# run-tests.sh — VantageAI local test runner
# Usage: scripts/run-tests.sh [--suite NAME] [--file FILE] [--test EXPR] [-- PYTEST_ARGS]
set -euo pipefail

SUITES=()
FILES=()
TEST_NAME=""
EXTRA_ARGS=()
PARSING_EXTRA=0

validate_arg() {
  local val="$1" flag="$2"
  if [[ ! "$val" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "ERROR: Invalid value for $flag: '$val' (alphanumeric, underscore, hyphen only)" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  if [[ $PARSING_EXTRA -eq 1 ]]; then
    EXTRA_ARGS+=("$1"); shift; continue
  fi
  case "$1" in
    --suite) validate_arg "$2" "--suite"; SUITES+=("$2"); shift 2 ;;
    --file)  validate_arg "$2" "--file";  FILES+=("$2");  shift 2 ;;
    --test)  validate_arg "$2" "--test";  TEST_NAME="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: scripts/run-tests.sh [--suite NAME] [--file FILE] [--test EXPR] [-- ARGS]"
      echo ""
      echo "  --suite  Partial or exact suite name (e.g. '35' or '35_cross_platform_console')"
      echo "  --file   Test file within suite, without .py extension"
      echo "  --test   pytest -k filter expression"
      echo "  --       All following args are passed to pytest verbatim"
      echo ""
      echo "Examples:"
      echo "  scripts/run-tests.sh"
      echo "  scripts/run-tests.sh --suite 35"
      echo "  scripts/run-tests.sh --suite 35 --file test_trend"
      echo "  scripts/run-tests.sh --suite 35 --test test_trend_7d_window -- -v -x"
      exit 0 ;;
    --) PARSING_EXTRA=1; shift ;;
    *)  echo "ERROR: Unknown argument: $1 (use --help for usage)" >&2; exit 1 ;;
  esac
done

SUITE_BASE="tests/suites"
if [[ ! -d "$SUITE_BASE" ]]; then
  echo "ERROR: Cannot find $SUITE_BASE — run from project root" >&2
  exit 1
fi

mapfile -t ALL_SUITES < <(ls -d "$SUITE_BASE"/[0-9]*/ 2>/dev/null | xargs -n1 basename | sort)

resolve_suite() {
  local pattern="$1"
  local matches=()
  for s in "${ALL_SUITES[@]}"; do
    [[ "$s" == "$pattern" || "$s" == *"$pattern"* ]] && matches+=("$s")
  done
  if [[ ${#matches[@]} -eq 0 ]]; then
    echo "ERROR: --suite '$pattern' matched no suites. Available: ${ALL_SUITES[*]}" >&2; exit 1
  fi
  if [[ ${#matches[@]} -gt 1 ]]; then
    echo "ERROR: --suite '$pattern' is ambiguous — matches: ${matches[*]}. Be more specific." >&2; exit 1
  fi
  echo "${matches[0]}"
}

CMD=(python -m pytest)

if [[ ${#SUITES[@]} -eq 0 ]]; then
  for s in "${ALL_SUITES[@]}"; do CMD+=("$SUITE_BASE/$s/"); done
else
  for pattern in "${SUITES[@]}"; do
    resolved=$(resolve_suite "$pattern")
    if [[ ${#FILES[@]} -gt 0 ]]; then
      for f in "${FILES[@]}"; do CMD+=("$SUITE_BASE/$resolved/${f%.py}.py"); done
    else
      CMD+=("$SUITE_BASE/$resolved/")
    fi
  done
fi

[[ -n "$TEST_NAME" ]] && CMD+=(-k "$TEST_NAME")
[[ ${#EXTRA_ARGS[@]} -gt 0 ]] && CMD+=("${EXTRA_ARGS[@]}")

echo "Running: ${CMD[*]}"
echo ""
"${CMD[@]}"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/run-tests.sh
```

- [ ] **Step 3: Smoke test the script**

```bash
# Help text
scripts/run-tests.sh --help

# Collect-only to verify suite discovery (no actual test runs)
scripts/run-tests.sh -- --collect-only -q 2>&1 | head -20

# Invalid arg must error
scripts/run-tests.sh --suite "../../bad" 2>&1 | grep "Invalid"
```

Expected: help exits 0; collect-only lists found tests; invalid input prints ERROR and exits non-zero.

- [ ] **Step 4: Commit**

```bash
git add scripts/run-tests.sh
git commit -m "feat(scripts): add run-tests.sh with suite discovery, partial match, input validation"
```

---

## Task 7: Test Suite — conftest + test_trend.py

**Files:**
- Create: `tests/suites/35_cross_platform_console/__init__.py`
- Create: `tests/suites/35_cross_platform_console/conftest.py`
- Create: `tests/suites/35_cross_platform_console/test_trend.py`

### Steps

- [ ] **Step 1: Create `__init__.py`**

```bash
touch tests/suites/35_cross_platform_console/__init__.py
```

- [ ] **Step 2: Create `tests/suites/35_cross_platform_console/conftest.py`**

```python
"""
conftest.py — Fixtures for Cross-Platform Console test suite (35)
Provides seeded_account (org with OTel data) and empty_headers (fresh org, no data).
"""

import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers


def _otel_payload(email: str, provider: str, model: str, cost: float, dev_id: str) -> dict:
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",  "value": {"stringValue": provider}},
                    {"key": "user.email",    "value": {"stringValue": email}},
                    {"key": "developer.id",  "value": {"stringValue": dev_id}},
                    {"key": "session.id",    "value": {"stringValue": f"sess-{uuid.uuid4().hex[:8]}"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-test", "version": "1.0"},
                "metrics": [{
                    "name": "claude_code.cost.usage",
                    "unit": "USD",
                    "sum": {
                        "dataPoints": [{
                            "asDouble": cost,
                            "timeUnixNano": str(int(time.time() * 1e9)),
                            "attributes": [
                                {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                            ]
                        }],
                        "isMonotonic": True,
                    }
                }]
            }]
        }]
    }


@pytest.fixture(scope="module")
def seeded_account():
    """
    Fresh org with two OTel events (claude_code + copilot_chat) seeded today.
    Returns (api_key, org_id, headers, dev_email, dev_id).
    """
    api_key, org_id, _cookies = fresh_account(prefix="cp35")
    hdrs = get_headers(api_key)
    dev_email = f"cp35dev_{uuid.uuid4().hex[:6]}@test.local"
    dev_id = str(uuid.uuid4())

    for provider, model, cost in [
        ("claude_code",  "claude-sonnet-4-6", 0.05),
        ("copilot_chat", "gpt-4o",             0.02),
    ]:
        payload = _otel_payload(dev_email, provider, model, cost, dev_id)
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                          json=payload, headers=hdrs, timeout=15)
        assert r.status_code in (200, 201), f"OTel seed failed: {r.status_code} {r.text}"

    time.sleep(2)
    return api_key, org_id, hdrs, dev_email, dev_id


@pytest.fixture(scope="module")
def headers(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    return hdrs


@pytest.fixture(scope="module")
def empty_headers():
    """Fresh org with absolutely no data — for testing full calendar spine."""
    api_key, _, _cookies = fresh_account(prefix="cp35e")
    return get_headers(api_key)
```

- [ ] **Step 3: Create `tests/suites/35_cross_platform_console/test_trend.py`**

```python
"""
test_trend.py — 12 tests for GET /v1/cross-platform/trend
"""

import datetime
import requests

from config.settings import API_URL

BASE = f"{API_URL}/v1/cross-platform/trend"


# ── Response shape ────────────────────────────────────────────────────────────

def test_trend_has_required_keys(headers):
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    for key in ("days", "providers", "series", "period_days"):
        assert key in data, f"Missing key: {key}"


def test_trend_series_data_length_matches_days(headers):
    r = requests.get(BASE, headers=headers, params={"days": 7}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    n = len(data["days"])
    for entry in data["series"]:
        assert len(entry["data"]) == n, (
            f"provider {entry['provider']}: data[{len(entry['data'])}] != days[{n}]"
        )


def test_trend_period_days_field_matches_param(headers):
    for days in (7, 30, 90):
        r = requests.get(BASE, headers=headers, params={"days": days}, timeout=15)
        assert r.status_code == 200
        assert r.json()["period_days"] == days


# ── Full calendar spine ───────────────────────────────────────────────────────

def test_trend_empty_org_returns_full_7d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 7}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert len(data["days"]) == 7
    assert data["series"] == []


def test_trend_empty_org_returns_full_30d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["days"]) == 30


def test_trend_empty_org_returns_full_90d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 90}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["days"]) == 90


def test_trend_days_are_in_ascending_order(headers):
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    days = r.json()["days"]
    assert days == sorted(days)


def test_trend_non_today_entries_are_zero(headers):
    """Seeded account has data for today only. All other days must be 0.0."""
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    today = datetime.date.today().isoformat()
    today_idx = data["days"].index(today) if today in data["days"] else None
    for entry in data["series"]:
        for i, v in enumerate(entry["data"]):
            if today_idx is not None and i == today_idx:
                continue
            assert v == 0 or v == 0.0, f"Expected 0.0 at index {i}, got {v}"


# ── Parameter validation ──────────────────────────────────────────────────────

def test_trend_days_91_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": 91}, timeout=15)
    assert r.status_code == 400
    assert "error" in r.json()


def test_trend_days_0_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": 0}, timeout=15)
    assert r.status_code == 400


def test_trend_days_abc_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": "abc"}, timeout=15)
    assert r.status_code == 400


def test_trend_no_auth_returns_401():
    r = requests.get(BASE, params={"days": 7}, timeout=15)
    assert r.status_code == 401
```

- [ ] **Step 4: Run the tests**

```bash
scripts/run-tests.sh --suite 35 --file test_trend -- -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/suites/35_cross_platform_console/
git commit -m "test(35): conftest + test_trend.py — 12 tests for /trend endpoint"
```

---

## Task 8: Test Suite — test_console_frontend.py

**Files:**
- Create: `tests/suites/35_cross_platform_console/test_console_frontend.py`

### Steps

- [ ] **Step 1: Create `tests/suites/35_cross_platform_console/test_console_frontend.py`**

```python
"""
test_console_frontend.py — 10 contract tests for routes consumed by the
Cross-Platform tab: /summary, /developers, /developer/:id, /live, /connections.
"""

import uuid
import requests

from config.settings import API_URL
from helpers.api import fresh_account, get_headers


# ── /summary ──────────────────────────────────────────────────────────────────

def test_summary_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "total_cost_usd" in data
    assert "by_provider" in data and isinstance(data["by_provider"], list)
    assert "budget" in data


def test_summary_invalid_days_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     headers=headers, params={"days": 999}, timeout=15)
    assert r.status_code == 400


def test_summary_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     params={"days": 30}, timeout=15)
    assert r.status_code == 401


# ── /developers ───────────────────────────────────────────────────────────────

def test_developers_includes_developer_id(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                     headers=hdrs, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    devs = r.json().get("developers", [])
    assert len(devs) >= 1
    assert "developer_id" in devs[0], "developer_id must be present"
    assert "by_provider" in devs[0] and isinstance(devs[0]["by_provider"], list)


def test_developers_no_null_developer_id(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    for dev in r.json().get("developers", []):
        assert dev.get("developer_id") is not None


# ── /developer/:id ────────────────────────────────────────────────────────────

def test_developer_detail_shape(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    devs = requests.get(f"{API_URL}/v1/cross-platform/developers",
                        headers=hdrs, params={"days": 30}, timeout=15).json().get("developers", [])
    assert devs, "No developers seeded"
    dev_id = devs[0]["developer_id"]

    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{dev_id}",
                     headers=hdrs, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "by_provider" in data and isinstance(data["by_provider"], list)
    assert "daily_trend" in data and isinstance(data["daily_trend"], list)
    assert "productivity" in data


def test_developer_detail_invalid_uuid_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/not-a-uuid",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 400


def test_developer_detail_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{uuid.uuid4()}",
                     params={"days": 30}, timeout=15)
    assert r.status_code == 401


# ── /live ─────────────────────────────────────────────────────────────────────

def test_live_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/live",
                     headers=headers, params={"limit": 5}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "events" in data and isinstance(data["events"], list)
    assert "is_stale" in data


def test_live_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/live",
                     params={"limit": 5}, timeout=15)
    assert r.status_code == 401


# ── /connections ──────────────────────────────────────────────────────────────

def test_connections_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/connections",
                     headers=headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "billing_connections" in data and isinstance(data["billing_connections"], list)
    assert "otel_sources" in data and isinstance(data["otel_sources"], list)
```

- [ ] **Step 2: Run the full suite 35**

```bash
scripts/run-tests.sh --suite 35 -- -v
```

Expected: all 22 tests pass.

- [ ] **Step 3: Run the full test suite to verify no regressions**

```bash
scripts/run-tests.sh -- -x -q
```

Expected: all passing tests from before this feature still pass. Note any pre-existing failures — they are not your problem.

- [ ] **Step 4: Commit**

```bash
git add tests/suites/35_cross_platform_console/test_console_frontend.py
git commit -m "test(35): test_console_frontend.py — 10 contract tests for cross-platform routes"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| 1a `/trend` with full calendar spine | Task 1 |
| 1b `validateDays` backfilled to all `?days=` routes | Task 2 |
| 1b `/developers` returns `developer_id`, filters NULLs | Task 2 |
| 1b `/developer/:id` replaces `:email`, UUID validation, role check | Task 2 |
| 1c `/live` email redaction for non-admin | Task 3 |
| 2a `window.apiFetch` exposure | Task 4 |
| 2a `.card-error` CSS, nav tab, section shell, modal element, script tag | Task 4 |
| 2a `nav()` lifecycle wiring | Task 4 |
| 2b cp-console.js IIFE structure, chart refs, period/color utils, esc() | Task 5 |
| 2c `loadCrossplatform`, 4 parallel fetches, period selector | Task 5 |
| 2d stacked area chart (`fill:true`, `stacked:true`), destroy before re-create | Task 5 |
| 2d doughnut chart with destroy before re-create | Task 5 |
| 2g period saved to `localStorage` | Task 5 |
| 2f developer table with `data-dev-id`, NULL row degradation | Task 5 |
| 2f developer modal with 3 sub-sections, `cpDevChart` lifecycle | Task 5 |
| 2e live poll with immediate first tick, jitter, 3-error backoff | Task 5 |
| 2c connections re-fetched on every tab activation | Task 5 |
| 3 `run-tests.sh` with validation, partial match, ambiguity error, discovery | Task 6 |
| 4 conftest with `seeded_account` and `empty_headers` fixtures | Task 7 |
| 4 `test_trend.py` — 12 tests including full spine, zero-fill, 400 validation | Task 7 |
| 4 `test_console_frontend.py` — 10 contract tests | Task 8 |

All spec requirements covered. No TBDs. Function names consistent throughout: `renderCpKpis`, `renderCpTrend`, `renderCpDonut`, `renderCpDevTable`, `renderCpLiveFeed`, `renderCpConnections`, `openDevModal`, `startCpLivePoll`, `stopCpLivePoll`, `loadCrossplatform`.
