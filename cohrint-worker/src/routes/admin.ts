import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly, superadminOnly, hasRole } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const admin = new Hono<{ Bindings: Bindings; Variables: Variables }>();

admin.use('*', authMiddleware, adminOnly);

// ── GET /v1/admin/overview — all teams with usage + budgets ──────────────────
admin.get('/overview', async (c) => {
  const orgId  = c.get('orgId');
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  // events.created_at is TEXT 'YYYY-MM-DD HH:MM:SS' — use ISO text, not unix seconds
  const d = new Date(Date.now() - (period - 1) * 86_400_000);
  d.setUTCHours(0, 0, 0, 0);
  const since = d.toISOString().replace('T', ' ').slice(0, 19);
  const monthStart = new Date().toISOString().slice(0, 7) + '-01 00:00:00';

  // Org-level totals
  const orgRow = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0)     AS total_cost_usd,
      COALESCE(SUM(total_tokens), 0) AS total_tokens,
      COALESCE(COUNT(*), 0)          AS total_requests,
      COALESCE(AVG(latency_ms), 0)   AS avg_latency_ms
    FROM events WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, since).first<Record<string, number>>();

  const mtd = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0) AS mtd_cost_usd,
      COUNT(*) AS mtd_event_count
    FROM events WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, monthStart).first<{ mtd_cost_usd: number; mtd_event_count: number }>();

  const org = await c.env.DB.prepare(
    'SELECT budget_usd, plan, name, email FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ budget_usd: number; plan: string; name: string; email: string }>();
  // benchmark_opt_in added in migration 0008 — query separately so older DBs don't 500
  let benchmark_opt_in = 0;
  try {
    const benchRow = await c.env.DB.prepare(
      'SELECT benchmark_opt_in FROM orgs WHERE id = ?'
    ).bind(orgId).first<{ benchmark_opt_in: number }>();
    benchmark_opt_in = benchRow?.benchmark_opt_in ?? 0;
  } catch { /* column may not exist on older deployments */ }

  // Per-team breakdown with budgets and member count
  const { results: teams } = await c.env.DB.prepare(`
    SELECT
      COALESCE(e.team, 'unassigned') AS team,
      SUM(e.cost_usd)                AS cost_usd,
      SUM(e.total_tokens)            AS tokens,
      COUNT(*)                       AS requests,
      AVG(e.latency_ms)              AS avg_latency_ms,
      COALESCE(b.budget_usd, 0)      AS budget_usd,
      CASE WHEN b.budget_usd > 0
        THEN ROUND(SUM(e.cost_usd) / b.budget_usd * 100, 1)
        ELSE NULL
      END AS budget_pct,
      COALESCE((
        SELECT COUNT(*) FROM org_members m
        WHERE m.org_id = e.org_id AND m.scope_team = e.team
      ), 0) AS member_count
    FROM events e
    LEFT JOIN team_budgets b ON b.org_id = e.org_id AND b.team = e.team
    WHERE e.org_id = ? AND e.created_at >= ?
    GROUP BY e.team
    ORDER BY cost_usd DESC
  `).bind(orgId, since).all();

  // Members list with their usage (join on user_id or scope_team)
  const { results: members } = await c.env.DB.prepare(`
    SELECT m.id, m.email, m.name, m.role, m.scope_team, m.api_key_hint,
           datetime(m.created_at, 'unixepoch') AS created_at
    FROM org_members m
    WHERE m.org_id = ?
    ORDER BY m.created_at ASC
  `).bind(orgId).all();

  const budgetPct = org?.budget_usd
    ? Math.round(((mtd?.mtd_cost_usd ?? 0) / org.budget_usd) * 100)
    : 0;

  const eventsThisMonth = mtd?.mtd_event_count ?? 0;
  const eventsLimit     = (org?.plan ?? 'free') === 'free' ? 50_000 : null;

  return c.json({
    org: {
      id:               orgId,
      name:             org?.name,
      email:            org?.email,
      plan:             org?.plan ?? 'free',
      budget_usd:       org?.budget_usd ?? 0,
      budget_pct:       budgetPct,
      mtd_cost_usd:     mtd?.mtd_cost_usd ?? 0,
      events_this_month: eventsThisMonth,
      events_limit:     eventsLimit,
      benchmark_opt_in: benchmark_opt_in === 1,
    },
    totals:  orgRow ?? {},
    teams,
    members,
    period_days: period,
  });
});

