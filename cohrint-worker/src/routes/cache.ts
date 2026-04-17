/**
 * Semantic Cache routes — /v1/cache
 *
 * Uses Workers AI (BGE-small-en-v1.5, 384 dims) + Vectorize (cosine similarity)
 * to serve previously-seen LLM responses for semantically equivalent prompts.
 *
 * Endpoints:
 *   POST /v1/cache/lookup    — find a cached response for a prompt (auth required)
 *   POST /v1/cache/store     — store a prompt+response pair (auth required)
 *   GET  /v1/cache/stats     — hit rate + savings stats (auth required)
 *   PATCH /v1/cache/config   — update org cache config (admin required)
 *   DELETE /v1/cache/entries/:id — remove a cache entry (admin required)
 */

import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';

const EMBEDDING_MODEL = '@cf/baai/bge-small-en-v1.5' as const;

export const cache = new Hono<{ Bindings: Bindings; Variables: Variables }>();

cache.use('*', authMiddleware);

// ── Helpers ───────────────────────────────────────────────────────────────────

async function getOrgCacheConfig(db: D1Database, orgId: string) {
  const row = await db
    .prepare('SELECT * FROM org_cache_config WHERE org_id = ?')
    .bind(orgId)
    .first<{ enabled: number; similarity_threshold: number; min_prompt_length: number; max_cache_age_days: number }>();
  return row ?? { enabled: 1, similarity_threshold: 0.92, min_prompt_length: 10, max_cache_age_days: 30 };
}

async function embedText(ai: Ai, text: string): Promise<number[]> {
  const result = await ai.run(EMBEDDING_MODEL, { text: [text] }) as { data: number[][] };
  return result.data[0];
}

function generateId(): string {
  return crypto.randomUUID();
}

// ── POST /v1/cache/lookup ─────────────────────────────────────────────────────

cache.post('/lookup', async (c) => {
  const orgId    = c.get('orgId');
  const scopeTeam = c.get('scopeTeam') as string | null;
  const body = await c.req.json<{ prompt: string; model: string }>().catch(() => null);

  if (!body?.prompt || !body?.model) {
    return c.json({ error: 'prompt and model are required' }, 400);
  }

  const config = await getOrgCacheConfig(c.env.DB, orgId);
  if (!config.enabled) return c.json({ hit: false, reason: 'cache_disabled' });
  if (body.prompt.length < config.min_prompt_length) {
    return c.json({ hit: false, reason: 'prompt_too_short' });
  }

  // Generate embedding for the incoming prompt
  const embedding = await embedText(c.env.AI, body.prompt);

  // Query Vectorize for nearest neighbor within this org+model+team namespace
  const vectorizeFilter: Record<string, string> = { org_id: orgId, model: body.model };
  if (scopeTeam) vectorizeFilter['team_id'] = scopeTeam;
  const matches = await c.env.VECTORIZE.query(embedding, {
    topK: 1,
    filter: vectorizeFilter,
    returnMetadata: 'indexed',
  });

  const top = matches.matches[0];
  if (!top || top.score < config.similarity_threshold) {
    return c.json({ hit: false, score: top?.score ?? 0 });
  }

  // Fetch full entry from D1 — re-enforce team isolation at DB level
  const teamClause = scopeTeam ? ' AND (team_id = ? OR team_id IS NULL)' : '';
  const entry = await c.env.DB
    .prepare(`SELECT * FROM semantic_cache_entries WHERE id = ? AND org_id = ?${teamClause}`)
    .bind(...([top.id, orgId, ...(scopeTeam ? [scopeTeam] : [])] as [string, string, ...string[]]))
    .first<{
      id: string; response_text: string; cost_usd: number;
      prompt_tokens: number; completion_tokens: number;
      hit_count: number; total_savings_usd: number;
    }>();

  if (!entry) return c.json({ hit: false, reason: 'entry_not_found' });

  // Check age
  const ageQuery = await c.env.DB
    .prepare("SELECT (julianday('now') - julianday(created_at)) AS age_days FROM semantic_cache_entries WHERE id = ?")
    .bind(top.id)
    .first<{ age_days: number }>();

  if (ageQuery && ageQuery.age_days > config.max_cache_age_days) {
    // Stale — delete from Vectorize + D1 asynchronously
    c.executionCtx.waitUntil(Promise.all([
      c.env.VECTORIZE.deleteByIds([top.id]),
      c.env.DB.prepare('DELETE FROM semantic_cache_entries WHERE id = ?').bind(top.id).run(),
    ]));
    return c.json({ hit: false, reason: 'entry_expired' });
  }

  // Record the hit — update counters asynchronously
  const newSavings = entry.total_savings_usd + entry.cost_usd;
  c.executionCtx.waitUntil(
    c.env.DB
      .prepare(`UPDATE semantic_cache_entries
                SET hit_count = hit_count + 1,
                    total_savings_usd = ?,
                    last_hit_at = datetime('now')
                WHERE id = ?`)
      .bind(newSavings, entry.id)
      .run()
  );

  return c.json({
    hit: true,
    score: top.score,
    response: entry.response_text,
    prompt_tokens: entry.prompt_tokens,
    completion_tokens: entry.completion_tokens,
    saved_usd: entry.cost_usd,
    cache_entry_id: entry.id,
  });
});

// ── POST /v1/cache/store ──────────────────────────────────────────────────────

