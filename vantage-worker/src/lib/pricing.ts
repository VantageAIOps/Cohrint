/**
 * Shared LLM pricing table and cost utilities.
 * Rates are per 1M tokens (USD).
 * Imported by: routes/otel.ts, routes/analytics.ts
 */

export interface ModelPrice {
  input:      number;  // per 1M input tokens
  output:     number;  // per 1M output tokens
  cache:      number;  // per 1M cache-read tokens  (~10% of input for Claude)
  cacheWrite: number;  // per 1M cache-write tokens (~125% of input for Claude)
}

export const MODEL_PRICES: Record<string, ModelPrice> = {
  // cacheWrite = prompt cache creation rate (25% premium for Claude, same as input for others)
  // cache      = prompt cache read rate     (Claude: ~90% discount vs input)
  'claude-opus-4-6':      { input: 15.00, output: 75.00, cache: 1.50,  cacheWrite: 18.75 },
  'claude-sonnet-4-6':    { input:  3.00, output: 15.00, cache: 0.30,  cacheWrite:  3.75 },
  'claude-haiku-4-5':     { input:  0.80, output:  4.00, cache: 0.08,  cacheWrite:  1.00 },
  'claude-3-5-sonnet':    { input:  3.00, output: 15.00, cache: 0.30,  cacheWrite:  3.75 },
  'claude-3-haiku':       { input:  0.25, output:  1.25, cache: 0.03,  cacheWrite:  0.31 },
  'gpt-4o':               { input:  2.50, output: 10.00, cache: 1.25,  cacheWrite:  2.50 },
  'gpt-4o-mini':          { input:  0.15, output:  0.60, cache: 0.075, cacheWrite:  0.15 },
  'o1':                   { input: 15.00, output: 60.00, cache: 7.50,  cacheWrite: 15.00 },
  'o3-mini':              { input:  1.10, output:  4.40, cache: 0.55,  cacheWrite:  1.10 },
  'gemini-2.0-flash':     { input:  0.10, output:  0.40, cache: 0.025, cacheWrite:  0.10 },
  'gemini-1.5-pro':       { input:  1.25, output:  5.00, cache: 0.31,  cacheWrite:  1.25 },
  'gemini-1.5-flash':     { input:  0.075,output:  0.30, cache: 0.018, cacheWrite:  0.075},
};

/** Fuzzy-match a model string to a pricing entry. Returns null if not found. */
export function lookupPrice(model: string): ModelPrice | null {
  if (!model) return null;
  if (MODEL_PRICES[model]) return MODEL_PRICES[model];
  const lower = model.toLowerCase();
  const key = Object.keys(MODEL_PRICES).find(k => lower.includes(k) || k.includes(lower));
  return key ? MODEL_PRICES[key] : null;
}

/** Full cost estimate including cache read/write differentials. */
export function estimateCostUsd(
  model: string | null,
  inputTokens: number,
  outputTokens: number,
  cachedTokens: number,
  cacheCreationTokens = 0,
): number {
  if (!model) return 0;
  const price = lookupPrice(model);
  if (!price) return 0;
  const cacheWriteCost = (cacheCreationTokens / 1e6) * price.cacheWrite;
  const cacheReadCost  = (cachedTokens / 1e6) * price.cache;
  const regularInput   = Math.max(0, inputTokens - cachedTokens - cacheCreationTokens);
  const inputCost      = (regularInput / 1e6) * price.input;
  const outputCost     = (outputTokens / 1e6) * price.output;
  return cacheWriteCost + cacheReadCost + inputCost + outputCost;
}

/**
 * Compute USD saved by provider-native cache reads vs paying full input rate.
 * savings = cached_tokens × (input_price - cache_read_price) / 1M
 */
export function estimateCacheSavings(model: string, cacheTokens: number): number {
  if (!model || cacheTokens <= 0) return 0;
  const price = lookupPrice(model);
  if (!price) return 0;
  return (cacheTokens / 1e6) * (price.input - price.cache);
}