// ── GET /v1/admin/audit — fetch audit log (admin+ only) ───────────────────
admin.get('/audit', async (c) => {
  const orgId = c.get('orgId');
  const role = c.get('role');
  // Require at least admin (ceo/superadmin/owner also pass via hasRole)
  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Audit log requires admin or higher role' }, 403);
  }

  const limit        = Math.min(parseInt(c.req.query('limit') ?? '50', 10), 500);
  const since        = c.req.query('since') ?? null;
  const until        = c.req.query('until') ?? null;
  const actorRole    = c.req.query('actor_role') ?? null;
  const resourceType = c.req.query('resource_type') ?? null;
  const eventName    = c.req.query('event_name') ?? null;

  const conditions: string[] = ['org_id = ?'];
  const params: unknown[]    = [orgId];

  if (since)        { conditions.push('created_at >= ?'); params.push(since); }
  if (until)        { conditions.push('created_at <= ?'); params.push(until); }
  if (actorRole)    { conditions.push('actor_role = ?');  params.push(actorRole); }
  if (resourceType) { conditions.push('resource = ?');    params.push(resourceType); }
  if (eventName)    { conditions.push('action LIKE ?');   params.push(eventName + '%'); }

  params.push(limit);
  const { results } = await c.env.DB.prepare(`
    SELECT actor_email, actor_role, event_type, action, resource,
           detail, ip_address, created_at
    FROM audit_events
    WHERE ${conditions.join(' AND ')}
    ORDER BY created_at DESC
    LIMIT ?
  `).bind(...params).all();

  return c.json({
    events: results,
    count: results.length,
    filters: { since, until, actor_role: actorRole, resource_type: resourceType, event_name: eventName },
  });
});

// ── GET /v1/admin/security — security overview stats (admin+ only) ────────
admin.get('/security', async (c) => {
  const orgId = c.get('orgId');
  const role = c.get('role');
  if (!hasRole(role, 'admin')) {
    return c.json({ error: 'Security view requires admin or higher role' }, 403);
  }

  const now = Math.floor(Date.now() / 1000);
  const dayAgo = now - 86400;

  // Count audit events today
  const auditToday = await c.env.DB.prepare(`
    SELECT COUNT(*) as count FROM audit_events WHERE org_id = ? AND created_at >= ?
  `).bind(orgId, dayAgo).first() as { count: number } | null;

  // Count active members
  const memberCount = await c.env.DB.prepare(`
    SELECT COUNT(*) as count FROM org_members WHERE org_id = ?
  `).bind(orgId).first() as { count: number } | null;

  // Get org plan
  const org = await c.env.DB.prepare(`
    SELECT plan, budget_usd FROM orgs WHERE id = ?
  `).bind(orgId).first() as { plan: string; budget_usd: number } | null;

  const plan = org?.plan || 'free';
  const retentionDays = plan === 'enterprise' ? 'unlimited' : plan === 'team' ? 90 : 7;

  return c.json({
    audit_events_today: auditToday?.count ?? 0,
    active_members: (memberCount?.count ?? 0) + 1, // +1 for owner
    plan,
    retention_days: retentionDays,
    security_features: {
      api_key_hashing: 'SHA-256',
      session_security: 'HTTP-only, SameSite=Lax, Secure',
      data_encryption: 'AES-256 at rest (Cloudflare D1)',
      access_control: 'RBAC (owner/superadmin/ceo/admin/member/viewer)',
      rate_limiting: true,
    }
  });
});

