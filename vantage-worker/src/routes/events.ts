import { Hono } from 'hono';
import { Bindings, Variables, EventIn, BatchIn } from '../types';
import { authMiddleware } from '../middleware/auth';
import { maybeSendBudgetAlert } from './alerts';

const events = new Hono<{ Bindings: Bindings; Variables: Variables }>();

// Invalidate all analytics KV cache keys for an org — including team-scoped
// variants (e.g. analytics:summary:orgId:engineering). Uses KV.list so new
// team names never cause stale data.
async function invalidateOrgAnalyticsCache(kv: KVNamespace, orgId: string): Promise<void> {
  const prefixes = [
    `analytics:summary:${orgId}:`,
    `analytics:kpis:${orgId}:`,
    `analytics:timeseries:${orgId}:`,
  ];
  await Promise.all(prefixes.map(async (prefix) => {
    const listed = await kv.list({ prefix });
    if (listed.keys.length > 0) {
      await Promise.all(listed.keys.map(k => kv.delete(k.name)));
    }
  }));
}

events.use('*', authMiddleware);

// Block viewer-role keys from ingesting events
events.use('/', async (c, next) => {
  if (c.req.method !== 'GET' && c.get('role') === 'viewer') {
    return c.json({ error: 'Viewer keys are read-only and cannot ingest events' }, 403);
  }
  return await next();
});
events.use('/batch', async (c, next) => {
  if (c.get('role') === 'viewer') {
    return c.json({ error: 'Viewer keys are read-only and cannot ingest events' }, 403);
  }
  return await next();
});

// ── Budget policy enforcement ─────────────────────────────────────────────────
interface BudgetCheck {
  blocked: boolean;
  throttled: boolean;
  pct: number;
  policy_id: string | null;
  scope: string | null;
}

async function checkBudgetPolicy(
  db: D1Database,
  kv: KVNamespace,
  orgId: string,
  eventCost: number,
  team: string | null,
): Promise<BudgetCheck> {
  // Fetch active policies: org-level and team-level (if team provided)
  // Order: team policy takes precedence over org policy for block/throttle
  const policies = await db.prepare(`
    SELECT id, scope, scope_target, monthly_limit_usd, enforcement
    FROM budget_policies
    WHERE org_id = ?
      AND enforcement IN ('block', 'throttle', 'alert')
      AND (scope = 'org' OR (scope = 'team' AND scope_target = ?))
    ORDER BY CASE scope WHEN 'team' THEN 0 ELSE 1 END
    LIMIT 5
  `).bind(orgId, team ?? '').all<{ id: string; scope: string; scope_target: string | null; monthly_limit_usd: number; enforcement: string }>();

  for (const policy of policies.results ?? []) {
    // Get MTD spend for this scope
    const mtdKey = policy.scope === 'team'
      ? `mtd:${orgId}:team:${policy.scope_target}`
      : `mtd:${orgId}:org`;

    let mtdCost: number;
    try {
      const cached = await kv.get(mtdKey);
      mtdCost = cached ? parseFloat(cached) : 0;
    } catch {
      mtdCost = 0;
    }

    // If KV cache is stale/zero, query D1 directly
    if (mtdCost === 0) {
      const startOfMonth = new Date();
      startOfMonth.setUTCDate(1);
      startOfMonth.setUTCHours(0, 0, 0, 0);
      const monthStart = Math.floor(startOfMonth.getTime() / 1000);

      let mtdRow: { total: number } | null;
      if (policy.scope === 'team' && policy.scope_target) {
        mtdRow = await db.prepare(`
          SELECT COALESCE(SUM(cost_usd), 0) AS total FROM events
          WHERE org_id = ? AND team = ? AND created_at >= ?
        `).bind(orgId, policy.scope_target, monthStart).first<{ total: number }>();
      } else {
        mtdRow = await db.prepare(`
          SELECT COALESCE(SUM(cost_usd), 0) AS total FROM events
          WHERE org_id = ? AND created_at >= ?
        `).bind(orgId, monthStart).first<{ total: number }>();
      }
      mtdCost = mtdRow?.total ?? 0;
    }

    const projectedCost = mtdCost + eventCost;
    const pct = policy.monthly_limit_usd > 0 ? (projectedCost / policy.monthly_limit_usd) * 100 : 0;

    if (policy.enforcement === 'block' && projectedCost > policy.monthly_limit_usd) {
      return { blocked: true, throttled: false, pct, policy_id: policy.id, scope: policy.scope };
    }
    if (policy.enforcement === 'throttle' && projectedCost > policy.monthly_limit_usd) {
      return { blocked: false, throttled: true, pct, policy_id: policy.id, scope: policy.scope };
    }
  }

  return { blocked: false, throttled: false, pct: 0, policy_id: null, scope: null };
}

