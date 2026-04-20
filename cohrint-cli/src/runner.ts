import { spawn } from "child_process";
import { bus } from "./event-bus.js";
import { createSpinner } from "./ui.js";
import type { SpawnArgs } from "./agents/registry.js";
import { parseIntBounded } from "./sanitize.js";

const MAX_OUTPUT_BYTES = 5 * 1024 * 1024;
const TOOL_BULLET = "⏺";
const RESULT_PREFIX = "⎿";

// Strip terminal control chars from agent output before writing to stdout.
// Preserves \t \n \r but blocks ESC (\x1b), which prevents a compromised
// or prompt-injected agent from emitting CSI color bombs, OSC 8 fake
// hyperlinks, or — most importantly — OSC 52 clipboard writes
// (\x1b]52;c;<base64>\x07) that many modern terminal emulators honor.
// Also strips DEL, BS, NUL, and C1 control chars.
const CONTROL_STRIP_RX = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g;
function sanitizeDisplay(s: string): string {
  return s.replace(CONTROL_STRIP_RX, "");
}

function formatToolInput(name: string, input: Record<string, unknown>): string {
  const MAX = 70;
  const s = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));
  let preview: string;
  switch (name) {
    case "Bash":
      preview = s(input["command"] ?? "")
        .replace(/\s+/g, " ")
        .trim();
      break;
    case "Write":
    case "Read":
    case "Edit":
    case "MultiEdit":
      preview = s(input["file_path"] ?? "");
      break;
    case "Grep":
      preview =
        s(input["pattern"] ?? "") + (input["path"] ? ` in ${s(input["path"])}` : "");
      break;
    case "Glob":
      preview = s(input["pattern"] ?? "");
      break;
    case "Agent":
      preview = s(input["description"] ?? input["prompt"] ?? "");
      break;
    case "WebFetch":
      preview = s(input["url"] ?? "");
      break;
    case "WebSearch":
      preview = s(input["query"] ?? "");
      break;
    default: {
      const first = Object.entries(input)[0];
      preview = first ? `${first[0]}=${s(first[1])}` : "";
    }
  }
  return preview.length > MAX ? preview.slice(0, MAX - 1) + "…" : preview;
}

interface LineResult {
  display?: string;
  tokenText?: string;
  sessionId?: string;
  outputTokens?: number;
}

class ClaudeStreamRenderer {
  private pendingTools = new Map<string, string>(); // tool_use_id → tool name

