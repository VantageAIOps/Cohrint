/**
 * T010 — Cloudflare Queues consumer for async event ingest.
 *
 * Receives batches from the `cohrint-ingest` queue (max 100 messages, 5s timeout).
 * Performs DB.batch([INSERT OR IGNORE...]) for "event" messages and updates KV
 * free-tier counters. On D1 error the handler throws so Queues retries the batch.
 *
 * Message types:
 *   "event"   — standard SDK event ingest (EventIn)
 *   "rescore" — T019 quality re-scoring stub (ack immediately)
 */

import { createLogger } from '../lib/logger'
import { emitMetric } from '../lib/metrics'
import { Bindings, EventIn } from '../types'

// ── Message shapes ────────────────────────────────────────────────────────────

interface IngestMessage {
  type: 'event'
  orgId: string
  event: EventIn
}

interface RescoreMessage {
  type: 'rescore'
  orgId: string
  eventId: string
  fieldsToReset: string[]
}

type QueueMessage = IngestMessage | RescoreMessage

// ── Entry point ───────────────────────────────────────────────────────────────

export async function handleIngestBatch(
  batch: MessageBatch<QueueMessage>,
  env: Bindings,
): Promise<void> {
  const log = createLogger(batch.queue)

  // Separate by type
  const eventMessages  = batch.messages.filter((m): m is Message<IngestMessage>  => m.body.type === 'event')
  const rescoreMessages = batch.messages.filter((m): m is Message<RescoreMessage> => m.body.type === 'rescore')

  // Process events
  if (eventMessages.length > 0) {
    await processEvents(eventMessages, env, log)
  }

  // Process rescore requests (T019 — null out score fields and re-ack)
  if (rescoreMessages.length > 0) {
    await processRescore(rescoreMessages, env, log)
  }
}

// ── Event processing ──────────────────────────────────────────────────────────

