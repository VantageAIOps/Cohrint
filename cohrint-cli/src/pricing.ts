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

// Bound per-call token inputs so a hostile agent feeding giant counts can't
// produce Infinity cost (N * price overflows past Number.MAX_SAFE_INTEGER
// at roughly 1.2e14 tokens). 1e10 is already absurd (~$750k on opus-4-6).
const MAX_TOKENS_PER_CALL = 10_000_000_000;

function _safeTokens(n: unknown): number {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return 0;
  if (n > MAX_TOKENS_PER_CALL) return MAX_TOKENS_PER_CALL;
  return Math.floor(n);
}

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
        // Scrub: model may originate from agent stdout and could contain
        // escape bytes aimed at the operator's terminal.
        const safeModel = String(model).replace(/[\x00-\x1f\x7f-\x9f]/g, "").slice(0, 80);
        process.stderr.write(`  [vantage] Unknown model "${safeModel}" — cost set to $0\n`);
      }
      return 0;
    }
  }
  const pt = _safeTokens(promptTokens);
  const ct = _safeTokens(completionTokens);
  const kt = _safeTokens(cachedTokens);
  const billableInput = Math.max(0, pt - kt);
  const inputCost = (billableInput * price.input) / 1_000_000;
  const cacheCost = (kt * price.cache) / 1_000_000;
  const outputCost = (ct * price.output) / 1_000_000;
  const total = inputCost + cacheCost + outputCost;
  return Number.isFinite(total) && total >= 0 ? total : 0;
}
