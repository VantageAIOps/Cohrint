import { spawn } from "node:child_process";
import type { SpawnArgs } from "./agents/types.js";
import { bus } from "./event-bus.js";
import { createSpinner } from "./ui.js";

export interface RunResult {
  exitCode: number;
  stdout: string;
  durationMs: number;
  sessionId?: string;
}

const MAX_OUTPUT_BYTES = 5 * 1024 * 1024; // 5MB output cap

// ⏺ bullet matching Claude terminal (U+23FA) + ⎿ result prefix (U+23BF)
const TOOL_BULLET = "\u23FA";
const RESULT_PREFIX = "\u23BF";

/** Format a tool's input object into a short preview string (max 70 chars). */
function formatToolInput(name: string, input: Record<string, unknown>): string {
  const MAX = 70;
  const s = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

  let preview: string;
  switch (name) {
    case "Bash":
      preview = s(input["command"] ?? "").replace(/\s+/g, " ").trim();
      break;
    case "Write": case "Read": case "Edit": case "MultiEdit":
      preview = s(input["file_path"] ?? "");
      break;
    case "Grep":
      preview = s(input["pattern"] ?? "") +
        (input["path"] ? ` in ${s(input["path"])}` : "");
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

  return preview.length > MAX ? preview.slice(0, MAX - 1) + "\u2026" : preview;
}

/**
 * Stateful renderer for Claude Code's stream-json format.
 * Produces terminal output that matches Claude's native display:
 *   ⏺ Bash(command...)
 *     ⎿  output line 1
 *        output line 2
 *        … +N lines
 *
 * Returns { display, tokenText, sessionId } where:
 *   display   — what gets written to the terminal
 *   tokenText — just the assistant text content (for token counting)
 */
export class ClaudeStreamRenderer {
  private pendingTools = new Map<string, string>(); // tool_use_id → tool name

  process(line: string): { display?: string; tokenText?: string; sessionId?: string } {
    if (!line.trim()) return {};
    try {
      const obj = JSON.parse(line) as Record<string, unknown>;

      // ── assistant turn: text + tool_use blocks ──────────────────────────────
      if (obj["type"] === "assistant") {
        const content = (
          (obj["message"] as Record<string, unknown> | undefined)?.["content"]
        ) as Array<Record<string, unknown>> | undefined;
        if (!content?.length) return {};

        const displayParts: string[] = [];
        const tokenParts: string[] = [];

        for (const block of content) {
          if (block["type"] === "text") {
            const t = String(block["text"] ?? "");
            if (t) { displayParts.push(t); tokenParts.push(t); }
          } else if (block["type"] === "tool_use") {
            const toolName = String(block["name"] ?? "Tool");
            const toolId   = String(block["id"]   ?? "");
            const input    = (block["input"] as Record<string, unknown>) ?? {};
            const preview  = formatToolInput(toolName, input);
            displayParts.push(`\n${TOOL_BULLET} ${toolName}(${preview})\n`);
            if (toolId) this.pendingTools.set(toolId, toolName);
          }
        }

        const display   = displayParts.join("");
        const tokenText = tokenParts.join("");
        return display ? { display, tokenText: tokenText || undefined } : {};
      }

      // ── tool result ─────────────────────────────────────────────────────────
      if (obj["type"] === "tool_result") {
        const toolId = String(obj["tool_use_id"] ?? "");
        this.pendingTools.delete(toolId);

        const raw = obj["content"];
        let resultText = "";
        if (typeof raw === "string") {
          resultText = raw;
        } else if (Array.isArray(raw)) {
          resultText = (raw as Array<Record<string, unknown>>)
            .filter(b => b["type"] === "text")
            .map(b => String(b["text"] ?? ""))
            .join("");
        }

        if (!resultText.trim()) return {};

        const lines = resultText.split("\n");
        const MAX_RESULT_LINES = 10;
        const shown    = lines.slice(0, MAX_RESULT_LINES);
        const overflow = lines.length - MAX_RESULT_LINES;

        const indented = shown
          .map((l, i) => (i === 0 ? `  ${RESULT_PREFIX}  ${l}` : `     ${l}`))
          .join("\n");
        const suffix = overflow > 0
          ? `\n     \u2026 +${overflow} lines (ctrl+o to expand)` : "";

        return { display: `${indented}${suffix}\n` };
      }

      // ── session ID (system init + result events) ────────────────────────────
      if (obj["type"] === "result" || obj["type"] === "system") {
        const sid = obj["session_id"] as string | undefined;
        if (isValidSessionId(sid)) return { sessionId: sid };
        return {};
      }

      return {};
    } catch {
      // Non-JSON line (non-Claude agents) — pass through as-is
      return { display: line + "\n", tokenText: line + "\n" };
    }
  }
}

/**
 * Stateless parser for buffered mode — extracts text content and session ID only.
 * Used by runAgentBuffered where display formatting is not needed.
 */
function parseStreamLine(line: string): { text?: string; sessionId?: string } {
  if (!line.trim()) return {};
  try {
    const obj = JSON.parse(line) as Record<string, unknown>;
    if (obj["type"] === "assistant") {
      const msg = obj["message"] as Record<string, unknown> | undefined;
      const content = msg?.["content"] as Array<Record<string, unknown>> | undefined;
      const text = content
        ?.filter((c) => c["type"] === "text")
        .map((c) => c["text"] as string)
        .join("") ?? "";
      return text ? { text } : {};
    }
    if (obj["type"] === "result" || obj["type"] === "system") {
      const sid = obj["session_id"] as string | undefined;
      if (isValidSessionId(sid)) return { sessionId: sid };
      return {};
    }
    return {};
  } catch {
    return { text: line + "\n" };
  }
}
// Timeout: VANTAGE_TIMEOUT env var overrides default 5-minute limit
const DEFAULT_TIMEOUT_MS = Number(process.env.VANTAGE_TIMEOUT) || 300_000;

/** Env vars that could be used to inject code into child processes */
const BLOCKED_ENV = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'PYTHONPATH'];
// NODE_OPTIONS intentionally not blocked — legitimate for memory/debug config

