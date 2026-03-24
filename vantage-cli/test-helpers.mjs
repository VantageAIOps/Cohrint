#!/usr/bin/env node
// Unit test harness — called by pytest
// Usage: node test-helpers.mjs optimize "prompt text"
//        node test-helpers.mjs tokens "text to count"
//        node test-helpers.mjs cost "model" inputTokens outputTokens [cachedTokens]
//        node test-helpers.mjs cheapest "model" inputTokens outputTokens
//        node test-helpers.mjs models

const FILLER_PHRASES = [
  "i'd like you to", "i want you to", "i need you to",
  "would you mind", "could you please", "can you please",
  "please note that", "it is important to note that",
  "as an ai language model", "as a helpful assistant",
  "in order to", "for the purpose of", "with regard to",
  "in the context of", "it should be noted that",
  "it is worth mentioning that", "i was wondering if you could",
  "it goes without saying", "needless to say",
  "as previously mentioned", "as stated above",
  "for your information", "i would appreciate it if you could",
  "please be advised that", "at the end of the day",
  "in today's world", "in this day and age",
  "each and every", "first and foremost",
  "due to the fact that", "on account of the fact that",
  "in light of the fact that", "despite the fact that",
  "the reason is because", "whether or not",
];

const FILLER_WORDS_RE = /\b(please|kindly|basically|essentially|actually|literally|obviously|clearly|simply|just|very|really|quite|rather|somewhat|pretty|fairly)\b/gi;

const VERBOSE_REWRITES = [
  [/\bin order to\b/gi, 'to'], [/\bfor the purpose of\b/gi, 'for'],
  [/\bwith regard to\b/gi, 'regarding'], [/\bwith respect to\b/gi, 'regarding'],
  [/\bin the event that\b/gi, 'if'], [/\bin the case of\b/gi, 'for'],
  [/\bat this point in time\b/gi, 'now'], [/\bat the present time\b/gi, 'now'],
  [/\bprior to\b/gi, 'before'], [/\bsubsequent to\b/gi, 'after'],
  [/\bin close proximity to\b/gi, 'near'], [/\ba large number of\b/gi, 'many'],
  [/\ba small number of\b/gi, 'few'], [/\bthe majority of\b/gi, 'most'],
  [/\bon a daily basis\b/gi, 'daily'], [/\bon a regular basis\b/gi, 'regularly'],
  [/\bis able to\b/gi, 'can'], [/\bare able to\b/gi, 'can'],
  [/\bhas the ability to\b/gi, 'can'], [/\bhave the ability to\b/gi, 'can'],
  [/\bmake a decision\b/gi, 'decide'], [/\btake into consideration\b/gi, 'consider'],
  [/\bthe fact that\b/gi, 'that'], [/\bin spite of\b/gi, 'despite'],
  [/\bdue to the fact that\b/gi, 'because'], [/\bon account of\b/gi, 'because'],
  [/\bfor the reason that\b/gi, 'because'], [/\bwith the exception of\b/gi, 'except'],
  [/\bin the near future\b/gi, 'soon'], [/\bin regard to\b/gi, 'about'],
  [/\bpertaining to\b/gi, 'about'], [/\bby means of\b/gi, 'by'],
  [/\bin conjunction with\b/gi, 'with'], [/\bin an effort to\b/gi, 'to'],
  [/\bas a consequence of\b/gi, 'because of'], [/\bin the process of\b/gi, 'while'],
];

const PRICES = {
  "gpt-4o": { provider: "openai", input: 2.50, output: 10.00, cache: 1.25 },
  "gpt-4o-mini": { provider: "openai", input: 0.15, output: 0.60, cache: 0.075 },
  "o1": { provider: "openai", input: 15.00, output: 60.00, cache: 7.50 },
  "claude-opus-4-6": { provider: "anthropic", input: 15.00, output: 75.00, cache: 1.50 },
  "claude-sonnet-4-6": { provider: "anthropic", input: 3.00, output: 15.00, cache: 0.30 },
  "claude-haiku-4-5": { provider: "anthropic", input: 0.80, output: 4.00, cache: 0.08 },
  "gemini-2.0-flash": { provider: "google", input: 0.10, output: 0.40, cache: 0.025 },
  "gemini-1.5-pro": { provider: "google", input: 1.25, output: 5.00, cache: 0.31 },
  "llama-3.3-70b": { provider: "meta", input: 0.23, output: 0.40, cache: 0.0 },
  "mistral-large-latest": { provider: "mistral", input: 2.00, output: 6.00, cache: 0.0 },
  "deepseek-chat": { provider: "deepseek", input: 0.27, output: 1.10, cache: 0.0 },
  "grok-2": { provider: "xai", input: 2.00, output: 10.00, cache: 0.0 },
  "o3-mini": { provider: "openai", input: 1.10, output: 4.40, cache: 0.55 },
  "gpt-3.5-turbo": { provider: "openai", input: 0.50, output: 1.50, cache: 0.25 },
  "gemini-1.5-flash": { provider: "google", input: 0.075, output: 0.30, cache: 0.018 },
};

