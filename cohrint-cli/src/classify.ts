export function looksLikeStructuredData(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true;
  if (trimmed.startsWith("```")) return true;
  if (/```[\s\S]*?```/.test(text)) return true;
  if (/`[^`\n]+`/.test(text)) return true;
  if ((text.match(/https?:\/\//g) || []).length > 2) return true;
  if ((text.match(/[{}()\[\];=<>]/g) || []).length > text.length * 0.1) return true;
  return false;
}
