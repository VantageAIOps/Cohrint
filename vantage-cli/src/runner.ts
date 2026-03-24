import { spawn } from "node:child_process";
import type { SpawnArgs } from "./agents/types.js";
import { bus } from "./event-bus.js";

export interface RunResult {
  exitCode: number;
  stdout: string;
  durationMs: number;
}

/**
 * Spawn the agent process, streaming stdout/stderr to the terminal in real time.
 * Accumulates stdout for token counting after exit.
 */
export function runAgent(spawnArgs: SpawnArgs, agentName: string): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const chunks: Buffer[] = [];

    const child = spawn(spawnArgs.command, spawnArgs.args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ...(spawnArgs.env ?? {}) },
    });

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    child.stdout.on("data", (chunk: Buffer) => {
      chunks.push(chunk);
      process.stdout.write(chunk);
    });

    child.stderr.on("data", (chunk: Buffer) => {
      process.stderr.write(chunk);
    });

    child.on("error", (err) => {
      reject(err);
    });

    child.on("close", (code) => {
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(chunks).toString("utf-8");
      const exitCode = code ?? 1;

      bus.emit("agent:completed", {
        agent: agentName,
        exitCode,
        outputText: stdout,
        durationMs,
      });

      resolve({ exitCode, stdout, durationMs });
    });
  });
}

/**
 * Same as runAgent but buffers all output instead of streaming.
 * Useful for /compare mode where we run multiple agents in parallel.
 */
export function runAgentBuffered(spawnArgs: SpawnArgs, agentName: string): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    const child = spawn(spawnArgs.command, spawnArgs.args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env, ...(spawnArgs.env ?? {}) },
    });

    if (child.pid) {
      bus.emit("agent:started", {
        agent: agentName,
        pid: child.pid,
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutChunks.push(chunk);
    });

    child.stderr.on("data", (chunk: Buffer) => {
      stderrChunks.push(chunk);
    });

    child.on("error", (err) => {
      reject(err);
    });

    child.on("close", (code) => {
      const durationMs = Date.now() - start;
      const stdout = Buffer.concat(stdoutChunks).toString("utf-8");
      const exitCode = code ?? 1;

      bus.emit("agent:completed", {
        agent: agentName,
        exitCode,
        outputText: stdout,
        durationMs,
      });

      resolve({ exitCode, stdout, durationMs });
    });
  });
}