// ── Free-tier event limit helper ──────────────────────────────────────────────
const FREE_TIER_LIMIT = 50_000;

async function checkFreeTierLimit(db: D1Database, orgId: string, adding = 1): Promise<{ blocked: boolean; used: number }> {
  const row = await db.prepare(`
    SELECT o.plan,
           COALESCE((
             SELECT COUNT(*) FROM events
             WHERE org_id = o.id
               AND created_at >= strftime('%s', 'now', 'start of month')
           ), 0) AS mtd_count
    FROM orgs o WHERE o.id = ?
  `).bind(orgId).first<{ plan: string; mtd_count: number }>();

  if (!row || row.plan !== 'free') return { blocked: false, used: row?.mtd_count ?? 0 };
  const used = Number(row.mtd_count);
  return { blocked: used + adding >= FREE_TIER_LIMIT, used };
}

// ── POST /v1/events — ingest a single event ───────────────────────────────────
events.post('/', async (c) => {
  const orgId = c.get('orgId');
  let body: EventIn;
  try { body = await c.req.json<EventIn>(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  const { blocked, used } = await checkFreeTierLimit(c.env.DB, orgId, 1);
  if (blocked) {
    return c.json({
      error: 'Free tier limit reached',
      message: `Your org has used ${used.toLocaleString()} / ${FREE_TIER_LIMIT.toLocaleString()} free events this month. Upgrade to Team plan to continue tracking.`,
      upgrade_url: 'https://vantageaiops.com/signup.html',
      events_used: used,
      events_limit: FREE_TIER_LIMIT,
    }, 429);
  }

  // Budget policy enforcement (block/throttle)
  const eventCost = (body as unknown as Record<string, unknown>).total_cost_usd as number ?? 0;
  const eventTeam = (body as unknown as Record<string, unknown>).team as string ?? null;
  const budgetCheck = await checkBudgetPolicy(c.env.DB, c.env.KV, orgId, eventCost, eventTeam);
  if (budgetCheck.blocked) {
    return c.json({
      error: 'Budget limit exceeded',
      message: `This org's ${budgetCheck.scope}-level budget has been exceeded (${Math.round(budgetCheck.pct)}% used). Contact your admin.`,
      budget_pct: budgetCheck.pct,
      policy_id: budgetCheck.policy_id,
    }, 429);
  }
  // throttle: allow through but add header warning
  const isBudgetThrottled = budgetCheck.throttled;

  // Accept 'id' as alias for 'event_id'
  const r = body as unknown as Record<string, unknown>;
  if (!body.event_id && r.id) {
    (body as unknown as Record<string, unknown>).event_id = r.id;
  }
  if (!body.event_id) {
    return c.json({ error: 'event_id is required' }, 400);
  }

  // Validate prompt_hash format (hex string, 32–128 chars)
  if (body.prompt_hash && !/^[0-9a-f]{32,128}$/i.test(body.prompt_hash)) {
    return c.json({ error: 'prompt_hash must be a hex string between 32 and 128 characters' }, 400);
  }

  // Duplicate detection via prompt_hash (24h rolling window)
  let cacheWarning: string | undefined;
  if (body.prompt_hash) {
    const phashKey = `phash:${orgId}:${body.prompt_hash}`;
    try {
      const existing = await c.env.KV.get(phashKey);
      if (existing) {
        const prev = JSON.parse(existing) as { event_id: string; cost_usd: number; model: string; ts: number };
        const agoMin = Math.round((Date.now() / 1000 - prev.ts) / 60);
        const currentCost = body.total_cost_usd ?? body.cost_total_usd ?? 0;
        body.cache_hit = 1;
        // wasted_cost_usd in analytics sums cost_usd of cache_hit=1 rows (this duplicate call's cost)
        // so the warning shows the same cost that will be aggregated in the KPI
        cacheWarning = `Duplicate call detected — identical prompt sent ${agoMin}m ago. Wasted: $${currentCost.toFixed(4)}. Consider caching the response client-side.`;
      }
    } catch { /* KV unavailable — proceed without dedup */ }
  }

  let result;
  try {
    result = await insertEvent(c.env.DB, orgId, body);
  } catch (err) {
    if (err instanceof RangeError) return c.json({ error: err.message }, 400);
    throw err;
  }
  if (!result.success) return c.json({ error: 'Failed to insert event' }, 500);

  // Write prompt_hash to KV for future dedup (TTL: 24h)
  if (body.prompt_hash) {
    const phashKey = `phash:${orgId}:${body.prompt_hash}`;
    const costUsd = body.total_cost_usd ?? body.cost_total_usd ?? 0;
    try {
      await c.env.KV.put(phashKey, JSON.stringify({
        event_id: body.event_id,
        cost_usd: costUsd,
        model: body.model ?? '',
        ts: Math.floor(Date.now() / 1000),
      }), { expirationTtl: 86400 });
    } catch { /* best-effort */ }
  }

  // Broadcast to SSE subscribers via KV pub channel
  await broadcastEvent(c.env.KV, orgId, body);

  // Fire budget alerts asynchronously (non-blocking)
  c.executionCtx.waitUntil((async () => {
    try {
      const org = await c.env.DB.prepare('SELECT budget_usd FROM orgs WHERE id = ?')
        .bind(orgId).first<{ budget_usd: number }>();
      if (org?.budget_usd) {
        const startOfMonth = new Date();
        startOfMonth.setUTCDate(1); startOfMonth.setUTCHours(0, 0, 0, 0);
        const monthStart = Math.floor(startOfMonth.getTime() / 1000);
        const mtdRow = await c.env.DB.prepare(
          'SELECT COALESCE(SUM(cost_usd), 0) AS total FROM events WHERE org_id = ? AND created_at >= ?'
        ).bind(orgId, monthStart).first<{ total: number }>();
        await maybeSendBudgetAlert(c.env.DB, c.env.KV, orgId, mtdRow?.total ?? 0, org.budget_usd);
      }
    } catch { /* non-critical */ }
  })());

  // Invalidate all analytics caches (all scopes including team-scoped variants)
  try { await invalidateOrgAnalyticsCache(c.env.KV, orgId); } catch { /* best-effort */ }

  const response: Record<string, unknown> = { ok: true, id: body.event_id };
  if (cacheWarning) response.cache_warning = cacheWarning;
  if (isBudgetThrottled) response.budget_warning = `Budget threshold exceeded (${Math.round(budgetCheck.pct)}% used). Events are being throttled.`;
  return c.json(response, 201);
});

// ── POST /v1/events/batch — ingest a batch of events ─────────────────────────
events.post('/batch', async (c) => {
  const orgId = c.get('orgId');
  let body: BatchIn;
  try { body = await c.req.json<BatchIn>(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  if (!Array.isArray(body.events) || body.events.length === 0) {
    return c.json({ error: 'events array is required and must not be empty' }, 400);
  }
  if (body.events.length > 500) {
    return c.json({ error: 'Batch size exceeds maximum of 500 events' }, 400);
  }

  // Validate prompt_hash format for each event
  for (const ev of body.events) {
    if (ev.prompt_hash && !/^[0-9a-f]{32,128}$/i.test(ev.prompt_hash)) {
      return c.json({ error: `prompt_hash must be a hex string between 32 and 128 characters (event ${ev.event_id ?? '?'})` }, 400);
    }
  }

  const { blocked, used } = await checkFreeTierLimit(c.env.DB, orgId, body.events.length);
  if (blocked) {
    return c.json({
      error: 'Free tier limit reached',
      message: `Your org has used ${used.toLocaleString()} / ${FREE_TIER_LIMIT.toLocaleString()} free events this month. Upgrade to Team plan to continue tracking.`,
      upgrade_url: 'https://vantageaiops.com/signup.html',
      events_used: used,
      events_limit: FREE_TIER_LIMIT,
    }, 429);
  }

  const batchCost = body.events.reduce((s, ev) => s + (ev.total_cost_usd ?? ev.cost_total_usd ?? 0), 0);
  const batchTeam = body.events[0]?.team ?? null;
  const batchBudgetCheck = await checkBudgetPolicy(c.env.DB, c.env.KV, orgId, batchCost, batchTeam ?? null);
  if (batchBudgetCheck.blocked) {
    return c.json({ error: 'Budget limit exceeded', budget_pct: batchBudgetCheck.pct, policy_id: batchBudgetCheck.policy_id }, 429);
  }

  // Prompt-hash dedup — check KV for each event that includes a prompt_hash
  for (const ev of body.events) {
    if (!ev.prompt_hash) continue;
    const phashKey = `phash:${orgId}:${ev.prompt_hash}`;
    try {
      const existing = await c.env.KV.get(phashKey);
      if (existing) {
        ev.cache_hit = 1;
      } else {
        const costUsd = ev.total_cost_usd ?? ev.cost_total_usd ?? 0;
        await c.env.KV.put(phashKey, JSON.stringify({
          event_id: ev.event_id,
          cost_usd: costUsd,
          model: ev.model ?? '',
          ts: Math.floor(Date.now() / 1000),
        }), { expirationTtl: 86400 });
      }
    } catch { /* KV unavailable — proceed without dedup */ }
  }

  // Bulk insert using D1 batch API
  let stmts;
  try {
    stmts = body.events.map(ev =>
      buildInsertStmt(c.env.DB, orgId, ev, body.sdk_language, body.sdk_version)
    );
  } catch (err) {
    if (err instanceof RangeError) return c.json({ error: err.message }, 400);
    throw err;
  }

  const results = await c.env.DB.batch(stmts);
  const failed  = results.filter(r => !r.success).length;

  // Broadcast last event for live stream
  if (body.events.length > 0) {
    await broadcastEvent(c.env.KV, orgId, body.events[body.events.length - 1]);
  }

  // Invalidate all analytics caches (all scopes including team-scoped variants)
  try { await invalidateOrgAnalyticsCache(c.env.KV, orgId); } catch { /* best-effort */ }

  return c.json({
    ok:       true,
    accepted: body.events.length - failed,
    failed,
  }, 201);
});

// ── PATCH /v1/events/:id/scores — update quality scores async ────────────────
events.patch('/:id/scores', async (c) => {
  const orgId = c.get('orgId');
  const id    = c.req.param('id');
  let body: Record<string, number>;
  try { body = await c.req.json(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

  await c.env.DB.prepare(`
    UPDATE events SET
      hallucination_score = ?, faithfulness_score = ?,
      relevancy_score     = ?, consistency_score  = ?,
      toxicity_score      = ?, efficiency_score   = ?
    WHERE id = ? AND org_id = ?
  `).bind(
    body.hallucination_score ?? null,
    body.faithfulness_score  ?? null,
    body.relevancy_score     ?? null,
    body.consistency_score   ?? null,
    body.toxicity_score      ?? null,
    body.efficiency_score    ?? null,
    id, orgId,
  ).run();

  return c.json({ ok: true });
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function buildInsertStmt(
  db: D1Database,
  orgId: string,
  ev: EventIn,
  sdkLang?: string,
  sdkVer?: string,
): D1PreparedStatement {
  // Accept both canonical field names and SDK-prefixed aliases
  // SDK sends: usage_prompt_tokens, cost_total_cost_usd, etc.
  // REST clients may send: prompt_tokens, total_cost_usd, cost_usd, etc.
  const r = ev as unknown as Record<string, unknown>;

  const eventId        = ev.event_id ?? r.id as string | undefined;
  const promptTokens   = Number(ev.prompt_tokens   ?? r.usage_prompt_tokens   ?? 0);
  const completionTok  = Number(ev.completion_tokens ?? r.usage_completion_tokens ?? 0);
  const cacheTok       = Number(ev.cache_tokens    ?? r.usage_cached_tokens   ?? r.cache_tokens   ?? 0);
  const totalTokens    = Number(ev.total_tokens    ?? r.usage_total_tokens    ?? (promptTokens + completionTok));

  // Reject scientific-notation inflation and negative values (e.g. "1e10" = 10 billion)
  const MAX_TOKENS = 10_000_000;
  if (
    promptTokens  < 0 || promptTokens  > MAX_TOKENS ||
    completionTok < 0 || completionTok > MAX_TOKENS ||
    cacheTok      < 0 || cacheTok      > MAX_TOKENS ||
    totalTokens   < 0 || totalTokens   > MAX_TOKENS
  ) {
    throw new RangeError(`Token count out of valid range (0–${MAX_TOKENS})`);
  }
  const costUsd        = Number(ev.total_cost_usd  ?? ev.cost_total_usd       ??
                         r.cost_total_cost_usd ?? r.cost_usd ?? 0);
  const latencyMs      = ev.latency_ms      ?? r.latency_ms            as number ?? 0;
  const tagsValue      = ev.tags ?? (r.tags as Record<string, string> | undefined);

  const ts = ev.timestamp
    ? Math.floor(new Date(ev.timestamp).getTime() / 1000)
    : Math.floor(Date.now() / 1000);

  return db.prepare(`
    INSERT OR IGNORE INTO events (
      id, org_id, provider, model,
      prompt_tokens, completion_tokens, cache_tokens, total_tokens,
      cost_usd, latency_ms,
      team, project, user_id, feature, endpoint, environment,
      is_streaming, stream_chunks,
      trace_id, parent_event_id, agent_name, span_depth,
      tags, sdk_language, sdk_version,
      prompt_hash, cache_hit,
      created_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
  `).bind(
    eventId, orgId, ev.provider ?? '', ev.model ?? '',
    promptTokens, completionTok,
    cacheTok, totalTokens,
    costUsd, latencyMs,
    ev.team ?? null, ev.project ?? null, ev.user_id ?? null,
    ev.feature ?? null, ev.endpoint ?? null,
    ev.environment ?? 'production',
    ev.is_streaming ? 1 : 0, ev.stream_chunks ?? 0,
    ev.trace_id ?? null, ev.parent_event_id ?? null,
    ev.agent_name ?? null, ev.span_depth ?? 0,
    tagsValue ? JSON.stringify(tagsValue) : null,
    ev.sdk_language ?? sdkLang ?? null,
    ev.sdk_version  ?? sdkVer  ?? null,
    ev.prompt_hash ?? null, ev.cache_hit ?? 0,
    ts,
  );
}

async function insertEvent(db: D1Database, orgId: string, ev: EventIn) {
  return buildInsertStmt(db, orgId, ev).run();
}

interface StreamEvent {
  seqno: number;
  ts: number;
  provider: string;
  cost_usd: number;
  model: string | null;
  tokens: number;
}

async function broadcastEvent(kv: KVNamespace, orgId: string, ev: EventIn) {
  try {
    const seqno = Date.now();
    const r = ev as unknown as Record<string, unknown>;
    const streamEv: StreamEvent = {
      seqno,
      ts: seqno,
      provider: ev.provider ?? 'unknown',
      cost_usd: ev.total_cost_usd ?? ev.cost_total_usd ?? 0,
      model: ev.model ?? null,
      tokens: (Number(r.input_tokens ?? ev.prompt_tokens ?? 0)) +
              (Number(r.output_tokens ?? ev.completion_tokens ?? 0)),
    };
    const payload = JSON.stringify(streamEv);

    // Write latest (backwards compat for SSE reader during transition)
    await kv.put(`stream:${orgId}:latest`, payload, { expirationTtl: 60 });

    // Write circular buffer (max 25 events, newest first)
    const bufKey = `stream:${orgId}:buf`;
    const rawBuf = await kv.get(bufKey);
    const buf: StreamEvent[] = rawBuf ? JSON.parse(rawBuf) : [];
    buf.unshift(streamEv);
    if (buf.length > 25) buf.length = 25;
    await kv.put(bufKey, JSON.stringify(buf), { expirationTtl: 300 });
  } catch {
    // KV unavailable — event still recorded in D1, live feed skipped
  }
}

export { events };