async function processEvents(
  messages: Message<IngestMessage>[],
  env: Bindings,
  log: ReturnType<typeof createLogger>,
): Promise<void> {
  // Group by orgId for KV free-tier counter updates
  const byOrg = new Map<string, { msg: IngestMessage; idx: number }[]>()
  for (let i = 0; i < messages.length; i++) {
    const body = messages[i].body
    const arr = byOrg.get(body.orgId) ?? []
    arr.push({ msg: body, idx: i })
    byOrg.set(body.orgId, arr)
  }

  // Build D1 batch (INSERT OR IGNORE)
  const stmts = messages.map(({ body: { event: e, orgId } }) => {
    const ts = e.timestamp
      ? Math.floor(new Date(e.timestamp).getTime() / 1000)
      : Math.floor(Date.now() / 1000)

    return env.DB.prepare(`
      INSERT OR IGNORE INTO events
        (id, org_id, provider, model,
         prompt_tokens, completion_tokens, cache_tokens, total_tokens,
         cost_usd, latency_ms,
         team, project, user_id, feature, endpoint, environment,
         is_streaming, stream_chunks,
         trace_id, parent_event_id, agent_name, span_depth,
         sdk_language, sdk_version,
         prompt_hash, cache_hit,
         created_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `).bind(
      e.event_id, orgId,
      e.provider ?? '', e.model ?? '',
      e.prompt_tokens   ?? null,
      e.completion_tokens ?? null,
      e.cache_tokens    ?? null,
      e.total_tokens    ?? null,
      e.total_cost_usd  ?? e.cost_total_usd ?? null,
      e.latency_ms      ?? null,
      e.team     ?? null, e.project  ?? null, e.user_id ?? null,
      e.feature  ?? null, e.endpoint ?? null,
      e.environment ?? 'production',
      e.is_streaming ? 1 : 0,
      e.stream_chunks    ?? 0,
      e.trace_id         ?? null,
      e.parent_event_id  ?? null,
      e.agent_name       ?? null,
      e.span_depth       ?? 0,
      e.sdk_language     ?? null,
      e.sdk_version      ?? null,
      e.prompt_hash      ?? null,
      e.cache_hit        ?? 0,
      ts,
    )
  })

  let results: D1Result[]
  try {
    results = await env.DB.batch(stmts)
  } catch (err) {
    log.error('events-consumer: D1 batch failed', {
      err: err instanceof Error ? err : new Error(String(err)),
    })
    emitMetric(env.METRICS, { event: 'events.d1_error', orgId: 'batch', values: { count: messages.length } })
    throw err // Let Queues retry the batch
  }

  // Tally accepted vs duplicate and ack all messages
  let accepted  = 0
  let duplicates = 0

  for (let i = 0; i < results.length; i++) {
    const wasInserted = (results[i].meta?.changes ?? 0) > 0
    if (wasInserted) { accepted++ } else { duplicates++ }
    messages[i].ack() // ack both: duplicates are expected, not retryable
  }

  // Build rollup upsert for each accepted event
  const rollupStmts = messages
    .filter((_, idx) => (results[idx]?.meta?.changes ?? 0) > 0)
    .map(msg => {
      const { event: e, orgId } = msg.body
      const ts = e.timestamp ? Math.floor(new Date(e.timestamp).getTime() / 1000) : Math.floor(Date.now() / 1000)
      const dayUnix = Math.floor(ts / 86400) * 86400  // UTC midnight
      const model = e.model ?? 'unknown'
      const provider = e.provider ?? ''
      const team = e.team ?? ''
      const cost = e.total_cost_usd ?? e.cost_total_usd ?? 0
      const prompt = e.prompt_tokens ?? 0
      const completion = e.completion_tokens ?? 0
      const cache = e.cache_tokens ?? 0
      const total = e.total_tokens ?? (prompt + completion)
      const latency = e.latency_ms ?? 0
      const isHit = (e.cache_hit ?? 0) ? 1 : 0

      return env.DB.prepare(`
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
      `).bind(orgId, dayUnix, model, provider, team, cost, prompt, completion, cache, total, isHit, latency)
    })

  if (rollupStmts.length > 0) {
    try {
      await env.DB.batch(rollupStmts)
    } catch (err) {
      log.warn('events-consumer: rollup upsert failed (non-fatal)', { err: err instanceof Error ? err : new Error(String(err)) })
      // Non-fatal: events are still stored; rollup can be backfilled
    }
  }

  // Update KV free-tier counters per org (SOLE WRITER for T010)
  const now      = new Date()
  const monthKey = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`

  for (const [orgId, entries] of byOrg) {
    // Count how many inserts succeeded for this org
    const insertedForOrg = entries.reduce((sum, { idx }) => {
      return sum + ((results[idx]?.meta?.changes ?? 0) > 0 ? 1 : 0)
    }, 0)

    if (insertedForOrg > 0) {
      const kvKey = `freetier:${orgId}:${monthKey}`
      try {
        const current = parseInt(await env.KV.get(kvKey) ?? '0', 10)
        await env.KV.put(kvKey, String(current + insertedForOrg), {
          expirationTtl: 40 * 24 * 3600, // 40 days covers month rollover
        })
      } catch {
        log.warn('events-consumer: KV freetier update failed', { orgId })
      }
    }
  }

  // Emit WAE metrics
  emitMetric(env.METRICS, { event: 'events.accepted',  orgId: 'batch', values: { count: accepted } })
  emitMetric(env.METRICS, { event: 'events.duplicate', orgId: 'batch', values: { count: duplicates } })

  log.info('events-consumer: batch processed', {
    total: messages.length,
    accepted,
    duplicates,
  })
}

// ── Rescore processing ────────────────────────────────────────────────────────

const SAFE_SCORE_COLUMNS = new Set([
  'hallucination_score',
  'faithfulness_score',
  'relevancy_score',
  'toxicity_score',
  'efficiency_score',
])

async function processRescore(
  messages: Message<RescoreMessage>[],
  env: Bindings,
  log: ReturnType<typeof createLogger>,
): Promise<void> {
  for (const msg of messages) {
    const { orgId, eventId, fieldsToReset } = msg.body

    // Filter to only safe, known column names (defence-in-depth)
    const safeFields = fieldsToReset.filter(f => SAFE_SCORE_COLUMNS.has(f))

    if (safeFields.length === 0) {
      log.warn('rescore: no valid fields — skipping', { eventId, orgId })
      msg.ack()
      continue
    }

    // Build parameterised SET clause: "field1 = NULL, field2 = NULL"
    // safeFields are validated against a static allowlist — safe to interpolate
    const setClause = safeFields.map(f => `${f} = NULL`).join(', ')
    const sql = `UPDATE events SET ${setClause} WHERE event_id = ? AND org_id = ?`

    try {
      await env.DB.prepare(sql).bind(eventId, orgId).run()
      log.info('rescore: fields cleared', { eventId, orgId, fields: safeFields })
    } catch (err) {
      log.error('rescore: D1 update failed', {
        err: err instanceof Error ? err : new Error(String(err)),
        eventId,
        orgId,
      })
      // Re-throw to let Queues retry this message
      throw err
    }

    msg.ack()
  }
}

// ── DLQ consumer ──────────────────────────────────────────────────────────────
// Receives messages that exhausted all retries from the main ingest queue.
// Stores each message to KV under key `dlq:entry:{timestamp_ms}:{id}`
// with a 7-day TTL so GET /v1/superadmin/ingest/dlq can surface them.

export async function handleDlqBatch(
  batch: MessageBatch<QueueMessage>,
  env: Bindings,
): Promise<void> {
  const log = createLogger(batch.queue)

  for (const msg of batch.messages) {
    const ts  = Date.now()
    const key = `dlq:entry:${ts}:${msg.id}`
    const entry = {
      id:        msg.id,
      body:      msg.body,
      timestamp: new Date(ts).toISOString(),
      queue:     batch.queue,
    }
    try {
      await env.KV.put(key, JSON.stringify(entry), { expirationTtl: 7 * 24 * 3600 })
      const orgId = (msg.body as IngestMessage).orgId ?? 'unknown'
      emitMetric(env.METRICS, { event: 'ingest.dlq_stored', orgId, values: { count: 1 } })
    } catch (err) {
      log.error('dlq-consumer: KV write failed', {
        err:   err instanceof Error ? err : new Error(String(err)),
        msgId: msg.id,
      })
    }
    msg.ack()
  }

  log.info('dlq-consumer: batch processed', { count: batch.messages.length })
}
