/**
 * classify.ts — prompt classification utilities
 * Extracted so test harnesses can import the real function.
 */

/**
 * Returns true when text should skip the prompt optimizer.
 * Detects JSON, code blocks, inline code, URL-heavy content, and code-like
 * high-symbol-density strings.
 */
export function looksLikeStructuredData(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true; // JSON
  if (trimmed.startsWith("```")) return true; // code block
  if (/```[\s\S]*?```/.test(text)) return true; // fenced code block anywhere
  if (/`[^`\n]+`/.test(text)) return true; // inline code
  if ((text.match(/https?:\/\//g) || []).length > 2) return true; // URL-heavy
  if ((text.match(/[{}()\[\];=<>]/g) || []).length > text.length * 0.1) return true; // code-like
  return false;
}
