/**
 * VantageAI — Cross-Platform Cost API
 *
 * Serves aggregated data from OTel telemetry + billing APIs.
 * Powers the "All AI Spend" dashboard with live/near-real-time data.
 *
 * Endpoints:
 *   GET /v1/cross-platform/summary        — total spend, by provider, by tool type
 *   GET /v1/cross-platform/developers     — per-developer spend table
 *   GET /v1/cross-platform/developer/:email — single developer drill-down
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
function sqliteDateSince(days: number): string {
  const d = new Date(Date.now() - days * 86400000);
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

// ── GET /summary — total spend across all platforms ─────────────────────────

crossplatform.get('/summary', async (c) => {
  const orgId = c.get('orgId');
  const days = parseInt(c.req.query('days') ?? '30', 10);
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
  const days = parseInt(c.req.query('days') ?? '30', 10);
  const since = sqliteDateSince(days);

  const developers = await c.env.DB.prepare(`
    SELECT
      developer_email,
      COALESCE(SUM(cost_usd), 0) as total_cost,
      COALESCE(SUM(input_tokens), 0) as input_tokens,
      COALESCE(SUM(output_tokens), 0) as output_tokens,
      COALESCE(SUM(commits), 0) as commits,
      COALESCE(SUM(pull_requests), 0) as pull_requests,
      COALESCE(SUM(lines_added), 0) as lines_added,
      COALESCE(SUM(lines_removed), 0) as lines_removed,
      COALESCE(SUM(active_time_s), 0) as active_time_s,
      COUNT(DISTINCT provider) as providers_used,
      GROUP_CONCAT(DISTINCT provider) as providers,
      COUNT(*) as records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email
    ORDER BY total_cost DESC
  `).bind(orgId, since).all();

  // Calculate ROI metrics per developer
  const devList = (developers.results ?? []).map((d: any) => {
    const costPerPR = d.pull_requests > 0 ? (d.total_cost / d.pull_requests) : null;
    const costPerCommit = d.commits > 0 ? (d.total_cost / d.commits) : null;
    const linesPerDollar = d.total_cost > 0 ? Math.round((d.lines_added + d.lines_removed) / d.total_cost) : null;
    return {
      ...d,
      providers: d.providers ? d.providers.split(',') : [],
      cost_per_pr: costPerPR ? Math.round(costPerPR * 100) / 100 : null,
      cost_per_commit: costPerCommit ? Math.round(costPerCommit * 100) / 100 : null,
      lines_per_dollar: linesPerDollar,
    };
  });

  return c.json({ period_days: days, developers: devList });
});

// ── GET /developer/:email — single developer drill-down ─────────────────────

crossplatform.get('/developer/:email', async (c) => {
  const orgId = c.get('orgId');
  const email = decodeURIComponent(c.req.param('email'));
  const days = parseInt(c.req.query('days') ?? '30', 10);
  const since = sqliteDateSince(days);

  // By provider
  const byProvider = await c.env.DB.prepare(`
    SELECT provider,
      COALESCE(SUM(cost_usd), 0) as cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) as tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_email = ? AND created_at >= ?
    GROUP BY provider ORDER BY cost DESC
  `).bind(orgId, email, since).all();

  // By model
  const byModel = await c.env.DB.prepare(`
    SELECT model,
      COALESCE(SUM(cost_usd), 0) as cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) as tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_email = ? AND created_at >= ? AND model IS NOT NULL
    GROUP BY model ORDER BY cost DESC LIMIT 10
  `).bind(orgId, email, since).all();

  // Daily trend
  const daily = await c.env.DB.prepare(`
    SELECT DATE(created_at) as day,
      COALESCE(SUM(cost_usd), 0) as cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) as tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_email = ? AND created_at >= ?
    GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 30
  `).bind(orgId, email, since).all();

  // Productivity (from OTel data)
  const productivity = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(commits), 0) as commits,
      COALESCE(SUM(pull_requests), 0) as pull_requests,
      COALESCE(SUM(lines_added), 0) as lines_added,
      COALESCE(SUM(lines_removed), 0) as lines_removed,
      COALESCE(SUM(active_time_s), 0) as active_time_s
    FROM cross_platform_usage
    WHERE org_id = ? AND developer_email = ? AND created_at >= ?
  `).bind(orgId, email, since).first();

  return c.json({
    email,
    period_days: days,
    by_provider: byProvider.results,
    by_model: byModel.results,
    daily_trend: daily.results,
    productivity,
  });
});

// ── GET /live — latest OTel events for real-time feed ───────────────────────

crossplatform.get('/live', async (c) => {
  const orgId = c.get('orgId');
  const limit = Math.min(parseInt(c.req.query('limit') ?? '50', 10), 200);

  const events = await c.env.DB.prepare(`
    SELECT
      provider, developer_email, model, event_name,
      cost_usd, tokens_in, tokens_out, duration_ms, timestamp
    FROM otel_events
    WHERE org_id = ?
    ORDER BY timestamp DESC
    LIMIT ?
  `).bind(orgId, limit).all();

  return c.json({ events: events.results });
});

// ── GET /models — cost by model across all providers ────────────────────────

crossplatform.get('/models', async (c) => {
  const orgId = c.get('orgId');
  const days = parseInt(c.req.query('days') ?? '30', 10);
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

  return c.json({
    billing_connections: connections.results,
    otel_sources: otelFreshness.results,
  });
});

// ── GET /budget — budget policies + current spend ───────────────────────────

crossplatform.get('/budget', async (c) => {
  const orgId = c.get('orgId');
  const monthStart = sqliteMonthStart();

  const policies = await c.env.DB.prepare(`
    SELECT * FROM budget_policies WHERE org_id = ?
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