function countTokens(text) {
  if (!text) return 0;
  const words = text.split(/\s+/).filter(w => w.length > 0);
  let count = 0;
  for (const w of words) {
    if (w.length <= 4) count += 1;
    else if (w.length <= 8) count += 1.3;
    else if (w.length <= 12) count += 1.8;
    else count += Math.ceil(w.length / 4);
  }
  return Math.ceil(count);
}

function compressPrompt(prompt) {
  let text = prompt;
  for (const phrase of FILLER_PHRASES) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`\\b${escaped}\\b`, 'gi'), '');
  }
  for (const [pattern, replacement] of VERBOSE_REWRITES) {
    text = text.replace(pattern, replacement);
  }
  text = text.replace(FILLER_WORDS_RE, '');
  const sentences = text.split(/(?<=[.!?])\s+/);
  const unique = []; const seen = new Set();
  for (const s of sentences) {
    const norm = s.toLowerCase().trim().replace(/\s+/g, ' ');
    if (norm.length > 2 && !seen.has(norm)) { seen.add(norm); unique.push(s); }
  }
  text = unique.join(' ');
  text = text.replace(/\n{3,}/g, '\n\n').replace(/[ \t]{2,}/g, ' ').replace(/\s+([.!?,;:])/g, '$1').replace(/([.!?])\1+/g, '$1');
  return text.trim();
}

function calculateCost(model, promptTokens, completionTokens, cachedTokens = 0) {
  let price = PRICES[model];
  if (!price) {
    const lower = model.toLowerCase();
    const key = Object.keys(PRICES).find(k => lower.includes(k) || k.includes(lower));
    price = key ? PRICES[key] : { provider: "unknown", input: 0, output: 0, cache: 0 };
  }
  const uncached = Math.max(0, promptTokens - cachedTokens);
  const inputCostUsd = (uncached / 1e6) * price.input + (cachedTokens / 1e6) * price.cache;
  const outputCostUsd = (completionTokens / 1e6) * price.output;
  return { inputCostUsd, outputCostUsd, totalCostUsd: inputCostUsd + outputCostUsd };
}

function findCheapest(currentModel, promptTokens, completionTokens) {
  const { totalCostUsd: currentCost } = calculateCost(currentModel, promptTokens, completionTokens);
  let best = null;
  for (const [name] of Object.entries(PRICES)) {
    if (name === currentModel) continue;
    const { totalCostUsd } = calculateCost(name, promptTokens, completionTokens);
    if (totalCostUsd < currentCost && (!best || totalCostUsd < best.costUsd)) {
      best = { model: name, costUsd: totalCostUsd };
    }
  }
  return best;
}

const cmd = process.argv[2];
const arg1 = process.argv[3] || "";
const arg2 = process.argv[4] || "0";
const arg3 = process.argv[5] || "0";
const arg4 = process.argv[6] || "0";

if (cmd === "optimize") {
  const orig = arg1;
  const compressed = compressPrompt(orig);
  const origTok = countTokens(orig);
  const compTok = countTokens(compressed);
  console.log(JSON.stringify({
    original: orig, optimized: compressed,
    originalTokens: origTok, optimizedTokens: compTok,
    savedTokens: origTok - compTok,
    savedPercent: origTok > 0 ? Math.round((origTok - compTok) / origTok * 100) : 0,
  }));
} else if (cmd === "tokens") {
  console.log(JSON.stringify({ text: arg1, tokens: countTokens(arg1) }));
} else if (cmd === "cost") {
  const r = calculateCost(arg1, parseInt(arg2), parseInt(arg3), parseInt(arg4));
  console.log(JSON.stringify(r));
} else if (cmd === "cheapest") {
  const r = findCheapest(arg1, parseInt(arg2), parseInt(arg3));
  if (r) {
    const { totalCostUsd: currentCost } = calculateCost(arg1, parseInt(arg2), parseInt(arg3));
    r.savingsUsd = currentCost - r.costUsd;
  }
  console.log(JSON.stringify(r));
} else if (cmd === "models") {
  console.log(JSON.stringify({ count: Object.keys(PRICES).length, models: Object.keys(PRICES) }));
} else {
  console.log("Usage: node test-helpers.mjs <optimize|tokens|cost|cheapest|models> [args...]");
}
