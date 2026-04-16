import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, hasRole } from '../middleware/auth';
import { logAudit } from '../lib/audit';
import { estimateCacheSavings } from '../lib/pricing';
const analytics = new Hono<{ Bindings: Bindings; Variables: Variables }>();

analytics.use('*', authMiddleware);

// ── Scope helper — appends "AND e.team = ?" when member has a team scope ──────
// Always qualify with table alias "e" to avoid ambiguity when other joined
// tables (e.g. team_budgets) also have a "team" column.
function teamScope(scopeTeam: string | null): { clause: string; args: unknown[] } {
  return scopeTeam
    ? { clause: ' AND e.team = ?', args: [scopeTeam] }
    : { clause: '',                args: [] };
}

// ── GET /v1/analytics/summary ─────────────────────────────────────────────────
analytics.get('/summary', async (c) => {
  const orgId       = c.get('orgId');
  const scopeTeam   = c.get('scopeTeam');
  const role        = c.get('role');
  const memberEmail = c.get('memberEmail');
  const isPrivileged = hasRole(role, 'admin');
  const { clause, args } = teamScope(scopeTeam);
  // Non-admin members only see their own events
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  // Optional agent_name filter — e.g. ?agent=claude-code for integration status checks
  const agentFilter = c.req.query('agent') ?? null;
  const agentClause = agentFilter ? ' AND agent_name = ?' : '';
  const agentArgs   = agentFilter ? [agentFilter] : [];

  // KV cache — 5 min TTL. Agent-filtered requests bypass cache (low-volume, targeted).
  const cacheKey = `analytics:summary:${orgId}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  if (!agentFilter) {
    try {
      const cached = await c.env.KV.get(cacheKey);
      if (cached) return c.json(JSON.parse(cached));
    } catch { /* KV unavailable — continue to DB */ }
  }

  const now        = Math.floor(Date.now() / 1000);
  // Align to UTC midnight so "today" is a calendar day, not a rolling 24-hour window
  const today      = Math.floor(Date.now() / 86_400_000) * 86_400;
  const month      = now - 30 * 86_400;
  const thirty     = now - 30 * 60;

  const [totals, session] = await c.env.DB.batch([
    c.env.DB.prepare(`
      SELECT
        COALESCE(SUM(cost_usd), 0)     AS today_cost_usd,
        COALESCE(SUM(total_tokens), 0) AS today_tokens,
        COALESCE(COUNT(*), 0)          AS today_requests,
        MAX(created_at)                AS last_event_at
      FROM events WHERE org_id = ? AND created_at >= ?${clause}${agentClause}${devClause}
    `).bind(orgId, today, ...args, ...agentArgs, ...devArgs),
    c.env.DB.prepare(`
      SELECT COALESCE(SUM(cost_usd), 0) AS session_cost_usd
      FROM events WHERE org_id = ? AND created_at >= ?${clause}${agentClause}${devClause}
    `).bind(orgId, thirty, ...args, ...agentArgs, ...devArgs),
  ]);

  const mtd = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd
    FROM events WHERE org_id = ? AND created_at >= ?${clause}${agentClause}${devClause}
  `).bind(orgId, month, ...args, ...agentArgs, ...devArgs).first<{ mtd_cost_usd: number }>();

  // Budget: per-team when scoped, org-wide otherwise
  let budgetUsd = 0;
  let orgPlan = 'free';
  if (scopeTeam) {
    const tb = await c.env.DB.prepare(
      'SELECT budget_usd FROM team_budgets WHERE org_id = ? AND team = ?'
    ).bind(orgId, scopeTeam).first<{ budget_usd: number }>();
    budgetUsd = tb?.budget_usd ?? 0;
    const org = await c.env.DB.prepare('SELECT plan FROM orgs WHERE id = ?')
      .bind(orgId).first<{ plan: string }>();
    orgPlan = org?.plan ?? 'free';
  } else {
    const org = await c.env.DB.prepare(
      'SELECT budget_usd, plan FROM orgs WHERE id = ?'
    ).bind(orgId).first<{ budget_usd: number; plan: string }>();
    budgetUsd = org?.budget_usd ?? 0;
    orgPlan = org?.plan ?? 'free';
  }

  const t = totals.results[0] as Record<string, number>;
  const s = (session.results[0] as Record<string, number>) ?? {};
  const budgetPct = budgetUsd > 0
    ? Math.round(((mtd?.mtd_cost_usd ?? 0) / budgetUsd) * 100)
    : null; // null = no budget set; 0 = budget set but 0% used

  const result = {
    today_cost_usd:   t?.today_cost_usd   ?? 0,
    today_tokens:     t?.today_tokens     ?? 0,
    today_requests:   t?.today_requests   ?? 0,
    last_event_at:    t?.last_event_at    ?? null,
    // Aliases used by SDK privacy tests and cross-platform clients
    total_cost_usd:   t?.today_cost_usd   ?? 0,
    total_tokens:     t?.today_tokens     ?? 0,
    total_events:     t?.today_requests   ?? 0,
    mtd_cost_usd:     mtd?.mtd_cost_usd   ?? 0,
    session_cost_usd: s?.session_cost_usd ?? 0,
    budget_pct:       budgetPct,
    budget_usd:       budgetUsd,
    plan:             orgPlan,
    scope_team:       scopeTeam ?? null,
  };
  if (!agentFilter) {
    try { await c.env.KV.put(cacheKey, JSON.stringify(result), { expirationTtl: 300 }); } catch { /* best-effort */ }
  }
  logAudit(c, { event_type: 'data_access', event_name: 'data_access.analytics', resource_type: 'analytics', metadata: { endpoint: '/v1/analytics/summary' } });
  return c.json(result);
});

