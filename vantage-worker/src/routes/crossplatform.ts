/**
 * VantageAI — Cross-Platform Cost API
 *
 * Serves aggregated data from OTel telemetry + billing APIs.
 * Powers the "All AI Spend" dashboard with live/near-real-time data.
 *
 * Endpoints:
 *   GET /v1/cross-platform/summary        — total spend, by provider, by tool type
 *   GET /v1/cross-platform/developers     — per-developer spend table
 *   GET /v1/cross-platform/trend          — daily cost per provider (stacked chart)
 *   GET /v1/cross-platform/developer/:id  — single developer drill-down (admin/owner)
 *   GET /v1/cross-platform/live           — last 50 OTel events (SSE-ready)
 *   GET /v1/cross-platform/models         — cost by model across all providers
 *   GET /v1/cross-platform/connections    — provider connection status
 *   GET /v1/cross-platform/budget         — budget policies + current spend
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const crossplatform = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// Use the shared auth middleware — supports both session cookies (dashboard)
// and Bearer tokens (API/SDK/tests)
crossplatform.use('*', authMiddleware);

// SQLite datetime('now') produces 'YYYY-MM-DD HH:MM:SS' (no T, no Z).
// All date comparisons must use the same format to avoid string comparison bugs.
// Align to UTC midnight so the window covers exactly `days` calendar days
// (today + previous days-1), not a rolling window from the current timestamp.
function sqliteDateSince(days: number): string {
  const todayMidnightMs = Math.floor(Date.now() / 86400000) * 86400000;
  const d = new Date(todayMidnightMs - (days - 1) * 86400000);
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
}

function sqliteTodayStart(): string {
  const d = new Date();
  return d.toISOString().split('T')[0] + ' 00:00:00';
}

function sqliteMonthStart(): string {
  const d = new Date();
  return d.toISOString().slice(0, 7) + '-01 00:00:00';
}

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

// ── GET /summary — total spend across all platforms ─────────────────────────

crossplatform.get('/summary', async (c) => {
  const orgId = c.get('orgId');
  let days: number;
  try {
    days = validateDays(c.req.query('days'));
  } catch {
    return c.json({ error: 'days must be 7, 30, or 90' }, 400);
  }
  const since = sqliteDateSince(days);

  // Total spend
  const total = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0) as total_cost,
      COALESCE(SUM(input_tokens), 0) as total_input_tokens,
      COALESCE(SUM(output_tokens), 0) as total_output_tokens,
      COALESCE(SUM(cached_tokens), 0) as total_cached_tokens,
      COUNT(*) as total_records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, since).first();

  // By provider
  const byProvider = await c.env.DB.prepare(`
    SELECT
      provider,
      COALESCE(SUM(cost_usd), 0) as cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) as tokens,
      COUNT(*) as records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY provider ORDER BY cost DESC
  `).bind(orgId, since).all();

  // By source (otel vs billing_api)
  const bySource = await c.env.DB.prepare(`
    SELECT
      source,
      COALESCE(SUM(cost_usd), 0) as cost,
      COUNT(*) as records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY source
  `).bind(orgId, since).all();

  // Today's spend
  const todayStart = sqliteTodayStart();
  const today = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) as today_cost,
           COALESCE(SUM(input_tokens + output_tokens), 0) as today_tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, todayStart).first();

  // Budget check
  const budget = await c.env.DB.prepare(`
    SELECT monthly_limit_usd FROM budget_policies
    WHERE org_id = ? AND scope = 'org' LIMIT 1
  `).bind(orgId).first() as { monthly_limit_usd: number } | null;

  const monthStart = sqliteMonthStart();
  const monthSpend = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) as month_cost
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, monthStart).first() as { month_cost: number } | null;

  // Previous period for trend comparison
  const prevSince = sqliteDateSince(days * 2);
  const prevUntil = since;
  const prevTotal = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) as prev_cost
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND created_at < ?
  `).bind(orgId, prevSince, prevUntil).first() as { prev_cost: number } | null;

  const budgetLimit = budget?.monthly_limit_usd ?? 0;
  const budgetUsed = monthSpend?.month_cost ?? 0;
  const budgetPct = budgetLimit > 0 ? Math.round((budgetUsed / budgetLimit) * 100) : 0;

  return c.json({
    period_days: days,
    total_cost_usd: total?.total_cost ?? 0,
    previous_period_cost: prevTotal?.prev_cost ?? 0,
    total_input_tokens: total?.total_input_tokens ?? 0,
    total_output_tokens: total?.total_output_tokens ?? 0,
    total_cached_tokens: total?.total_cached_tokens ?? 0,
    total_records: total?.total_records ?? 0,
    today_cost_usd: today?.today_cost ?? 0,
    today_tokens: today?.today_tokens ?? 0,
    by_provider: byProvider.results,
    by_source: bySource.results,
    budget: {
      monthly_limit_usd: budgetLimit,
      month_spend_usd: budgetUsed,
      budget_pct: budgetPct,
    },
  });
});

// ── GET /developers — per-developer spend table ─────────────────────────────

crossplatform.get('/developers', async (c) => {
  const orgId = c.get('orgId');
  const role   = c.get('role');
  let days: number;
  try {
    days = validateDays(c.req.query('days'));
  } catch {
    return c.json({ error: 'days must be 7, 30, or 90' }, 400);
  }
  const since = sqliteDateSince(days);

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
    GROUP BY developer_id, developer_email
    ORDER BY total_cost DESC
  `).bind(orgId, since).all();

  // Per-developer per-provider cost breakdown (for bar chart segmentation)
  const byProviderRows = await c.env.DB.prepare(`
    SELECT developer_id, developer_email,
           provider,
           COALESCE(SUM(cost_usd), 0) as cost,
           COUNT(*) as records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_id, developer_email, provider
    ORDER BY developer_email, cost DESC
  `).bind(orgId, since).all();

  const byProviderMap: Record<string, { provider: string; cost: number; records: number }[]> = {};
  for (const row of (byProviderRows.results ?? []) as any[]) {
    if (!byProviderMap[row.developer_id]) byProviderMap[row.developer_id] = [];
    byProviderMap[row.developer_id].push({ provider: row.provider, cost: row.cost, records: row.records });
  }

  // Calculate ROI metrics per developer
  const isAdmin = role === 'owner' || role === 'admin';
  const devList = (developers.results ?? []).map((d: any) => {
    const costPerPR = d.pull_requests > 0 ? (d.total_cost / d.pull_requests) : null;
    const costPerCommit = d.commits > 0 ? (d.total_cost / d.commits) : null;
    const linesPerDollar = d.total_cost > 0 ? Math.round((d.lines_added + d.lines_removed) / d.total_cost) : null;
    return {
      ...d,
      developer_email: isAdmin ? d.developer_email : redactEmail(d.developer_email),
      providers: d.providers ? d.providers.split(',') : [],
      by_provider: byProviderMap[d.developer_id] ?? [],
      cost_per_pr: costPerPR ? Math.round(costPerPR * 100) / 100 : null,
      cost_per_commit: costPerCommit ? Math.round(costPerCommit * 100) / 100 : null,
      lines_per_dollar: linesPerDollar,
    };
  });

  return c.json({ period_days: days, developers: devList });
});

// ── GET /developer/:id — single developer drill-down (admin/owner only) ──────

crossplatform.get('/developer/:id', async (c) => {
  const orgId = c.get('orgId');
  const role   = c.get('role');

  const id = c.req.param('id');
  // UUID v4 format: 8-4-4-4-12 hex chars
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)) {
    return c.json({ error: 'Invalid id' }, 400);
  }

  // Access control: owner/admin see all; member/viewer may only view their own data
  if (role !== 'owner' && role !== 'admin') {
    const memberEmail = c.get('memberEmail');
    const owns = await c.env.DB.prepare(`
      SELECT 1 FROM cross_platform_usage
      WHERE org_id = ? AND developer_id = ? AND developer_email = ? LIMIT 1
    `).bind(orgId, id, memberEmail).first();
    if (!owns) return c.json({ error: 'Forbidden' }, 403);
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

/** Redacts `user@domain.com` to `u***@domain.com` for non-admin roles. */
function redactEmail(email: string | null): string | null {
  if (!email) return null;
  const at = email.indexOf('@');
  if (at < 1) return '***';
  return email[0] + '***' + email.slice(at);
}