cache.post('/store', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam') as string | null;
  const body = await c.req.json<{
    prompt: string;
    model: string;
    response: string;
    prompt_tokens?: number;
    completion_tokens?: number;
    cost_usd?: number;
    prompt_hash?: string;
  }>().catch(() => null);

  if (!body?.prompt || !body?.model || !body?.response) {
    return c.json({ error: 'prompt, model, and response are required' }, 400);
  }

  const config = await getOrgCacheConfig(c.env.DB, orgId);
  if (!config.enabled) return c.json({ stored: false, reason: 'cache_disabled' });
  if (body.prompt.length < config.min_prompt_length) {
    return c.json({ stored: false, reason: 'prompt_too_short' });
  }

  // Check for exact-match duplicate via prompt_hash
  if (body.prompt_hash) {
    const existing = await c.env.DB
      .prepare('SELECT id FROM semantic_cache_entries WHERE org_id = ? AND prompt_hash = ? AND model = ?')
      .bind(orgId, body.prompt_hash, body.model)
      .first<{ id: string }>();
    if (existing) return c.json({ stored: false, reason: 'duplicate', cache_entry_id: existing.id });
  }

  const id = generateId();
  const embedding = await embedText(c.env.AI, body.prompt);

  // Insert into Vectorize with org/model/team metadata for filtered search
  const vectorizeMeta: Record<string, string> = { org_id: orgId, model: body.model };
  if (scopeTeam) vectorizeMeta['team_id'] = scopeTeam;
  await c.env.VECTORIZE.upsert([{
    id,
    values: embedding,
    metadata: vectorizeMeta,
  }]);

  // Persist to D1
  const promptHash = body.prompt_hash ?? null;
  await c.env.DB
    .prepare(`INSERT INTO semantic_cache_entries
              (id, org_id, team_id, prompt_hash, prompt_text, model, response_text,
               prompt_tokens, completion_tokens, cost_usd, vectorize_id, created_at)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))`)
    .bind(
      id, orgId, scopeTeam ?? null, promptHash, body.prompt, body.model, body.response,
      body.prompt_tokens ?? 0, body.completion_tokens ?? 0,
      body.cost_usd ?? 0, id,
    )
    .run();

  return c.json({ stored: true, cache_entry_id: id }, 201);
});

// ── GET /v1/cache/stats ───────────────────────────────────────────────────────

cache.get('/stats', async (c) => {
  const orgId = c.get('orgId');
  const [stats, config] = await Promise.all([
    c.env.DB
      .prepare(`SELECT
          COUNT(*) AS total_entries,
          SUM(hit_count) AS total_hits,
          SUM(total_savings_usd) AS total_savings_usd,
          COUNT(DISTINCT model) AS models_cached
        FROM semantic_cache_entries
        WHERE org_id = ?`)
      .bind(orgId)
      .first<{
        total_entries: number; total_hits: number;
        total_savings_usd: number; models_cached: number;
      }>(),
    getOrgCacheConfig(c.env.DB, orgId),
  ]);

  // Recent entries (last 10)
  const recent = await c.env.DB
    .prepare(`SELECT id, model, prompt_hash, hit_count, total_savings_usd, cost_usd, created_at, last_hit_at
              FROM semantic_cache_entries
              WHERE org_id = ?
              ORDER BY created_at DESC LIMIT 10`)
    .bind(orgId)
    .all<{ id: string; model: string; prompt_hash: string; hit_count: number; total_savings_usd: number; cost_usd: number; created_at: string; last_hit_at: string | null }>();

  return c.json({
    config,
    stats: {
      total_entries: stats?.total_entries ?? 0,
      total_hits: stats?.total_hits ?? 0,
      total_savings_usd: stats?.total_savings_usd ?? 0,
      models_cached: stats?.models_cached ?? 0,
    },
    recent_entries: recent.results,
  });
});

// ── PATCH /v1/cache/config ────────────────────────────────────────────────────

cache.patch('/config', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const body = await c.req.json<{
    enabled?: boolean;
    similarity_threshold?: number;
    min_prompt_length?: number;
    max_cache_age_days?: number;
  }>().catch(() => null);

  if (!body) return c.json({ error: 'invalid body' }, 400);

  if (body.similarity_threshold !== undefined &&
      (body.similarity_threshold < 0 || body.similarity_threshold > 1)) {
    return c.json({ error: 'similarity_threshold must be between 0 and 1' }, 400);
  }

  await c.env.DB
    .prepare(`INSERT INTO org_cache_config (org_id, enabled, similarity_threshold, min_prompt_length, max_cache_age_days)
              VALUES (?, ?, ?, ?, ?)
              ON CONFLICT(org_id) DO UPDATE SET
                enabled = COALESCE(excluded.enabled, enabled),
                similarity_threshold = COALESCE(excluded.similarity_threshold, similarity_threshold),
                min_prompt_length = COALESCE(excluded.min_prompt_length, min_prompt_length),
                max_cache_age_days = COALESCE(excluded.max_cache_age_days, max_cache_age_days),
                updated_at = datetime('now')`)
    .bind(
      orgId,
      body.enabled !== undefined ? (body.enabled ? 1 : 0) : null,
      body.similarity_threshold ?? null,
      body.min_prompt_length ?? null,
      body.max_cache_age_days ?? null,
    )
    .run();

  return c.json({ updated: true });
});

// ── DELETE /v1/cache/entries/:id ──────────────────────────────────────────────

cache.delete('/entries/:id', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const entryId = c.req.param('id');

  const entry = await c.env.DB
    .prepare('SELECT vectorize_id FROM semantic_cache_entries WHERE id = ? AND org_id = ?')
    .bind(entryId, orgId)
    .first<{ vectorize_id: string | null }>();

  if (!entry) return c.json({ error: 'not found' }, 404);

  await Promise.all([
    entry.vectorize_id ? c.env.VECTORIZE.deleteByIds([entry.vectorize_id]) : Promise.resolve(),
    c.env.DB.prepare('DELETE FROM semantic_cache_entries WHERE id = ? AND org_id = ?').bind(entryId, orgId).run(),
  ]);

  return c.json({ deleted: true });
});
