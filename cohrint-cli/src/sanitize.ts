import { basename, isAbsolute } from "path";
import type { AgentConfig, VantageConfig } from "./config.js";

const VALID_PERMISSION_MODES = new Set([
  "default",
  "acceptEdits",
  "bypassPermissions",
  "plan",
]);

const MAX_ARGV_ITEMS = 64;
const MAX_ARGV_LEN = 4096;
const MAX_SYSTEM_PROMPT = 8192;
const MODEL_RX = /^[A-Za-z0-9._:\-]{1,80}$/;
// No whitespace — prevents smuggling flag-like fragments ("Bash --foo") when
// tool names get joined with "," and passed via --allowedTools.
const ALLOWED_TOOL_RX = /^[A-Za-z_][A-Za-z0-9_():,*/\-.]{0,79}$/;

function _warn(msg: string): void {
  // Strict "1" — any truthy value (including "0" and "false") would otherwise
  // silence all sanitization warnings, which an attacker with env control
  // could use to hide evidence of config tampering.
  if (process.env.VANTAGE_SANITIZE_SILENT === "1") return;
  process.stderr.write(`[vantage] config: ${msg}\n`);
}

export function sanitizeAgentCommand(
  command: string | undefined,
  expectedBinary: string
): string {
  if (!command) return expectedBinary;
  const c = String(command);
  if (c === expectedBinary) return c;
  if (isAbsolute(c) && basename(c) === expectedBinary) return c;
  _warn(
    `ignoring suspicious command override "${c}" for agent ${expectedBinary} — falling back to "${expectedBinary}"`
  );
  return expectedBinary;
}

function _sanitizeArgv(items: unknown, label: string): string[] {
  if (!Array.isArray(items)) return [];
  const out: string[] = [];
  for (const raw of items) {
    if (typeof raw !== "string") continue;
    if (raw.length > MAX_ARGV_LEN) {
      _warn(`${label} entry too long (${raw.length} bytes) — dropped`);
      continue;
    }
    out.push(raw);
    if (out.length >= MAX_ARGV_ITEMS) {
      _warn(`${label} capped at ${MAX_ARGV_ITEMS} items`);
      break;
    }
  }
  return out;
}

// Defense-in-depth: every agent adapter's buildCommand/buildContinueCommand
// must wrap caller-provided `config.args` / `config.extraFlags` with this
// before spreading into spawn argv. Even though `loadConfig` already runs
// `sanitizeConfig`, the adapters must not trust their AgentConfig input — a
// future caller could assemble one inline.
export function sanitizeAgentArgs(items: unknown, label = "agent.args"): string[] {
  return _sanitizeArgv(items, label);
}

export function sanitizeAgentConfig(raw: AgentConfig | undefined): AgentConfig | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const out: AgentConfig = {};
  if (raw.command !== undefined) out.command = String(raw.command);
  if (raw.args !== undefined) out.args = _sanitizeArgv(raw.args, "agent.args");
  if (raw.extraFlags !== undefined)
    out.extraFlags = _sanitizeArgv(raw.extraFlags, "agent.extraFlags");
  if (raw.permissionMode !== undefined) {
    const pm = String(raw.permissionMode);
    if (VALID_PERMISSION_MODES.has(pm)) out.permissionMode = pm;
    else _warn(`invalid permissionMode "${pm}" — ignored`);
  }
  if (raw.allowedTools !== undefined) {
    out.allowedTools = Array.isArray(raw.allowedTools)
      ? raw.allowedTools.filter((t): t is string => {
          if (typeof t !== "string") return false;
          if (!ALLOWED_TOOL_RX.test(t)) {
            _warn(`rejecting allowedTools entry "${t}" (must match ${ALLOWED_TOOL_RX})`);
            return false;
          }
          return true;
        })
      : [];
  }
  return out;
}

const DANGEROUS_KEYS = new Set(["__proto__", "constructor", "prototype"]);

function _localhostHttpAllowed(): boolean {
  return process.env.VANTAGE_ALLOW_HTTP === "1";
}

