export interface ModelPrice {
  input: number;
  output: number;
  cache: number;
}

/** Prices in USD per 1M tokens */
export const PRICES: Record<string, ModelPrice> = {
  "gpt-4o":               { input: 2.50,  output: 10.00, cache: 1.25 },
  "gpt-4o-mini":          { input: 0.15,  output: 0.60,  cache: 0.075 },
  "o1":                   { input: 15.00, output: 60.00, cache: 7.50 },
  "o3-mini":              { input: 1.10,  output: 4.40,  cache: 0.55 },
  "gpt-3.5-turbo":        { input: 0.50,  output: 1.50,  cache: 0.25 },
  "claude-opus-4-6":      { input: 15.00, output: 75.00, cache: 1.50 },
  "claude-sonnet-4-6":    { input: 3.00,  output: 15.00, cache: 0.30 },
  "claude-haiku-4-5":     { input: 0.80,  output: 4.00,  cache: 0.08 },
  "gemini-2.0-flash":     { input: 0.10,  output: 0.40,  cache: 0.025 },
  "gemini-1.5-pro":       { input: 1.25,  output: 5.00,  cache: 0.31 },
  "gemini-1.5-flash":     { input: 0.075, output: 0.30,  cache: 0.018 },
  "llama-3.3-70b":        { input: 0.23,  output: 0.40,  cache: 0.0 },
  "mistral-large-latest": { input: 2.00,  output: 6.00,  cache: 0.0 },
  "deepseek-chat":        { input: 0.27,  output: 1.10,  cache: 0.0 },
  "grok-2":               { input: 2.00,  output: 10.00, cache: 0.0 },
};

/**
 * Calculate cost in USD for a given model and token counts.
 * Prices are per 1M tokens, so divide by 1_000_000.
 */
export function calculateCost(
  model: string,
  promptTokens: number,
  completionTokens: number,
  cachedTokens: number = 0
): number {
  const price = PRICES[model];
  if (!price) {
    return 0;
  }
  const billableInput = Math.max(0, promptTokens - cachedTokens);
  const inputCost = (billableInput * price.input) / 1_000_000;
  const cacheCost = (cachedTokens * price.cache) / 1_000_000;
  const outputCost = (completionTokens * price.output) / 1_000_000;
  return inputCost + cacheCost + outputCost;
}

export interface CheapestResult {
  model: string;
  cost: number;
  savings: number;
  savingsPercent: number;
}

/**
 * Find the cheapest model for the given token usage compared to currentModel.
 */
export function findCheapest(
  currentModel: string,
  promptTokens: number,
  completionTokens: number
): CheapestResult | null {
  const currentCost = calculateCost(currentModel, promptTokens, completionTokens);
  if (currentCost === 0) return null;

  let cheapestModel = currentModel;
  let cheapestCost = currentCost;

  for (const [model, _price] of Object.entries(PRICES)) {
    const cost = calculateCost(model, promptTokens, completionTokens);
    if (cost < cheapestCost) {
      cheapestCost = cost;
      cheapestModel = model;
    }
  }

  if (cheapestModel === currentModel) return null;

  const savings = currentCost - cheapestCost;
  const savingsPercent = Math.round((savings / currentCost) * 100);

  return {
    model: cheapestModel,
    cost: cheapestCost,
    savings,
    savingsPercent,
  };
}
