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

/**
 * Parse a single stream-json line from Claude Code.
 * Returns the displayable text and/or session ID extracted from it.
 * Falls back to returning the raw line as text if it's not valid JSON.
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
    // Capture session_id from both the "system" (init, first event) and "result"
    // (last event) events. "system" is more reliable — it appears even on error exits.
    if (obj["type"] === "result" || obj["type"] === "system") {
      const sid = obj["session_id"] as string | undefined;
      if (isValidSessionId(sid)) return { sessionId: sid };
      return {};
    }
    // tool/other lines — suppress from display
    return {};
  } catch {
    // Not JSON — display as-is (non-Claude agents or plain text output)
    return { text: line + "\n" };
  }
}
// Timeout: VANTAGE_TIMEOUT env var overrides default 5-minute limit
const DEFAULT_TIMEOUT_MS = Number(process.env.VANTAGE_TIMEOUT) || 300_000;

/** Env vars that could be used to inject code into child processes */
const BLOCKED_ENV = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'PYTHONPATH', 'NODE_OPTIONS'];

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
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: ["pipe", "pipe", "pipe"],
        env: buildSafeEnv(spawnArgs.env),
      });
      // Only pipe stdin when data is actually being piped in (non-TTY).
      // In interactive TTY mode, closing stdin immediately prevents claude from
      // printing "Warning: no stdin data received in 3s" while waiting for input
      // that will never arrive.
      if (!process.stdin.isTTY) {
        process.stdin.pipe(child.stdin!);
      } else {
        child.stdin?.end();
      }
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

    let firstChunk = true;
    let truncationWarned = false;

    function flushLine(line: string) {
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      if (!text) return;
      if (firstChunk) {
        stopSpinner();
        firstChunk = false;
      }
      const buf = Buffer.from(text);
      totalBytes += buf.length;
      if (totalBytes <= MAX_OUTPUT_BYTES) {
        chunks.push(buf);
        const ok = process.stdout.write(buf);
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

    child.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(chunk);
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
      const stdout = Buffer.concat(chunks).toString("utf-8");
      const exitCode = code ?? 1;

      bus.emit("agent:completed", {
        agent: agentName,
        exitCode,
        outputText: stdout,
        durationMs,
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
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: ["pipe", "pipe", "pipe"],
        env: buildSafeEnv(spawnArgs.env),
      });
      // Pipe host stdin so buffered mode also supports stdin-based workflows
      process.stdin.pipe(child.stdin!);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      reject(new Error(`Failed to start '${spawnArgs.command}': ${msg}`));
      return;
    }

    // Timeout guard — kill process if it hangs (grace = 10% of timeout, max 10s)
    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
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
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`));
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code) => {
      clearTimeout(timer);
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
      });

      if (timedOut) {
        reject(new Error(`Agent timed out after ${Math.round(timeoutMs / 1000)}s`));
      } else {
        resolve({ exitCode, stdout, durationMs, sessionId: capturedSessionId });
      }
    });
  });
}
