import { spawn } from "child_process";
import { bus } from "./event-bus.js";
import { createSpinner } from "./ui.js";
import type { SpawnArgs } from "./agents/registry.js";

const MAX_OUTPUT_BYTES = 5 * 1024 * 1024;
const TOOL_BULLET = "⏺";
const RESULT_PREFIX = "⎿";

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
        const outputTokens =
          typeof usage?.["output_tokens"] === "number"
            ? (usage["output_tokens"] as number)
            : undefined;
        if (outputTokens !== undefined) return { outputTokens };
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

const DEFAULT_TIMEOUT_MS = Number(process.env.VANTAGE_TIMEOUT) || 300_000;
const BLOCKED_ENV = [
  "LD_PRELOAD",
  "LD_LIBRARY_PATH",
  "DYLD_INSERT_LIBRARIES",
  "PYTHONPATH",
];
const SAFE_PASS_ENV = new Set([
  "PATH",
  "HOME",
  "SHELL",
  "TERM",
  "LANG",
  "COLORTERM",
  "TERM_PROGRAM",
]);

function buildSafeEnv(extra?: Record<string, string>): Record<string, string> {
  // VANTAGE_PASS_ENV is a comma-separated list of additional env var names to
  // forward beyond the SAFE_PASS_ENV defaults. BLOCKED_ENV vars are stripped
  // regardless (they can be used for code injection via dynamic linkers).
  const extraAllowed = new Set(
    (process.env.VANTAGE_PASS_ENV ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter((k) => k.length > 0 && !BLOCKED_ENV.includes(k))
  );
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined) continue; // strip undefined values — cast-safe
    if (BLOCKED_ENV.includes(k)) continue;
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
}

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
    let lineBuffer = "";
    let child: ReturnType<typeof spawn>;

    try {
      const stdinMode = process.stdin.isTTY ? "inherit" : "pipe";
      child = spawn(spawnArgs.command, spawnArgs.args, {
        stdio: [stdinMode, "pipe", "inherit"],
        env: buildSafeEnv(spawnArgs.env),
      });
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
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    const renderer = new ClaudeStreamRenderer();
    let firstChunk = true;
    let truncationWarned = false;
    let capturedCostUsd: number | undefined;
    const capturedDenials: PermissionDenial[] = [];

    function flushLine(line: string) {
      const { display, tokenText, sessionId } = renderer.process(line);
      if (sessionId) capturedSessionId = sessionId;

      try {
        const obj = JSON.parse(line) as Record<string, unknown>;
        if (obj["type"] === "result") {
          if (typeof obj["total_cost_usd"] === "number")
            capturedCostUsd = obj["total_cost_usd"] as number;
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
        const ok = process.stdout.write(display);
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
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    child.on("error", (err: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      stopSpinner();
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
          process.stdin.once("end", () => {
            child.stdin?.end();
          });
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
        command: `${spawnArgs.command} ${spawnArgs.args.join(" ")}`,
      });
    }

    let truncationWarned = false;
    let capturedCostUsd: number | undefined;

    function flushLine(line: string) {
      const { text, sessionId } = parseStreamLine(line);
      if (sessionId) capturedSessionId = sessionId;
      // Also capture cost from the result line (mirrors runAgent behaviour).
      if (line.trim()) {
        try {
          const obj = JSON.parse(line) as Record<string, unknown>;
          if (obj["type"] === "result" && typeof obj["total_cost_usd"] === "number") {
            capturedCostUsd = obj["total_cost_usd"] as number;
          }
        } catch {}
      }
      if (!text) return;
      const buf = Buffer.from(text);
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
      const lines = lineBuffer.split("\n");
      lineBuffer = lines.pop() ?? "";
      for (const line of lines) flushLine(line);
    });

    child.stderr?.on("data", (_chunk: Buffer) => {});

    child.on("error", (err: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      stopSpinner();
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
        });
      }
    });
  });
}
