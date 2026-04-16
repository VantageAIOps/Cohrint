/**
 * Amp Local File Scanner
 *
 * Path:   ~/.local/share/amp/threads/
 * Format: JSON files — one per conversation thread
 *
 * Each thread JSON contains messages with model and token usage.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { calculateCost } from "../pricing.js";
import type {
  ScannerPlugin,
  ScanOptions,
  ToolSession,
  ParsedMessage,
} from "./types.js";

// ── Helpers ──────────────────────────────────────────────────────────────────

function getThreadsDir(): string {
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "amp", "threads");
  }
  return join(homedir(), ".local", "share", "amp", "threads");
}

async function dirExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isDirectory();
  } catch {
    return false;
  }
}

function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.split(/\s+/).filter(Boolean).length * 1.33);
}

function inferProvider(model: string): string {
  if (model.startsWith("claude")) return "anthropic";
  if (model.startsWith("gpt") || model.startsWith("o1") || model.startsWith("o3")) return "openai";
  if (model.startsWith("gemini")) return "google";
  return "unknown";
}

function extractText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (typeof c === "object" && c !== null) {
          const obj = c as Record<string, unknown>;
          return String(obj.text ?? obj.content ?? "");
        }
        return String(c);
      })
      .join(" ");
  }
  return "";
}

/** Recursively find all JSON files */
async function findJsonFiles(dir: string): Promise<string[]> {
  const files: string[] = [];
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...(await findJsonFiles(fullPath)));
      } else if (entry.name.endsWith(".json") || entry.name.endsWith(".jsonl")) {
        files.push(fullPath);
      }
    }
  } catch {
    // Not readable
  }
  return files;
}

// ── Parse a single Amp thread ────────────────────────────────────────────────

async function parseAmpThread(
  filePath: string,
  options?: ScanOptions,
): Promise<ToolSession | null> {
  let raw: string;
  try {
    raw = await readFile(filePath, "utf-8");
  } catch {
    return null;
  }

  // Handle both JSON and JSONL
  let threadMessages: Record<string, unknown>[] = [];
  let threadMeta: Record<string, unknown> = {};

  if (filePath.endsWith(".jsonl")) {
    // JSONL: one message per line
    const lines = raw.split("\n").filter((l) => l.trim());
    for (const line of lines) {
      try {
        threadMessages.push(JSON.parse(line));
      } catch {
        // Skip invalid lines
      }
    }
  } else {
    // JSON: object with messages array or thread data
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        threadMessages = parsed;
      } else {
        threadMeta = parsed;
        threadMessages = (parsed.messages ?? parsed.turns ?? parsed.history ?? []) as Record<string, unknown>[];
      }
    } catch {
      return null;
    }
  }

  if (threadMessages.length === 0) return null;

  const messages: ParsedMessage[] = [];
  let model = String(threadMeta.model ?? "unknown");
  let startedAt = "";
  let endedAt = "";

  for (const msg of threadMessages) {
    const role = String(msg.role ?? "user");
    const msgModel = String(msg.model ?? model);
    if (msg.model) model = msgModel;

    const ts = String(msg.timestamp ?? msg.created_at ?? msg.ts ?? "");
    if (ts) {
      if (!startedAt || ts < startedAt) startedAt = ts;
      if (!endedAt || ts > endedAt) endedAt = ts;
    }

    // Check for usage data
    const usage = msg.usage as Record<string, number> | undefined;
    let inputTokens = usage?.input_tokens ?? usage?.prompt_tokens ?? 0;
    let outputTokens = usage?.output_tokens ?? usage?.completion_tokens ?? 0;
    const cacheRead = usage?.cache_read_input_tokens ?? usage?.cached_tokens ?? 0;

    // Fallback: estimate from content
    if (!inputTokens && !outputTokens && msg.content) {
      const text = extractText(msg.content);
      const tokens = estimateTokens(text);
      if (role === "user") {
        inputTokens = tokens;
      } else if (role === "assistant") {
        outputTokens = tokens;
      }
    }

    const normalizedRole: "user" | "assistant" | "system" | "tool" =
      role === "assistant" ? "assistant" : role === "system" ? "system" : role === "tool" ? "tool" : "user";

    let costUsd = 0;
    if (normalizedRole === "assistant" && (inputTokens > 0 || outputTokens > 0)) {
      costUsd = calculateCost(msgModel, inputTokens + cacheRead, outputTokens, cacheRead).totalCostUsd;
    }

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: ts || new Date().toISOString(),
        role: normalizedRole,
        model: msgModel,
        inputTokens,
        outputTokens,
        cacheReadTokens: cacheRead,
        cacheCreationTokens: 0,
        costUsd,
      });
    }
  }

  // Fallback timestamps
  if (!startedAt) {
    try {
      const s = await stat(filePath);
      startedAt = s.birthtime.toISOString();
      endedAt = s.mtime.toISOString();
    } catch {
      startedAt = new Date().toISOString();
      endedAt = startedAt;
    }
  }

  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  const pathParts = filePath.split("/");
  const sessionId = pathParts[pathParts.length - 1]?.replace(/\.(json|jsonl)$/, "") ?? "unknown";

  const totalInputTokens = messages.reduce((s, m) => s + m.inputTokens, 0);
  const totalOutputTokens = messages.reduce((s, m) => s + m.outputTokens, 0);
  const totalCacheRead = messages.reduce((s, m) => s + m.cacheReadTokens, 0);
  const totalCostUsd = messages.reduce((s, m) => s + m.costUsd, 0);
  const turnCount = messages.filter((m) => m.role === "assistant").length;

  return {
    tool: "amp",
    sessionId,
    filePath,
    startedAt,
    endedAt,
    cwd: String(threadMeta.cwd ?? ""),
    gitBranch: "",
    toolVersion: String(threadMeta.version ?? ""),
    model,
    provider: inferProvider(model),
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens: totalCacheRead,
    totalCacheCreationTokens: 0,
    totalCostUsd,
    turnCount: turnCount || 1,
    messages,
  };
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const ampScanner: ScannerPlugin = {
  name: "amp",
  displayName: "Amp",
  description: "~/.local/share/amp/threads/ — JSON thread files",

  async detect(): Promise<boolean> {
    return dirExists(getThreadsDir());
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const dir = getThreadsDir();
    if (!(await dirExists(dir))) return [];

    const files = await findJsonFiles(dir);
    const BATCH_SIZE = 50;
    const sessions: ToolSession[] = [];

    for (let i = 0; i < files.length; i += BATCH_SIZE) {
      const batch = files.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        batch.map((f) => parseAmpThread(f, options)),
      );
      for (const s of results) {
        if (s) sessions.push(s);
      }
    }

    sessions.sort((a, b) => (b.startedAt > a.startedAt ? 1 : -1));
    if (options?.limit) return sessions.slice(0, options.limit);
    return sessions;
  },
};
