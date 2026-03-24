import { spawn } from "node:child_process";
import type { SpawnArgs } from "./agents/types.js";
import { bus } from "./event-bus.js";

export interface RunResult {
  exitCode: number;
  stdout: string;
  durationMs: number;
}

const MAX_OUTPUT_BYTES = 5 * 1024 * 1024; // 5MB output cap
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

    child.stdout?.on("data", (chunk: Buffer) => {
      totalBytes += chunk.length;
      if (totalBytes <= MAX_OUTPUT_BYTES) {
        chunks.push(chunk);
      }
      const ok = process.stdout.write(chunk);
      if (!ok) {
        child.stdout?.pause();
        process.stdout.once("drain", () => child.stdout?.resume());
      }
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(chunk);
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
        resolve({ exitCode, stdout, durationMs });
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
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let stdoutBytes = 0;
    let timedOut = false;

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

    child.stdout?.on("data", (chunk: Buffer) => {
      stdoutBytes += chunk.length;
      if (stdoutBytes <= MAX_OUTPUT_BYTES) {
        stdoutChunks.push(chunk);
      }
    });

    child.stderr?.on("data", (chunk: Buffer) => {
      stderrChunks.push(chunk);
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
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(stdoutChunks).toString("utf-8");
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
        resolve({ exitCode, stdout, durationMs });
      }
    });
  });
}
