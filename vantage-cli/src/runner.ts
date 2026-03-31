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
    if (obj["type"] === "result") {
      return { sessionId: obj["session_id"] as string | undefined };
    }
    // system/init/tool lines — suppress from display
    return {};
  } catch {
    // Not JSON — display as-is (non-Claude agents or plain text output)
    return { text: line + "\n" };
  }
}
const DEFAULT_TIMEOUT_MS = 300_000; // 5 minute timeout

/** Env vars that could be used to inject code into child processes */
const BLOCKED_ENV = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'PYTHONPATH', 'NODE_OPTIONS'];
const safeEnv = Object.fromEntries(
  Object.entries(process.env).filter(([k]) => !BLOCKED_ENV.includes(k))
);

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
        stdio: ["ignore", "pipe", "pipe"],
        env: { ...safeEnv, ...(spawnArgs.env ?? {}) },
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      reject(new Error(`Failed to start '${spawnArgs.command}': ${msg}`));
      return;
    }

    const spinner = createSpinner("Thinking");

    // Timeout guard — kill process if it hangs (grace = 10% of timeout, max 10s)
    const grace = Math.min(Math.ceil(timeoutMs * 0.1), 10000);
    const timer = setTimeout(() => {
      timedOut = true;
      spinner.stop();
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

    function flushLine(line: string) {
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      if (!text) return;
      if (firstChunk) {
        spinner.stop();
        firstChunk = false;
      }
      const buf = Buffer.from(text);
      totalBytes += buf.length;
      if (totalBytes <= MAX_OUTPUT_BYTES) chunks.push(buf);
      const ok = process.stdout.write(buf);
      if (!ok) {
        child.stdout?.pause();
        process.stdout.once("drain", () => child.stdout?.resume());
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
      spinner.stop();
      if ((err as NodeJS.ErrnoException).code === "ENOENT") {
        reject(new Error(`'${spawnArgs.command}' not found. Install it or check your PATH.`));
      } else {
        reject(new Error(`Agent process error: ${err.message}`));
      }
    });

    child.on("close", (code) => {
      clearTimeout(timer);
      spinner.stop();
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
        stdio: ["ignore", "pipe", "pipe"],
        env: { ...safeEnv, ...(spawnArgs.env ?? {}) },
      });
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

    function flushLine(line: string) {
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      if (!text) return;
      const buf = Buffer.from(text);
      textBytes += buf.length;
      if (textBytes <= MAX_OUTPUT_BYTES) textChunks.push(buf);
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
