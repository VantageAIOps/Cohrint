/**
 * Privacy Engine — strips sensitive data before forwarding stats to Cohrint.
 *
 * SECURITY MODEL:
 *   - API keys NEVER leave the local machine
 *   - Prompts/responses are NEVER sent to Cohrint servers
 *   - Only anonymized statistics are forwarded:
 *     model, provider, token counts, cost, latency, status code, team, environment
 *   - Optional: send hashed prompt fingerprints (SHA-256) for dedup detection
 */

import { createHash } from "crypto";

export type PrivacyLevel = "strict" | "standard" | "relaxed";

export interface PrivacyConfig {
  /** Privacy level (default: "strict")
   *  - strict:   No text, no previews, no hashes — pure numbers only
   *  - standard: Hashed prompt fingerprints for dedup (no readable text)
   *  - relaxed:  First 100 chars of prompt/response (for debugging — NOT recommended in production)
   */
  level: PrivacyLevel;

  /** If true, redact model names to generic labels (e.g., "frontier-1" instead of "gpt-4o") */
  redactModelNames?: boolean;

  /** Custom fields to always strip (on top of defaults) */
  additionalRedactFields?: string[];
}

export const DEFAULT_PRIVACY: PrivacyConfig = {
  level: "strict",
  redactModelNames: false,
  additionalRedactFields: [],
};

/** Fields that are ALWAYS stripped regardless of privacy level */
const ALWAYS_STRIP = [
  "api_key",
  "authorization",
  "x-api-key",
  "openai_api_key",
  "anthropic_api_key",
  "google_api_key",
] as const;

/** Fields stripped in strict and standard modes */
const TEXT_FIELDS = [
  "request_preview",
  "response_preview",
  "system_preview",
  "prompt_text",
  "response_text",
  "system_prompt",
  "messages",
  "content",
] as const;

export interface SanitizedEvent {
  event_id: string;
  timestamp: number;
  org_id: string;
  environment: string;
  provider: string;
  model: string;
  endpoint: string;
  team: string;
  latency_ms: number;
  ttft_ms: number;
  status_code: number;
  error?: string;
  // Token stats only — no text
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens: number;
  // Cost stats
  cost_input_usd: number;
  cost_output_usd: number;
  cost_total_usd: number;
  cheapest_model: string;
  cheapest_cost_usd: number;
  potential_saving_usd: number;
  // Optional hash for dedup (standard mode)
  prompt_hash?: string;
  // Source tag
  source: "local-proxy";
}

/** Hash text to a non-reversible fingerprint */
export function hashText(text: string): string {
  return createHash("sha256").update(text).digest("hex").slice(0, 16);
}

/**
 * Sanitize a raw LLM response event — strip all sensitive data,
 * keep only the statistics needed for cost tracking.
 */
export function sanitizeEvent(
  raw: Record<string, unknown>,
  config: PrivacyConfig = DEFAULT_PRIVACY,
): SanitizedEvent {
  // Start with a clean stats-only object
  const sanitized: SanitizedEvent = {
    event_id: String(raw.event_id ?? `lp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`),
    timestamp: Number(raw.timestamp) || Date.now() / 1000,
    org_id: String(raw.org_id ?? ""),
    environment: String(raw.environment ?? "production"),
    provider: String(raw.provider ?? "unknown"),
    model: config.redactModelNames
      ? redactModelName(String(raw.model ?? ""))
      : String(raw.model ?? ""),
    endpoint: String(raw.endpoint ?? ""),
    team: String(raw.team ?? ""),
    latency_ms: safeNum(raw.latency_ms),
    ttft_ms: safeNum(raw.ttft_ms),
    status_code: safeNum(raw.status_code, 200),
    prompt_tokens: safeNum(raw.prompt_tokens),
    completion_tokens: safeNum(raw.completion_tokens),
    total_tokens: safeNum(raw.total_tokens) ||
      safeNum(raw.prompt_tokens) + safeNum(raw.completion_tokens),
    cached_tokens: safeNum(raw.cached_tokens),
    cost_input_usd: safeNum(raw.cost_input_usd),
    cost_output_usd: safeNum(raw.cost_output_usd),
    cost_total_usd: safeNum(raw.cost_total_usd),
    cheapest_model: String(raw.cheapest_model ?? ""),
    cheapest_cost_usd: safeNum(raw.cheapest_cost_usd),
    potential_saving_usd: safeNum(raw.potential_saving_usd),
    source: "local-proxy",
  };

  // Error messages — strip stack traces, keep first line only
  if (raw.error) {
    sanitized.error = String(raw.error).split("\n")[0].slice(0, 200);
  }

  // Standard mode: add prompt hash for dedup detection
  if (config.level === "standard" || config.level === "relaxed") {
    const promptText = String(raw.prompt_text ?? raw.request_preview ?? "");
    if (promptText) {
      sanitized.prompt_hash = hashText(promptText);
    }
  }

  return sanitized;
}

/** Redact model name to a generic tier label */
function redactModelName(model: string): string {
  const lower = model.toLowerCase();
  if (lower.includes("gpt-4") || lower.includes("opus") || lower.includes("gemini-pro"))
    return "frontier-model";
  if (lower.includes("gpt-3.5") || lower.includes("haiku") || lower.includes("flash"))
    return "budget-model";
  if (lower.includes("sonnet") || lower.includes("mini"))
    return "mid-model";
  return "unknown-model";
}

function safeNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Verify that a sanitized event contains NO sensitive data.
 * Throws if any forbidden field is found. Use in tests.
 */
export function assertNoSensitiveData(event: Record<string, unknown>): void {
  const allForbidden = [...ALWAYS_STRIP, ...TEXT_FIELDS];
  for (const field of allForbidden) {
    if (field in event && event[field]) {
      throw new Error(`Sensitive field "${field}" found in sanitized event`);
    }
  }
  // Check for anything that looks like an API key
  const json = JSON.stringify(event);
  if (/sk-[a-zA-Z0-9]{20,}/.test(json)) {
    throw new Error("OpenAI API key pattern detected in sanitized event");
  }
  if (/anthropic-[a-zA-Z0-9]{20,}/.test(json)) {
    throw new Error("Anthropic API key pattern detected in sanitized event");
  }
}
