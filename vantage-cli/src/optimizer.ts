export const FILLER_PHRASES: string[] = [
  "i'd like you to",
  "i want you to",
  "i need you to",
  "would you mind",
  "could you please",
  "can you please",
  "please note that",
  "it is important to note that",
  "as an ai language model",
  "as a helpful assistant",
  "in order to",
  "for the purpose of",
  "with regard to",
  "in the context of",
  "it should be noted that",
  "it is worth mentioning that",
  "i was wondering if you could",
  "it goes without saying",
  "needless to say",
  "as previously mentioned",
  "as stated above",
  "for your information",
  "i would appreciate it if you could",
  "please be advised that",
  "at the end of the day",
  "in today's world",
  "in this day and age",
  "each and every",
  "first and foremost",
  "due to the fact that",
  "on account of the fact that",
  "in light of the fact that",
  "despite the fact that",
  "the reason is because",
  "whether or not",
];

export const VERBOSE_REWRITES: [RegExp, string][] = [
  [/\bin order to\b/gi, "to"],
  [/\bfor the purpose of\b/gi, "to"],
  [/\bwith regard to\b/gi, "regarding"],
  [/\bin the context of\b/gi, "in"],
  [/\bdue to the fact that\b/gi, "because"],
  [/\bon account of the fact that\b/gi, "because"],
  [/\bin light of the fact that\b/gi, "since"],
  [/\bdespite the fact that\b/gi, "although"],
  [/\bthe reason is because\b/gi, "because"],
  [/\bin the event that\b/gi, "if"],
  [/\bin the near future\b/gi, "soon"],
  [/\bat this point in time\b/gi, "now"],
  [/\bat the present time\b/gi, "now"],
  [/\bfor all intents and purposes\b/gi, "effectively"],
  [/\bin a manner of speaking\b/gi, ""],
  [/\bby means of\b/gi, "by"],
  [/\bin the amount of\b/gi, "for"],
  [/\bhas the ability to\b/gi, "can"],
  [/\bis able to\b/gi, "can"],
  [/\bit is possible that\b/gi, "possibly"],
  [/\bthere is a possibility that\b/gi, "possibly"],
  [/\bit is necessary that\b/gi, "must"],
  [/\bit is important that\b/gi, "must"],
  [/\bhas the capacity to\b/gi, "can"],
  [/\bin close proximity to\b/gi, "near"],
  [/\ba large number of\b/gi, "many"],
  [/\ba small number of\b/gi, "few"],
  [/\bthe vast majority of\b/gi, "most"],
  [/\bon a regular basis\b/gi, "regularly"],
  [/\bin an effort to\b/gi, "to"],
  [/\bwith the exception of\b/gi, "except"],
  [/\bas a consequence of\b/gi, "because of"],
  [/\bas a result of\b/gi, "from"],
  [/\bfor the reason that\b/gi, "because"],
  [/\bin such a way that\b/gi, "so that"],
  [/\bin spite of\b/gi, "despite"],
  [/\buntil such time as\b/gi, "until"],
  [/\bwith reference to\b/gi, "about"],
  [/\bin relation to\b/gi, "about"],
  [/\bin connection with\b/gi, "about"],
  [/\btake into consideration\b/gi, "consider"],
  [/\bmake a decision\b/gi, "decide"],
];

export const FILLER_WORDS_RE =
  /\b(just|really|very|quite|basically|actually|simply|honestly|literally|definitely|certainly|absolutely|obviously|clearly|essentially|practically|virtually|merely|somewhat|rather|fairly|pretty much)\b/gi;

/**
 * Approximate token count using character-based heuristic.
 * ~1 token per 4 characters for English text, ~1 per 3 for code.
 * More accurate than word-based counting for mixed content.
 */
export function countTokens(text: string): number {
  if (!text || text.trim().length === 0) return 0;
  const trimmed = text.trim();
  // Detect code-heavy content (higher token density)
  const codeChars = (trimmed.match(/[{}()\[\];=<>|&!~^%]/g) || []).length;
  const isCodeHeavy = codeChars > trimmed.length * 0.05;
  const charsPerToken = isCodeHeavy ? 3 : 4;
  return Math.ceil(trimmed.length / charsPerToken);
}

/**
 * 5-layer compression engine:
 * 1. Remove filler phrases
 * 2. Apply verbose rewrites
 * 3. Strip filler words
 * 4. Collapse whitespace
 * 5. Trim
 */
export function compressPrompt(prompt: string): string {
  let result = prompt;

  // Layer 1: Remove filler phrases
  for (const phrase of FILLER_PHRASES) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(escaped, "gi");
    result = result.replace(re, "");
  }

  // Layer 2: Apply verbose rewrites
  for (const [pattern, replacement] of VERBOSE_REWRITES) {
    result = result.replace(pattern, replacement);
  }

  // Layer 3: Strip filler words
  result = result.replace(FILLER_WORDS_RE, "");

  // Layer 4: Collapse whitespace
  result = result.replace(/\s{2,}/g, " ");

  // Layer 5: Trim
  result = result.trim();

  return result;
}

export function getOptimizationTips(prompt: string): string[] {
  const tips: string[] = [];
  const lower = prompt.toLowerCase();

  for (const phrase of FILLER_PHRASES) {
    if (lower.includes(phrase)) {
      tips.push(`Remove filler phrase: "${phrase}"`);
    }
  }

  for (const [pattern] of VERBOSE_REWRITES) {
    if (pattern.test(prompt)) {
      tips.push(`Simplify verbose phrase: "${pattern.source}"`);
      pattern.lastIndex = 0; // Reset regex state
    }
  }

  const fillerMatches = prompt.match(FILLER_WORDS_RE);
  if (fillerMatches && fillerMatches.length > 0) {
    const unique = [...new Set(fillerMatches.map((w) => w.toLowerCase()))];
    tips.push(`Remove filler words: ${unique.join(", ")}`);
  }

  if (prompt.length > 2000) {
    tips.push("Consider breaking this into smaller, focused prompts");
  }

  return tips;
}

export interface OptimizationResult {
  original: string;
  optimized: string;
  originalTokens: number;
  optimizedTokens: number;
  savedTokens: number;
  savedPercent: number;
}

export function optimizePrompt(prompt: string): OptimizationResult {
  const original = prompt;
  const optimized = compressPrompt(prompt);
  const originalTokens = countTokens(original);
  const optimizedTokens = countTokens(optimized);
  const savedTokens = originalTokens - optimizedTokens;
  const savedPercent = originalTokens > 0 ? Math.round((savedTokens / originalTokens) * 100) : 0;

  return {
    original,
    optimized,
    originalTokens,
    optimizedTokens,
    savedTokens,
    savedPercent,
  };
}