// ── GET /v1/admin/members/:id/usage — usage for a specific member ─────────────
admin.get('/members/:id/usage', async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');
  const period   = Math.min(parseInt(c.req.query('period') ?? '30', 10) || 30, 365);
  const since    = Math.floor(Date.now() / 1000) - period * 86_400;

  const member = await c.env.DB.prepare(
    'SELECT email, name, role, scope_team FROM org_members WHERE id = ? AND org_id = ?'
  ).bind(memberId, orgId).first<{ email: string; name: string; role: string; scope_team: string | null }>();

  if (!member) return c.json({ error: 'Member not found' }, 404);

  // If member has a scope_team, filter by it; otherwise show all org events
  // (members without a scope can ingest under any team tag — use user_id for attribution)
  const clause = member.scope_team ? ' AND team = ?' : '';
  const args   = member.scope_team ? [orgId, since, member.scope_team] : [orgId, since];

  const stats = await c.env.DB.prepare(`
    SELECT
      COALESCE(SUM(cost_usd), 0)     AS total_cost_usd,
      COALESCE(SUM(total_tokens), 0) AS total_tokens,
      COALESCE(COUNT(*), 0)          AS total_requests,
      COALESCE(AVG(latency_ms), 0)   AS avg_latency_ms
    FROM events WHERE org_id = ? AND created_at >= ?${clause}
  `).bind(...args).first();

  return c.json({ member, stats, period_days: period });
});

// ── GET /v1/admin/team-budgets — list all team budgets ───────────────────────
admin.get('/team-budgets', async (c) => {
  const orgId = c.get('orgId');

  const { results } = await c.env.DB.prepare(`
    SELECT team, budget_usd, datetime(updated_at, 'unixepoch') AS updated_at
    FROM team_budgets WHERE org_id = ?
    ORDER BY team ASC
  `).bind(orgId).all();

  return c.json({ budgets: results });
});

// ── PUT /v1/admin/team-budgets/:team — set budget for a team ─────────────────
admin.put('/team-budgets/:team', async (c) => {
  const orgId = c.get('orgId');
  const team  = c.req.param('team');
  let body: { budget_usd?: number; updated_at?: number };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (typeof body.budget_usd !== 'number' || body.budget_usd < 0) {
    return c.json({ error: 'budget_usd must be a non-negative number' }, 400);
  }

  // Optimistic concurrency: if caller supplies updated_at, use it in the WHERE
  // clause so a concurrent write that already changed the row returns 409.
  const existingRow = await c.env.DB.prepare(
    'SELECT updated_at FROM team_budgets WHERE org_id = ? AND team = ?'
  ).bind(orgId, team).first<{ updated_at: number } | null>();

  if (existingRow !== null) {
    // Row exists — do a guarded UPDATE
    const expectedUpdatedAt = body.updated_at ?? existingRow.updated_at;
    const result = await c.env.DB.prepare(`
      UPDATE team_budgets SET budget_usd = ?, updated_at = unixepoch()
      WHERE org_id = ? AND team = ? AND updated_at = ?
    `).bind(body.budget_usd, orgId, team, expectedUpdatedAt).run();

    if (result.meta.changes === 0) {
      return c.json({ error: 'Conflict: budget was updated by another request. Fetch the latest and retry.' }, 409);
    }
  } else {
    // Row does not exist — safe to insert
    await c.env.DB.prepare(`
      INSERT INTO team_budgets (org_id, team, budget_usd, updated_at)
      VALUES (?, ?, ?, unixepoch())
    `).bind(orgId, team, body.budget_usd).run();
  }

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin_action.budget_policy_changed',
    resource_type: 'budget_policy',
    resource_id:   team,
    metadata:      { budget_usd: body.budget_usd },
  });

  return c.json({ ok: true, team, budget_usd: body.budget_usd });
});

// ── DELETE /v1/admin/team-budgets/:team — remove team budget ─────────────────
admin.delete('/team-budgets/:team', async (c) => {
  const orgId = c.get('orgId');
  const team  = c.req.param('team');

  await c.env.DB.prepare(
    'DELETE FROM team_budgets WHERE org_id = ? AND team = ?'
  ).bind(orgId, team).run();

  return c.json({ ok: true });
});

// ── PATCH /v1/admin/org — update org-level budget, name, or benchmark opt-in ─
admin.patch('/org', async (c) => {
  const orgId = c.get('orgId');
  let body: { budget_usd?: number; name?: string; benchmark_opt_in?: boolean };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const updates: string[] = [];
  const params: unknown[] = [];

  if (typeof body.budget_usd === 'number' && body.budget_usd >= 0) {
    updates.push('budget_usd = ?'); params.push(body.budget_usd);
  }
  if (typeof body.name === 'string' && body.name.trim()) {
    updates.push('name = ?'); params.push(body.name.trim());
  }
  if (typeof body.benchmark_opt_in === 'boolean') {
    updates.push('benchmark_opt_in = ?'); params.push(body.benchmark_opt_in ? 1 : 0);
  }
  if (updates.length === 0) return c.json({ error: 'Provide budget_usd, name, or benchmark_opt_in.' }, 400);

  params.push(orgId);
  await c.env.DB.prepare(
    `UPDATE orgs SET ${updates.join(', ')} WHERE id = ?`
  ).bind(...params).run();

  return c.json({ ok: true });
});

