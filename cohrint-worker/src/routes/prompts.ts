/**
 * Prompt Registry routes — /v1/prompts
 *
 * Versioned prompt templates with per-version cost tracking.
 * SDK can tag events with a version_id to enable automatic cost attribution.
 *
 * Endpoints:
 *   GET    /v1/prompts                           — list all prompts (auth)
 *   POST   /v1/prompts                           — create prompt (admin)
 *   GET    /v1/prompts/:id                       — get prompt + all versions (auth)
 *   PATCH  /v1/prompts/:id                       — update name/description (admin)
 *   DELETE /v1/prompts/:id                       — soft delete (admin)
 *   POST   /v1/prompts/:id/versions              — add new version (admin)
 *   GET    /v1/prompts/:id/versions/:versionId   — get single version (auth)
 *   POST   /v1/prompts/usage                     — record event usage (auth, called by SDK)
 *   GET    /v1/prompts/analytics/comparison      — cost comparison across versions (auth)
 */

import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware, adminOnly } from '../middleware/auth';

export const prompts = new Hono<{ Bindings: Bindings; Variables: Variables }>();

prompts.use('*', authMiddleware);

// ── Helpers ───────────────────────────────────────────────────────────────────

function generateId(): string {
  return crypto.randomUUID();
}

// ── GET /v1/prompts ───────────────────────────────────────────────────────────

prompts.get('/', async (c) => {
  const orgId = c.get('orgId');

  const rows = await c.env.DB
    .prepare(`SELECT p.id, p.name, p.description, p.created_by, p.created_at, p.updated_at,
                COUNT(pv.id) AS version_count,
                MAX(pv.version_num) AS latest_version,
                SUM(pv.total_cost_usd) AS total_cost_usd,
                SUM(pv.total_calls) AS total_calls
              FROM prompts p
              LEFT JOIN prompt_versions pv ON pv.prompt_id = p.id
              WHERE p.org_id = ? AND p.deleted_at IS NULL
              GROUP BY p.id
              ORDER BY p.updated_at DESC`)
    .bind(orgId)
    .all<{
      id: string; name: string; description: string | null;
      created_by: string; created_at: string; updated_at: string;
      version_count: number; latest_version: number | null;
      total_cost_usd: number; total_calls: number;
    }>();

  return c.json({ prompts: rows.results });
});

// ── POST /v1/prompts ──────────────────────────────────────────────────────────

prompts.post('/', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const memberEmail = c.get('memberEmail') ?? 'owner';
  const body = await c.req.json<{
    name: string;
    description?: string;
    initial_version?: { content: string; model?: string; notes?: string };
  }>().catch(() => null);

  if (!body?.name?.trim()) return c.json({ error: 'name is required' }, 400);

  const promptId = generateId();

  try {
    await c.env.DB
      .prepare(`INSERT INTO prompts (id, org_id, name, description, created_by)
                VALUES (?, ?, ?, ?, ?)`)
      .bind(promptId, orgId, body.name.trim(), body.description ?? null, memberEmail)
      .run();
  } catch (e: unknown) {
    if (e instanceof Error && e.message?.includes('UNIQUE')) {
      return c.json({ error: 'a prompt with this name already exists' }, 409);
    }
    throw e;
  }

  // Optionally create first version inline
  let firstVersion: { id: string; version_num: number } | null = null;
  if (body.initial_version?.content) {
    const versionId = generateId();
    await c.env.DB
      .prepare(`INSERT INTO prompt_versions (id, prompt_id, version_num, content, model, notes, created_by)
                VALUES (?, ?, 1, ?, ?, ?, ?)`)
      .bind(versionId, promptId, body.initial_version.content, body.initial_version.model ?? null, body.initial_version.notes ?? null, memberEmail)
      .run();
    firstVersion = { id: versionId, version_num: 1 };
  }

  return c.json({ id: promptId, name: body.name.trim(), first_version: firstVersion }, 201);
});

// ── POST /v1/prompts/usage ────────────────────────────────────────────────────
// Called by SDK to attribute an LLM event to a specific prompt version
// MUST be registered before /:id to avoid Hono route shadowing

