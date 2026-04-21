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
    // JOIN orgs to split real (is_test=0) vs test (is_test=1) traffic per day
    c.env.DB.prepare(`
      SELECT date(e.created_at,'unixepoch') AS day,
             COUNT(*) AS events,
             COUNT(DISTINCT e.org_id) AS active_orgs,
             COALESCE(SUM(e.cost_usd),0) AS cost_usd,
             COUNT(CASE WHEN o.is_test = 0 THEN 1 END) AS real_events,
             COUNT(CASE WHEN o.is_test = 1 THEN 1 END) AS test_events,
             COALESCE(SUM(CASE WHEN o.is_test = 0 THEN e.cost_usd ELSE 0 END),0) AS real_cost_usd,
             COUNT(DISTINCT CASE WHEN o.is_test = 0 THEN e.org_id END) AS real_active_orgs
      FROM events e
      JOIN orgs o ON o.id = e.org_id
      WHERE e.created_at >= ?
      GROUP BY day ORDER BY day
    `).bind(since).all<{
      day: string; events: number; active_orgs: number; cost_usd: number;
      real_events: number; test_events: number; real_cost_usd: number; real_active_orgs: number;
    }>(),

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

// ── POST /v1/superadmin/events/rescore — queue score-field backfill for an org ──────────
// Rate limited: 1 req / 15 min per org_id (KV key rescore:ratelimit:{orgId}, TTL 900s)
// Body: { org_id, from (ISO date), to (ISO date), fields_to_clear: string[] }
superadmin.post('/events/rescore', async (c) => {
  let body: { org_id?: unknown; from?: unknown; to?: unknown; fields_to_clear?: unknown };
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const { org_id, from, to, fields_to_clear } = body;

  // ── Validate required fields ────────────────────────────────────────────────
  if (typeof org_id !== 'string' || !org_id.trim()) {
    return c.json({ error: 'org_id is required' }, 400);
  }
  if (typeof from !== 'string' || isNaN(Date.parse(from))) {
    return c.json({ error: 'from must be a valid ISO date string' }, 400);
  }
  if (typeof to !== 'string' || isNaN(Date.parse(to))) {
    return c.json({ error: 'to must be a valid ISO date string' }, 400);
  }
  if (!Array.isArray(fields_to_clear) || fields_to_clear.length === 0) {
    return c.json({ error: 'fields_to_clear must be a non-empty array' }, 400);
  }

  const ALLOWED_FIELDS = new Set([
    'hallucination_score', 'faithfulness_score', 'relevancy_score',
    'toxicity_score', 'efficiency_score',
  ]);
  const validFields = (fields_to_clear as unknown[]).filter(
    (f): f is string => typeof f === 'string' && ALLOWED_FIELDS.has(f),
  );
  if (validFields.length === 0) {
    return c.json({
      error: `fields_to_clear contains no valid field names. Allowed: ${[...ALLOWED_FIELDS].join(', ')}`,
    }, 400);
  }

  // ── Rate limit: 1 req / 15 min per org ────────────────────────────────────
  const rlKey = `rescore:ratelimit:${org_id}`;
  const existing = await c.env.KV.get(rlKey);
  if (existing !== null) {
    return c.json({ error: 'Rate limit exceeded: 1 rescore request per 15 minutes per org' }, 429);
  }
  await c.env.KV.put(rlKey, '1', { expirationTtl: 900 });

  // ── Query events in date range (unix timestamps) ───────────────────────────
  const fromUnix = Math.floor(new Date(from).getTime() / 1000);
  const toUnix   = Math.floor(new Date(to).getTime()   / 1000);

  const { results: rows } = await c.env.DB.prepare(`
    SELECT id, event_id FROM events
    WHERE org_id = ? AND created_at BETWEEN ? AND ?
    LIMIT 10000
  `).bind(org_id, fromUnix, toUnix).all<{ id: number; event_id: string }>();

  // ── Enqueue rescore messages ───────────────────────────────────────────────
  if (rows.length > 0 && c.env.INGEST_QUEUE) {
    const QUEUE_BATCH_MAX = 100; // Cloudflare sendBatch limit
    for (let i = 0; i < rows.length; i += QUEUE_BATCH_MAX) {
      const slice = rows.slice(i, i + QUEUE_BATCH_MAX);
      await c.env.INGEST_QUEUE.sendBatch(
        slice.map(row => ({
          body: {
            type: 'rescore' as const,
            orgId: org_id,
            eventId: row.event_id,
            fieldsToReset: validFields,
          },
        })),
      );
    }
  }

  // ── Audit log ─────────────────────────────────────────────────────────────
  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    org_id, 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'score.rescore_triggered',
      resource_type: 'events',
      metadata: { org_id, from, to, fields_to_clear: validFields, event_count: rows.length },
    },
  );

  return c.json({
    ok:              true,
    queued:          rows.length,
    org_id,
    from,
    to,
    fields_to_clear: validFields,
  });
});