/** Safe vars that VANTAGE_PASS_ENV is allowed to re-enable (prevents arbitrary env injection) */
const SAFE_PASS_ENV = new Set(["PATH", "HOME", "SHELL", "TERM", "LANG", "COLORTERM", "TERM_PROGRAM"]);

/**
 * Build a safe env by blocking injection vectors.
 * Callers can whitelist additional vars via VANTAGE_PASS_ENV (comma-separated),
 * but only vars present in SAFE_PASS_ENV are accepted to prevent arbitrary injection.
 */
function buildSafeEnv(extra?: Record<string, string>): Record<string, string> {
  const passEnv = (process.env.VANTAGE_PASS_ENV ?? "")
    .split(",")
    .map(s => s.trim())
    .filter(k => k && SAFE_PASS_ENV.has(k));
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([k]) => !BLOCKED_ENV.includes(k) || passEnv.includes(k))
  ) as Record<string, string>;
  return { ...env, ...(extra ?? {}) };
}

/** Validate that a string looks like a UUID (session IDs from Claude Code) */
function isValidSessionId(id: string | undefined): id is string {
  return typeof id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

/**
 * Spawn the agent process, streaming stdout/stderr to the terminal in real time.
 * Accumulates stdout for token counting after exit.
 */
export function runAgent(
  spawnArgs: SpawnArgs,
  agentName: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const chunks: Buffer[] = [];
    let totalBytes = 0;
    let timedOut = false;
    let capturedSessionId: string | undefined;
    let lineBuffer = "";

    let child: ReturnType<typeof spawn>;
    try {
      // stdin: "inherit" in TTY mode passes the real terminal fd to the child.
      //   This lets the agent show permission prompts and receive the user's
      //   y/n response directly — exactly like running the agent manually.
      // stdin: "pipe" in non-TTY (pipe) mode — the prompt is already passed via
      //   -p flag, so we feed whatever is left in stdin without closing it early.
      // stdout: always "pipe" so we can parse stream-json and relay formatted output.
      // stderr: "inherit" so native errors / warnings go straight to the terminal.
      const stdinMode = process.stdin.isTTY ? "inherit" : "pipe";
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: [stdinMode, "pipe", "inherit"],
        env: buildSafeEnv(spawnArgs.env),
      });
      if (!process.stdin.isTTY) {
        // If stdin was already consumed (e.g. readStdin() read it before this
        // call), the "end" event already fired and won't fire again.  Close the
        // child's stdin immediately so the agent doesn't wait for input it will
        // never receive (avoids the 3-second "no stdin data" warning from the
        // Claude CLI that pushes total runtime past COST_TIMEOUT_MS).
        if (process.stdin.readableEnded || process.stdin.destroyed) {
          child.stdin?.end();
        } else {
          process.stdin.pipe(child.stdin!, { end: false });
          process.stdin.once("end", () => { child.stdin?.end(); });
        }
      }
      // TTY mode: stdin is the terminal itself — no piping needed.
    } catch (err) {
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

    // Timeout guard — kill process if it hangs (grace = 10% of timeout, max 10s)
    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
      stopSpinner();
      process.stderr.write(`\n  ⏱ Agent timed out after ${Math.round(timeoutMs / 1000)}s — terminating\n`);
      child.kill("SIGTERM");
      setTimeout(() => { if (!child.killed) child.kill("SIGKILL"); }, grace);
    }, timeoutMs);

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    const renderer = new ClaudeStreamRenderer();
    let firstChunk = true;
    let truncationWarned = false;

    function flushLine(line: string) {
      const { display, tokenText, sessionId } = renderer.process(line);
      if (sessionId) capturedSessionId = sessionId;
      if (!display) return;
      if (firstChunk) {
        stopSpinner();
        firstChunk = false;
      }
      // Store only assistant text content for token counting (not tool formatting)
      if (tokenText) {
        const tbuf = Buffer.from(tokenText);
        totalBytes += tbuf.length;
        if (totalBytes <= MAX_OUTPUT_BYTES) chunks.push(tbuf);
      }
      // Always write the full display output (includes tool bullets + results)
      if (totalBytes <= MAX_OUTPUT_BYTES) {
        const ok = process.stdout.write(display);
        if (!ok) {
          child.stdout?.pause();
          process.stdout.once("drain", () => child.stdout?.resume());
        }
      } else if (!truncationWarned) {
        truncationWarned = true;
        console.warn(`[vantage] Output truncated at ${Math.round(MAX_OUTPUT_BYTES / 1024 / 1024)}MB limit`);
      }
    }

    child.stdout?.on("data", (chunk: Buffer) => {
      lineBuffer += chunk.toString("utf-8");
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    // stderr is inherited — no relay handler needed; permission prompts go directly to terminal

    child.on("error", (err) => {
      clearTimeout(timer);
      stopSpinner();
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`));
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      stopSpinner();
      // Flush any remaining buffered content
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
        resolve({ exitCode, stdout, durationMs, sessionId: capturedSessionId });
      }
    });
  });
}

/**
 * Same as runAgent but buffers all output instead of streaming.
 * Useful for /compare mode where we run multiple agents in parallel.
 */
export function runAgentBuffered(
  spawnArgs: SpawnArgs,
  agentName: string,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const textChunks: Buffer[] = [];
    let textBytes = 0;
    let timedOut = false;
    let capturedSessionId: string | undefined;
    let lineBuffer = "";

    let child: ReturnType<typeof spawn>;
    try {
      const stdinMode = process.stdin.isTTY ? "inherit" : "pipe";
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: [stdinMode, "pipe", "pipe"],
        env: buildSafeEnv(spawnArgs.env),
      });
      if (!process.stdin.isTTY) {
        if (process.stdin.readableEnded || process.stdin.destroyed) {
          child.stdin?.end();
        } else {
          process.stdin.pipe(child.stdin!, { end: false });
          process.stdin.once("end", () => { child.stdin?.end(); });
        }
      }
    } catch (err) {
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
    // Timeout guard — kill process if it hangs (grace = 10% of timeout, max 10s)
    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
      stopSpinner();
      process.stderr.write(`\n  ⏱ Agent timed out after ${Math.round(timeoutMs / 1000)}s — terminating\n`);
      child.kill("SIGTERM");
      setTimeout(() => { if (!child.killed) child.kill("SIGKILL"); }, grace);
    }, timeoutMs);

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    let truncationWarned = false;

    function flushLine(line: string) {
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      if (!text) return;
      const buf = Buffer.from(text);
      textBytes += buf.length;
      if (textBytes <= MAX_OUTPUT_BYTES) {
        textChunks.push(buf);
      } else if (!truncationWarned) {
        truncationWarned = true;
        console.warn(`[vantage] Output truncated at ${Math.round(MAX_OUTPUT_BYTES / 1024 / 1024)}MB limit`);
      }
    }

    child.stdout?.on("data", (chunk: Buffer) => {
      lineBuffer += chunk.toString("utf-8");
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      // Discard stderr in buffered mode (callers only use stdout)
    });

    child.on("error", (err) => {
      clearTimeout(timer);
      stopSpinner();
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`));
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      stopSpinner();
      // Flush any remaining buffered content
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
        resolve({ exitCode, stdout, durationMs, sessionId: capturedSessionId });
      }
    });
  });
}
