/**
 * Pricing table — copied from vantage-js-sdk for standalone use.
 * Keeps the local proxy self-contained with no cross-package deps.
 */

export interface ModelPrice {
  provider: string;
  input: number;   // $ per 1M tokens
  output: number;  // $ per 1M tokens
  cache: number;   // $ per 1M cached tokens
}

export const PRICES: Record<string, ModelPrice> = {
  // OpenAI
  "gpt-4o":               { provider: "openai",    input: 2.50,  output: 10.00, cache: 1.25  },
  "gpt-4o-mini":          { provider: "openai",    input: 0.15,  output: 0.60,  cache: 0.075 },
  "o1":                   { provider: "openai",    input: 15.00, output: 60.00, cache: 7.50  },
  "o3-mini":              { provider: "openai",    input: 1.10,  output: 4.40,  cache: 0.55  },
  "gpt-3.5-turbo":        { provider: "openai",    input: 0.50,  output: 1.50,  cache: 0.25  },
  // Anthropic
  "claude-opus-4-6":      { provider: "anthropic", input: 15.00, output: 75.00, cache: 1.50  },
  "claude-sonnet-4-6":    { provider: "anthropic", input: 3.00,  output: 15.00, cache: 0.30  },
  "claude-haiku-4-5":     { provider: "anthropic", input: 0.80,  output: 4.00,  cache: 0.08  },
  "claude-3-5-sonnet":    { provider: "anthropic", input: 3.00,  output: 15.00, cache: 0.30  },
  "claude-3-haiku":       { provider: "anthropic", input: 0.25,  output: 1.25,  cache: 0.03  },
  // Google
  "gemini-2.0-flash":     { provider: "google",    input: 0.10,  output: 0.40,  cache: 0.025 },
  "gemini-1.5-pro":       { provider: "google",    input: 1.25,  output: 5.00,  cache: 0.31  },
  "gemini-1.5-flash":     { provider: "google",    input: 0.075, output: 0.30,  cache: 0.018 },
  // Meta
  "llama-3.3-70b":        { provider: "meta",      input: 0.23,  output: 0.40,  cache: 0.0   },
  "llama-3.1-405b":       { provider: "meta",      input: 0.80,  output: 0.80,  cache: 0.0   },
  "llama-3.1-8b":         { provider: "meta",      input: 0.06,  output: 0.06,  cache: 0.0   },
  // Mistral
  "mistral-large-latest": { provider: "mistral",   input: 2.00,  output: 6.00,  cache: 0.0   },
  "mistral-small-latest": { provider: "mistral",   input: 0.20,  output: 0.60,  cache: 0.0   },
  // DeepSeek
  "deepseek-chat":        { provider: "deepseek",  input: 0.27,  output: 1.10,  cache: 0.0   },
  "deepseek-reasoner":    { provider: "deepseek",  input: 0.55,  output: 2.19,  cache: 0.0   },
  // Cohere
  "command-r-plus":       { provider: "cohere",    input: 2.50,  output: 10.00, cache: 0.0   },
  "command-r":            { provider: "cohere",    input: 0.15,  output: 0.60,  cache: 0.0   },
  // xAI
  "grok-2":               { provider: "xai",       input: 2.00,  output: 10.00, cache: 0.0   },
};

export function calculateCost(
  model: string,
  promptTokens: number,
  completionTokens: number,
  cachedTokens = 0,
): { inputCostUsd: number; outputCostUsd: number; totalCostUsd: number } {
  let price = PRICES[model];
  if (!price) {
    const lower = model.toLowerCase();
    const key = Object.keys(PRICES).find((k) => lower.includes(k) || k.includes(lower));
    price = key ? PRICES[key] : { provider: "unknown", input: 0, output: 0, cache: 0 };
  }
  const uncached = Math.max(0, promptTokens - cachedTokens);
  const inputCostUsd = (uncached / 1e6) * price.input + (cachedTokens / 1e6) * price.cache;
  const outputCostUsd = (completionTokens / 1e6) * price.output;
  return { inputCostUsd, outputCostUsd, totalCostUsd: inputCostUsd + outputCostUsd };
}

export function findCheapest(
  currentModel: string,
  promptTokens: number,
  completionTokens: number,
): { model: string; costUsd: number } | null {
  const { totalCostUsd: currentCost } = calculateCost(currentModel, promptTokens, completionTokens);
  let best: { model: string; costUsd: number } | null = null;
  for (const [name] of Object.entries(PRICES)) {
    if (name === currentModel) continue;
    const { totalCostUsd } = calculateCost(name, promptTokens, completionTokens);
    if (totalCostUsd < currentCost && (!best || totalCostUsd < best.costUsd)) {
      best = { model: name, costUsd: totalCostUsd };
    }
  }
  return best;
}