// /v1/admin/audit-log is intentionally disabled for org API keys.
// The org audit log is at /v1/audit-log.  Return 403 so callers get a
// proper authorization error rather than a 404 "not found".
admin.get('/audit-log', (c) => {
  return c.json({ error: 'Forbidden: use /v1/audit-log for org audit logs' }, 403);
});

// ── Budget Policies CRUD ──────────────────────────────────────────────────────
// scope:  'org' | 'team' | 'developer' | 'provider' | 'team_provider'
// scope_target: team name / developer email / provider name / "team::provider" combo
// provider_target: provider name when scope = 'team_provider' (scope_target = team)
// enforcement: 'alert' | 'throttle' | 'block'

const VALID_SCOPES = new Set(['org', 'team', 'developer', 'provider', 'team_provider']);
const VALID_ENFORCEMENT = new Set(['alert', 'throttle', 'block']);

// ── GET /v1/admin/budget-policies — list all budget policies ─────────────────
admin.get('/budget-policies', adminOnly, async (c) => {
  const orgId = c.get('orgId');

  const { results } = await c.env.DB.prepare(`
    SELECT id, scope, scope_target, provider_target,
           monthly_limit_usd,
           alert_threshold_50, alert_threshold_80, alert_threshold_100,
           enforcement, created_at, updated_at
    FROM budget_policies WHERE org_id = ?
    ORDER BY scope, scope_target
  `).bind(orgId).all();

  return c.json({ policies: results });
});

// ── POST /v1/admin/budget-policies — create a budget policy ──────────────────
admin.post('/budget-policies', async (c) => {
  const orgId = c.get('orgId');

  let body: {
    scope: string;
    scope_target?: string;
    provider_target?: string;
    monthly_limit_usd: number;
    alert_threshold_50?: boolean;
    alert_threshold_80?: boolean;
    alert_threshold_100?: boolean;
    enforcement?: string;
  };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (!VALID_SCOPES.has(body.scope)) {
    return c.json({ error: `scope must be one of: ${[...VALID_SCOPES].join(', ')}` }, 400);
  }
  if (typeof body.monthly_limit_usd !== 'number' || body.monthly_limit_usd <= 0) {
    return c.json({ error: 'monthly_limit_usd must be a positive number' }, 400);
  }
  const enforcement = body.enforcement ?? 'alert';
  if (!VALID_ENFORCEMENT.has(enforcement)) {
    return c.json({ error: `enforcement must be one of: ${[...VALID_ENFORCEMENT].join(', ')}` }, 400);
  }
  // Scopes that require scope_target
  if (['team', 'developer', 'provider', 'team_provider'].includes(body.scope) && !body.scope_target) {
    return c.json({ error: `scope_target is required when scope = '${body.scope}'` }, 400);
  }
  // team_provider requires provider_target
  if (body.scope === 'team_provider' && !body.provider_target) {
    return c.json({ error: 'provider_target is required when scope = team_provider' }, 400);
  }

  const countResult = await c.env.DB.prepare(
    'SELECT COUNT(*) as cnt FROM budget_policies WHERE org_id = ?'
  ).bind(orgId).first<{ cnt: number }>();

  if ((countResult?.cnt ?? 0) >= 100) {
    return c.json({ error: 'Budget policy limit reached (max 100 per org)' }, 429);
  }

  const id = crypto.randomUUID();
  await c.env.DB.prepare(`
    INSERT INTO budget_policies
      (id, org_id, scope, scope_target, provider_target,
       monthly_limit_usd, alert_threshold_50, alert_threshold_80, alert_threshold_100,
       enforcement, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
  `).bind(
    id, orgId,
    body.scope,
    body.scope_target ?? null,
    body.provider_target ?? null,
    body.monthly_limit_usd,
    body.alert_threshold_50 !== false ? 1 : 0,
    body.alert_threshold_80 !== false ? 1 : 0,
    body.alert_threshold_100 !== false ? 1 : 0,
    enforcement,
  ).run();

  logAudit(c, {
    event_type: 'admin_action', event_name: 'admin_action.budget_policy_created',
    resource_type: 'budget_policy', resource_id: id,
    metadata: { scope: body.scope, scope_target: body.scope_target, monthly_limit_usd: body.monthly_limit_usd },
  });

  return c.json({ ok: true, id }, 201);
});

