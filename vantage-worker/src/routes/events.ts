import { Hono } from 'hono';
import { Bindings, Variables, EventIn, BatchIn } from '../types';
import { authMiddleware } from '../middleware/auth';

const events = new Hono<{ Bindings: Bindings; Variables: Variables }>();

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

// ── Free-tier event limit helper ──────────────────────────────────────────────
const FREE_TIER_LIMIT = 10_000;

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
  return { blocked: used + adding > FREE_TIER_LIMIT, used };
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

  // Accept 'id' as alias for 'event_id'
  const r = body as unknown as Record<string, unknown>;
  if (!body.event_id && r.id) {
    (body as unknown as Record<string, unknown>).event_id = r.id;
  }
  if (!body.event_id) {
    return c.json({ error: 'event_id is required' }, 400);
  }

  const result = await insertEvent(c.env.DB, orgId, body);
  if (!result.success) return c.json({ error: 'Failed to insert event' }, 500);

  // Broadcast to SSE subscribers via KV pub channel
  await broadcastEvent(c.env.KV, orgId, body);

  return c.json({ ok: true, id: body.event_id }, 201);
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

  // Bulk insert using D1 batch API
  const stmts = body.events.map(ev =>
    buildInsertStmt(c.env.DB, orgId, ev, body.sdk_language, body.sdk_version)
  );

  const results = await c.env.DB.batch(stmts);
  const failed  = results.filter(r => !r.success).length;

  // Broadcast last event for live stream
  if (body.events.length > 0) {
    await broadcastEvent(c.env.KV, orgId, body.events[body.events.length - 1]);
  }

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
  const promptTokens   = ev.prompt_tokens   ?? r.usage_prompt_tokens   as number ?? 0;
  const completionTok  = ev.completion_tokens ?? r.usage_completion_tokens as number ?? 0;
  const cacheTok       = ev.cache_tokens    ?? r.usage_cached_tokens   as number ?? r.cache_tokens as number ?? 0;
  const totalTokens    = ev.total_tokens    ?? r.usage_total_tokens    as number ?? (promptTokens + completionTok);
  const costUsd        = ev.total_cost_usd  ?? ev.cost_total_usd       ??
                         r.cost_total_cost_usd as number ?? r.cost_usd as number ?? 0;
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
      tags, sdk_language, sdk_version, created_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
    ts,
  );
}

async function insertEvent(db: D1Database, orgId: string, ev: EventIn) {
  return buildInsertStmt(db, orgId, ev).run();
}

async function broadcastEvent(kv: KVNamespace, orgId: string, ev: EventIn) {
  // Store last event per org in KV so SSE stream can serve it
  // TTL 60s — only recent events matter for live stream
  const payload = JSON.stringify({
    provider: ev.provider,
    model:    ev.model,
    total_tokens: ev.total_tokens ?? ((ev.prompt_tokens ?? 0) + (ev.completion_tokens ?? 0)),
    cost_total_usd: ev.total_cost_usd ?? ev.cost_total_usd,
    latency_ms: ev.latency_ms,
    team: ev.team,
    ts: Date.now(),
  });
  try {
    await kv.put(`stream:${orgId}:latest`, payload, { expirationTtl: 60 });
  } catch {
    // KV unavailable — event still recorded in D1, SSE broadcast skipped
  }
}

export { events };
