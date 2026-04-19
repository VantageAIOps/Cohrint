interface ModelPrice {
  input: number;
  output: number;
  cache: number;
}

const PRICES: Record<string, ModelPrice> = {
  "gpt-4o": { input: 2.5, output: 10, cache: 1.25 },
  "gpt-4o-mini": { input: 0.15, output: 0.6, cache: 0.075 },
  "o1": { input: 15, output: 60, cache: 7.5 },
  "o3-mini": { input: 1.1, output: 4.4, cache: 0.55 },
  "gpt-3.5-turbo": { input: 0.5, output: 1.5, cache: 0.25 },
  "claude-opus-4-6": { input: 15, output: 75, cache: 1.5 },
  "claude-sonnet-4-6": { input: 3, output: 15, cache: 0.3 },
  "claude-haiku-4-5": { input: 0.8, output: 4, cache: 0.08 },
  "gemini-2.0-flash": { input: 0.1, output: 0.4, cache: 0.025 },
  "gemini-1.5-pro": { input: 1.25, output: 5, cache: 0.31 },
  "gemini-1.5-flash": { input: 0.075, output: 0.3, cache: 0.018 },
  "llama-3.3-70b": { input: 0.23, output: 0.4, cache: 0 },
  "mistral-large-latest": { input: 2, output: 6, cache: 0 },
  "deepseek-chat": { input: 0.27, output: 1.1, cache: 0 },
  "grok-2": { input: 2, output: 10, cache: 0 },
};

export function calculateCost(
  model: string,
  promptTokens: number,
  completionTokens: number,
  cachedTokens = 0
): number {
  let price = PRICES[model];
  if (!price) {
    const lower = model.toLowerCase();
    const key = Object.keys(PRICES).find(
      (k) => lower.startsWith(k) || k.startsWith(lower)
    );
    if (key) {
      price = PRICES[key];
    } else {
      if (typeof process !== "undefined" && process.stderr) {
        process.stderr.write(`  [vantage] Unknown model "${model}" — cost set to $0\n`);
      }
      return 0;
    }
  }
  const billableInput = Math.max(0, promptTokens - cachedTokens);
  const inputCost = (billableInput * price.input) / 1_000_000;
  const cacheCost = (cachedTokens * price.cache) / 1_000_000;
  const outputCost = (completionTokens * price.output) / 1_000_000;
  return inputCost + cacheCost + outputCost;
}