  process(line: string): LineResult {
    if (!line.trim()) return {};
    try {
      const obj = JSON.parse(line) as Record<string, unknown>;

      if (obj["type"] === "content_block_delta") {
        const delta = obj["delta"] as Record<string, unknown> | undefined;
        if (delta?.["type"] === "text_delta") {
          const text = String(delta["text"] ?? "");
          if (text) return { display: text, tokenText: text };
        }
        return {};
      }

      if (obj["type"] === "content_block_start") {
        const block = obj["content_block"] as Record<string, unknown> | undefined;
        if (block?.["type"] === "tool_use") {
          const toolName = String(block["name"] ?? "Tool");
          const toolId = String(block["id"] ?? "");
          if (toolId) this.pendingTools.set(toolId, toolName);
          return { display: `\n${TOOL_BULLET} ${toolName}\n` };
        }
        return {};
      }

      if (obj["type"] === "message_delta") {
        const usage = obj["usage"] as Record<string, unknown> | undefined;
        const raw = usage?.["output_tokens"];
        // Agent JSON is untrusted — Infinity/NaN/negative would propagate
        // into cost math if any downstream caller picked this up.
        if (
          typeof raw === "number" &&
          Number.isFinite(raw) &&
          raw >= 0 &&
          raw <= 100_000_000
        ) {
          return { outputTokens: raw };
        }
        return {};
      }

      if (obj["type"] === "assistant") {
        const content = (obj["message"] as Record<string, unknown> | undefined)?.[
          "content"
        ] as unknown[] | undefined;
        if (!content?.length) return {};
        const displayParts: string[] = [];
        const tokenParts: string[] = [];
        for (const block of content) {
          const b = block as Record<string, unknown>;
          if (b["type"] === "text") {
            const t = String(b["text"] ?? "");
            if (t) {
              displayParts.push(t);
              tokenParts.push(t);
            }
          } else if (b["type"] === "tool_use") {
            const toolName = String(b["name"] ?? "Tool");
            const toolId = String(b["id"] ?? "");
            const input = (b["input"] ?? {}) as Record<string, unknown>;
            const preview = formatToolInput(toolName, input);
            displayParts.push(`\n${TOOL_BULLET} ${toolName}(${preview})\n`);
            if (toolId) this.pendingTools.set(toolId, toolName);
          }
        }
        const display = displayParts.join("");
        const tokenText = tokenParts.join("");
        return display ? { display, tokenText: tokenText || undefined } : {};
      }

      if (obj["type"] === "tool_result") {
        const toolId = String(obj["tool_use_id"] ?? "");
        this.pendingTools.delete(toolId);
        const raw = obj["content"];
        let resultText = "";
        if (typeof raw === "string") {
          resultText = raw;
        } else if (Array.isArray(raw)) {
          resultText = (raw as Record<string, unknown>[])
            .filter((b) => b["type"] === "text")
            .map((b) => String(b["text"] ?? ""))
            .join("");
        }
        if (!resultText.trim()) return {};
        const lines = resultText.split("\n");
        const MAX_RESULT_LINES = 10;
        const shown = lines.slice(0, MAX_RESULT_LINES);
        const overflow = lines.length - MAX_RESULT_LINES;
        const indented = shown
          .map((l, i) => (i === 0 ? `  ${RESULT_PREFIX}  ${l}` : `     ${l}`))
          .join("\n");
        const suffix = overflow > 0 ? `\n     … +${overflow} lines (ctrl+o to expand)` : "";
        return { display: `${indented}${suffix}\n` };
      }

      if (obj["type"] === "result" || obj["type"] === "system") {
        const sid = obj["session_id"];
        if (isValidSessionId(sid)) return { sessionId: sid as string };
        return {};
      }

      return {};
    } catch {
      return { display: line + "\n", tokenText: line + "\n" };
    }
  }
}

interface ParsedLine {
  text?: string;
  sessionId?: string;
}

function parseStreamLine(line: string): ParsedLine {
  if (!line.trim()) return {};
  try {
    const obj = JSON.parse(line) as Record<string, unknown>;
    if (obj["type"] === "assistant") {
      const msg = obj["message"] as Record<string, unknown> | undefined;
      const content = msg?.["content"] as Record<string, unknown>[] | undefined;
      const text =
        content
          ?.filter((c) => c["type"] === "text")
          .map((c) => c["text"])
          .join("") ?? "";
      return text ? { text } : {};
    }
    if (obj["type"] === "result" || obj["type"] === "system") {
      const sid = obj["session_id"];
      if (isValidSessionId(sid)) return { sessionId: sid as string };
      return {};
    }
    return {};
  } catch {
    return { text: line + "\n" };
  }
}

const DEFAULT_TIMEOUT_MS = parseIntBounded(
  process.env.VANTAGE_TIMEOUT,
  300_000,
  1_000,
  24 * 60 * 60 * 1000,
);

type ActiveChild = ReturnType<typeof spawn>;
let _activeChild: ActiveChild | null = null;
const _cancelHooks = new Set<() => void>();

function signalChildTree(c: ActiveChild, sig: NodeJS.Signals): void {
  if (!c.pid) return;
  let signalled = false;
  if (process.platform !== "win32") {
    try { process.kill(-c.pid, sig); signalled = true; } catch {}
  }
  if (!signalled) {
    try { c.kill(sig); } catch {}
  }
}

function registerCancelHook(fn: () => void): () => void {
  _cancelHooks.add(fn);
  return () => {
    _cancelHooks.delete(fn);
  };
}

