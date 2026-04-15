/**
 * VantageAI — Executive Dashboard API
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

function sqliteDateSince(days: number): string {
  const todayMs = Math.floor(Date.now() / 86400000) * 86400000;
  const d = new Date(todayMs - (days - 1) * 86400000);
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
}

function sqliteMonthStart(): string {
  const d = new Date();
  return d.toISOString().slice(0, 7) + '-01 00:00:00';
}

// ── GET /v1/analytics/executive — unified C-level dashboard ─────────────────
executive.get('/', async (c) => {
  const orgId = c.get('orgId');
  const days  = Math.min(parseInt(c.req.query('days') ?? '30', 10) || 30, 90);
  const since = sqliteDateSince(days);
  const monthStart = sqliteMonthStart();

  // ── 1. Org summary ─────────────────────────────────────────────────────────
  const org = await c.env.DB.prepare(
    'SELECT name, email, plan, budget_usd FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ name: string; email: string; plan: string; budget_usd: number }>();

  const orgTotals = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0)       AS total_cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
      COUNT(*)                         AS total_records
    FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, since).first<{ total_cost: number; total_tokens: number; total_records: number }>();

  const monthSpend = await c.env.DB.prepare(`
    SELECT COALESCE(SUM(cost_usd), 0) AS mtd_cost
    FROM cross_platform_usage WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, monthStart).first<{ mtd_cost: number }>();

  const budgetLimit = org?.budget_usd ?? 0;
  const mtdCost = monthSpend?.mtd_cost ?? 0;
  const budgetPct = budgetLimit > 0 ? Math.round((mtdCost / budgetLimit) * 100) : null;

  // ── 2. Per-team breakdown with per-provider sub-split ──────────────────────
  // Step A: total cost per team
  const { results: teamRows } = await c.env.DB.prepare(`
    SELECT
      COALESCE(team, 'unassigned')     AS team,
      COALESCE(SUM(cost_usd), 0)       AS cost,
      COALESCE(SUM(input_tokens + output_tokens), 0) AS tokens,
      COUNT(DISTINCT developer_email)  AS developer_count,
      COUNT(*)                         AS records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY team ORDER BY cost DESC
  `).bind(orgId, since).all<{ team: string; cost: number; tokens: number; developer_count: number; records: number }>();

  // Step B: per-team per-provider breakdown
  const { results: teamProviderRows } = await c.env.DB.prepare(`
    SELECT
      COALESCE(team, 'unassigned') AS team,
      provider,
      COALESCE(SUM(cost_usd), 0)  AS cost
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY team, provider ORDER BY team, cost DESC
  `).bind(orgId, since).all<{ team: string; provider: string; cost: number }>();

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

  // ── 3. Provider breakdown (org-wide) ──────────────────────────────────────
  const { results: providerRows } = await c.env.DB.prepare(`
    SELECT
      provider,
      COALESCE(SUM(cost_usd), 0)   AS cost,
      COUNT(DISTINCT developer_email) AS developer_count,
      COUNT(*)                     AS records
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY provider ORDER BY cost DESC
  `).bind(orgId, since).all<{ provider: string; cost: number; developer_count: number; records: number }>();

  // ── 4. Top 15 individual spenders across org ───────────────────────────────
  const { results: topDevs } = await c.env.DB.prepare(`
    SELECT
      developer_email,
      COALESCE(team, 'unassigned')      AS team,
      COALESCE(SUM(cost_usd), 0)        AS cost,
      COALESCE(SUM(pull_requests), 0)   AS pull_requests,
      COALESCE(SUM(commits), 0)         AS commits,
      COALESCE(SUM(lines_added), 0)     AS lines_added,
      GROUP_CONCAT(DISTINCT provider)   AS providers
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email, team
    ORDER BY cost DESC LIMIT 15
  `).bind(orgId, since).all<any>();

  // ── 5. Budget policies overview ────────────────────────────────────────────
  const { results: policies } = await c.env.DB.prepare(`
    SELECT scope, scope_target, provider_target, monthly_limit_usd, enforcement
    FROM budget_policies WHERE org_id = ?
    ORDER BY scope, scope_target
  `).bind(orgId).all<any>();

  // Attach current MTD spend to each policy
  const policiesWithSpend = await Promise.all((policies ?? []).map(async (p: any) => {
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
      spend = row?.s ?? 0;
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

  // ── 7. Savings opportunity summary ────────────────────────────────────────
  // Estimate: developers with cache_hit_rate < 20% could save ~15% with prompt tuning
  const { results: cacheStats } = await c.env.DB.prepare(`
    SELECT
      developer_email,
      COALESCE(SUM(cached_tokens), 0)                                              AS cached,
      COALESCE(SUM(input_tokens + output_tokens + cached_tokens), 0)               AS total_tokens,
      COALESCE(SUM(cost_usd), 0)                                                   AS cost
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email
  `).bind(orgId, since).all<{ developer_email: string; cached: number; total_tokens: number; cost: number }>();

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
    top_developers: (topDevs ?? []).map((d: any) => ({
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