// ── PUT /v1/admin/budget-policies/:id — update a budget policy ───────────────
admin.put('/budget-policies/:id', async (c) => {
  const orgId = c.get('orgId');
  const policyId = c.req.param('id');

  const existing = await c.env.DB.prepare(
    'SELECT id FROM budget_policies WHERE id = ? AND org_id = ?'
  ).bind(policyId, orgId).first();
  if (!existing) return c.json({ error: 'Policy not found' }, 404);

  let body: {
    monthly_limit_usd?: number;
    alert_threshold_50?: boolean;
    alert_threshold_80?: boolean;
    alert_threshold_100?: boolean;
    enforcement?: string;
  };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const updates: string[] = ["updated_at = datetime('now')"];
  const params: unknown[] = [];

  if (body.monthly_limit_usd !== undefined) {
    if (typeof body.monthly_limit_usd !== 'number' || body.monthly_limit_usd <= 0) {
      return c.json({ error: 'monthly_limit_usd must be a positive number' }, 400);
    }
    updates.push('monthly_limit_usd = ?'); params.push(body.monthly_limit_usd);
  }
  if (typeof body.alert_threshold_50 === 'boolean') {
    updates.push('alert_threshold_50 = ?'); params.push(body.alert_threshold_50 ? 1 : 0);
  }
  if (typeof body.alert_threshold_80 === 'boolean') {
    updates.push('alert_threshold_80 = ?'); params.push(body.alert_threshold_80 ? 1 : 0);
  }
  if (typeof body.alert_threshold_100 === 'boolean') {
    updates.push('alert_threshold_100 = ?'); params.push(body.alert_threshold_100 ? 1 : 0);
  }
  if (body.enforcement && VALID_ENFORCEMENT.has(body.enforcement)) {
    updates.push('enforcement = ?'); params.push(body.enforcement);
  }

  params.push(policyId, orgId);
  await c.env.DB.prepare(
    `UPDATE budget_policies SET ${updates.join(', ')} WHERE id = ? AND org_id = ?`
  ).bind(...params).run();

  logAudit(c, {
    event_type: 'admin_action', event_name: 'admin_action.budget_policy_updated',
    resource_type: 'budget_policy', resource_id: policyId, metadata: body,
  });

  return c.json({ ok: true });
});

// ── DELETE /v1/admin/budget-policies/:id — remove a budget policy ─────────────
admin.delete('/budget-policies/:id', async (c) => {
  const orgId = c.get('orgId');
  const policyId = c.req.param('id');

  const result = await c.env.DB.prepare(
    'DELETE FROM budget_policies WHERE id = ? AND org_id = ?'
  ).bind(policyId, orgId).run();

  if (result.meta.changes === 0) return c.json({ error: 'Policy not found' }, 404);

  logAudit(c, {
    event_type: 'admin_action', event_name: 'admin_action.budget_policy_deleted',
    resource_type: 'budget_policy', resource_id: policyId, metadata: {},
  });

  return c.json({ ok: true });
});