// ── GET /v1/analytics/kpis?period=30 ─────────────────────────────────────────
analytics.get('/kpis', async (c) => {
  const orgId       = c.get('orgId');
  const scopeTeam   = c.get('scopeTeam');
  const role        = c.get('role');
  const memberEmail = c.get('memberEmail');
  const isPrivileged = hasRole(role, 'admin');
  const { clause, args } = teamScope(scopeTeam);
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  // Align to UTC midnight: show today + previous (period-1) days = exactly `period` calendar days
  const since  = Math.floor(Date.now() / 86_400_000) * 86_400 - (period - 1) * 86_400;

  const kpisCacheKey = `analytics:kpis:${orgId}:${period}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  try {
    const cached = await c.env.KV.get(kpisCacheKey);
    if (cached) return c.json(JSON.parse(cached));
  } catch { /* KV unavailable */ }

  const row = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0)                   AS total_cost_usd,
      COALESCE(SUM(total_tokens), 0)               AS total_tokens,
      COALESCE(COUNT(*), 0)                        AS total_requests,
      COALESCE(AVG(latency_ms), 0)                 AS avg_latency_ms,
      AVG(efficiency_score)                        AS efficiency_score,
      AVG(hallucination_score)                     AS avg_hallucination_score,
      AVG(faithfulness_score)                      AS avg_faithfulness_score,
      AVG(relevancy_score)                         AS avg_relevancy_score,
      AVG(toxicity_score)                          AS avg_toxicity_score,
      COUNT(CASE WHEN hallucination_score IS NOT NULL THEN 1 END) AS scored_events,
      COALESCE(SUM(CASE WHEN is_streaming=1 THEN 1 ELSE 0 END), 0) AS streaming_requests,
      COALESCE(SUM(prompt_tokens), 0)              AS total_prompt_tokens,
      COALESCE(SUM(cache_tokens), 0)               AS cache_tokens_total,
      COALESCE(SUM(CASE WHEN cache_hit=1 THEN 1 ELSE 0 END), 0)        AS duplicate_calls,
      COALESCE(SUM(CASE WHEN cache_hit=1 THEN cost_usd ELSE 0 END), 0) AS wasted_cost_usd
    FROM events WHERE org_id = ? AND created_at >= ?${clause}${devClause}
  `).bind(orgId, since, ...args, ...devArgs).first<Record<string, number>>();

  // Compute cache savings per model (rate varies by model, can't be done in SQL alone)
  const { results: cacheByModel } = await c.env.DB.prepare(`
    SELECT model, COALESCE(SUM(cache_tokens), 0) AS cache_tokens, COALESCE(SUM(total_tokens), 0) AS tokens
    FROM events WHERE org_id = ? AND created_at >= ?${clause}${devClause}
    GROUP BY model
  `).bind(orgId, since, ...args, ...devArgs).all<{ model: string; cache_tokens: number; tokens: number }>();

  const totalCacheTokens  = (row?.cache_tokens_total ?? 0) as number;
  const totalPromptTokens = (row?.total_prompt_tokens ?? 0) as number;
  const cacheSavingsUsd   = cacheByModel.reduce((sum, r) => sum + estimateCacheSavings(r.model, r.cache_tokens), 0);
  // cache_hit_rate_pct: cached input tokens as a % of total input tokens (prompt tokens only, not output)
  const cacheHitRatePct   = totalPromptTokens > 0 ? Math.round((totalCacheTokens / totalPromptTokens) * 1000) / 10 : 0;

  const kpisResult = {
    total_cost_usd:           (row?.total_cost_usd ?? 0) as number,
    total_tokens:             (row?.total_tokens ?? 0) as number,
    total_requests:           (row?.total_requests ?? 0) as number,
    avg_latency_ms:           (row?.avg_latency_ms ?? 0) as number,
    // null when no events have been scored — never substitute a fake default
    efficiency_score:         row?.efficiency_score != null ? (row.efficiency_score as number) : null,
    streaming_requests:       (row?.streaming_requests ?? 0) as number,
    cache_tokens_total:       totalCacheTokens,
    duplicate_calls:          (row?.duplicate_calls ?? 0) as number,
    wasted_cost_usd:          Math.round(((row?.wasted_cost_usd ?? 0) as number) * 1e6) / 1e6,
    cache_savings_usd:        Math.round(cacheSavingsUsd * 1e6) / 1e6,
    cache_hit_rate_pct:       cacheHitRatePct,
    // Quality score aggregates — null when no events have been scored yet
    quality: {
      avg_hallucination_score: row?.avg_hallucination_score != null ? Math.round((row.avg_hallucination_score as number) * 1000) / 1000 : null,
      avg_faithfulness_score:  row?.avg_faithfulness_score  != null ? Math.round((row.avg_faithfulness_score  as number) * 1000) / 1000 : null,
      avg_relevancy_score:     row?.avg_relevancy_score     != null ? Math.round((row.avg_relevancy_score     as number) * 1000) / 1000 : null,
      avg_toxicity_score:      row?.avg_toxicity_score      != null ? Math.round((row.avg_toxicity_score      as number) * 1000) / 1000 : null,
      scored_events:           (row?.scored_events ?? 0) as number,
      coverage_pct:            (row?.total_requests ?? 0) > 0
        ? Math.round(((row?.scored_events ?? 0) as number) / ((row?.total_requests as number)) * 1000) / 10
        : 0,
    },
  };
  try { await c.env.KV.put(kpisCacheKey, JSON.stringify(kpisResult), { expirationTtl: 300 }); } catch { /* best-effort */ }
  logAudit(c, { event_type: 'data_access', event_name: 'data_access.analytics', resource_type: 'analytics', metadata: { endpoint: '/v1/analytics/kpis' } });
  return c.json(kpisResult);
});

