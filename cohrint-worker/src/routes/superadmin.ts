/**
 * Superadmin routes — platform-level analytics + control.
 *
 * Auth: Bearer token = SUPERADMIN_SECRET env var.
 * All routes return 403 if the secret doesn't match.
 *
 * Endpoints:
 *   POST /v1/superadmin/auth                — validate secret, return echo
 *   GET  /v1/superadmin/stats               — platform-wide overview
 *   GET  /v1/superadmin/users               — signup + login activity
 *   GET  /v1/superadmin/geography           — requests by country + colo
 *   GET  /v1/superadmin/features            — feature name usage breakdown
 *   GET  /v1/superadmin/traffic             — daily request timeseries
 *   GET  /v1/superadmin/storage             — DB row counts per table + KV keys
 *   POST /v1/superadmin/reset               — soft/hard reset operations
 */

import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { logAuditRaw } from '../lib/audit';

const superadmin = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// ── Auth guard middleware ─────────────────────────────────────────────────────
// Always return 403 on any auth failure — including the case where
// SUPERADMIN_SECRET is not configured on this deployment. Returning a distinct
// 503 in that case would leak deployment configuration state to anonymous
// callers (lets an attacker distinguish "misconfigured" from "bad token" and
// walk through deployments looking for one without the guard set).
superadmin.use('*', async (c, next) => {
  const secret = c.env.SUPERADMIN_SECRET;
  const auth   = c.req.header('Authorization') ?? '';
  const token  = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';

  // If no secret is configured, no token can ever match — short-circuit with 403.
  if (!secret) {
    return c.json({ error: 'Forbidden' }, 403);
  }

  // Constant-time comparison to prevent timing attacks.
  // Hash both values to ensure equal length, then compare hashes.
  const enc = new TextEncoder();
  const [hashA, hashB] = await Promise.all([
    crypto.subtle.digest('SHA-256', enc.encode(token)),
    crypto.subtle.digest('SHA-256', enc.encode(secret)),
  ]);
  const arrA = new Uint8Array(hashA);
  const arrB = new Uint8Array(hashB);
  let diff = 0;
  for (let i = 0; i < arrA.length; i++) diff |= arrA[i] ^ arrB[i];
  if (diff !== 0) {
    return c.json({ error: 'Forbidden' }, 403);
  }
  return next();
});

// ── POST /v1/superadmin/auth — validate secret ───────────────────────────────
superadmin.post('/auth', (c) => {
  return c.json({ ok: true, ts: new Date().toISOString() });
});

// ── GET /v1/superadmin/stats — platform overview ─────────────────────────────
superadmin.get('/stats', async (c) => {
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  // Bootstrap tables once if missing
  await bootstrapTables(c.env.DB);

  const [orgRow, eventRow, recentOrgs, pageviews] = await Promise.all([
    c.env.DB.prepare(`
      SELECT
        COUNT(*)                                       AS total_orgs,
        SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS new_orgs_period,
        COUNT(DISTINCT plan)                           AS plan_count
      FROM orgs
    `).bind(since).first<{ total_orgs: number; new_orgs_period: number; plan_count: number }>(),

    c.env.DB.prepare(`
      SELECT
        COUNT(*)                    AS total_events,
        COALESCE(SUM(cost_usd), 0)  AS total_cost_usd,
        COALESCE(SUM(total_tokens),0) AS total_tokens,
        COUNT(DISTINCT org_id)      AS active_orgs,
        COALESCE(AVG(latency_ms),0) AS avg_latency_ms
      FROM events WHERE created_at >= ?
    `).bind(since).first<{
      total_events: number; total_cost_usd: number; total_tokens: number;
      active_orgs: number; avg_latency_ms: number;
    }>(),

    c.env.DB.prepare(`
      SELECT id, name, email, plan, datetime(created_at,'unixepoch') AS signed_up
      FROM orgs ORDER BY created_at DESC LIMIT 10
    `).all<{ id: string; name: string; email: string; plan: string; signed_up: string }>(),

    c.env.DB.prepare(`
      SELECT COUNT(*) AS views, COUNT(DISTINCT session_id) AS sessions
      FROM platform_pageviews WHERE created_at >= ?
    `).bind(since).first<{ views: number; sessions: number }>(),
  ]);

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    period_days:      period,
    orgs:             orgRow,
    events:           eventRow,
    pageviews:        pageviews,
    recent_signups:   recentOrgs.results,
    generated_at:     new Date().toISOString(),
  });
});