// ── GET /live — latest OTel events for real-time feed ───────────────────────

crossplatform.get('/live', async (c) => {
  const orgId  = c.get('orgId');
  const role   = c.get('role');
  const isAdmin = role === 'owner' || role === 'admin';
  const rawLimit = parseInt(c.req.query('limit') ?? '50', 10);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 200) : 50;

  // Primary: last 5 minutes only (truly live)
  const recent = await c.env.DB.prepare(`
    SELECT
      provider, developer_email, model, event_name,
      cost_usd, tokens_in, tokens_out, duration_ms, timestamp
    FROM otel_events
    WHERE org_id = ? AND timestamp > datetime('now', '-5 minutes')
    ORDER BY timestamp DESC
    LIMIT ?
  `).bind(orgId, limit).all();

  if (recent.results && recent.results.length > 0) {
    const events = (recent.results as any[]).map(e => ({
      ...e,
      developer_email: isAdmin ? e.developer_email : redactEmail(e.developer_email),
    }));
    return c.json({ events, is_stale: false });
  }

  // Fallback: no recent activity — return last known events with staleness flag
  const fallback = await c.env.DB.prepare(`
    SELECT
      provider, developer_email, model, event_name,
      cost_usd, tokens_in, tokens_out, duration_ms, timestamp
    FROM otel_events
    WHERE org_id = ?
    ORDER BY timestamp DESC
    LIMIT ?
  `).bind(orgId, Math.min(limit, 20)).all();

  const events = (fallback.results ?? [] as any[]).map((e: any) => ({
    ...e,
    developer_email: isAdmin ? e.developer_email : redactEmail(e.developer_email),
  }));
  return c.json({
    events,
    is_stale: true,
    message: 'No activity in the last 5 minutes — showing most recent events',
  });
});