// ── GET /v1/admin/developers/recommendations — ranked dev efficiency ──────────
// Returns developers ranked by cost efficiency signals for superadmin review.
admin.get('/developers/recommendations', async (c) => {
  const orgId = c.get('orgId');
  const days  = Math.min(parseInt(c.req.query('days') ?? '30', 10) || 30, 90);
  const since = (() => {
    const d = new Date(Date.now() - (days - 1) * 86400000);
    return d.toISOString().slice(0, 10) + ' 00:00:00';
  })();

  const { results } = await c.env.DB.prepare(`
    SELECT
      developer_email,
      team,
      COALESCE(SUM(cost_usd), 0)       AS total_cost,
      COALESCE(SUM(commits), 0)         AS commits,
      COALESCE(SUM(pull_requests), 0)   AS pull_requests,
      COALESCE(SUM(lines_added), 0)     AS lines_added,
      COALESCE(SUM(lines_removed), 0)   AS lines_removed,
      COALESCE(SUM(cached_tokens), 0)   AS cached_tokens,
      COALESCE(SUM(input_tokens + output_tokens + cached_tokens), 0) AS total_tokens
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email, team
    ORDER BY total_cost DESC
    LIMIT 50
  `).bind(orgId, since).all<{ developer_email: string; team: string; total_cost: number; commits: number; pull_requests: number; lines_added: number; lines_removed: number; cached_tokens: number; total_tokens: number }>();

  const recs = (results ?? []).map((d) => {
    const costPerPR      = d.pull_requests > 0 ? +(d.total_cost / d.pull_requests).toFixed(4) : null;
    const costPerCommit  = d.commits > 0       ? +(d.total_cost / d.commits).toFixed(4) : null;
    const cacheRate      = d.total_tokens > 0  ? +(d.cached_tokens / d.total_tokens * 100).toFixed(1) : null;
    const linesPerDollar = d.total_cost > 0    ? Math.round((d.lines_added + d.lines_removed) / d.total_cost) : null;

    // Multi-signal savings estimate:
    //   Signal 1 — low cache rate (<20%): potential ~30% savings proportional to how far below 20%
    //   Signal 2 — no PRs (cost exists but no productivity signal): flag as unattributed spend
    //   Signal 3 — zero lines/$ when cost > $5 (pure chat, no code output): flag as workflow issue
    let savingsOpportunity = 0;
    if (d.total_cost > 1) {
      // Cache signal: scale savings linearly — 0% cache → 30% savings, 20% cache → 0% savings
      if (cacheRate !== null && cacheRate < 20) {
        const cacheSavingsPct = (20 - Number(cacheRate)) / 20 * 0.30;
        savingsOpportunity += d.total_cost * cacheSavingsPct;
      }
      // No-PR signal: cost with no attributed PRs suggests unbounded exploration
      if (d.pull_requests === 0 && d.total_cost > 5) {
        savingsOpportunity += d.total_cost * 0.10;
      }
      // Low output signal: no code lines produced despite spend
      if (linesPerDollar !== null && linesPerDollar < 10 && d.total_cost > 5) {
        savingsOpportunity += d.total_cost * 0.10;
      }
    }
    savingsOpportunity = +savingsOpportunity.toFixed(4);

    // Identify the primary savings reason for the dashboard tooltip
    const savingsReasons: string[] = [];
    if (cacheRate !== null && cacheRate < 20 && d.total_cost > 1) savingsReasons.push('low_cache_rate');
    if (d.pull_requests === 0 && d.total_cost > 5) savingsReasons.push('no_pr_attribution');
    if (linesPerDollar !== null && linesPerDollar < 10 && d.total_cost > 5) savingsReasons.push('low_code_output');

    return {
      developer_email: d.developer_email,
      team: d.team,
      total_cost: d.total_cost,
      cost_per_pr: costPerPR,
      cost_per_commit: costPerCommit,
      cache_hit_rate_pct: cacheRate,
      lines_per_dollar: linesPerDollar,
      savings_opportunity_usd: savingsOpportunity,
      savings_reasons: savingsReasons,
    };
  });

  // Sort by savings_opportunity desc
  recs.sort((a, b) => b.savings_opportunity_usd - a.savings_opportunity_usd);

  // Explain when empty — helps the dashboard show a meaningful message
  // Check whether the org has *any* cross-platform data at all (not just in this period)
  let empty_reason: string | null = null;
  if (recs.length === 0) {
    const anyData = await c.env.DB.prepare(
      'SELECT 1 FROM cross_platform_usage WHERE org_id = ? LIMIT 1'
    ).bind(orgId).first();
    empty_reason = anyData
      ? `No developer efficiency data for the selected period (${days}d). Try a longer range.`
      : 'No cross-platform usage data yet. Connect GitHub via the Integrations tab to populate developer efficiency metrics.';
  }

  return c.json({ period_days: days, recommendations: recs, empty_reason });
});