// ── GET /v1/superadmin/users — signup + login activity ───────────────────────
superadmin.get('/users', async (c) => {
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  await bootstrapTables(c.env.DB);

  const [signups, dailySignups, sessions, avgSession] = await Promise.all([
    c.env.DB.prepare(`
      SELECT id, name, email, plan,
             datetime(created_at,'unixepoch') AS created_at
      FROM orgs WHERE created_at >= ?
      ORDER BY created_at DESC LIMIT 100
    `).bind(since).all<{ id: string; name: string; email: string; plan: string; created_at: string }>(),

    c.env.DB.prepare(`
      SELECT date(created_at,'unixepoch') AS day, COUNT(*) AS count
      FROM orgs WHERE created_at >= ?
      GROUP BY day ORDER BY day
    `).bind(since).all<{ day: string; count: number }>(),

    c.env.DB.prepare(`
      SELECT COUNT(*) AS total_sessions,
             COUNT(DISTINCT org_id) AS unique_orgs
      FROM platform_sessions WHERE created_at >= ?
    `).bind(since).first<{ total_sessions: number; unique_orgs: number }>(),

    c.env.DB.prepare(`
      SELECT COALESCE(AVG(duration_sec), 0) AS avg_duration_sec
      FROM platform_sessions WHERE created_at >= ? AND duration_sec > 0
    `).bind(since).first<{ avg_duration_sec: number }>(),
  ]);

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    period_days:   period,
    signups:       signups.results,
    daily_signups: dailySignups.results,
    sessions:      sessions,
    avg_session:   avgSession,
  });
});

// ── GET /v1/superadmin/geography — country + colo breakdown ──────────────────
superadmin.get('/geography', async (c) => {
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  await bootstrapTables(c.env.DB);

  const [countries, colos] = await Promise.all([
    c.env.DB.prepare(`
      SELECT country, COUNT(*) AS requests
      FROM platform_requests WHERE created_at >= ? AND country IS NOT NULL
      GROUP BY country ORDER BY requests DESC LIMIT 50
    `).bind(since).all<{ country: string; requests: number }>(),

    c.env.DB.prepare(`
      SELECT colo, COUNT(*) AS requests
      FROM platform_requests WHERE created_at >= ? AND colo IS NOT NULL
      GROUP BY colo ORDER BY requests DESC LIMIT 30
    `).bind(since).all<{ colo: string; requests: number }>(),
  ]);

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    period_days: period,
    countries:   countries.results,
    colos:       colos.results,
  });
});

// ── GET /v1/superadmin/features — feature usage across all orgs ───────────────
superadmin.get('/features', async (c) => {
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  const [features, models, providers] = await Promise.all([
    c.env.DB.prepare(`
      SELECT COALESCE(feature, 'untagged') AS feature,
             COUNT(*) AS events,
             COUNT(DISTINCT org_id) AS orgs,
             COALESCE(SUM(cost_usd),0) AS cost_usd
      FROM events WHERE created_at >= ?
      GROUP BY feature ORDER BY events DESC LIMIT 30
    `).bind(since).all<{ feature: string; events: number; orgs: number; cost_usd: number }>(),

    c.env.DB.prepare(`
      SELECT model, COUNT(*) AS events,
             COALESCE(SUM(cost_usd),0) AS cost_usd,
             COALESCE(AVG(latency_ms),0) AS avg_latency_ms
      FROM events WHERE created_at >= ?
      GROUP BY model ORDER BY events DESC LIMIT 20
    `).bind(since).all<{ model: string; events: number; cost_usd: number; avg_latency_ms: number }>(),

    c.env.DB.prepare(`
      SELECT provider, COUNT(*) AS events,
             COALESCE(SUM(cost_usd),0) AS cost_usd
      FROM events WHERE created_at >= ?
      GROUP BY provider ORDER BY events DESC LIMIT 15
    `).bind(since).all<{ provider: string; events: number; cost_usd: number }>(),
  ]);

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    period_days: period,
    features:    features.results,
    models:      models.results,
    providers:   providers.results,
  });
});

// ── GET /v1/superadmin/traffic — daily request + user timeseries ─────────────
superadmin.get('/traffic', async (c) => {
  const period = Math.min(parseInt(c.req.query('period') ?? '30', 10), 365);
  const since  = Math.floor(Date.now() / 1000) - period * 86_400;

  await bootstrapTables(c.env.DB);

  const [apiTraffic, pageTraffic] = await Promise.all([
    c.env.DB.prepare(`
      SELECT date(created_at,'unixepoch') AS day,
             COUNT(*) AS events,
             COUNT(DISTINCT org_id) AS active_orgs,
             COALESCE(SUM(cost_usd),0) AS cost_usd
      FROM events WHERE created_at >= ?
      GROUP BY day ORDER BY day
    `).bind(since).all<{ day: string; events: number; active_orgs: number; cost_usd: number }>(),

    c.env.DB.prepare(`
      SELECT date(created_at,'unixepoch') AS day,
             COUNT(*) AS pageviews,
             COUNT(DISTINCT session_id) AS sessions
      FROM platform_pageviews WHERE created_at >= ?
      GROUP BY day ORDER BY day
    `).bind(since).all<{ day: string; pageviews: number; sessions: number }>(),
  ]);

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    period_days:  period,
    api_traffic:  apiTraffic.results,
    page_traffic: pageTraffic.results,
  });
});