prompts.post('/usage', async (c) => {
  const orgId = c.get('orgId');
  const body = await c.req.json<{
    version_id: string;
    event_id: string;
    cost_usd?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
  }>().catch(() => null);

  if (!body?.version_id || !body?.event_id) {
    return c.json({ error: 'version_id and event_id are required' }, 400);
  }

  // Verify version belongs to an org prompt
  const version = await c.env.DB
    .prepare(`SELECT pv.id, pv.prompt_id, pv.total_calls, pv.total_cost_usd,
                pv.avg_prompt_tokens, pv.avg_completion_tokens
              FROM prompt_versions pv
              JOIN prompts p ON p.id = pv.prompt_id
              WHERE pv.id = ? AND p.org_id = ? AND p.deleted_at IS NULL`)
    .bind(body.version_id, orgId)
    .first<{
      id: string; prompt_id: string; total_calls: number; total_cost_usd: number;
      avg_prompt_tokens: number; avg_completion_tokens: number;
    }>();

  if (!version) return c.json({ error: 'version not found' }, 404);

  const costUsd = body.cost_usd ?? 0;
  const promptTokens = body.prompt_tokens ?? 0;
  const completionTokens = body.completion_tokens ?? 0;

  const usageId = generateId();
  const newCalls = version.total_calls + 1;
  const newTotalCost = version.total_cost_usd + costUsd;
  const newAvgCost = newTotalCost / newCalls;
  const newAvgPrompt = Math.round(
    (version.avg_prompt_tokens * version.total_calls + promptTokens) / newCalls
  );
  const newAvgCompletion = Math.round(
    (version.avg_completion_tokens * version.total_calls + completionTokens) / newCalls
  );

  await c.env.DB.batch([
    c.env.DB
      .prepare(`INSERT OR IGNORE INTO prompt_usage (id, version_id, event_id, org_id, cost_usd, prompt_tokens, completion_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?)`)
      .bind(usageId, body.version_id, body.event_id, orgId, costUsd, promptTokens, completionTokens),
    c.env.DB
      .prepare(`UPDATE prompt_versions SET
                  total_calls = ?, total_cost_usd = ?, avg_cost_usd = ?,
                  avg_prompt_tokens = ?, avg_completion_tokens = ?
                WHERE id = ?`)
      .bind(newCalls, newTotalCost, newAvgCost, newAvgPrompt, newAvgCompletion, version.id),
  ]);

  return c.json({ recorded: true }, 201);
});

// ── GET /v1/prompts/analytics/comparison ─────────────────────────────────────
// MUST be registered before /:id to avoid Hono route shadowing

prompts.get('/analytics/comparison', async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.query('prompt_id');

  if (!promptId) return c.json({ error: 'prompt_id query param required' }, 400);

  // Verify prompt ownership
  const prompt = await c.env.DB
    .prepare('SELECT id, name FROM prompts WHERE id = ? AND org_id = ? AND deleted_at IS NULL')
    .bind(promptId, orgId)
    .first<{ id: string; name: string }>();
  if (!prompt) return c.json({ error: 'not found' }, 404);

  const versions = await c.env.DB
    .prepare(`SELECT
                pv.id, pv.version_num, pv.model, pv.notes, pv.created_at,
                pv.total_calls, pv.total_cost_usd, pv.avg_cost_usd,
                pv.avg_prompt_tokens, pv.avg_completion_tokens,
                substr(pv.content, 1, 100) AS content_preview
              FROM prompt_versions pv
              WHERE pv.prompt_id = ?
              ORDER BY pv.version_num ASC`)
    .bind(promptId)
    .all<{
      id: string; version_num: number; model: string | null; notes: string | null;
      created_at: string; total_calls: number; total_cost_usd: number;
      avg_cost_usd: number; avg_prompt_tokens: number; avg_completion_tokens: number;
      content_preview: string;
    }>();

  // Cost delta between consecutive versions
  const vList = versions.results;
  const withDelta = vList.map((v, i) => {
    const prev = i > 0 ? vList[i - 1] : null;
    const costDelta = prev && prev.avg_cost_usd > 0
      ? ((v.avg_cost_usd - prev.avg_cost_usd) / prev.avg_cost_usd) * 100
      : null;
    return { ...v, cost_delta_pct: costDelta !== null ? Math.round(costDelta * 10) / 10 : null };
  });

  return c.json({ prompt, versions: withDelta });
});

// ── GET /v1/prompts/:id ───────────────────────────────────────────────────────

prompts.get('/:id', async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.param('id');

  const prompt = await c.env.DB
    .prepare('SELECT * FROM prompts WHERE id = ? AND org_id = ? AND deleted_at IS NULL')
    .bind(promptId, orgId)
    .first<{ id: string; name: string; description: string | null; created_by: string; created_at: string; updated_at: string }>();

  if (!prompt) return c.json({ error: 'not found' }, 404);

  const versions = await c.env.DB
    .prepare(`SELECT id, version_num, model, notes, created_by, created_at,
                total_calls, total_cost_usd, avg_cost_usd,
                avg_prompt_tokens, avg_completion_tokens,
                substr(content, 1, 200) AS content_preview,
                length(content) AS content_length
              FROM prompt_versions
              WHERE prompt_id = ?
              ORDER BY version_num DESC`)
    .bind(promptId)
    .all<{
      id: string; version_num: number; model: string | null; notes: string | null;
      created_by: string; created_at: string; total_calls: number;
      total_cost_usd: number; avg_cost_usd: number;
      avg_prompt_tokens: number; avg_completion_tokens: number;
      content_preview: string; content_length: number;
    }>();

  return c.json({ ...prompt, versions: versions.results });
});

