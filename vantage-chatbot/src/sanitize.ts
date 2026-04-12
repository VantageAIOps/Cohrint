const REDACT_PATTERNS: RegExp[] = [
  /\bvnt_[A-Za-z0-9_-]{20,}\b/g,
  /\bsk-ant-[A-Za-z0-9_-]{20,}\b/g,
  /\bsk-[A-Za-z0-9]{20,}\b/g,
  /\b(?:\d{1,3}\.){3}\d{1,3}\b/g,
  /\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b/g,
  /(?:DROP|DELETE|TRUNCATE|ALTER)\s+TABLE/gi,
];

export function sanitize(text: string): string {
  let out = text;
  for (const pattern of REDACT_PATTERNS) {
    out = out.replace(pattern, "[REDACTED]");
  }
  return out;
}
