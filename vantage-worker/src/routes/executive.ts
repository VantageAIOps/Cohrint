/**
 * Cohrint — Executive Dashboard API
 *
 * Single endpoint returning org-wide cost intelligence for CEO/Superadmin roles.
 * Designed for the 32-person, 3-team business case where a CEO needs:
 *   - Budget utilization per team × per tool side-by-side
 *   - Top individual spenders with team attribution
 *   - Org-wide savings opportunity estimate
 *   - Provider breakdown (Claude vs Gemini vs Copilot)
 *   - Budget policy compliance overview
 *
 * Endpoints:
 *   GET /v1/analytics/executive   — unified CEO/superadmin dashboard data
 */

import { Hono } from 'hono';
import type { Bindings, Variables } from '../types';
import { authMiddleware, executiveOnly } from '../middleware/auth';

const executive = new Hono<{ Bindings: Bindings; Variables: Variables }>();

executive.use('*', authMiddleware, executiveOnly);

function sqliteMonthStart(): string {
  const d = new Date();
  return d.toISOString().slice(0, 7) + '-01 00:00:00';
}

// ── GET /v1/analytics/executive — unified C-level dashboard ─────────────────
executive.get('/', async (c) => {
  const orgId = c.get('orgId');
  const days  = Math.min(parseInt(c.req.query('days') ?? '30', 10) || 30, 90);

  // Two since values: ISO string for cross_platform_usage, Unix seconds for events
  const sinceIso  = new Date(Date.now() - days * 86_400_000).toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
  const sinceUnix = Math.floor(Date.now() / 1000) - days * 86_400;

  const monthStart = sqliteMonthStart();
  const monthStartUnix = Math.floor(new Date(new Date().toISOString().slice(0, 7) + '-01T00:00:00Z').getTime() / 1000);

  // ── 1. Org summary ─────────────────────────────────────────────────────────
  const org = await c.env.DB.prepare(
    'SELECT name, plan, budget_usd FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ name: string; plan: string; budget_usd: number }>();

  // UNION totals from both tables
  const orgTotals = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT cost_usd, input_tokens + output_tokens AS tokens
      FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT cost_usd, prompt_tokens + completion_tokens AS tokens
      FROM events WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT
      COALESCE(SUM(cost_usd), 0)   AS total_cost,
      COALESCE(SUM(tokens), 0)     AS total_tokens,
      COALESCE(COUNT(*), 0)        AS total_records
    FROM all_usage
  `).bind(orgId, sinceIso, orgId, sinceUnix).first<{ total_cost: number; total_tokens: number; total_records: number }>();

  // MTD spend from both tables
  const monthSpendCpu = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost
    FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, monthStart).first<{ mtd_cost: number }>();
  const monthSpendEvt = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost
    FROM events WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
  `).bind(orgId, monthStartUnix).first<{ mtd_cost: number }>();

  const budgetLimit = org?.budget_usd ?? 0;
  const mtdCost = (monthSpendCpu?.mtd_cost ?? 0) + (monthSpendEvt?.mtd_cost ?? 0);
  const budgetPct = budgetLimit > 0 ? Math.round((mtdCost / budgetLimit) * 100) : null;

  // ── 2. Per-team breakdown with per-provider sub-split ──────────────────────
  // Step A: total cost per team (UNION both tables)
  const { results: teamRows } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT team, provider, developer_email, cost_usd,
             input_tokens + output_tokens AS tokens
      FROM cross_platform_usage
      WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT team, model AS provider, developer_email, cost_usd,
             prompt_tokens + completion_tokens AS tokens
      FROM events
      WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT
      COALESCE(team, 'unassigned')         AS team,
      COALESCE(SUM(cost_usd), 0)           AS cost,
      COALESCE(SUM(tokens), 0)             AS tokens,
      COUNT(DISTINCT developer_email)      AS developer_count,
      COUNT(*)                             AS records
    FROM all_usage
    GROUP BY team ORDER BY cost DESC
  `).bind(orgId, sinceIso, orgId, sinceUnix).all<{ team: string; cost: number; tokens: number; developer_count: number; records: number }>();

  // Step B: per-team per-provider breakdown (UNION both tables)
  const { results: teamProviderRows } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT COALESCE(team, 'unassigned') AS team, provider, cost_usd
      FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT COALESCE(team, 'unassigned') AS team, model AS provider, cost_usd
      FROM events WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT team, provider, COALESCE(SUM(cost_usd), 0) AS cost
    FROM all_usage
    GROUP BY team, provider ORDER BY team, cost DESC
  `).bind(orgId, sinceIso, orgId, sinceUnix).all<{ team: string; provider: string; cost: number }>();

  // Step C: team budgets
  const { results: teamBudgets } = await c.env.DB.prepare(`
    SELECT team, budget_usd FROM team_budgets WHERE org_id = ?
  `).bind(orgId).all<{ team: string; budget_usd: number }>();

  const budgetByTeam = Object.fromEntries(teamBudgets.map(b => [b.team, b.budget_usd]));

  // Merge team rows with per-provider breakdown
  const teamMap = new Map<string, { team: string; cost: number; tokens: number; developer_count: number; records: number; budget_usd: number; budget_pct: number | null; by_provider: { provider: string; cost: number }[] }>();
  for (const t of (teamRows ?? [])) {
    const budget = budgetByTeam[t.team] ?? 0;
    teamMap.set(t.team, {
      ...t,
      budget_usd: budget,
      budget_pct: budget > 0 ? Math.round((t.cost / budget) * 100) : null,
      by_provider: [],
    });
  }
  for (const tp of (teamProviderRows ?? [])) {
    teamMap.get(tp.team)?.by_provider.push({ provider: tp.provider, cost: tp.cost });
  }

  // ── 3. Provider breakdown (org-wide, UNION both tables) ───────────────────
  const { results: providerRows } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT provider, developer_email, cost_usd
      FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
      UNION ALL
      SELECT model AS provider, developer_email, cost_usd
      FROM events WHERE org_id = ? AND created_at >= ? AND cost_usd > 0
    )
    SELECT
      provider,
      COALESCE(SUM(cost_usd), 0)          AS cost,
      COUNT(DISTINCT developer_email)     AS developer_count,
      COUNT(*)                            AS records
    FROM all_usage
    GROUP BY provider ORDER BY cost DESC
  `).bind(orgId, sinceIso, orgId, sinceUnix).all<{ provider: string; cost: number; developer_count: number; records: number }>();

  // ── 4. Top 15 individual spenders across org (UNION both tables) ──────────
  const { results: topDevs } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT team, provider, developer_email, cost_usd,
             pull_requests, commits, lines_added
      FROM cross_platform_usage
      WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
      UNION ALL
      SELECT team, model AS provider, developer_email, cost_usd,
             0 AS pull_requests, 0 AS commits, 0 AS lines_added
      FROM events
      WHERE org_id = ? AND created_at >= ? AND cost_usd > 0 AND developer_email IS NOT NULL
    )
    SELECT
      developer_email,
      COALESCE(team, 'unassigned')        AS team,
      COALESCE(SUM(cost_usd), 0)          AS cost,
      COALESCE(SUM(pull_requests), 0)     AS pull_requests,
      COALESCE(SUM(commits), 0)           AS commits,
      COALESCE(SUM(lines_added), 0)       AS lines_added,
      GROUP_CONCAT(DISTINCT provider)     AS providers
    FROM all_usage
    GROUP BY developer_email, team
    ORDER BY cost DESC LIMIT 15
  `).bind(orgId, sinceIso, orgId, sinceUnix).all<{ developer_email: string; team: string; cost: number; pull_requests: number; commits: number; lines_added: number; providers: string | null }>();

  // ── 5. Budget policies overview ────────────────────────────────────────────
  interface PolicyRow {
    scope: string;
    scope_target: string | null;
    provider_target: string | null;
    monthly_limit_usd: number;
    enforcement: string;
  }
  const { results: policies } = await c.env.DB.prepare(`
    SELECT scope, scope_target, provider_target, monthly_limit_usd, enforcement
    FROM budget_policies WHERE org_id = ?
    ORDER BY scope, scope_target
  `).bind(orgId).all<PolicyRow>();

  // Attach current MTD spend to each policy
  const policiesWithSpend = await Promise.all((policies ?? []).map(async (p: PolicyRow) => {
    let spend = 0;
    if (p.scope === 'org') {
      spend = mtdCost;
    } else if (p.scope === 'team' && p.scope_target) {
      const row = await c.env.DB.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS s
        FROM cross_platform_usage WHERE org_id = ? AND team = ? AND created_at >= ?
      `).bind(orgId, p.scope_target, monthStart).first<{ s: number }>();
      spend = row?.s ?? 0;
    } else if (p.scope === 'developer' && p.scope_target) {
      const row = await c.env.DB.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS s
        FROM cross_platform_usage WHERE org_id = ? AND developer_email = ? AND created_at >= ?
      `).bind(orgId, p.scope_target, monthStart).first<{ s: number }>();
      const row2 = await c.env.DB.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS s
        FROM events WHERE org_id = ? AND developer_email = ? AND created_at >= ?
      `).bind(orgId, p.scope_target, monthStartUnix).first<{ s: number }>();
      spend = (row?.s ?? 0) + (row2?.s ?? 0);
    } else if (p.scope === 'provider' && p.scope_target) {
      const row = await c.env.DB.prepare(`
        SELECT COALESCE(SUM(cost_usd), 0) AS s
        FROM cross_platform_usage WHERE org_id = ? AND provider = ? AND created_at >= ?
      `).bind(orgId, p.scope_target, monthStart).first<{ s: number }>();
      spend = row?.s ?? 0;
    }
    return {
      ...p,
      mtd_spend_usd: +spend.toFixed(4),
      budget_pct: p.monthly_limit_usd > 0 ? Math.round((spend / p.monthly_limit_usd) * 100) : null,
    };
  }));

  // ── 6. Org member role distribution ───────────────────────────────────────
  const { results: memberRoles } = await c.env.DB.prepare(`
    SELECT role, COUNT(*) AS count FROM org_members WHERE org_id = ? GROUP BY role
  `).bind(orgId).all<{ role: string; count: number }>();

  // ── 7. Savings opportunity summary (UNION both tables) ────────────────────
  // Estimate: developers with cache_hit_rate < 20% could save ~15% with prompt tuning
  const { results: cacheStats } = await c.env.DB.prepare(`
    WITH all_usage AS (
      SELECT developer_email, cached_tokens,
             input_tokens + output_tokens + cached_tokens AS total_toks, cost_usd
      FROM cross_platform_usage
      WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
      UNION ALL
      SELECT developer_email, cache_tokens AS cached_tokens,
             prompt_tokens + completion_tokens + cache_tokens AS total_toks, cost_usd
      FROM events
      WHERE org_id = ? AND created_at >= ? AND cost_usd > 0 AND developer_email IS NOT NULL
    )
    SELECT
      developer_email,
      COALESCE(SUM(cached_tokens), 0)  AS cached,
      COALESCE(SUM(total_toks), 0)     AS total_tokens,
      COALESCE(SUM(cost_usd), 0)       AS cost
    FROM all_usage
    GROUP BY developer_email
  `).bind(orgId, sinceIso, orgId, sinceUnix).all<{ developer_email: string; cached: number; total_tokens: number; cost: number }>();

  let totalSavingsOpportunity = 0;
  for (const d of (cacheStats ?? [])) {
    const cacheRate = d.total_tokens > 0 ? d.cached / d.total_tokens : 0;
    if (cacheRate < 0.20 && d.cost > 1) totalSavingsOpportunity += d.cost * 0.15;
  }

  return c.json({
    period_days: days,
    generated_at: new Date().toISOString(),
    org: {
      name:         org?.name,
      plan:         org?.plan ?? 'free',
      budget_usd:   budgetLimit,
      mtd_cost_usd: +mtdCost.toFixed(4),
      budget_pct:   budgetPct,
    },
    totals: {
      total_cost_usd:         +(orgTotals?.total_cost ?? 0).toFixed(4),
      total_tokens:           orgTotals?.total_tokens ?? 0,
      total_records:          orgTotals?.total_records ?? 0,
      savings_opportunity_usd: +totalSavingsOpportunity.toFixed(4),
    },
    by_team:       [...teamMap.values()],
    by_provider:   providerRows ?? [],
    top_developers: (topDevs ?? []).map((d) => ({
      developer_email: d.developer_email,
      team:            d.team,
      cost:            +(d.cost ?? 0).toFixed(4),
      pull_requests:   d.pull_requests,
      commits:         d.commits,
      lines_added:     d.lines_added,
      providers:       d.providers ? d.providers.split(',') : [],
      cost_per_pr:     d.pull_requests > 0 ? +(d.cost / d.pull_requests).toFixed(4) : null,
    })),
    budget_policies: policiesWithSpend,
    member_roles:    memberRoles ?? [],
  });
});

export { executive };