export function sanitizeConfig(raw: VantageConfig): VantageConfig {
  const agents: Record<string, AgentConfig> = {};
  if (raw.agents && typeof raw.agents === "object") {
    for (const [name, cfg] of Object.entries(raw.agents)) {
      if (DANGEROUS_KEYS.has(name)) continue;
      const clean = sanitizeAgentConfig(cfg);
      if (clean) agents[name] = clean;
    }
  }
  const apiBase = String(raw.vantageApiBase || "");
  const isLocalhostHttp =
    /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/.test(apiBase);
  const validApiBase =
    apiBase === "" ||
    apiBase.startsWith("https://") ||
    (isLocalhostHttp && _localhostHttpAllowed());
  if (!validApiBase) {
    if (isLocalhostHttp) {
      _warn(
        `rejecting http://localhost vantageApiBase "${apiBase}" — set VANTAGE_ALLOW_HTTP=1 to opt into plaintext for local dev`
      );
    } else {
      _warn(`rejecting non-HTTPS vantageApiBase "${apiBase}" — falling back to default`);
    }
  }
  // Explicit allowlist — never blindly spread untrusted input. Unknown top-level
  // fields are dropped so a future-added sensitive field can't sneak through
  // unvalidated from a stale/malicious config.json.
  const out: VantageConfig = {
    defaultAgent:
      typeof raw.defaultAgent === "string" ? raw.defaultAgent : "claude",
    agents,
    vantageApiKey:
      typeof raw.vantageApiKey === "string" ? raw.vantageApiKey : "",
    vantageApiBase: validApiBase ? apiBase : "https://api.cohrint.com",
    privacy: typeof raw.privacy === "string" ? raw.privacy : "anonymized",
    optimization:
      raw.optimization && typeof raw.optimization === "object" && !Array.isArray(raw.optimization)
        ? { enabled: Boolean((raw.optimization as { enabled?: unknown }).enabled) }
        : { enabled: true },
    tracking:
      raw.tracking && typeof raw.tracking === "object" && !Array.isArray(raw.tracking)
        ? {
            enabled: Boolean((raw.tracking as { enabled?: unknown }).enabled),
            batchSize: parseIntBounded(
              String((raw.tracking as { batchSize?: unknown }).batchSize ?? ""),
              10,
              1,
              10_000
            ),
            flushInterval: parseIntBounded(
              String((raw.tracking as { flushInterval?: unknown }).flushInterval ?? ""),
              30_000,
              1_000,
              24 * 60 * 60 * 1000
            ),
          }
        : { enabled: true, batchSize: 10, flushInterval: 30_000 },
  };
  if (typeof raw.debug === "boolean") out.debug = raw.debug;
  return out;
}

export function sanitizeModelFlag(v: string | undefined): string | undefined {
  if (!v) return undefined;
  if (!MODEL_RX.test(v)) {
    _warn(`--model value rejected (must match ${MODEL_RX.source})`);
    return undefined;
  }
  return v;
}

export function sanitizeSystemFlag(v: string | undefined): string | undefined {
  if (!v) return undefined;
  if (v.startsWith("-")) {
    _warn(`--system value rejected (must not start with '-')`);
    return undefined;
  }
  if (v.length > MAX_SYSTEM_PROMPT) {
    _warn(`--system value truncated from ${v.length} to ${MAX_SYSTEM_PROMPT} bytes`);
    return v.slice(0, MAX_SYSTEM_PROMPT);
  }
  return v;
}

/**
 * Parse an env/flag integer with bounds. Returns `defaultValue` on NaN,
 * non-finite, or out-of-range input. Accepts 0 (unlike `Number(v) || d`).
 */
export function parseIntBounded(
  v: string | undefined,
  defaultValue: number,
  min = 0,
  max = Number.MAX_SAFE_INTEGER
): number {
  if (v === undefined || v === "") return defaultValue;
  const n = parseInt(String(v), 10);
  if (!Number.isFinite(n) || n < min || n > max) return defaultValue;
  return n;
}

/**
 * Read and parse a JSON response body with a size cap. Node's fetch buffers
 * the whole body before JSON.parse, so a compromised or hijacked API endpoint
 * could OOM the CLI by serving a multi-gigabyte blob. Returns null on oversize,
 * non-JSON, or fetch failure — callers should treat null as "no data".
 */
const MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024;
export async function safeFetchJson(
  res: Response,
  maxBytes: number = MAX_JSON_RESPONSE_BYTES
): Promise<unknown | null> {
  try {
    const buf = await res.arrayBuffer();
    if (buf.byteLength > maxBytes) {
      _warn(
        `API response too large (${buf.byteLength} bytes > ${maxBytes}) — discarding`
      );
      return null;
    }
    if (buf.byteLength === 0) return null;
    return JSON.parse(Buffer.from(buf).toString("utf-8"));
  } catch {
    return null;
  }
}

export function assertHttpsApiBase(base: string): boolean {
  if (!base) return false;
  if (base.startsWith("https://")) return true;
  if (
    /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/.test(base) &&
    _localhostHttpAllowed()
  ) {
    return true;
  }
  _warn(`refusing to send API key to non-HTTPS URL "${base}"`);
  return false;
}
