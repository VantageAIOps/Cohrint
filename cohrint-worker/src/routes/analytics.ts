import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, hasRole } from '../middleware/auth';
import { logAudit } from '../lib/audit';
import { estimateCacheSavings } from '../lib/pricing';
import { scopedDb } from '../lib/db';
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

// ── Date helpers ──────────────────────────────────────────────────────────────
// created_at column types diverge by table:
//   events / orgs / org_members / platform_*       → INTEGER unixepoch  (use *Unix)
//   cross_platform_usage / otel_events / audit_*   → TEXT 'YYYY-MM-DD HH:MM:SS'  (use *Text)
// Binding the wrong side silently coerces to 0 and returns ALL rows instead
// of the filtered window, so pick per-table.
function sinceText(periodDays: number): string {
  const d = new Date(Date.now() - (periodDays - 1) * 86_400_000);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString().replace('T', ' ').slice(0, 19);
}
function sinceUnix(periodDays: number): number {
  const d = new Date(Date.now() - (periodDays - 1) * 86_400_000);
  d.setUTCHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
}
function todayUnix(): number {
  const d = new Date();
  d.setUTCHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
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
  // Agent-filtered requests fall back to raw events (rollup has no agent_name column)
  const agentFilter = c.req.query('agent') ?? null;
  const agentClause = agentFilter ? ' AND agent_name = ?' : '';
  const agentArgs   = agentFilter ? [agentFilter] : [];

  // KV cache — 2 min TTL (reduced from 5 min since rollup data is already aggregated).
  // Agent-filtered requests bypass cache (low-volume, targeted).
  const cacheKey = `analytics:summary:${orgId}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  if (!agentFilter) {
    try {
      const cached = await c.env.KV.get(cacheKey);
      if (cached) return c.json(JSON.parse(cached));
    } catch { /* KV unavailable — continue to DB */ }
  }

  const today      = todayUnix();
  const month      = sinceUnix(30);
  const thirty     = Math.floor((Date.now() - 30 * 60_000) / 1000);

  const sdb = scopedDb(c.env.DB, orgId);

  // Rollup team scope uses plain `team` column (no table alias needed — single table)
  const rollupTeamClause = scopeTeam ? ' AND team = ?' : '';
  const rollupTeamArgs   = scopeTeam ? [scopeTeam] : [];

  // Use rollup for today + MTD aggregates (fast, pre-aggregated).
  // Session (30-min window) stays on raw events — too short for daily rollup.
  // Agent-filter fallback also uses raw events since rollup has no agent_name column.
  let totals: D1Result;
  let mtd: { mtd_cost_usd: number } | null;

  if (agentFilter) {
    // Agent-filtered path: raw events table
    [totals] = await c.env.DB.batch([
      sdb.prepare(`
        SELECT
          COALESCE(SUM(cost_usd), 0)     AS today_cost_usd,
          COALESCE(SUM(total_tokens), 0) AS today_tokens,
          COALESCE(COUNT(*), 0)          AS today_requests,
          MAX(created_at)                AS last_event_at
        FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${agentClause}${devClause}
      `).bind(today, ...args, ...agentArgs, ...devArgs),
    ]);
    mtd = await sdb.prepare(`
      SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd
      FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${agentClause}${devClause}
    `).bind(month, ...args, ...agentArgs, ...devArgs).first<{ mtd_cost_usd: number }>();
  } else {
    // Normal path: use rollup for today + MTD
    // Rollup has no developer_email or agent_name — privileged users only for rollup path.
    // Non-privileged members fall back to raw events so dev-scoping is preserved.
    if (!isPrivileged) {
      // Fall back to raw events for member-scoped queries (rollup has no developer_email)
      [totals] = await c.env.DB.batch([
        sdb.prepare(`
          SELECT
            COALESCE(SUM(cost_usd), 0)     AS today_cost_usd,
            COALESCE(SUM(total_tokens), 0) AS today_tokens,
            COALESCE(COUNT(*), 0)          AS today_requests,
            MAX(created_at)                AS last_event_at
          FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
        `).bind(today, ...args, ...devArgs),
      ]);
      mtd = await sdb.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd
        FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
      `).bind(month, ...args, ...devArgs).first<{ mtd_cost_usd: number }>();
    } else {
      // Privileged users: query rollup directly
      [totals] = await c.env.DB.batch([
        sdb.prepare(`
          SELECT
            COALESCE(SUM(cost_usd), 0)     AS today_cost_usd,
            COALESCE(SUM(total_tokens), 0) AS today_tokens,
            COALESCE(SUM(requests), 0)     AS today_requests,
            NULL                           AS last_event_at
          FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day = ?${rollupTeamClause}
        `).bind(today, ...rollupTeamArgs),
      ]);
      mtd = await sdb.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd
        FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day >= ?${rollupTeamClause}
      `).bind(month, ...rollupTeamArgs).first<{ mtd_cost_usd: number }>();
    }
  }

  // last_event_at for privileged rollup path: fetch from raw events (single cheap query)
  let lastEventAt: number | null = null;
  if (isPrivileged && !agentFilter) {
    const lastRow = await sdb.prepare(`
      SELECT MAX(created_at) AS last_event_at FROM events WHERE {{ORG_SCOPE}}${rollupTeamClause}
    `).bind(...rollupTeamArgs).first<{ last_event_at: number | null }>();
    lastEventAt = lastRow?.last_event_at ?? null;
  } else {
    lastEventAt = ((totals.results[0] as Record<string, number>)?.last_event_at as number) ?? null;
  }

  // Session (30-min window) always on raw events
  const session = await sdb.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS session_cost_usd
    FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${agentClause}${devClause}
  `).bind(thirty, ...args, ...agentArgs, ...devArgs).first<{ session_cost_usd: number }>();

  // Budget: per-team when scoped, org-wide otherwise
  let budgetUsd = 0;
  let orgPlan = 'free';
  if (scopeTeam) {
    const tb = await sdb.prepare(
      'SELECT budget_usd FROM team_budgets WHERE {{ORG_SCOPE}} AND team = ?'
    ).bind(scopeTeam).first<{ budget_usd: number }>();
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

  const t = (totals.results[0] ?? {}) as Record<string, number>;
  const budgetPct = budgetUsd > 0
    ? Math.round(((mtd?.mtd_cost_usd ?? 0) / budgetUsd) * 100)
    : null; // null = no budget set; 0 = budget set but 0% used

  // Cost forecasting — project MTD spend to month end
  const now = new Date();
  const daysElapsed = Math.max(now.getUTCDate(), 1);
  const daysInMonth = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate();
  const mtdCost = mtd?.mtd_cost_usd ?? 0;
  const dailyAvgCostUsd = Math.round((mtdCost / daysElapsed) * 1_000_000) / 1_000_000;
  const projectedMonthEndUsd = Math.round(dailyAvgCostUsd * daysInMonth * 1_000_000) / 1_000_000;
  // Days until budget exhausted: (budget - mtd) / daily_avg; null if no budget or no spend rate
  let daysUntilBudgetExhausted: number | null = null;
  if (budgetUsd > 0 && dailyAvgCostUsd > 0) {
    const remaining = budgetUsd - mtdCost;
    daysUntilBudgetExhausted = remaining <= 0 ? 0 : Math.ceil(remaining / dailyAvgCostUsd);
  }

  const result = {
    today_cost_usd:              t?.today_cost_usd   ?? 0,
    today_tokens:                t?.today_tokens     ?? 0,
    today_requests:              t?.today_requests   ?? 0,
    last_event_at:               lastEventAt,
    // Aliases used by SDK privacy tests and cross-platform clients
    total_cost_usd:              t?.today_cost_usd   ?? 0,
    total_tokens:                t?.today_tokens     ?? 0,
    total_events:                t?.today_requests   ?? 0,
    mtd_cost_usd:                mtd?.mtd_cost_usd   ?? 0,
    session_cost_usd:            session?.session_cost_usd ?? 0,
    budget_pct:                  budgetPct,
    budget_usd:                  budgetUsd,
    plan:                        orgPlan,
    scope_team:                  scopeTeam ?? null,
    // Forecast fields
    daily_avg_cost_usd:          dailyAvgCostUsd,
    projected_month_end_usd:     projectedMonthEndUsd,
    days_until_budget_exhausted: daysUntilBudgetExhausted,
  };
  if (!agentFilter) {
    // 2 min TTL (was 5 min) — rollup data is already aggregated, slightly fresher
    try { await c.env.KV.put(cacheKey, JSON.stringify(result), { expirationTtl: 120 }); } catch { /* best-effort */ }
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
  const since  = sinceUnix(period);

  const kpisCacheKey = `analytics:kpis:${orgId}:${period}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  try {
    const cached = await c.env.KV.get(kpisCacheKey);
    if (cached) return c.json(JSON.parse(cached));
  } catch { /* KV unavailable */ }

  const sdb = scopedDb(c.env.DB, orgId);
  const rollupTeamClause = scopeTeam ? ' AND team = ?' : '';
  const rollupTeamArgs   = scopeTeam ? [scopeTeam] : [];

  // Privileged users: use rollup for aggregate counts + latency avg.
  // Non-privileged: fall back to raw events (rollup has no developer_email).
  // Quality scores (hallucination, faithfulness, etc.) always come from raw events.
  let rollupRow: Record<string, number> | null = null;
  let rawRow: Record<string, number> | null = null;

  if (isPrivileged) {
    rollupRow = await sdb.prepare(`
      SELECT
        COALESCE(SUM(cost_usd), 0)                              AS total_cost_usd,
        COALESCE(SUM(total_tokens), 0)                          AS total_tokens,
        COALESCE(SUM(requests), 0)                              AS total_requests,
        CAST(SUM(latency_ms_sum) AS REAL) / NULLIF(SUM(requests), 0) AS avg_latency_ms,
        COALESCE(SUM(prompt_tokens), 0)                         AS total_prompt_tokens,
        COALESCE(SUM(cache_tokens), 0)                          AS cache_tokens_total,
        COALESCE(SUM(cache_hits), 0)                            AS duplicate_calls
      FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day >= ?${rollupTeamClause}
    `).bind(since, ...rollupTeamArgs).first<Record<string, number>>();
  } else {
    rawRow = await sdb.prepare(`
      SELECT
        COALESCE(SUM(cost_usd), 0)                   AS total_cost_usd,
        COALESCE(SUM(total_tokens), 0)               AS total_tokens,
        COALESCE(COUNT(*), 0)                        AS total_requests,
        COALESCE(AVG(latency_ms), 0)                 AS avg_latency_ms,
        COALESCE(SUM(prompt_tokens), 0)              AS total_prompt_tokens,
        COALESCE(SUM(cache_tokens), 0)               AS cache_tokens_total,
        COALESCE(SUM(CASE WHEN cache_hit=1 THEN 1 ELSE 0 END), 0) AS duplicate_calls,
        COALESCE(SUM(CASE WHEN cache_hit=1 THEN cost_usd ELSE 0 END), 0) AS wasted_cost_usd
      FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
    `).bind(since, ...args, ...devArgs).first<Record<string, number>>();
  }

  // Quality scores always from raw events (rollup has no score columns)
  const qualityRow = await sdb.prepare(`
    SELECT
      AVG(efficiency_score)                        AS efficiency_score,
      AVG(hallucination_score)                     AS avg_hallucination_score,
      AVG(faithfulness_score)                      AS avg_faithfulness_score,
      AVG(relevancy_score)                         AS avg_relevancy_score,
      AVG(toxicity_score)                          AS avg_toxicity_score,
      COUNT(CASE WHEN hallucination_score IS NOT NULL THEN 1 END) AS scored_events,
      COALESCE(SUM(CASE WHEN is_streaming=1 THEN 1 ELSE 0 END), 0) AS streaming_requests,
      COALESCE(SUM(CASE WHEN cache_hit=1 THEN cost_usd ELSE 0 END), 0) AS wasted_cost_usd
    FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
  `).bind(since, ...args, ...devArgs).first<Record<string, number>>();

  const row = rollupRow ?? rawRow;

  // Compute cache savings per model (rate varies by model, can't be done in SQL alone)
  // Use rollup for privileged users, raw events for members
  const { results: cacheByModel } = isPrivileged
    ? await sdb.prepare(`
        SELECT model, COALESCE(SUM(cache_tokens), 0) AS cache_tokens, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day >= ?${rollupTeamClause}
        GROUP BY model
      `).bind(since, ...rollupTeamArgs).all<{ model: string; cache_tokens: number; tokens: number }>()
    : await sdb.prepare(`
        SELECT model, COALESCE(SUM(cache_tokens), 0) AS cache_tokens, COALESCE(SUM(total_tokens), 0) AS tokens
        FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
        GROUP BY model
      `).bind(since, ...args, ...devArgs).all<{ model: string; cache_tokens: number; tokens: number }>();

  const totalCacheTokens  = (row?.cache_tokens_total ?? 0) as number;
  const totalPromptTokens = (row?.total_prompt_tokens ?? 0) as number;
  const cacheSavingsUsd   = cacheByModel.reduce((sum, r) => sum + estimateCacheSavings(r.model, r.cache_tokens), 0);
  // cache_hit_rate_pct: cached input tokens as a % of total input tokens (prompt tokens only, not output)
  const cacheHitRatePct   = totalPromptTokens > 0 ? Math.round((totalCacheTokens / totalPromptTokens) * 1000) / 10 : 0;

  const totalRequests = (row?.total_requests ?? 0) as number;

  const kpisResult = {
    total_cost_usd:           (row?.total_cost_usd ?? 0) as number,
    total_tokens:             (row?.total_tokens ?? 0) as number,
    total_requests:           totalRequests,
    avg_latency_ms:           (row?.avg_latency_ms ?? 0) as number,
    // null when no events have been scored — never substitute a fake default
    efficiency_score:         qualityRow?.efficiency_score != null ? (qualityRow.efficiency_score as number) : null,
    streaming_requests:       (qualityRow?.streaming_requests ?? 0) as number,
    cache_tokens_total:       totalCacheTokens,
    duplicate_calls:          (row?.duplicate_calls ?? 0) as number,
    wasted_cost_usd:          Math.round(((qualityRow?.wasted_cost_usd ?? 0) as number) * 1e6) / 1e6,
    cache_savings_usd:        Math.round(cacheSavingsUsd * 1e6) / 1e6,
    cache_hit_rate_pct:       cacheHitRatePct,
    // Quality score aggregates — null when no events have been scored yet
    quality: {
      avg_hallucination_score: qualityRow?.avg_hallucination_score != null ? Math.round((qualityRow.avg_hallucination_score as number) * 1000) / 1000 : null,
      avg_faithfulness_score:  qualityRow?.avg_faithfulness_score  != null ? Math.round((qualityRow.avg_faithfulness_score  as number) * 1000) / 1000 : null,
      avg_relevancy_score:     qualityRow?.avg_relevancy_score     != null ? Math.round((qualityRow.avg_relevancy_score     as number) * 1000) / 1000 : null,
      avg_toxicity_score:      qualityRow?.avg_toxicity_score      != null ? Math.round((qualityRow.avg_toxicity_score      as number) * 1000) / 1000 : null,
      scored_events:           (qualityRow?.scored_events ?? 0) as number,
      coverage_pct:            totalRequests > 0
        ? Math.round(((qualityRow?.scored_events ?? 0) as number) / totalRequests * 1000) / 10
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
  // sinceUnixDay: unix timestamp of the earliest day midnight we want
  const sinceUnixDay = Math.floor(sinceMs / 1000);
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  const tsCacheKey = `analytics:timeseries:${orgId}:${period}:${scopeTeam ?? 'all'}:${isPrivileged ? 'all' : (memberEmail ?? 'anon')}`;
  try {
    const cached = await c.env.KV.get(tsCacheKey);
    if (cached) return c.json(JSON.parse(cached));
  } catch { /* KV unavailable */ }

  const sdb = scopedDb(c.env.DB, orgId);

  // Privileged users: use rollup (events_daily_rollup.date_unix_day is INTEGER unix midnight).
  // date_unix_day → ISO date string via date(date_unix_day, 'unixepoch').
  // Non-privileged: fall back to raw events (rollup has no developer_email).
  let results: unknown[];
  if (isPrivileged) {
    const { results: rollupResults } = await sdb.prepare(`
      SELECT
        date(date_unix_day, 'unixepoch')          AS date,
        SUM(cost_usd)                             AS cost_usd,
        SUM(total_tokens)                         AS tokens,
        SUM(requests)                             AS requests
      FROM events_daily_rollup
      WHERE {{ORG_SCOPE}} AND date_unix_day >= ?${teamClause}
      GROUP BY date_unix_day
      ORDER BY date_unix_day ASC
    `).bind(sinceUnixDay, ...teamArgs).all();
    results = rollupResults;
  } else {
    // Raw events — created_at is INTEGER unixepoch
    const { results: rawResults } = await sdb.prepare(`
      SELECT
        date(created_at, 'unixepoch')             AS date,
        SUM(cost_usd)                             AS cost_usd,
        SUM(total_tokens)                         AS tokens,
        COUNT(*)                                  AS requests
      FROM events
      WHERE {{ORG_SCOPE}} AND created_at >= ?${teamClause}${devClause}
      GROUP BY date
      ORDER BY date ASC
    `).bind(sinceUnixDay, ...teamArgs, ...devArgs).all();
    results = rawResults;
  }

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
  const limit  = Math.min(Math.max(parseInt(c.req.query('limit')  ?? '25', 10) || 25, 1), 200);
  const offset = Math.max(parseInt(c.req.query('offset') ?? '0', 10) || 0, 0);
  const sinceUnixDay = sinceUnix(period);
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const { clause, args } = teamScope(scopeTeam);
  const devClause = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  const sdb = scopedDb(c.env.DB, orgId);

  // Privileged users: use rollup for model breakdown.
  // Non-privileged: fall back to raw events (rollup has no developer_email).
  let results: unknown[];
  if (isPrivileged) {
    const { results: rollupResults } = await sdb.prepare(`
      SELECT
        model, provider,
        SUM(cost_usd)                                                       AS cost_usd,
        SUM(total_tokens)                                                   AS tokens,
        SUM(requests)                                                       AS requests,
        CAST(SUM(latency_ms_sum) AS REAL) / NULLIF(SUM(requests), 0)       AS avg_latency_ms
      FROM events_daily_rollup
      WHERE {{ORG_SCOPE}} AND date_unix_day >= ?${teamClause}
      GROUP BY model, provider
      ORDER BY cost_usd DESC
      LIMIT ? OFFSET ?
    `).bind(sinceUnixDay, ...teamArgs, limit, offset).all();
    results = rollupResults;
  } else {
    const { results: rawResults } = await sdb.prepare(`
      SELECT
        model, provider,
        SUM(cost_usd)                     AS cost_usd,
        SUM(total_tokens)                 AS tokens,
        COUNT(*)                          AS requests,
        AVG(latency_ms)                   AS avg_latency_ms
      FROM events
      WHERE {{ORG_SCOPE}} AND created_at >= ?${clause}${devClause}
      GROUP BY model, provider
      ORDER BY cost_usd DESC
      LIMIT ? OFFSET ?
    `).bind(sinceUnixDay, ...args, ...devArgs, limit, offset).all();
    results = rawResults;
  }

  logAudit(c, { event_type: 'data_access', event_name: 'data_access.analytics', resource_type: 'analytics', metadata: { endpoint: '/v1/analytics/models' } });
  return c.json({ models: results, limit, offset });
});

// ── GET /v1/analytics/teams?period=30 ────────────────────────────────────────
// Members with scope_team set see only their own team row + its budget.
// Admins/owners see all teams + budgets.
analytics.get('/teams', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');
  const role      = c.get('role');
  const isPrivileged = hasRole(role, 'admin');
  const { clause, args } = teamScope(scopeTeam);
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const since  = sinceUnix(period);

  // Privileged users: use rollup for team breakdown (faster full-table aggregation).
  // Non-privileged: fall back to raw events (rollup has no developer_email).
  // Both paths join team_budgets + budget_policies for budget_usd/budget_pct.
  // NOTE: This query joins r (rollup), team_budgets(b), budget_policies(bp) — all three
  // tables have org_id. Using `r.org_id = ?` avoids ambiguity in the WHERE clause.
  if (isPrivileged) {
    const teamFilter = scopeTeam ? ' AND r.team = ?' : '';
    const teamFilterArgs = scopeTeam ? [scopeTeam] : [];
    const { results } = await c.env.DB.prepare(`
      SELECT
        COALESCE(r.team, 'unassigned') AS team,
        SUM(r.cost_usd)                AS cost_usd,
        SUM(r.total_tokens)            AS tokens,
        SUM(r.requests)                AS requests,
        COALESCE(b.budget_usd, bp.monthly_limit_usd, 0) AS budget_usd,
        CASE WHEN COALESCE(b.budget_usd, bp.monthly_limit_usd, 0) > 0
          THEN ROUND(SUM(r.cost_usd) / COALESCE(b.budget_usd, bp.monthly_limit_usd) * 100, 1)
          ELSE NULL
        END AS budget_pct
      FROM events_daily_rollup r
      LEFT JOIN team_budgets b ON b.org_id = r.org_id AND b.team = r.team
      LEFT JOIN budget_policies bp ON bp.org_id = r.org_id AND bp.scope = 'team' AND bp.scope_target = r.team
      WHERE r.org_id = ? AND r.date_unix_day >= ?${teamFilter}
      GROUP BY r.team
      ORDER BY cost_usd DESC
      LIMIT 20
    `).bind(orgId, since, ...teamFilterArgs).all();
    return c.json({ teams: results });
  }

  // Non-privileged fallback: raw events
  // NOTE: Joins events(e), team_budgets(b), budget_policies(bp) — keep `e.org_id = ?`
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
  const role   = c.get('role') as string;
  if (!hasRole(role, 'admin')) return c.json({ business_units: [], by_team_provider: [], period_days: 0 });
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const sinceIso   = sinceText(period);  // cross_platform_usage = TEXT
  const sinceEvts  = sinceUnix(period);  // events               = INTEGER

  const sdb = scopedDb(c.env.DB, orgId);

  // UNION events + cross_platform_usage for complete picture.
  // Both sides of the UNION have {{ORG_SCOPE}} — wrapper injects orgId at both positions.
  const { results } = await sdb.prepare(`
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
      WHERE {{ORG_SCOPE}} AND created_at >= ?
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
      WHERE {{ORG_SCOPE}} AND created_at >= ? AND cost_usd > 0
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
  `).bind(sinceIso, sinceEvts).all();

  // Per-business-unit team breakdown — both UNION sides have {{ORG_SCOPE}}.
  const { results: byTeam } = await sdb.prepare(`
    WITH all_usage AS (
      SELECT COALESCE(business_unit, cost_center, 'unassigned') AS business_unit,
             team, provider, cost_usd
      FROM cross_platform_usage WHERE {{ORG_SCOPE}} AND created_at >= ?
      UNION ALL
      SELECT COALESCE(business_unit, 'unassigned') AS business_unit,
             team, model AS provider, cost_usd
      FROM events WHERE {{ORG_SCOPE}} AND created_at >= ? AND cost_usd > 0
    )
    SELECT business_unit,
           COALESCE(team, 'unassigned') AS team,
           provider,
           SUM(cost_usd) AS cost_usd
    FROM all_usage
    GROUP BY business_unit, team, provider
    ORDER BY cost_usd DESC
    LIMIT 200
  `).bind(sinceIso, sinceEvts).all();

  return c.json({ business_units: results, by_team_provider: byTeam, period_days: period });
});

// ── GET /v1/analytics/traces?period=7 ────────────────────────────────────────
// Defaults to 7 days, max 90. Union-sources from two tables:
//   - events:       primary trace source populated by SDK/agent ingest
//   - otel_traces:  span-level rows from OTLP ingest (no cost, no team/dev)
// otel_traces joins only for admins with no team scope (it lacks team and
// developer_email columns, so filtering by scope would drop every row).
// Non-admin filter includes developer_email IS NULL so members still see
// their own traces when the client ingest path omitted developer_email.
analytics.get('/traces', async (c) => {
  const orgId      = c.get('orgId');
  const scopeTeam  = c.get('scopeTeam');
  const role       = c.get('role') as string;
  const memberEmail = c.get('memberEmail') as string | undefined;
  const { clause, args } = teamScope(scopeTeam);
  const isPrivileged = hasRole(role, 'admin');
  const devClause  = isPrivileged ? '' : ' AND (developer_email = ? OR developer_email IS NULL)';
  const devArgs    = isPrivileged ? [] : [memberEmail];
  const period = Math.min(parseInt(c.req.query('period') ?? '7', 10) || 7, 90);
  const since  = sinceUnix(period);
  const sinceIso = sinceText(period);

  const sdb = scopedDb(c.env.DB, orgId);

  const includeOtel = isPrivileged && !scopeTeam;

  const eventsQuery = `
    SELECT
      trace_id,
      MIN(agent_name)      AS name,
      COUNT(*)             AS spans,
      COALESCE(SUM(cost_usd), 0)   AS cost,
      COALESCE(SUM(latency_ms), 0) AS latency,
      MAX(CASE WHEN parent_event_id IS NULL THEN 1 ELSE 0 END) AS has_root,
      MIN(created_at)      AS started_at,
      'events' AS source
    FROM events
    WHERE {{ORG_SCOPE}} AND trace_id IS NOT NULL AND created_at >= ?${clause}${devClause}
    GROUP BY trace_id
  `;

  const otelQuery = `
    SELECT
      trace_id,
      MIN(operation_name)                              AS name,
      COUNT(*)                                         AS spans,
      0                                                AS cost,
      COALESCE(SUM(duration_ms), 0)                    AS latency,
      MAX(CASE WHEN parent_span_id IS NULL OR parent_span_id = '' THEN 1 ELSE 0 END) AS has_root,
      CAST(strftime('%s', MIN(created_at)) AS INTEGER) AS started_at,
      'otel' AS source
    FROM otel_traces
    WHERE {{ORG_SCOPE}} AND trace_id IS NOT NULL AND created_at >= ?
    GROUP BY trace_id
  `;

  const eventsResult = await sdb.prepare(`${eventsQuery} ORDER BY started_at DESC LIMIT 100`)
    .bind(since, ...args, ...devArgs).all<Record<string, unknown>>();
  let eventsRows = eventsResult.results;

  if (includeOtel) {
    try {
      const otelResult = await sdb.prepare(`${otelQuery} ORDER BY started_at DESC LIMIT 100`)
        .bind(sinceIso).all<Record<string, unknown>>();
      const merged = [...eventsRows, ...otelResult.results]
        .sort((a, b) => (b.started_at as number) - (a.started_at as number))
        .slice(0, 100);
      return c.json({ traces: merged, period_days: period, total: merged.length });
    } catch {
      // otel_traces unavailable — return events-only results
    }
  }

  return c.json({ traces: eventsRows, period_days: period, total: eventsRows.length });
});

// ── GET /v1/analytics/traces/:traceId — full span tree for one trace ──────────
// First tries the events table. Falls back to otel_traces for admins (where
// the span-level OTLP ingest lives). Non-admin filter includes NULL-email
// rows so members can see their own agent-generated traces.
analytics.get('/traces/:traceId', async (c) => {
  const orgId       = c.get('orgId');
  const traceId     = c.req.param('traceId');
  const role        = c.get('role');
  const memberEmail = c.get('memberEmail');
  const scopeTeam   = c.get('scopeTeam');
  const { clause, args } = teamScope(scopeTeam);
  const isPrivileged = hasRole(role, 'admin');
  const devClause = isPrivileged ? '' : ' AND (developer_email = ? OR developer_email IS NULL)';
  const devArgs   = isPrivileged ? [] : [memberEmail];

  const sdb = scopedDb(c.env.DB, orgId);

  const { results } = await sdb.prepare(`
    SELECT
      id,
      parent_event_id   AS parent_id,
      agent_name,
      model,
      provider,
      feature,
      span_depth,
      prompt_tokens,
      completion_tokens,
      cache_tokens,
      cost_usd,
      latency_ms,
      created_at
    FROM events
    WHERE {{ORG_SCOPE}} AND trace_id = ?${clause}${devClause}
    ORDER BY created_at ASC
  `).bind(traceId, ...args, ...devArgs).all();

  if (results.length) return c.json({ trace_id: traceId, spans: results, source: 'events' });

  // Fall back to otel_traces (admin + un-scoped only — table lacks team/dev cols)
  if (isPrivileged && !scopeTeam) {
    const { results: otelRows } = await sdb.prepare(`
      SELECT
        span_id                                          AS id,
        parent_span_id                                   AS parent_id,
        operation_name                                   AS agent_name,
        NULL                                             AS model,
        NULL                                             AS provider,
        NULL                                             AS feature,
        0                                                AS span_depth,
        0                                                AS prompt_tokens,
        0                                                AS completion_tokens,
        0                                                AS cache_tokens,
        0                                                AS cost_usd,
        duration_ms                                      AS latency_ms,
        CAST(strftime('%s', created_at) AS INTEGER)      AS created_at
      FROM otel_traces
      WHERE {{ORG_SCOPE}} AND trace_id = ?
      ORDER BY start_time_ms ASC
    `).bind(traceId).all();
    if (otelRows.length) return c.json({ trace_id: traceId, spans: otelRows, source: 'otel' });
  }

  return c.json({ error: 'trace not found' }, 404);
});

// ── GET /v1/analytics/today — hourly spend for the current UTC day ───────────
analytics.get('/today', async (c) => {
  const orgId      = c.get('orgId');
  const scopeTeam  = c.get('scopeTeam');
  const role       = c.get('role') as string;
  const memberEmail = c.get('memberEmail') as string | undefined;
  const isPrivileged = hasRole(role, 'admin');
  const teamClause = scopeTeam ? ' AND team = ?' : '';
  const teamArgs   = scopeTeam ? [scopeTeam] : [];
  const devClause  = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs    = isPrivileged ? [] : [memberEmail];
  // created_at is INTEGER unixepoch on events, TEXT on cross_platform_usage — bind per-table.
  const todayStr  = new Date().toISOString().split('T')[0] + ' 00:00:00';
  const todayUnix = Math.floor(Date.now() / 86_400_000) * 86_400;

  const sdb = scopedDb(c.env.DB, orgId);

  const [evRows, cpuRows] = await Promise.all([
    sdb.prepare(`
      SELECT
        CAST(strftime('%H', created_at, 'unixepoch') AS INTEGER) AS hour,
        SUM(cost_usd)                        AS cost_usd,
        SUM(prompt_tokens + completion_tokens) AS tokens,
        COUNT(*)                             AS requests
      FROM events
      WHERE {{ORG_SCOPE}} AND created_at >= ?${teamClause}${devClause}
      GROUP BY hour
    `).bind(todayUnix, ...teamArgs, ...devArgs).all<{ hour: number; cost_usd: number; tokens: number; requests: number }>(),
    sdb.prepare(`
      SELECT
        CAST(strftime('%H', created_at) AS INTEGER) AS hour,
        SUM(cost_usd)                               AS cost_usd,
        SUM(input_tokens + output_tokens)           AS tokens,
        COUNT(*)                                    AS requests
      FROM cross_platform_usage
      WHERE {{ORG_SCOPE}} AND created_at >= ?${teamClause}${devClause}
      GROUP BY hour
    `).bind(todayStr, ...teamArgs, ...devArgs).all<{ hour: number; cost_usd: number; tokens: number; requests: number }>(),
  ]);

  // Merge both sources by hour
  const merged = new Map<number, { hour: number; cost_usd: number; tokens: number; requests: number }>();
  for (const row of [...(evRows.results ?? []), ...(cpuRows.results ?? [])]) {
    const existing = merged.get(row.hour);
    if (existing) {
      existing.cost_usd += row.cost_usd;
      existing.tokens   += row.tokens;
      existing.requests += row.requests;
    } else {
      merged.set(row.hour, { ...row });
    }
  }
  const results = Array.from(merged.values()).sort((a, b) => a.hour - b.hour);

  return c.json({ date: todayStr.slice(0, 10), hours: results });
});

// ── GET /v1/analytics/cost — CI cost gate ────────────────────────────────────
analytics.get('/cost', async (c) => {
  const orgId      = c.get('orgId');
  const scopeTeam  = c.get('scopeTeam');
  const role       = c.get('role') as string;
  const memberEmail = c.get('memberEmail') as string | undefined;
  const { clause, args } = teamScope(scopeTeam);
  const isPrivileged = hasRole(role, 'admin');
  const devClause  = isPrivileged ? '' : ' AND developer_email = ?';
  const devArgs    = isPrivileged ? [] : [memberEmail];
  const period = Math.min(parseInt(c.req.query('period') ?? '7', 10) || 7, 30);
  const since  = sinceUnix(period);
  const today  = todayUnix();

  const sdb = scopedDb(c.env.DB, orgId);

  // Privileged users: use rollup.
  // Non-privileged: fall back to raw events (rollup has no developer_email).
  if (isPrivileged) {
    const rollupTeamClause = scopeTeam ? ' AND team = ?' : '';
    const rollupTeamArgs   = scopeTeam ? [scopeTeam] : [];
    const [total, todayRow] = await c.env.DB.batch([
      sdb.prepare(
        `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day>=?${rollupTeamClause}`
      ).bind(since, ...rollupTeamArgs),
      sdb.prepare(
        `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events_daily_rollup WHERE {{ORG_SCOPE}} AND date_unix_day=?${rollupTeamClause}`
      ).bind(today, ...rollupTeamArgs),
    ]);
    return c.json({
      total_cost_usd: (total.results[0] as Record<string, number>)?.cost ?? 0,
      today_cost_usd: (todayRow.results[0] as Record<string, number>)?.cost ?? 0,
      period_days:    period,
    });
  }

  const [total, todayRow] = await c.env.DB.batch([
    sdb.prepare(
      `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events WHERE {{ORG_SCOPE}} AND created_at>=?${clause}${devClause}`
    ).bind(since, ...args, ...devArgs),
    sdb.prepare(
      `SELECT COALESCE(SUM(cost_usd),0) AS cost FROM events WHERE {{ORG_SCOPE}} AND created_at>=?${clause}${devClause}`
    ).bind(today, ...args, ...devArgs),
  ]);

  return c.json({
    total_cost_usd: (total.results[0] as Record<string, number>)?.cost ?? 0,
    today_cost_usd: (todayRow.results[0] as Record<string, number>)?.cost ?? 0,
    period_days:    period,
  });
});

export { analytics };