// ── GET /v1/admin/developers/quality — per-developer avg quality scores ────────
admin.get('/developers/quality', async (c) => {
  const orgId = c.get('orgId');
  const days  = Math.min(parseInt(c.req.query('days') ?? '30', 10) || 30, 90);
  const since = (() => {
    const d = new Date(Date.now() - (days - 1) * 86400000);
    return Math.floor(d.getTime() / 1000);
  })();

  const { results } = await c.env.DB.prepare(`
    SELECT
      developer_email,
      AVG(hallucination_score)   AS avg_hallucination_score,
      AVG(faithfulness_score)    AS avg_faithfulness_score,
      AVG(relevancy_score)       AS avg_relevancy_score,
      COUNT(CASE WHEN hallucination_score IS NOT NULL THEN 1 END) AS scored_events,
      COUNT(*)                   AS total_events
    FROM events
    WHERE org_id = ? AND created_at >= ? AND developer_email IS NOT NULL
    GROUP BY developer_email
    ORDER BY avg_hallucination_score DESC NULLS LAST
  `).bind(orgId, since).all<{
    developer_email: string;
    avg_hallucination_score: number | null;
    avg_faithfulness_score: number | null;
    avg_relevancy_score: number | null;
    scored_events: number;
    total_events: number;
  }>();

  const quality = (results ?? []).map((r) => ({
    developer_email: r.developer_email,
    avg_hallucination_score: r.avg_hallucination_score != null ? Math.round(r.avg_hallucination_score * 1000) / 1000 : null,
    avg_faithfulness_score:  r.avg_faithfulness_score  != null ? Math.round(r.avg_faithfulness_score  * 1000) / 1000 : null,
    avg_relevancy_score:     r.avg_relevancy_score     != null ? Math.round(r.avg_relevancy_score     * 1000) / 1000 : null,
    scored_events: r.scored_events,
    total_events:  r.total_events,
  }));

  return c.json({ period_days: days, quality });
});

// ── GET /v1/admin/budget-alerts — individuals/teams that hit thresholds ────────
admin.get('/budget-alerts', async (c) => {
  const orgId    = c.get('orgId');
  const threshold = Math.max(0, Math.min(100, parseFloat(c.req.query('threshold_pct') ?? '80')));

  // Get all budget policies with their current MTD spend
  const startOfMonth = new Date();
  startOfMonth.setUTCDate(1); startOfMonth.setUTCHours(0, 0, 0, 0);
  const monthStartIso  = startOfMonth.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');
  const monthStartUnix = Math.floor(startOfMonth.getTime() / 1000);

  const { results: policies } = await c.env.DB.prepare(`
    SELECT id, scope, scope_target, monthly_limit_usd, enforcement
    FROM budget_policies
    WHERE org_id = ?
  `).bind(orgId).all<{ id: string; scope: string; scope_target: string | null; monthly_limit_usd: number; enforcement: string }>();

  // Batch MTD spend in 2 queries (cross_platform_usage + events) instead of N+1 per policy.
  // Aggregate spend grouped by scope dimension, then join in JS.
  const [cpuRows, evRows] = await Promise.all([
    c.env.DB.prepare(`
      SELECT
        COALESCE(SUM(cost_usd), 0)                                       AS org_cost,
        COALESCE(SUM(CASE WHEN team              IS NOT NULL THEN cost_usd ELSE 0 END), 0) AS _unused,
        team, developer_email, provider
      FROM cross_platform_usage
      WHERE org_id = ? AND created_at >= ?
      GROUP BY team, developer_email, provider
    `).bind(orgId, monthStartIso).all<{ org_cost: number; team: string | null; developer_email: string | null; provider: string | null }>(),
    c.env.DB.prepare(`
      SELECT COALESCE(SUM(cost_usd), 0) AS org_cost, developer_email
      FROM events
      WHERE org_id = ? AND created_at >= ?
      GROUP BY developer_email
    `).bind(orgId, monthStartUnix).all<{ org_cost: number; developer_email: string | null }>(),
  ]);

  // Pre-aggregate totals by dimension for O(1) lookup per policy
  let cpuOrgTotal = 0, evOrgTotal = 0;
  const cpuByTeam    = new Map<string, number>();
  const cpuByDev     = new Map<string, number>();
  const cpuByProv    = new Map<string, number>();
  const evByDev      = new Map<string, number>();

  for (const r of cpuRows.results ?? []) {
    const c2 = r.org_cost;
    cpuOrgTotal += c2;
    if (r.team)            cpuByTeam.set(r.team, (cpuByTeam.get(r.team) ?? 0) + c2);
    if (r.developer_email) cpuByDev.set(r.developer_email, (cpuByDev.get(r.developer_email) ?? 0) + c2);
    if (r.provider)        cpuByProv.set(r.provider, (cpuByProv.get(r.provider) ?? 0) + c2);
  }
  for (const r of evRows.results ?? []) {
    evOrgTotal += r.org_cost;
    if (r.developer_email) evByDev.set(r.developer_email, (evByDev.get(r.developer_email) ?? 0) + r.org_cost);
  }

  const alerts: unknown[] = [];

  for (const p of policies) {
    let mtdCost = 0;
    if (p.scope === 'org') {
      mtdCost = cpuOrgTotal + evOrgTotal;
    } else if (p.scope === 'team' && p.scope_target) {
      mtdCost = cpuByTeam.get(p.scope_target) ?? 0;
    } else if (p.scope === 'developer' && p.scope_target) {
      mtdCost = (cpuByDev.get(p.scope_target) ?? 0) + (evByDev.get(p.scope_target) ?? 0);
    } else if (p.scope === 'provider' && p.scope_target) {
      mtdCost = cpuByProv.get(p.scope_target) ?? 0;
    }

    const pct = p.monthly_limit_usd > 0 ? Math.round((mtdCost / p.monthly_limit_usd) * 100) : 0;
    if (pct >= threshold) {
      alerts.push({
        policy_id:          p.id,
        scope:              p.scope,
        scope_target:       p.scope_target,
        monthly_limit_usd:  p.monthly_limit_usd,
        mtd_cost_usd:       Math.round(mtdCost * 10000) / 10000,
        budget_pct:         pct,
        enforcement:        p.enforcement,
        status:             pct >= 100 ? 'exceeded' : 'warning',
      });
    }
  }

  alerts.sort((a, b) => (b as { budget_pct: number }).budget_pct - (a as { budget_pct: number }).budget_pct);

  return c.json({ alerts, threshold_pct: threshold, generated_at: new Date().toISOString() });
});