export function cancelActiveAgent(): boolean {
  const c = _activeChild;
  const hadWork = !!c || _cancelHooks.size > 0;
  if (c && !c.killed && c.exitCode === null) {
    try {
      signalChildTree(c, "SIGINT");
      const sigterm = setTimeout(() => {
        if (!c.killed && c.exitCode === null) signalChildTree(c, "SIGTERM");
      }, 400);
      const sigkill = setTimeout(() => {
        if (!c.killed && c.exitCode === null) signalChildTree(c, "SIGKILL");
      }, 1200);
      sigterm.unref?.();
      sigkill.unref?.();
    } catch {}
  }
  // Fire cancel hooks BEFORE clearing — each hook stops its spinner and
  // resolves its promise synchronously so the REPL unblocks even if the
  // child takes a while to actually die.
  const hooks = [..._cancelHooks];
  _cancelHooks.clear();
  for (const h of hooks) {
    try { h(); } catch {}
  }
  _activeChild = null;
  return hadWork;
}

export function hasActiveAgent(): boolean {
  const c = _activeChild;
  return !!((c && !c.killed && c.exitCode === null) || _cancelHooks.size > 0);
}
const BLOCKED_ENV = new Set([
  "LD_PRELOAD",
  "LD_LIBRARY_PATH",
  "LD_AUDIT",
  "DYLD_INSERT_LIBRARIES",
  "DYLD_LIBRARY_PATH",
  "DYLD_FALLBACK_LIBRARY_PATH",
  "DYLD_FRAMEWORK_PATH",
  "PYTHONPATH",
  "NODE_OPTIONS",
]);

function _isBlockedEnv(name: string): boolean {
  return BLOCKED_ENV.has(name.toUpperCase());
}
const SAFE_PASS_ENV = new Set([
  "PATH",
  "HOME",
  "SHELL",
  "TERM",
  "LANG",
  "COLORTERM",
  "TERM_PROGRAM",
  "USER",
  "LOGNAME",
  "PWD",
  "TMPDIR",
  "TMP",
  "TEMP",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "XDG_CACHE_HOME",
  "XDG_RUNTIME_DIR",
  "LC_ALL",
  "LC_CTYPE",
  "LC_MESSAGES",
  "TZ",
  "SSH_AUTH_SOCK",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_AUTH_TOKEN",
  "CLAUDE_CODE_OAUTH_TOKEN",
  "OPENAI_API_KEY",
  "OPENAI_API_BASE",
  "GOOGLE_API_KEY",
  "GEMINI_API_KEY",
  "NODE_EXTRA_CA_CERTS",
  "HTTPS_PROXY",
  "HTTP_PROXY",
  "NO_PROXY",
]);

function buildSafeEnv(extra?: Record<string, string>): Record<string, string> {
  // VANTAGE_PASS_ENV is a comma-separated list of additional env var names to
  // forward beyond the SAFE_PASS_ENV defaults. BLOCKED_ENV vars are stripped
  // regardless (they can be used for code injection via dynamic linkers).
  const extraAllowed = new Set(
    (process.env.VANTAGE_PASS_ENV ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter((k) => k.length > 0 && !_isBlockedEnv(k))
  );
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue; // strip undefined values — cast-safe
    if (_isBlockedEnv(k)) continue;
    if (SAFE_PASS_ENV.has(k) || extraAllowed.has(k)) {
      env[k] = v;
    }
  }
  return { ...env, ...extra };
}

export function isValidSessionId(id: unknown): boolean {
  return (
    typeof id === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
  );
}

// Agent stdout is untrusted. total_cost_usd from a compromised/hostile agent
// could arrive as Infinity, NaN, or 1e308 — which would poison session totals
// and get shipped to the telemetry API. Bound to a sane range.
const MAX_PLAUSIBLE_COST_USD = 1_000_000;
function parseFiniteCost(v: unknown): number | undefined {
  if (typeof v !== "number") return undefined;
  if (!Number.isFinite(v)) return undefined;
  if (v < 0 || v > MAX_PLAUSIBLE_COST_USD) return undefined;
  return v;
}

export interface PermissionDenial {
  toolName: string;
  toolInput: Record<string, unknown>;
}

export interface RunResult {
  exitCode: number;
  stdout: string;
  durationMs: number;
  sessionId?: string;
  costUsd?: number;
  permissionDenials: PermissionDenial[];
  staleSession?: boolean;
  notLoggedIn?: boolean;
}

const NOT_LOGGED_IN_RE = /Not logged in|Please run \/login|Please run `\/login`/i;