// ── GET /v1/superadmin/storage — table sizes + KV key count ──────────────────
superadmin.get('/storage', async (c) => {
  const tables = ['orgs', 'events', 'org_members', 'team_budgets',
                  'alert_configs', 'platform_pageviews', 'platform_requests', 'platform_sessions'];

  // Use a validated allowlist — never interpolate untrusted values into SQL
  const ALLOWED_TABLES = new Set(tables);
  const counts: Record<string, number> = {};
  await Promise.all(tables.map(async (t) => {
    if (!ALLOWED_TABLES.has(t)) { counts[t] = -1; return; }
    try {
      // Each table name is from a hardcoded array above — safe for interpolation
      const row = await c.env.DB.prepare(`SELECT COUNT(*) AS n FROM ${t}`).first<{ n: number }>();
      counts[t] = row?.n ?? 0;
    } catch {
      counts[t] = -1; // table doesn't exist yet
    }
  }));

  // KV key count via list (limited to 1000 keys max — platform tracking prefix)
  let kvCount = 0;
  try {
    const kv = await c.env.KV.list({ limit: 1000 });
    kvCount = kv.keys.length + (kv.list_complete ? 0 : 1000); // rough estimate if truncated
  } catch { /* best effort */ }

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    }
  );

  return c.json({
    db_tables:    counts,
    kv_keys_approx: kvCount,
    generated_at: new Date().toISOString(),
  });
});

// ── POST /v1/superadmin/reset — soft/hard reset ───────────────────────────────
superadmin.post('/reset', async (c) => {
  let body: { target?: string; mode?: string; confirm?: string };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const { target = '', mode = 'soft', confirm = '' } = body;

  // Safety gate: caller must echo back the target + mode
  if (confirm !== `${target}-${mode}`) {
    return c.json({
      error: 'confirm field must equal "<target>-<mode>" (e.g. "events-soft")',
    }, 400);
  }

  const allowed_targets = ['events', 'platform_pageviews', 'platform_requests',
                           'platform_sessions', 'kv', 'all_platform'];
  if (!allowed_targets.includes(target)) {
    return c.json({ error: `Unknown target. Allowed: ${allowed_targets.join(', ')}` }, 400);
  }
  if (!['soft', 'hard'].includes(mode)) {
    return c.json({ error: 'mode must be "soft" or "hard"' }, 400);
  }

  const results: string[] = [];

  // KV reset
  if (target === 'kv' || target === 'all_platform') {
    try {
      if (mode === 'hard') {
        // Delete all KV keys (up to 1000)
        const listed = await c.env.KV.list({ limit: 1000 });
        await Promise.all(listed.keys.map(k => c.env.KV.delete(k.name)));
        results.push(`kv: deleted ${listed.keys.length} keys`);
      } else {
        // Soft: delete only rate-limit and throttle keys (keep session keys)
        const rl   = await c.env.KV.list({ prefix: 'rl:', limit: 500 });
        const thr  = await c.env.KV.list({ prefix: 'throttle:', limit: 500 });
        const all  = [...rl.keys, ...thr.keys];
        await Promise.all(all.map(k => c.env.KV.delete(k.name)));
        results.push(`kv: cleared ${all.length} rate-limit/throttle keys`);
      }
    } catch (e: any) {
      results.push(`kv: error — ${e?.message}`);
    }
  }

  // DB table reset
  const dbTargets: string[] = target === 'all_platform'
    ? ['platform_pageviews', 'platform_requests', 'platform_sessions']
    : target !== 'kv' ? [target] : [];

  // Double-validate table names against allowlist before SQL interpolation
  const RESET_ALLOWED = new Set(allowed_targets.filter(t => t !== 'kv' && t !== 'all_platform'));
  for (const tbl of dbTargets) {
    if (!RESET_ALLOWED.has(tbl)) {
      results.push(`${tbl}: skipped — not in allowed table list`);
      continue;
    }
    try {
      if (mode === 'hard') {
        await c.env.DB.prepare(`DELETE FROM ${tbl}`).run();
        results.push(`${tbl}: all rows deleted`);
      } else {
        // Soft: delete rows older than 30 days
        const cutoff = Math.floor(Date.now() / 1000) - 30 * 86_400;
        const res = await c.env.DB.prepare(
          `DELETE FROM ${tbl} WHERE created_at < ?`
        ).bind(cutoff).run();
        results.push(`${tbl}: deleted rows older than 30 days (${res.meta.changes} rows)`);
      }
    } catch (e: any) {
      results.push(`${tbl}: error — ${e?.message}`);
    }
  }

  if (results.length === 0) results.push('no operations performed');

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method, target, mode, results },
    }
  );

  return c.json({
    ok:      true,
    target,
    mode,
    results,
    ts:      new Date().toISOString(),
  });
});

// ── Helper: bootstrap platform tracking tables if missing ────────────────────
async function bootstrapTables(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS platform_pageviews (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT,
      page       TEXT,
      referrer   TEXT,
      created_at INTEGER NOT NULL DEFAULT (unixepoch())
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS platform_requests (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      path       TEXT,
      method     TEXT,
      status     INTEGER,
      country    TEXT,
      colo       TEXT,
      created_at INTEGER NOT NULL DEFAULT (unixepoch())
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS platform_sessions (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      org_id       TEXT,
      session_id   TEXT,
      duration_sec INTEGER DEFAULT 0,
      created_at   INTEGER NOT NULL DEFAULT (unixepoch())
    )`),
  ]);
}

export { superadmin };