// ── GET /v1/analytics/timeseries?period=30 ───────────────────────────────────
analytics.get('/timeseries', async (c) => {
  const orgId       = c.get('orgId');
  const scopeTeam   = c.get('scopeTeam');
  const role        = c.get('role');
  const memberEmail = c.get('memberEmail');
  const isPrivileged = hasRole(role, 'admin');
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  // Align to UTC midnight: show today + previous (period-1) days = exactly `period` calendar days
  const todayMidnightMs = Math.floor(Date.now() / 86_400_000) * 86_400_000;
  const sinceMs = todayMidnightMs - (period - 1) * 86_400_000;
  const since = new Date(sinceMs).toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  const tsCacheKey = `analytics:timeseries:${orgId}:${period}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  try {
    const cached = await c.env.KV.get(tsCacheKey);
    if (cached) return c.json(JSON.parse(cached));
  } catch { /* KV unavailable */ }

  // cross_platform_usage.created_at is a TEXT datetime ('YYYY-MM-DD HH:MM:SS' UTC)
  // DATE(created_at) extracts the UTC date string directly — no unixepoch needed.
  const { results } = await c.env.DB.prepare(`
    SELECT
      DATE(created_at)                          AS date,
      SUM(cost_usd)                             AS cost_usd,
      SUM(input_tokens + output_tokens)         AS tokens,
      COUNT(*)                                  AS requests
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?${teamClause}${devClause}
    GROUP BY date
    ORDER BY date ASC
  `).bind(orgId, since, ...teamArgs, ...devArgs).all();

  const tsResult = { period, series: results };
  try { await c.env.KV.put(tsCacheKey, JSON.stringify(tsResult), { expirationTtl: 300 }); } catch { /* best-effort */ }
  logAudit(c, { event_type: 'data_access', event_name: 'data_access.analytics', resource_type: 'analytics', metadata: { endpoint: '/v1/analytics/timeseries' } });
  return c.json(tsResult);
});

// ── GET /v1/analytics/models?period=30 ───────────────────────────────────────
analytics.get('/models', async (c) => {
  const orgId       = c.get('orgId');
  const scopeTeam   = c.get('scopeTeam');
  const role        = c.get('role');
  const memberEmail = c.get('memberEmail');
  const isPrivileged = hasRole(role, 'admin');
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const todayMidnightMs = Math.floor(Date.now() / 86_400_000) * 86_400_000;
  const sinceMs = todayMidnightMs - (period - 1) * 86_400_000;
  const since = new Date(sinceMs).toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  const { results } = await c.env.DB.prepare(`
    SELECT
      model, provider,
      SUM(cost_usd)                     AS cost_usd,
      SUM(input_tokens + output_tokens) AS tokens,
      COUNT(*)                          AS requests,
      AVG(latency_ms)                   AS avg_latency_ms
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?${teamClause}${devClause}
    GROUP BY model, provider
    ORDER BY cost_usd DESC
    LIMIT 25
  `).bind(orgId, since, ...teamArgs, ...devArgs).all();

  logAudit(c, { event_type: 'data_access', event_name: 'data_access.analytics', resource_type: 'analytics', metadata: { endpoint: '/v1/analytics/models' } });
  return c.json({ models: results });
});

// ── GET /v1/analytics/teams?period=30 ────────────────────────────────────────
// Members with scope_team set see only their own team row + its budget.
// Admins/owners see all teams + budgets.
analytics.get('/teams', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const since  = Math.floor(Date.now() / 86_400_000) * 86_400 - (period - 1) * 86_400;

  const { results } = await c.env.DB.prepare(`
    SELECT
      COALESCE(e.team, 'unassigned') AS team,
      SUM(e.cost_usd)                AS cost_usd,
      SUM(e.total_tokens)            AS tokens,
      COUNT(*)                       AS requests,
      COALESCE(b.budget_usd, bp.monthly_limit_usd, 0) AS budget_usd,
      CASE WHEN COALESCE(b.budget_usd, bp.monthly_limit_usd, 0) > 0
        THEN ROUND(SUM(e.cost_usd) / COALESCE(b.budget_usd, bp.monthly_limit_usd) * 100, 1)
        ELSE NULL
      END AS budget_pct
    FROM events e
    LEFT JOIN team_budgets b ON b.org_id = e.org_id AND b.team = e.team
    LEFT JOIN budget_policies bp ON bp.org_id = e.org_id AND bp.scope = 'team' AND bp.scope_target = e.team
    WHERE e.org_id = ? AND e.created_at >= ?${clause}
    GROUP BY e.team
    ORDER BY cost_usd DESC
    LIMIT 20
  `).bind(orgId, since, ...args).all();

  return c.json({ teams: results });
});

// ── GET /v1/analytics/business-units — spend per business unit ────────────────
analytics.get('/business-units', async (c) => {
  const orgId  = c.get('orgId');
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const sinceIso  = new Date(Date.now() - period * 86_400_000).toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
  const sinceUnix = Math.floor(Date.now() / 1000) - period * 86_400;

  // UNION events + cross_platform_usage for complete picture
  const { results } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT
        COALESCE(business_unit, cost_center, 'unassigned') AS business_unit,
        team,
        provider,
        cost_usd,
        input_tokens + output_tokens AS tokens,
        lines_added,
        commits,
        pull_requests
      FROM cross_platform_usage
      WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT
        COALESCE(business_unit, 'unassigned') AS business_unit,
        team,
        model AS provider,
        cost_usd,
        prompt_tokens + completion_tokens AS tokens,
        0 AS lines_added,
        0 AS commits,
        0 AS pull_requests
      FROM events
      WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT
      business_unit,
      COALESCE(SUM(cost_usd), 0)            AS cost_usd,
      COALESCE(SUM(tokens), 0)              AS tokens,
      COUNT(*)                              AS records,
      COALESCE(SUM(commits), 0)            AS commits,
      COALESCE(SUM(pull_requests), 0)      AS pull_requests,
      COALESCE(SUM(lines_added), 0)        AS lines_added,
      COUNT(DISTINCT team)                  AS team_count
    FROM all_usage
    GROUP BY business_unit
    ORDER BY cost_usd DESC
    LIMIT 50
  `).bind(orgId, sinceIso, orgId, sinceUnix).all();

  // Per-business-unit team breakdown
  const { results: byTeam } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT COALESCE(business_unit, cost_center, 'unassigned') AS business_unit,
             team, provider, cost_usd
      FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT COALESCE(business_unit, 'unassigned') AS business_unit,
             team, model AS provider, cost_usd
      FROM events WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT business_unit,
           COALESCE(team, 'unassigned') AS team,
           provider,
           SUM(cost_usd) AS cost_usd
    FROM all_usage
    GROUP BY business_unit, team, provider
    ORDER BY cost_usd DESC
    LIMIT 200
  `).bind(orgId, sinceIso, orgId, sinceUnix).all();

  return c.json({ business_units: results, by_team_provider: byTeam, period_days: period });
});

// ── GET /v1/analytics/traces?period=1 ────────────────────────────────────────
analytics.get('/traces', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '1', 10) || 1, 30);
  const since  = Math.floor(Date.now() / 86_400_000) * 86_400 - (period - 1) * 86_400;

  const { results } = await c.env.DB.prepare(`
    SELECT
      trace_id,
      MIN(agent_name)      AS name,
      COUNT(*)             AS spans,
      SUM(cost_usd)        AS cost,
      SUM(latency_ms)      AS latency,
      MAX(CASE WHEN parent_event_id IS NULL THEN 1 ELSE 0 END) AS has_root,
      MIN(created_at)      AS started_at
    FROM events
    WHERE org_id = ? AND trace_id IS NOT NULL AND created_at >= ?${clause}
    GROUP BY trace_id
    ORDER BY started_at DESC
    LIMIT 100
  `).bind(orgId, since, ...args).all();

  return c.json({ traces: results });
});

// ── GET /v1/analytics/today — hourly spend for the current UTC day ───────────
analytics.get('/today', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const todayStr = new Date().toISOString().split('T')[0] + ' 00:00:00';

  const { results } = await c.env.DB.prepare(`
    SELECT
      CAST(strftime('%H', created_at) AS INTEGER) AS hour,
      SUM(cost_usd)                               AS cost_usd,
      SUM(input_tokens + output_tokens)           AS tokens,
      COUNT(*)                                    AS requests
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?${teamClause}
    GROUP BY hour
    ORDER BY hour ASC
  `).bind(orgId, todayStr, ...teamArgs).all();

  return c.json({ date: todayStr.slice(0, 10), hours: results });
});

// ── GET /v1/analytics/cost — CI cost gate ────────────────────────────────────
analytics.get('/cost', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '7', 10) || 7, 30);
  const since  = Math.floor(Date.now() / 86_400_000) * 86_400 - (period - 1) * 86_400;
  const today  = Math.floor(Date.now() / 86_400_000) * 86_400;

  const [total, todayRow] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events WHERE org_id=? AND created_at>=?${clause}`
    ).bind(orgId, since, ...args),
    c.env.DB.prepare(
      `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events WHERE org_id=? AND created_at>=?${clause}`
    ).bind(orgId, today, ...args),
  ]);

  return c.json({
    total_cost_usd: (total.results[0] as Record<string, number>)?.cost ?? 0,
    today_cost_usd: (todayRow.results[0] as Record<string, number>)?.cost ?? 0,
    period_days:    period,
  });
});

export { analytics };