export function runAgent(
  spawnArgs: SpawnArgs,
  agentName: string,
  timeoutMs = DEFAULT_TIMEOUT_MS
): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const chunks: Buffer[] = [];
    let totalBytes = 0;
    let timedOut = false;
    let capturedSessionId: string | undefined;
    let staleSessionDetected = false;
    let notLoggedInDetected = false;
    let lineBuffer = "";
    let child: ReturnType<typeof spawn>;

    try {
      const stdinMode = process.stdin.isTTY ? "ignore" : "pipe";
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: [stdinMode, "pipe", "pipe"],
        env: buildSafeEnv(spawnArgs.env),
        detached: process.platform !== "win32",
      });
      _activeChild = child;
      if (!process.stdin.isTTY) {
        if (process.stdin.readableEnded || process.stdin.destroyed) {
          child.stdin?.end();
        } else {
          process.stdin.pipe(child.stdin!, { end: false });
          process.stdin.once("end", () => {
            child.stdin?.end();
          });
        }
      }
      child.stderr?.on("data", (chunk: Buffer) => {
        const text = chunk.toString("utf-8");
        if (text.includes("No conversation found with session ID")) {
          staleSessionDetected = true;
          return;
        }
        if (NOT_LOGGED_IN_RE.test(text)) {
          notLoggedInDetected = true;
          return;
        }
        // A prompt-injected or compromised agent can emit OSC/CSI escapes on
        // stderr just as easily as on stdout. Mirror the stdout scrubbing
        // (sanitizeDisplay) so the terminal never sees attacker-controlled
        // control sequences (OSC 52 clipboard-write, OSC 8 fake hyperlinks, …).
        process.stderr.write(sanitizeDisplay(text));
      });
    } catch (err) {
      _activeChild = null;
      const msg = err instanceof Error ? err.message : String(err);
      reject(new Error(`Failed to start '${spawnArgs.command}': ${msg}`));
      return;
    }

    const spinner = createSpinner("Thinking");
    let spinnerStopped = false;
    const stopSpinner = () => {
      if (!spinnerStopped) {
        spinnerStopped = true;
        spinner?.stop();
      }
    };

    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
      stopSpinner();
      process.stderr.write(
        `\n  ⏱ Agent timed out after ${Math.round(timeoutMs / 1000)}s — terminating\n`
      );
      child.kill("SIGTERM");
      setTimeout(() => {
        if (!child.killed) child.kill("SIGKILL");
      }, grace);
    }, timeoutMs);

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
      });
    }

    const renderer = new ClaudeStreamRenderer();
    let firstChunk = true;
    let truncationWarned = false;
    let capturedCostUsd: number | undefined;
    const capturedDenials: PermissionDenial[] = [];

    let settled = false;
    const unregisterCancel = registerCancelHook(() => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stopSpinner();
      try { child.stdout?.removeAllListeners("data"); } catch {}
      try { child.stderr?.removeAllListeners("data"); } catch {}
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(chunks).toString("utf-8");
      bus.emit("agent:completed", {
        agent: agentName,
        exitCode: 130,
        outputText: stdout,
        durationMs,
        sessionId: capturedSessionId ?? undefined,
      });
      resolve({
        exitCode: 130,
        stdout,
        durationMs,
        sessionId: capturedSessionId,
        costUsd: capturedCostUsd,
        permissionDenials: capturedDenials,
        staleSession: staleSessionDetected || undefined,
        notLoggedIn: notLoggedInDetected || undefined,
      });
    });

    function flushLine(line: string) {
      if (NOT_LOGGED_IN_RE.test(line)) {
        notLoggedInDetected = true;
        return;
      }
      const { display, tokenText, sessionId } = renderer.process(line);
      if (sessionId) capturedSessionId = sessionId;

      try {
        const obj = JSON.parse(line) as Record<string, unknown>;
        if (obj["type"] === "result") {
          const cost = parseFiniteCost(obj["total_cost_usd"]);
          if (cost !== undefined) capturedCostUsd = cost;
          const denials = obj["permission_denials"];
          if (Array.isArray(denials)) {
            for (const d of denials as Record<string, unknown>[]) {
              capturedDenials.push({
                toolName: String(d["tool_name"] ?? "unknown"),
                toolInput: (d["tool_input"] ?? {}) as Record<string, unknown>,
              });
            }
          }
        }
      } catch {}

      if (!display) return;
      if (firstChunk) {
        stopSpinner();
        firstChunk = false;
      }
      if (tokenText) {
        const tbuf = Buffer.from(tokenText);
        totalBytes += tbuf.length;
        if (totalBytes <= MAX_OUTPUT_BYTES) chunks.push(tbuf);
      }
      if (totalBytes <= MAX_OUTPUT_BYTES) {
        const safe = sanitizeDisplay(display);
        const ok = process.stdout.write(safe);
        if (!ok) {
          child.stdout?.pause();
          process.stdout.once("drain", () => child.stdout?.resume());
        }
      } else if (!truncationWarned) {
        truncationWarned = true;
        console.warn(
          `[vantage] Output truncated at ${Math.round(MAX_OUTPUT_BYTES / 1024 / 1024)}MB limit`
        );
      }
    }

    child.stdout?.on("data", (chunk: Buffer) => {
      lineBuffer += chunk.toString("utf-8");
      if (lineBuffer.length > MAX_OUTPUT_BYTES) {
        flushLine(lineBuffer.slice(0, MAX_OUTPUT_BYTES));
        lineBuffer = "";
        return;
      }
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    child.on("error", (err: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      stopSpinner();
      if (_activeChild === child) _activeChild = null;
      unregisterCancel();
      if (settled) return;
      settled = true;
      if (err.code === "ENOENT") {
        reject(
          new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`)
        );
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code: number | null) => {
      clearTimeout(timer);
      stopSpinner();
      if (_activeChild === child) _activeChild = null;
      unregisterCancel();
      if (settled) return;
      settled = true;
      if (lineBuffer.trim()) flushLine(lineBuffer);
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(chunks).toString("utf-8");
      const exitCode = code ?? 1;

      bus.emit("agent:completed", {
        agent: agentName,
        exitCode,
        outputText: stdout,
        durationMs,
        sessionId: capturedSessionId ?? undefined,
      });

      if (timedOut) {
        reject(new Error(`Agent timed out after ${Math.round(timeoutMs / 1000)}s`));
      } else {
        resolve({
          exitCode,
          stdout,
          durationMs,
          sessionId: capturedSessionId,
          costUsd: capturedCostUsd,
          permissionDenials: capturedDenials,
          staleSession: staleSessionDetected || undefined,
          notLoggedIn: notLoggedInDetected || undefined,
        });
      }
    });
  });
}

export interface BufferedRunResult {
  exitCode: number;
  stdout: string;
  durationMs: number;
  sessionId?: string;
  costUsd?: number;
  permissionDenials: PermissionDenial[];
  staleSession?: boolean;
  notLoggedIn?: boolean;
}

export function runAgentBuffered(
  spawnArgs: SpawnArgs,
  agentName: string,
  timeoutMs = DEFAULT_TIMEOUT_MS
): Promise<BufferedRunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const textChunks: Buffer[] = [];
    let textBytes = 0;
    let timedOut = false;
    let capturedSessionId: string | undefined;
    let lineBuffer = "";
    let child: ReturnType<typeof spawn>;

    try {
      const stdinMode = process.stdin.isTTY ? "ignore" : "pipe";
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: [stdinMode, "pipe", "pipe"],
        env: buildSafeEnv(spawnArgs.env),
        detached: process.platform !== "win32",
      });
      _activeChild = child;
      if (!process.stdin.isTTY) {
        if (process.stdin.readableEnded || process.stdin.destroyed) {
          child.stdin?.end();
        } else {
          process.stdin.pipe(child.stdin!, { end: false });
          process.stdin.once("end", () => {
            child.stdin?.end();
          });
        }
      }
    } catch (err) {
      _activeChild = null;
      const msg = err instanceof Error ? err.message : String(err);
      reject(new Error(`Failed to start '${spawnArgs.command}': ${msg}`));
      return;
    }

    const spinner = createSpinner(`Running ${agentName}...`);
    let spinnerStopped = false;
    const stopSpinner = () => {
      if (!spinnerStopped) {
        spinnerStopped = true;
        spinner?.stop();
      }
    };

    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
      stopSpinner();
      process.stderr.write(
        `\n  ⏱ Agent timed out after ${Math.round(timeoutMs / 1000)}s — terminating\n`
      );
      child.kill("SIGTERM");
      setTimeout(() => {
        if (!child.killed) child.kill("SIGKILL");
      }, grace);
    }, timeoutMs);

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
      });
    }

    let truncationWarned = false;
    let capturedCostUsd: number | undefined;
    let staleSessionDetectedBuf = false;
    let notLoggedInDetectedBuf = false;

    let settled = false;
    const unregisterCancel = registerCancelHook(() => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stopSpinner();
      try { child.stdout?.removeAllListeners("data"); } catch {}
      try { child.stderr?.removeAllListeners("data"); } catch {}
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(textChunks).toString("utf-8");
      bus.emit("agent:completed", {
        agent: agentName,
        exitCode: 130,
        outputText: stdout,
        durationMs,
        sessionId: capturedSessionId ?? undefined,
      });
      resolve({
        exitCode: 130,
        stdout,
        durationMs,
        sessionId: capturedSessionId,
        costUsd: capturedCostUsd,
        permissionDenials: [],
        staleSession: staleSessionDetectedBuf || undefined,
        notLoggedIn: notLoggedInDetectedBuf || undefined,
      });
    });

    function flushLine(line: string) {
      if (NOT_LOGGED_IN_RE.test(line)) {
        notLoggedInDetectedBuf = true;
        return;
      }
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      // Also capture cost from the result line (mirrors runAgent behaviour).
      if (line.trim()) {
        try {
          const obj = JSON.parse(line) as Record<string, unknown>;
          if (obj["type"] === "result") {
            const cost = parseFiniteCost(obj["total_cost_usd"]);
            if (cost !== undefined) capturedCostUsd = cost;
          }
        } catch {}
      }
      if (!text) return;
      const buf = Buffer.from(sanitizeDisplay(text));
      textBytes += buf.length;
      if (textBytes <= MAX_OUTPUT_BYTES) {
        textChunks.push(buf);
      } else if (!truncationWarned) {
        truncationWarned = true;
        console.warn(
          `[vantage] Output truncated at ${Math.round(MAX_OUTPUT_BYTES / 1024 / 1024)}MB limit`
        );
      }
    }

    child.stdout?.on("data", (chunk: Buffer) => {
      lineBuffer += chunk.toString("utf-8");
      if (lineBuffer.length > MAX_OUTPUT_BYTES) {
        flushLine(lineBuffer.slice(0, MAX_OUTPUT_BYTES));
        lineBuffer = "";
        return;
      }
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      const text = chunk.toString("utf-8");
      if (text.includes("No conversation found with session ID")) staleSessionDetectedBuf = true;
      if (NOT_LOGGED_IN_RE.test(text)) notLoggedInDetectedBuf = true;
    });

    child.on("error", (err: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      stopSpinner();
      if (_activeChild === child) _activeChild = null;
      unregisterCancel();
      if (settled) return;
      settled = true;
      if (err.code === "ENOENT") {
        reject(
          new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`)
        );
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code: number | null) => {
      clearTimeout(timer);
      stopSpinner();
      if (_activeChild === child) _activeChild = null;
      unregisterCancel();
      if (settled) return;
      settled = true;
      if (lineBuffer.trim()) flushLine(lineBuffer);
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(textChunks).toString("utf-8");
      const exitCode = code ?? 1;

      bus.emit("agent:completed", {
        agent: agentName,
        exitCode,
        outputText: stdout,
        durationMs,
        sessionId: capturedSessionId ?? undefined,
      });

      if (timedOut) {
        reject(new Error(`Agent timed out after ${Math.round(timeoutMs / 1000)}s`));
      } else {
        resolve({
          exitCode,
          stdout,
          durationMs,
          sessionId: capturedSessionId,
          costUsd: capturedCostUsd,
          permissionDenials: [],
          staleSession: staleSessionDetectedBuf || undefined,
          notLoggedIn: notLoggedInDetectedBuf || undefined,
        });
      }
    });
  });
}