// ── PATCH /v1/prompts/:id ─────────────────────────────────────────────────────

prompts.patch('/:id', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.param('id');
  const body = await c.req.json<{ name?: string; description?: string }>().catch(() => null);

  if (!body) return c.json({ error: 'invalid body' }, 400);

  const prompt = await c.env.DB
    .prepare('SELECT id FROM prompts WHERE id = ? AND org_id = ? AND deleted_at IS NULL')
    .bind(promptId, orgId)
    .first();
  if (!prompt) return c.json({ error: 'not found' }, 404);

  await c.env.DB
    .prepare(`UPDATE prompts SET
                name = COALESCE(?, name),
                description = COALESCE(?, description),
                updated_at = datetime('now')
              WHERE id = ? AND org_id = ?`)
    .bind(body.name?.trim() ?? null, body.description ?? null, promptId, orgId)
    .run();

  return c.json({ updated: true });
});

// ── DELETE /v1/prompts/:id ────────────────────────────────────────────────────

prompts.delete('/:id', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.param('id');

  const result = await c.env.DB
    .prepare("UPDATE prompts SET deleted_at = datetime('now') WHERE id = ? AND org_id = ? AND deleted_at IS NULL")
    .bind(promptId, orgId)
    .run();

  if (!result.meta.changes) return c.json({ error: 'not found' }, 404);
  return c.json({ deleted: true });
});

// ── POST /v1/prompts/:id/versions ─────────────────────────────────────────────

prompts.post('/:id/versions', adminOnly, async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.param('id');
  const memberEmail = c.get('memberEmail') ?? 'owner';

  const prompt = await c.env.DB
    .prepare('SELECT id FROM prompts WHERE id = ? AND org_id = ? AND deleted_at IS NULL')
    .bind(promptId, orgId)
    .first();
  if (!prompt) return c.json({ error: 'not found' }, 404);

  const body = await c.req.json<{
    content: string;
    model?: string;
    notes?: string;
  }>().catch(() => null);

  if (!body?.content?.trim()) return c.json({ error: 'content is required' }, 400);

  // Get next version number
  const maxRow = await c.env.DB
    .prepare('SELECT MAX(version_num) AS max_num FROM prompt_versions WHERE prompt_id = ?')
    .bind(promptId)
    .first<{ max_num: number | null }>();

  const nextNum = (maxRow?.max_num ?? 0) + 1;
  const versionId = generateId();

  await c.env.DB
    .prepare(`INSERT INTO prompt_versions (id, prompt_id, version_num, content, model, notes, created_by)
              VALUES (?, ?, ?, ?, ?, ?, ?)`)
    .bind(versionId, promptId, nextNum, body.content.trim(), body.model ?? null, body.notes ?? null, memberEmail)
    .run();

  // Touch parent updated_at
  await c.env.DB
    .prepare("UPDATE prompts SET updated_at = datetime('now') WHERE id = ?")
    .bind(promptId)
    .run();

  return c.json({ id: versionId, version_num: nextNum }, 201);
});

// ── GET /v1/prompts/:id/versions/:versionId ───────────────────────────────────

prompts.get('/:id/versions/:versionId', async (c) => {
  const orgId = c.get('orgId');
  const promptId = c.req.param('id');
  const versionId = c.req.param('versionId');

  // Verify prompt belongs to org
  const prompt = await c.env.DB
    .prepare('SELECT id FROM prompts WHERE id = ? AND org_id = ? AND deleted_at IS NULL')
    .bind(promptId, orgId)
    .first();
  if (!prompt) return c.json({ error: 'not found' }, 404);

  const version = await c.env.DB
    .prepare('SELECT * FROM prompt_versions WHERE id = ? AND prompt_id = ?')
    .bind(versionId, promptId)
    .first<{
      id: string; prompt_id: string; version_num: number; content: string;
      model: string | null; notes: string | null; created_by: string; created_at: string;
      total_calls: number; total_cost_usd: number; avg_cost_usd: number;
      avg_prompt_tokens: number; avg_completion_tokens: number;
    }>();

  if (!version) return c.json({ error: 'not found' }, 404);
  return c.json(version);
});