// ── POST /v1/superadmin/rollup/backfill — rebuild events_daily_rollup from raw events ──
// Idempotent: uses INSERT ... ON CONFLICT DO UPDATE. Safe to re-run.
// Processes events in batches of 100 (D1 batch limit). Returns { processed: N }.
superadmin.post('/rollup/backfill', async (c) => {
  const BATCH_SIZE = 100;
  let offset = 0;
  let processed = 0;

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.rollup_backfill_started',
      metadata: { path: c.req.path },
    }
  );

  while (true) {
    const { results } = await c.env.DB.prepare(`
      SELECT
        org_id, model, provider, team,
        prompt_tokens, completion_tokens, cache_tokens, total_tokens,
        cost_usd, latency_ms, cache_hit, created_at
      FROM events
      ORDER BY created_at ASC
      LIMIT ? OFFSET ?
    `).bind(BATCH_SIZE, offset).all<{
      org_id: string;
      model: string | null;
      provider: string | null;
      team: string | null;
      prompt_tokens: number | null;
      completion_tokens: number | null;
      cache_tokens: number | null;
      total_tokens: number | null;
      cost_usd: number | null;
      latency_ms: number | null;
      cache_hit: number | null;
      created_at: number;
    }>();

    if (results.length === 0) break;

    const stmts = results.map(row => {
      const dayUnix = Math.floor(row.created_at / 86400) * 86400;
      const model   = row.model    ?? 'unknown';
      const provider = row.provider ?? '';
      const team    = row.team     ?? '';
      const cost    = row.cost_usd ?? 0;
      const prompt  = row.prompt_tokens ?? 0;
      const completion = row.completion_tokens ?? 0;
      const cache   = row.cache_tokens ?? 0;
      const total   = row.total_tokens ?? (prompt + completion);
      const latency = row.latency_ms ?? 0;
      const isHit   = row.cache_hit ? 1 : 0;

      return c.env.DB.prepare(`
        INSERT INTO events_daily_rollup
          (org_id, date_unix_day, model, provider, team, cost_usd, prompt_tokens, completion_tokens,
           cache_tokens, total_tokens, requests, cache_hits, latency_ms_sum)
        VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
        ON CONFLICT(org_id, date_unix_day, model, team) DO UPDATE SET
          cost_usd          = cost_usd + excluded.cost_usd,
          prompt_tokens     = prompt_tokens + excluded.prompt_tokens,
          completion_tokens = completion_tokens + excluded.completion_tokens,
          cache_tokens      = cache_tokens + excluded.cache_tokens,
          total_tokens      = total_tokens + excluded.total_tokens,
          requests          = requests + 1,
          cache_hits        = cache_hits + excluded.cache_hits,
          latency_ms_sum    = latency_ms_sum + excluded.latency_ms_sum
      `).bind(row.org_id, dayUnix, model, provider, team, cost, prompt, completion, cache, total, isHit, latency);
    });

    await c.env.DB.batch(stmts);
    processed += results.length;
    offset += BATCH_SIZE;

    if (results.length < BATCH_SIZE) break;
  }

  return c.json({ ok: true, processed, ts: new Date().toISOString() });
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

// ── GET /v1/superadmin/ingest/dlq — list DLQ entries stored in KV ────────────
superadmin.get('/ingest/dlq', async (c) => {
  const limit = Math.min(parseInt(c.req.query('limit') ?? '50', 10), 200);

  let entries: unknown[] = [];
  try {
    const listed = await c.env.KV.list({ prefix: 'dlq:entry:', limit });
    const values = await Promise.all(
      listed.keys.map(async (k) => {
        try {
          const raw = await c.env.KV.get(k.name);
          return raw ? JSON.parse(raw) : null;
        } catch {
          return null;
        }
      }),
    );
    entries = values.filter(Boolean);
    entries.sort((a: unknown, b: unknown) =>
      ((b as Record<string, string>).timestamp ?? '').localeCompare(
        (a as Record<string, string>).timestamp ?? '',
      ),
    );
  } catch (err) {
    return c.json({ error: `KV list failed: ${err instanceof Error ? err.message : String(err)}` }, 500);
  }

  logAuditRaw(c.env.DB, c.executionCtx,
    c.req.header('CF-Connecting-IP') ?? 'unknown',
    'superadmin', 'superadmin', 'superadmin',
    {
      event_type: 'admin_action',
      event_name: 'admin_action.superadmin_access',
      metadata: { path: c.req.path, method: c.req.method },
    },
  );

  return c.json({
    count:        entries.length,
    entries,
    generated_at: new Date().toISOString(),
  });
});

export { superadmin };
