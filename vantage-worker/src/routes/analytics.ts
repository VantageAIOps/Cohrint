import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const analytics = new Hono<{ Bindings: Bindings; Variables: Variables }>();

analytics.use('*', authMiddleware);

// Log every analytics read as a data_access event (fire-and-forget after response)
analytics.use('*', async (c, next) => {
  await next();
  logAudit(c, {
    event_type:    'data_access',
    event_name:    'data_access.analytics',
    resource_type: 'analytics',
    metadata:      { endpoint: c.req.path },
  });
});

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
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);

  const now   = Math.floor(Date.now() / 1000);
  const today = now - 86_400;
  const month = now - 30 * 86_400;
  const thirty = now - 30 * 60;

  const [totals, session] = await c.env.DB.batch([
    c.env.DB.prepare(`
      SELECT
        COALESCE(SUM(cost_usd), 0)     AS today_cost_usd,
        COALESCE(SUM(total_tokens), 0) AS today_tokens,
        COALESCE(COUNT(*), 0)          AS today_requests
      FROM events WHERE org_id = ? AND created_at >= ?${clause}
    `).bind(orgId, today, ...args),
    c.env.DB.prepare(`
      SELECT COALESCE(SUM(cost_usd), 0) AS session_cost_usd
      FROM events WHERE org_id = ? AND created_at >= ?${clause}
    `).bind(orgId, thirty, ...args),
  ]);

  const mtd = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd
    FROM events WHERE org_id = ? AND created_at >= ?${clause}
  `).bind(orgId, month, ...args).first<{ mtd_cost_usd: number }>();

  // Budget: per-team when scoped, org-wide otherwise
  let budgetUsd = 0;
  if (scopeTeam) {
    const tb = await c.env.DB.prepare(
      'SELECT budget_usd FROM team_budgets WHERE org_id = ? AND team = ?'
    ).bind(orgId, scopeTeam).first<{ budget_usd: number }>();
    budgetUsd = tb?.budget_usd ?? 0;
  } else {
    const org = await c.env.DB.prepare(
      'SELECT budget_usd, plan FROM orgs WHERE id = ?'
    ).bind(orgId).first<{ budget_usd: number; plan: string }>();
    budgetUsd = org?.budget_usd ?? 0;
  }

  const org = await c.env.DB.prepare('SELECT plan FROM orgs WHERE id = ?')
    .bind(orgId).first<{ plan: string }>();

  const t = totals.results[0] as Record<string, number>;
  const s = (session.results[0] as Record<string, number>) ?? {};
  const budgetPct = budgetUsd
    ? Math.round(((mtd?.mtd_cost_usd ?? 0) / budgetUsd) * 100)
    : 0;

  return c.json({
    today_cost_usd:   t?.today_cost_usd   ?? 0,
    today_tokens:     t?.today_tokens     ?? 0,
    today_requests:   t?.today_requests   ?? 0,
    mtd_cost_usd:     mtd?.mtd_cost_usd   ?? 0,
    session_cost_usd: s?.session_cost_usd ?? 0,
    budget_pct:       budgetPct,
    budget_usd:       budgetUsd,
    plan:             org?.plan ?? 'free',
    scope_team:       scopeTeam ?? null,
  });
});

// ── GET /v1/analytics/kpis?period=30 ─────────────────────────────────────────
analytics.get('/kpis', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  const row = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0)                   AS total_cost_usd,
      COALESCE(SUM(total_tokens), 0)               AS total_tokens,
      COALESCE(COUNT(*), 0)                        AS total_requests,
      COALESCE(AVG(latency_ms), 0)                 AS avg_latency_ms,
      COALESCE(AVG(efficiency_score), 74)          AS efficiency_score,
      COALESCE(SUM(CASE WHEN is_streaming=1 THEN 1 ELSE 0 END), 0) AS streaming_requests
    FROM events WHERE org_id = ? AND created_at >= ?${clause}
  `).bind(orgId, since, ...args).first();

  return c.json(row ?? {});
});

// ── GET /v1/analytics/timeseries?period=30 ───────────────────────────────────
analytics.get('/timeseries', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  const { results } = await c.env.DB.prepare(`
    SELECT
      DATE(created_at, 'unixepoch') AS date,
      SUM(cost_usd)                 AS cost_usd,
      SUM(total_tokens)             AS tokens,
      COUNT(*)                      AS requests
    FROM events
    WHERE org_id = ? AND created_at >= ?${clause}
    GROUP BY date
    ORDER BY date ASC
  `).bind(orgId, since, ...args).all();

  return c.json({ period, series: results });
});

// ── GET /v1/analytics/models?period=30 ───────────────────────────────────────
analytics.get('/models', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  const { results } = await c.env.DB.prepare(`
    SELECT
      model, provider,
      SUM(cost_usd)      AS cost_usd,
      SUM(total_tokens)  AS tokens,
      COUNT(*)           AS requests,
      AVG(latency_ms)    AS avg_latency_ms,
      SUM(CASE WHEN is_streaming=1 THEN 1 ELSE 0 END) AS streaming_count
    FROM events
    WHERE org_id = ? AND created_at >= ?${clause}
    GROUP BY model, provider
    ORDER BY cost_usd DESC
    LIMIT 25
  `).bind(orgId, since, ...args).all();

  return c.json({ models: results });
});

// ── GET /v1/analytics/teams?period=30 ────────────────────────────────────────
// Members with scope_team set see only their own team row + its budget.
// Admins/owners see all teams + budgets.
analytics.get('/teams', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  const { results } = await c.env.DB.prepare(`
    SELECT
      COALESCE(e.team, 'unassigned') AS team,
      SUM(e.cost_usd)                AS cost_usd,
      SUM(e.total_tokens)            AS tokens,
      COUNT(*)                       AS requests,
      COALESCE(b.budget_usd, 0)      AS budget_usd,
      CASE WHEN b.budget_usd > 0
        THEN ROUND(SUM(e.cost_usd) / b.budget_usd * 100, 1)
        ELSE NULL
      END AS budget_pct
    FROM events e
    LEFT JOIN team_budgets b ON b.org_id = e.org_id AND b.team = e.team
    WHERE e.org_id = ? AND e.created_at >= ?${clause}
    GROUP BY e.team
    ORDER BY cost_usd DESC
    LIMIT 20
  `).bind(orgId, since, ...args).all();

  return c.json({ teams: results });
});

// ── GET /v1/analytics/traces?period=1 ────────────────────────────────────────
analytics.get('/traces', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '1', 10), 30);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

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

// ── GET /v1/analytics/cost — CI cost gate ────────────────────────────────────
analytics.get('/cost', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '7', 10), 30);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;
  const today  = Math.floor(Date.now() / 1000) - 86_400;

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
