import { Hono } from 'hono';
import { Bindings, Variables, EventIn, BatchIn } from '../types';
import { authMiddleware } from '../middleware/auth';

const events = new Hono<{ Bindings: Bindings; Variables: Variables }>();

events.use('*', authMiddleware);

// ── POST /v1/events — ingest a single event ───────────────────────────────────
events.post('/', async (c) => {
  const orgId = c.get('orgId');
  let body: EventIn;
  try { body = await c.req.json<EventIn>(); }
  catch { return c.json({ error: 'Invalid JSON body' }, 400); }

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
  const totalTokens = ev.total_tokens
    ?? ((ev.prompt_tokens ?? 0) + (ev.completion_tokens ?? 0));

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
    ev.event_id, orgId, ev.provider ?? '', ev.model ?? '',
    ev.prompt_tokens ?? 0, ev.completion_tokens ?? 0,
    ev.cache_tokens ?? 0, totalTokens,
    ev.cost_total_usd ?? 0, ev.latency_ms ?? 0,
    ev.team ?? null, ev.project ?? null, ev.user_id ?? null,
    ev.feature ?? null, ev.endpoint ?? null,
    ev.environment ?? 'production',
    ev.is_streaming ? 1 : 0, ev.stream_chunks ?? 0,
    ev.trace_id ?? null, ev.parent_event_id ?? null,
    ev.agent_name ?? null, ev.span_depth ?? 0,
    ev.tags ? JSON.stringify(ev.tags) : null,
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
    cost_total_usd: ev.cost_total_usd,
    latency_ms: ev.latency_ms,
    team: ev.team,
    ts: Date.now(),
  });
  await kv.put(`stream:${orgId}:latest`, payload, { expirationTtl: 60 });
}

export { events };