// ── GET /models — cost by model across all providers ────────────────────────

crossplatform.get('/models', async (c) => {
  const orgId = c.get('orgId');
  let days: number;
  try {
    days = validateDays(c.req.query('days'));
  } catch {
    return c.json({ error: 'days must be 7, 30, or 90' }, 400);
  }
  const since = sqliteDateSince(days);

  const models = await c.env.DB.prepare(`
    SELECT model, provider,
      COALESCE(SUM(cost_usd), 0) as cost,
      COALESCE(SUM(input_tokens), 0) as input_tokens,
      COALESCE(SUM(output_tokens), 0) as output_tokens,
      COUNT(*) as requests
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND model IS NOT NULL
    GROUP BY model, provider ORDER BY cost DESC LIMIT 20
  `).bind(orgId, since).all();

  return c.json({ period_days: days, models: models.results });
});

// ── GET /connections — provider connection status ────────────────────────────

crossplatform.get('/connections', async (c) => {
  const orgId = c.get('orgId');
  const role   = c.get('role');
  const isAdmin = role === 'owner' || role === 'admin';

  const connections = await c.env.DB.prepare(`
    SELECT provider, status, last_sync_at, last_error, sync_interval_minutes, created_at
    FROM provider_connections WHERE org_id = ?
  `).bind(orgId).all();

  // Also check OTel data freshness per provider
  const otelFreshness = await c.env.DB.prepare(`
    SELECT provider, MAX(created_at) as last_data_at, COUNT(*) as record_count
    FROM cross_platform_usage
    WHERE org_id = ? AND source = 'otel'
    GROUP BY provider
  `).bind(orgId).all();

  // Include GitHub Copilot connections (stored in copilot_connections, not
  // provider_connections) so the dashboard connections panel shows Copilot status.
  const copilotConnections = await c.env.DB.prepare(`
    SELECT github_org, status, last_synced_at, last_error, created_at
    FROM copilot_connections WHERE org_id = ?
  `).bind(orgId).all();

  const copilotSources = (copilotConnections.results ?? []).map((r: any) => ({
    provider:      'github-copilot',
    github_org:    r.github_org,
    status:        r.status,
    last_synced_at: r.last_synced_at,
    last_error:    isAdmin ? r.last_error : undefined,
    created_at:    r.created_at,
  }));

  // Also include Datadog connections
  const datadogConnections = await c.env.DB.prepare(`
    SELECT datadog_site, status, last_synced_at, last_error, created_at
    FROM datadog_connections WHERE org_id = ? AND status != 'paused'
  `).bind(orgId).all();

  const datadogSources = (datadogConnections.results ?? []).map((r: any) => ({
    provider:      'datadog',
    datadog_site:  r.datadog_site,
    status:        r.status,
    last_synced_at: r.last_synced_at,
    last_error:    isAdmin ? r.last_error : undefined,
    created_at:    r.created_at,
  }));

  // Strip last_error from billing_connections for non-admin roles
  const billingConnections = isAdmin
    ? connections.results
    : (connections.results ?? []).map((r: any) => {
        const { last_error: _ignored, ...rest } = r;
        return rest;
      });

  return c.json({
    billing_connections: billingConnections,
    otel_sources:        otelFreshness.results,
    copilot_connections: copilotSources,
    datadog_connections: datadogSources,
  });
});

// ── GET /budget — budget policies + current spend ───────────────────────────

crossplatform.get('/budget', async (c) => {
  const orgId = c.get('orgId');
  const monthStart = sqliteMonthStart();

  const policies = await c.env.DB.prepare(`
    SELECT id, scope, scope_target, monthly_limit_usd,
           alert_threshold_50, alert_threshold_80, alert_threshold_100,
           enforcement, created_at
    FROM budget_policies WHERE org_id = ?
  `).bind(orgId).all();

  // Current spend per scope
  const orgSpend = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) as spend
    FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, monthStart).first() as { spend: number } | null;

  const teamSpend = await c.env.DB.prepare(`
    SELECT team, COALESCE(SUM(cost_usd), 0) as spend
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND team IS NOT NULL
    GROUP BY team
  `).bind(orgId, monthStart).all();

  const devSpend = await c.env.DB.prepare(`
    SELECT developer_email, COALESCE(SUM(cost_usd), 0) as spend
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email ORDER BY spend DESC LIMIT 50
  `).bind(orgId, monthStart).all();

  return c.json({
    policies: policies.results,
    current_spend: {
      org: orgSpend?.spend ?? 0,
      by_team: teamSpend.results,
      by_developer: devSpend.results,
    },
  });
});

export { crossplatform };
