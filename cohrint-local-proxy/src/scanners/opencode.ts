/**
 * OpenCode Local File Scanner
 *
 * Path:   ~/.local/share/opencode/opencode.db
 * Format: SQLite database
 *
 * Since we want zero native dependencies, we read the SQLite file
 * using a minimal SQLite parser that extracts text from table pages.
 *
 * OpenCode stores sessions with model, tokens, and cost data.
 * Fallback: also checks for JSON export files in the same directory.
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

function getOpenCodeDir(): string {
  if (process.platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "opencode");
  }
  return join(homedir(), ".local", "share", "opencode");
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

async function dirExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isDirectory();
  } catch {
    return false;
  }
}

function inferProvider(model: string): string {
  if (model.startsWith("claude")) return "anthropic";
  if (model.startsWith("gpt") || model.startsWith("o1") || model.startsWith("o3")) return "openai";
  if (model.startsWith("gemini")) return "google";
  if (model.startsWith("deepseek")) return "deepseek";
  return "unknown";
}

// ── SQLite minimal reader (read-only, text extraction) ───────────────────────
// We extract strings from SQLite pages without a full parser.
// This gives us approximate data — enough for cost tracking.

async function extractSqliteStrings(dbPath: string): Promise<string[][]> {
  let buf: Buffer;
  try {
    buf = await readFile(dbPath) as unknown as Buffer;
  } catch {
    return [];
  }

  // Verify SQLite header
  const header = buf.subarray(0, 16).toString("ascii");
  if (!header.startsWith("SQLite format 3")) return [];

  // Extract JSON-like strings from the database file
  const text = buf.toString("utf-8", 0, Math.min(buf.length, 10 * 1024 * 1024));
  const rows: string[][] = [];

  // Look for JSON objects that look like session/message records
  const jsonPattern = /\{[^{}]*"(?:model|role|input_tokens|prompt_tokens)"[^{}]*\}/g;
  let match: RegExpExecArray | null;
  while ((match = jsonPattern.exec(text)) !== null) {
    try {
      const obj = JSON.parse(match[0]);
      rows.push([JSON.stringify(obj)]);
    } catch {
      // Not valid JSON
    }
  }

  return rows;
}

// ── Parse JSON export files ──────────────────────────────────────────────────

async function parseJsonExports(
  dir: string,
  options?: ScanOptions,
): Promise<ToolSession[]> {
  const sessions: ToolSession[] = [];

  try {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
      const filePath = join(dir, entry.name);

      let raw: string;
      try {
        raw = await readFile(filePath, "utf-8");
      } catch {
        continue;
      }

      let data: Record<string, unknown>;
      try {
        data = JSON.parse(raw);
      } catch {
        continue;
      }

      // OpenCode JSON exports may have session-level data
      const msgList = (data.messages ?? data.history ?? []) as Record<string, unknown>[];
      if (msgList.length === 0) continue;

      const messages: ParsedMessage[] = [];
      let model = String(data.model ?? "unknown");
      let startedAt = "";
      let endedAt = "";

      for (const msg of msgList) {
        const role = String(msg.role ?? "user");
        const msgModel = String(msg.model ?? model);
        if (msg.model) model = msgModel;

        const ts = String(msg.timestamp ?? msg.created_at ?? "");
        if (ts) {
          if (!startedAt || ts < startedAt) startedAt = ts;
          if (!endedAt || ts > endedAt) endedAt = ts;
        }

        const usage = msg.usage as Record<string, number> | undefined;
        const inputTokens = usage?.input_tokens ?? usage?.prompt_tokens ?? 0;
        const outputTokens = usage?.output_tokens ?? usage?.completion_tokens ?? 0;

        const normalizedRole: "user" | "assistant" = role === "assistant" ? "assistant" : "user";
        let costUsd = 0;
        if (normalizedRole === "assistant" && (inputTokens > 0 || outputTokens > 0)) {
          costUsd = calculateCost(msgModel, inputTokens, outputTokens).totalCostUsd;
        }

        if (options?.includeMessages !== false) {
          messages.push({
            timestamp: ts || new Date().toISOString(),
            role: normalizedRole,
            model: msgModel,
            inputTokens,
            outputTokens,
            cacheReadTokens: 0,
            cacheCreationTokens: 0,
            costUsd,
          });
        }
      }

      if (!startedAt) {
        const s = await stat(filePath);
        startedAt = s.birthtime.toISOString();
        endedAt = s.mtime.toISOString();
      }

      if (options?.since && endedAt && endedAt < options.since) continue;
      if (options?.until && startedAt && startedAt > options.until) continue;

      sessions.push({
        tool: "opencode",
        sessionId: entry.name.replace(".json", ""),
        filePath,
        startedAt,
        endedAt,
        cwd: String(data.cwd ?? ""),
        gitBranch: "",
        toolVersion: String(data.version ?? ""),
        model,
        provider: inferProvider(model),
        totalInputTokens: messages.reduce((s, m) => s + m.inputTokens, 0),
        totalOutputTokens: messages.reduce((s, m) => s + m.outputTokens, 0),
        totalCacheReadTokens: 0,
        totalCacheCreationTokens: 0,
        totalCostUsd: messages.reduce((s, m) => s + m.costUsd, 0),
        turnCount: messages.filter((m) => m.role === "assistant").length || 1,
        messages,
      });
    }
  } catch {
    // Directory not readable
  }

  return sessions;
}

// ── Parse SQLite database ────────────────────────────────────────────────────

async function parseSqliteDb(
  dbPath: string,
  options?: ScanOptions,
): Promise<ToolSession[]> {
  const rows = await extractSqliteStrings(dbPath);
  if (rows.length === 0) return [];

  // Group extracted records into a single session
  const messages: ParsedMessage[] = [];
  let model = "unknown";

  for (const row of rows) {
    for (const cell of row) {
      try {
        const obj = JSON.parse(cell);
        const msgModel = obj.model ?? model;
        if (obj.model) model = msgModel;

        const role = obj.role === "assistant" ? "assistant" as const : "user" as const;
        const inputTokens = obj.input_tokens ?? obj.prompt_tokens ?? 0;
        const outputTokens = obj.output_tokens ?? obj.completion_tokens ?? 0;

        let costUsd = 0;
        if (role === "assistant" && (inputTokens > 0 || outputTokens > 0)) {
          costUsd = calculateCost(msgModel, inputTokens, outputTokens).totalCostUsd;
        }

        if (options?.includeMessages !== false) {
          messages.push({
            timestamp: obj.timestamp ?? obj.created_at ?? new Date().toISOString(),
            role,
            model: msgModel,
            inputTokens,
            outputTokens,
            cacheReadTokens: 0,
            cacheCreationTokens: 0,
            costUsd,
          });
        }
      } catch {
        // Skip invalid
      }
    }
  }

  if (messages.length === 0) return [];

  const s = await stat(dbPath);
  return [
    {
      tool: "opencode",
      sessionId: "opencode-db",
      filePath: dbPath,
      startedAt: s.birthtime.toISOString(),
      endedAt: s.mtime.toISOString(),
      cwd: "",
      gitBranch: "",
      toolVersion: "",
      model,
      provider: inferProvider(model),
      totalInputTokens: messages.reduce((sum, m) => sum + m.inputTokens, 0),
      totalOutputTokens: messages.reduce((sum, m) => sum + m.outputTokens, 0),
      totalCacheReadTokens: 0,
      totalCacheCreationTokens: 0,
      totalCostUsd: messages.reduce((sum, m) => sum + m.costUsd, 0),
      turnCount: messages.filter((m) => m.role === "assistant").length || 1,
      messages,
    },
  ];
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const openCodeScanner: ScannerPlugin = {
  name: "opencode",
  displayName: "OpenCode",
  description: "~/.local/share/opencode/opencode.db — SQLite + JSON exports",

  async detect(): Promise<boolean> {
    const dir = getOpenCodeDir();
    const dbPath = join(dir, "opencode.db");
    return (await dirExists(dir)) || (await pathExists(dbPath));
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const dir = getOpenCodeDir();
    const sessions: ToolSession[] = [];

    // Try SQLite database
    const dbPath = join(dir, "opencode.db");
    if (await pathExists(dbPath)) {
      sessions.push(...(await parseSqliteDb(dbPath, options)));
    }

    // Also check for JSON exports
    if (await dirExists(dir)) {
      sessions.push(...(await parseJsonExports(dir, options)));
    }

    sessions.sort((a, b) => (b.startedAt > a.startedAt ? 1 : -1));
    if (options?.limit) return sessions.slice(0, options.limit);
    return sessions;
  },
};
