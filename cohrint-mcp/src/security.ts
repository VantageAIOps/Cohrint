/**
 * Security helpers used by the Cohrint MCP server.
 *
 * Kept in a separate module so the sanitisers and permission model have a
 * dedicated surface for unit tests. Everything here is pure and synchronous.
 */

/** Hard caps on user-supplied input (mirrors index.ts constants). */
export const LIMITS = {
  MAX_PROMPT_CHARS:  200_000,
  MAX_MESSAGE_CHARS:  50_000,
  MAX_MESSAGES:        1_000,
  MAX_TAG_CHARS:         256,
} as const;

/** Tools that only read / compute — safe to expose by default. */
export const READ_ONLY_TOOLS: ReadonlySet<string> = new Set([
  'track_llm_call', 'get_summary', 'get_kpis', 'get_model_breakdown',
  'get_team_breakdown', 'check_budget', 'get_traces', 'get_cost_gate',
  'optimize_prompt', 'analyze_tokens', 'estimate_costs', 'compress_context',
  'find_cheapest_model', 'get_recommendations',
]);

/** Tools that mutate state outside the MCP process (filesystem, ~/.claude). */
export const WRITE_TOOLS: ReadonlySet<string> = new Set(['setup_claude_hook']);

/**
 * Compute the effective allowed-tool set from an env value.
 *   ""       → READ_ONLY_TOOLS  (default: no filesystem writes)
 *   "all"    → READ_ONLY_TOOLS ∪ WRITE_TOOLS
 *   "a,b,c"  → explicit whitelist
 */
export function resolveAllowedTools(raw: string | undefined): Set<string> {
  const trimmed = (raw ?? '').trim();
  if (!trimmed) return new Set(READ_ONLY_TOOLS);
  if (trimmed === 'all') return new Set([...READ_ONLY_TOOLS, ...WRITE_TOOLS]);
  return new Set(trimmed.split(',').map(t => t.trim()).filter(Boolean));
}

/**
 * Sanitise a user-supplied string.
 *
 * Steps: coerce → truncate to `maxLen` → strip control chars (0x00-0x1F
 * except \t \n \r, plus 0x7F). Note: \r is not stripped here but is
 * normalised to a space by escapeMd() for Markdown table contexts.
 *
 * Apply to anything that will be:
 *   - echoed back to the LLM in tool output (indirect prompt-injection vector), or
 *   - forwarded to the Cohrint API (header/URL-injection vector, DoS via size).
 */
export function sanitizeString(v: unknown, maxLen: number): string {
  const s = typeof v === 'string' ? v : v == null ? '' : String(v);
  const clipped = s.length > maxLen ? s.slice(0, maxLen) : s;
  // eslint-disable-next-line no-control-regex
  return clipped.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
}

/** Escape markdown pipe + newline/CR so sanitised text can't break a table row. */
export function escapeMd(s: string): string {
  return s.replace(/\|/g, '\\|').replace(/[\n\r]/g, ' ');
}

/**
 * Redact the secret portion of a Cohrint API key from a string.
 *
 * Key format is `crt_<org>_<secret>` (e.g. `crt_org1_abcdefgh…`). We only
 * redact the `<secret>` tail; the `crt_<org>_` prefix is low-sensitivity
 * (visible in org URLs). If the format doesn't parse cleanly, fall back
 * to masking everything after `crt_` but require at least 8 chars of tail.
 *
 * Returns the input unchanged for missing/short keys — **never** builds a
 * regex from a short key (an empty RegExp would match every byte and blank
 * out the entire log line).
 */
export function redactKey(s: string, apiKey: string): string {
  if (!apiKey || apiKey.length < 12) return s;

  let secretTail = '';
  if (apiKey.startsWith('crt_')) {
    const secondUnderscore = apiKey.indexOf('_', 4);
    if (secondUnderscore > 4 && secondUnderscore + 1 < apiKey.length) {
      secretTail = apiKey.slice(secondUnderscore + 1);
    }
  }
  // Fallback: mask last 2/3 of the key for non-standard formats.
  if (secretTail.length < 8) secretTail = apiKey.slice(Math.floor(apiKey.length / 3));
  if (!secretTail || secretTail.length < 8) return s;

  return s.split(secretTail).join('****');
}

/**
 * Throw when a tool isn't on the allowed list. Lets the caller bubble a
 * clear error up to the MCP client.
 */
export function assertToolAllowed(name: string, allowed: ReadonlySet<string>): void {
  if (allowed.has(name)) return;
  const hint = WRITE_TOOLS.has(name)
    ? ` Set COHRINT_MCP_ALLOW_SETUP=1 and COHRINT_MCP_ALLOWED_TOOLS=${name} to enable.`
    : ` Set COHRINT_MCP_ALLOWED_TOOLS=${name} (or "all") to enable.`;
  throw new Error(`Tool "${name}" is not enabled in this MCP session.${hint}`);
}
