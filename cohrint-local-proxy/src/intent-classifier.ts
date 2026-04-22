/**
 * Intent classifier — rule-based, zero latency, no API calls.
 * Classifies an LLM request as one of four coding-tool intents.
 */

export type CodingIntent = "autocomplete" | "generation" | "refactor" | "explanation";

interface Message {
  role: string;
  content: string | { type: string; text?: string }[];
}

function extractText(messages: Message[]): string {
  return messages
    .map((m) => {
      if (typeof m.content === "string") return m.content;
      if (Array.isArray(m.content)) {
        return m.content
          .filter((b) => b.type === "text" && b.text)
          .map((b) => b.text ?? "")
          .join(" ");
      }
      return "";
    })
    .join(" ")
    .toLowerCase()
    .slice(0, 2000); // only inspect first 2000 chars for speed
}

function estimateTokens(text: string): number {
  // rough: 1 token ≈ 4 chars
  return Math.ceil(text.length / 4);
}

const GENERATION_PATTERNS = [
  /\b(write|create|generate|implement|build|code|add|scaffold|make)\b/,
  /\b(function|class|component|module|api|endpoint|test|spec)\b/,
  /\bnew (file|feature|page|route|handler|service|hook)\b/,
];

const REFACTOR_PATTERNS = [
  /\b(refactor|rewrite|improve|optimize|simplify|clean|restructure|redesign)\b/,
  /\b(make (it|this|the code) (better|cleaner|faster|more readable))\b/,
  /\b(reduce|extract|split|merge|rename|move)\b/,
  /\b(technical debt|code smell|duplication)\b/,
];

const EXPLANATION_PATTERNS = [
  /\b(explain|describe|what (is|are|does)|how (does|do|can)|why (does|is|did))\b/,
  /\b(summarize|summary|overview|understand|clarify|elaborate)\b/,
  /\b(what('s| is) (the|this|that)|tell me about|help me understand)\b/,
];

export function classifyIntent(
  messages: Message[],
  system?: string,
): CodingIntent {
  const text = extractText(messages) + " " + (system ?? "").toLowerCase();
  const tokens = estimateTokens(text);

  // Autocomplete: very short requests with minimal context
  if (tokens < 40 && messages.length === 1) {
    const userMsg = messages[messages.length - 1];
    const content = typeof userMsg?.content === "string" ? userMsg.content : "";
    // Autocomplete signals: ends mid-sentence, no punctuation, short
    if (content.length < 120 && !/[.?!]$/.test(content.trim())) {
      return "autocomplete";
    }
  }

  // Score each intent by pattern matches
  const refactorScore = REFACTOR_PATTERNS.filter((p) => p.test(text)).length;
  const generationScore = GENERATION_PATTERNS.filter((p) => p.test(text)).length;
  const explanationScore = EXPLANATION_PATTERNS.filter((p) => p.test(text)).length;

  if (refactorScore >= generationScore && refactorScore >= explanationScore && refactorScore > 0) {
    return "refactor";
  }
  if (explanationScore >= generationScore && explanationScore > 0) {
    return "explanation";
  }
  if (generationScore > 0) {
    return "generation";
  }

  // Default: generation (most common coding request)
  return "generation";
}
