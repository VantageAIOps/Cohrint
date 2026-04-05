import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';
import { logAudit } from '../lib/audit';

const admin = new Hono<{ Bindings: Bindings; Variables: Variables }>();

admin.use('*', authMiddleware, adminOnly);

// ── GET /v1/admin/overview — all teams with usage + budgets ──────────────────
admin.get('/overview', async (c) => {
  const orgId  = c.get('orgId');
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

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
    FROM events WHERE org_id = ? AND created_at >= strftime('%s', 'now', 'start of month')
  `).bind(orgId).first<{ mtd_cost_usd: number; mtd_event_count: number }>();

  const org = await c.env.DB.prepare(
    'SELECT budget_usd, plan, name, email FROM orgs WHERE id = ?'
  ).bind(orgId).first<{ budget_usd: number; plan: string; name: string; email: string }>();

  // Per-team breakdown with budgets
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
      END AS budget_pct
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
  const eventsLimit     = (org?.plan ?? 'free') === 'free' ? 10_000 : null;

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
    },
    totals:  orgRow ?? {},
    teams,
    members,
    period_days: period,
  });
});

// ── GET /v1/admin/audit — fetch audit log ─────────────────────────────────
admin.get('/audit', async (c) => {
  const orgId = c.get('orgId');
  const role = c.get('role');
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Audit log requires owner or admin role' }, 403);
  }

  const limit = Math.min(parseInt(c.req.query('limit') ?? '50', 10), 200);
  const { results } = await c.env.DB.prepare(`
    SELECT action, actor_email, actor_role, resource, detail, ip_address, created_at
    FROM audit_events
    WHERE org_id = ?
    ORDER BY created_at DESC
    LIMIT ?
  `).bind(orgId, limit).all();

  return c.json({ events: results });
});

// ── GET /v1/admin/security — security overview stats ──────────────────────
admin.get('/security', async (c) => {
  const orgId = c.get('orgId');
  const role = c.get('role');
  if (role !== 'owner' && role !== 'admin') {
    return c.json({ error: 'Security view requires owner or admin role' }, 403);
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
      access_control: 'RBAC (owner/admin/member/viewer)',
      rate_limiting: true,
    }
  });
});

// ── GET /v1/admin/members/:id/usage — usage for a specific member ─────────────
admin.get('/members/:id/usage', async (c) => {
  const orgId    = c.get('orgId');
  const memberId = c.req.param('id');
  const period   = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
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
  let body: { budget_usd?: number };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (typeof body.budget_usd !== 'number' || body.budget_usd < 0) {
    return c.json({ error: 'budget_usd must be a non-negative number' }, 400);
  }

  await c.env.DB.prepare(`
    INSERT INTO team_budgets (org_id, team, budget_usd, updated_at)
    VALUES (?, ?, ?, unixepoch())
    ON CONFLICT(org_id, team) DO UPDATE SET budget_usd = excluded.budget_usd, updated_at = unixepoch()
  `).bind(orgId, team, body.budget_usd).run();

  logAudit(c, {
    event_type:    'admin_action',
    event_name:    'admin.team_budget.update',
    resource_type: 'team_budget',
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

// ── PATCH /v1/admin/org — update org-level budget or name ────────────────────
admin.patch('/org', async (c) => {
  const orgId = c.get('orgId');
  let body: { budget_usd?: number; name?: string };
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
  if (updates.length === 0) return c.json({ error: 'Provide budget_usd or name.' }, 400);

  params.push(orgId);
  await c.env.DB.prepare(
    `UPDATE orgs SET ${updates.join(', ')} WHERE id = ?`
  ).bind(...params).run();

  return c.json({ ok: true });
});

// ── GET /audit-log — all orgs, admin only ────────────────────────────────────

admin.get('/audit-log', async (c) => {
  const limit     = Math.max(1, Math.min(parseInt(c.req.query('limit')   ?? '100', 10), 500));
  const offset    = parseInt(c.req.query('offset')  ?? '0', 10);
  const eventType = c.req.query('event_type') ?? null;
  const orgFilter = c.req.query('org_id')     ?? null;
  const from      = c.req.query('from')
    ? Math.floor(new Date(c.req.query('from')! + 'T00:00:00Z').getTime() / 1000) : null;
  const to        = c.req.query('to')
    ? Math.floor(new Date(c.req.query('to')!   + 'T23:59:59Z').getTime() / 1000) : null;

  const conditions: string[] = [];
  const bindings: unknown[]  = [];
  if (orgFilter)    { conditions.push('org_id = ?');     bindings.push(orgFilter); }
  if (eventType)    { conditions.push('event_type = ?'); bindings.push(eventType); }
  if (from !== null){ conditions.push('created_at >= ?'); bindings.push(from); }
  if (to !== null)  { conditions.push('created_at <= ?'); bindings.push(to); }
  const where = conditions.length ? conditions.join(' AND ') : '1=1';

  const [rows, countRow] = await c.env.DB.batch([
    c.env.DB.prepare(
      `SELECT id, org_id, actor_email, actor_role, action, resource, detail,
              ip_address, event_type,
              datetime(created_at, 'unixepoch') AS created_at
       FROM audit_events WHERE ${where}
       ORDER BY created_at DESC LIMIT ? OFFSET ?`
    ).bind(...bindings, limit, offset),
    c.env.DB.prepare(
      `SELECT COUNT(*) AS total FROM audit_events WHERE ${where}`
    ).bind(...bindings),
  ]);

  const events = rows.results;
  const total  = (countRow.results[0] as { total: number }).total;
  return c.json({ events, total, has_more: offset + events.length < total });
});

export { admin };
