import { Hono } from 'hono';
import { Bindings, Variables } from '../types';
import { authMiddleware } from '../middleware/auth';

const optimizer = new Hono<{ Bindings: Bindings; Variables: Variables }>();

optimizer.use('*', authMiddleware);

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Approximate token count (word-count × 1.3, rounded up). */
function countTokens(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean);
  return Math.ceil(words.length * 1.3);
}

/** Hardcoded per-1K-token pricing: [input, output]. */
const MODEL_PRICING: Record<string, [number, number]> = {
  'gpt-4o':           [0.0025, 0.01],
  'gpt-4':            [0.03,   0.06],
  'gpt-3.5-turbo':    [0.0015, 0.002],
  'claude-3-sonnet':  [0.003,  0.015],
  'claude-3-haiku':   [0.00025, 0.00125],
  'gemini-pro':       [0.0005, 0.0015],
};

const FILLER_PHRASES = [
  "i'd like you to",
  "i want you to",
  "i need you to",
  "would you mind",
  "could you please",
  "can you please",
  "could you",
  "can you",
  "would you",
  "please",
  "kindly",
];

/** Simple prompt compressor: strip filler phrases + collapse whitespace. */
function compressPrompt(prompt: string): string {
  let text = prompt;
  for (const phrase of FILLER_PHRASES) {
    // Case-insensitive, word-boundary-aware replacement
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`\\b${escaped}\\b`, 'gi'), '');
  }
  // Collapse multiple spaces / newlines into single space, trim
  return text.replace(/\s+/g, ' ').trim();
}

// ── POST /v1/optimizer/compress ──────────────────────────────────────────────
optimizer.post('/compress', async (c) => {
  const body = await c.req.json<{ prompt: string; compression_rate?: number }>();
  if (!body.prompt) {
    return c.json({ error: 'prompt is required' }, 400);
  }

  const original = body.prompt;
  const compressed = compressPrompt(original);
  const originalTokens = countTokens(original);
  const compressedTokens = countTokens(compressed);
  const tokensSaved = originalTokens - compressedTokens;
  const compressionRatio = originalTokens > 0
    ? Math.round((1 - compressedTokens / originalTokens) * 10000) / 100
    : 0;

  // Persist optimization event (fire-and-forget — don't block the response)
  const orgId = c.get('orgId');
  if (orgId) {
    const optimizationTags = JSON.stringify({
      optimization: {
        type: 'compress',
        improvement_factor: originalTokens > 0
          ? Math.round((originalTokens / Math.max(compressedTokens, 1)) * 10) / 10
          : 1.0,
        tokens_saved: tokensSaved,
        cost_before_usd: null,
        cost_after_usd: null,
        compression_ratio_pct: compressionRatio,
      },
    });
    c.env.DB.prepare(
      `INSERT INTO events (id, org_id, model, prompt_tokens, completion_tokens, cache_tokens, total_tokens, cost_usd, tags)
       VALUES (?, ?, 'optimizer/compress', ?, ?, 0, ?, 0, ?)`
    )
      .bind(crypto.randomUUID(), orgId, originalTokens, compressedTokens, originalTokens, optimizationTags)
      .run()
      .catch((e: unknown) => console.error('optimizer compress tag insert failed', e));
  }

  return c.json({
    original_prompt:   original,
    compressed_prompt: compressed,
    original_tokens:   originalTokens,
    compressed_tokens: compressedTokens,
    compression_ratio: compressionRatio,
    tokens_saved:      tokensSaved,
  });
});

// ── POST /v1/optimizer/analyze ───────────────────────────────────────────────
optimizer.post('/analyze', async (c) => {
  const body = await c.req.json<{ text: string; model?: string }>();
  if (!body.text) {
    return c.json({ error: 'text is required' }, 400);
  }

  const model = body.model ?? 'gpt-4o';
  const pricing = MODEL_PRICING[model];
  if (!pricing) {
    return c.json({ error: `Unknown model: ${model}. Supported: ${Object.keys(MODEL_PRICING).join(', ')}` }, 400);
  }

  const tokenCount = countTokens(body.text);
  const [inputRate, outputRate] = pricing;
  // Estimate: assume output ≈ same length as input for cost estimation
  const inputCost  = (tokenCount / 1000) * inputRate;
  const outputCost = (tokenCount / 1000) * outputRate;
  const estimatedCost = inputCost + outputCost;

  return c.json({
    token_count:    tokenCount,
    estimated_cost: Math.round(estimatedCost * 1_000_000) / 1_000_000,
    cost_breakdown: {
      input_cost:  Math.round(inputCost  * 1_000_000) / 1_000_000,
      output_cost: Math.round(outputCost * 1_000_000) / 1_000_000,
    },
  });
});

// ── POST /v1/optimizer/estimate ──────────────────────────────────────────────
optimizer.post('/estimate', async (c) => {
  const body = await c.req.json<{ prompt: string; completion_tokens?: number }>();
  if (!body.prompt) {
    return c.json({ error: 'prompt is required' }, 400);
  }

  const inputTokens = countTokens(body.prompt);
  const outputTokens = body.completion_tokens ?? inputTokens;

  const comparison = Object.entries(MODEL_PRICING).map(([model, [inputRate, outputRate]]) => {
    const inputCost  = (inputTokens  / 1000) * inputRate;
    const outputCost = (outputTokens / 1000) * outputRate;
    const totalCost  = inputCost + outputCost;
    return {
      model,
      input_tokens:  inputTokens,
      output_tokens: outputTokens,
      input_cost:    Math.round(inputCost  * 1_000_000) / 1_000_000,
      output_cost:   Math.round(outputCost * 1_000_000) / 1_000_000,
      total_cost:    Math.round(totalCost  * 1_000_000) / 1_000_000,
    };
  });

  // Sort cheapest first
  comparison.sort((a, b) => a.total_cost - b.total_cost);

  return c.json({
    input_tokens:  inputTokens,
    output_tokens: outputTokens,
    models:        comparison,
  });
});

// ── GET /v1/optimizer/stats ──────────────────────────────────────────────────
optimizer.get('/stats', async (c) => {
  const orgId     = c.get('orgId');
  const scopeTeam = c.get('scopeTeam');

  let clause = '';
  const args: unknown[] = [orgId];

  if (scopeTeam) {
    clause = ' AND team = ?';
    args.push(scopeTeam);
  }

  // Sum tokens_saved stored inside the tags JSON column
  const row = await c.env.DB.prepare(`
    SELECT
      COUNT(*)                                                        AS total_events,
      COALESCE(SUM(
        CASE WHEN json_valid(tags) THEN CAST(json_extract(tags, '$.tokens_saved') AS INTEGER) ELSE 0 END
      ), 0)                                                           AS total_tokens_saved,
      COALESCE(SUM(cost_usd), 0)                                     AS total_cost_usd,
      COALESCE(SUM(total_tokens), 0)                                  AS total_tokens
    FROM events
    WHERE org_id = ?${clause}
  `).bind(...args).first();

  return c.json({
    total_events:       row?.total_events       ?? 0,
    total_tokens_saved: row?.total_tokens_saved ?? 0,
    total_cost_usd:     row?.total_cost_usd     ?? 0,
    total_tokens:       row?.total_tokens       ?? 0,
    scope_team:         scopeTeam ?? null,
  });
});

export { optimizer };