// ── GET /v1/admin/budget-control — superadmin Budget Control Center ───────────
// Returns all budget policies with current MTD spend per team and per provider.
admin.get('/budget-control', superadminOnly, async (c) => {
  const orgId = c.get('orgId');

  const startOfMonth = new Date();
  startOfMonth.setUTCDate(1); startOfMonth.setUTCHours(0, 0, 0, 0);
  const monthStartIso = startOfMonth.toISOString().replace('T', ' ').replace(/\.\d+Z$/, '');

  // All budget policies for the org
  const { results: policies } = await c.env.DB.prepare(
    `SELECT id, scope, scope_target, provider_target,
            monthly_limit_usd, enforcement,
            alert_threshold_50, alert_threshold_80, alert_threshold_100,
            created_at, updated_at
     FROM budget_policies WHERE org_id = ?
     ORDER BY scope, scope_target`
  ).bind(orgId).all();

  // MTD spend per team
  const { results: teamSpend } = await c.env.DB.prepare(`
    SELECT team,
           COALESCE(SUM(cost_usd), 0)              AS spend_this_month,
           COUNT(DISTINCT developer_email)          AS developer_count,
           COUNT(*)                                 AS request_count
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY team
    ORDER BY spend_this_month DESC
  `).bind(orgId, monthStartIso).all();

  // MTD spend per provider/tool
  const { results: providerSpend } = await c.env.DB.prepare(`
    SELECT provider,
           COALESCE(SUM(cost_usd), 0) AS spend_this_month,
           COUNT(*)                   AS request_count
    FROM cross_platform_usage
    WHERE org_id = ? AND created_at >= ?
    GROUP BY provider
    ORDER BY spend_this_month DESC
  `).bind(orgId, monthStartIso).all();

  return c.json({
    policies:       policies       ?? [],
    team_spend:     teamSpend      ?? [],
    provider_spend: providerSpend  ?? [],
    generated_at:   new Date().toISOString(),
  });
});

export { admin };
