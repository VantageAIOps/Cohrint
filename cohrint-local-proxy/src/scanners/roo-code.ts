/**
 * Roo Code (formerly Roo Cline) Local File Scanner
 *
 * Path:   ~/.config/Code/User/globalStorage/rooveterinaryinc.roo-cline/tasks/
 * Format: Each task is a directory with:
 *   - api_conversation_history.json — array of API messages with usage
 *   - ui_messages.json — UI-rendered messages
 *
 * API conversation entries contain:
 *   { role, content, usage?: { input_tokens, output_tokens, ... }, model }
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

function getTasksDir(): string {
  // macOS path
  const platform = process.platform;
  if (platform === "darwin") {
    return join(
      homedir(),
      "Library",
      "Application Support",
      "Code",
      "User",
      "globalStorage",
      "rooveterinaryinc.roo-cline",
      "tasks",
    );
  }
  // Linux
  if (platform === "linux") {
    return join(
      homedir(),
      ".config",
      "Code",
      "User",
      "globalStorage",
      "rooveterinaryinc.roo-cline",
      "tasks",
    );
  }
  // Windows
  return join(
    process.env.APPDATA ?? join(homedir(), "AppData", "Roaming"),
    "Code",
    "User",
    "globalStorage",
    "rooveterinaryinc.roo-cline",
    "tasks",
  );
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

// ── Parse a Roo Code task directory ──────────────────────────────────────────

async function parseRooTask(
  taskDir: string,
  taskId: string,
  options?: ScanOptions,
): Promise<ToolSession | null> {
  const apiHistoryPath = join(taskDir, "api_conversation_history.json");

  let raw: string;
  try {
    raw = await readFile(apiHistoryPath, "utf-8");
  } catch {
    return null;
  }

  let history: Record<string, unknown>[];
  try {
    const parsed = JSON.parse(raw);
    history = Array.isArray(parsed) ? parsed : [];
  } catch {
    return null;
  }

  if (history.length === 0) return null;

  const messages: ParsedMessage[] = [];
  let model = "unknown";
  let startedAt = "";
  let endedAt = "";

  for (const entry of history) {
    const role = String(entry.role ?? "user");
    const entryModel = String(entry.model ?? model);
    if (entry.model) model = entryModel;

    const ts = String(entry.ts ?? entry.timestamp ?? "");
    if (ts) {
      if (!startedAt || ts < startedAt) startedAt = ts;
      if (!endedAt || ts > endedAt) endedAt = ts;
    }

    // Roo Code stores usage on assistant messages
    const usage = entry.usage as Record<string, number> | undefined;
    const inputTokens = usage?.input_tokens ?? usage?.prompt_tokens ?? 0;
    const outputTokens = usage?.output_tokens ?? usage?.completion_tokens ?? 0;
    const cacheRead = usage?.cache_read_input_tokens ?? usage?.cached_tokens ?? 0;
    const cacheCreation = usage?.cache_creation_input_tokens ?? 0;

    const normalizedRole: "user" | "assistant" | "system" | "tool" =
      role === "assistant" ? "assistant" : role === "system" ? "system" : "user";

    let costUsd = 0;
    if (normalizedRole === "assistant" && (inputTokens > 0 || outputTokens > 0)) {
      const totalPrompt = inputTokens + cacheRead;
      costUsd = calculateCost(entryModel, totalPrompt, outputTokens, cacheRead).totalCostUsd;
    }

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: ts || new Date().toISOString(),
        role: normalizedRole,
        model: entryModel,
        inputTokens,
        outputTokens,
        cacheReadTokens: cacheRead,
        cacheCreationTokens: cacheCreation,
        costUsd,
      });
    }
  }

  // Fallback timestamps from file stat
  if (!startedAt) {
    try {
      const s = await stat(taskDir);
      startedAt = s.birthtime.toISOString();
      endedAt = s.mtime.toISOString();
    } catch {
      startedAt = new Date().toISOString();
      endedAt = startedAt;
    }
  }

  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  const totalInputTokens = messages.reduce((s, m) => s + m.inputTokens, 0);
  const totalOutputTokens = messages.reduce((s, m) => s + m.outputTokens, 0);
  const totalCacheRead = messages.reduce((s, m) => s + m.cacheReadTokens, 0);
  const totalCacheCreation = messages.reduce((s, m) => s + m.cacheCreationTokens, 0);
  const totalCostUsd = messages.reduce((s, m) => s + m.costUsd, 0);
  const turnCount = messages.filter((m) => m.role === "assistant").length;

  return {
    tool: "roo-code",
    sessionId: taskId,
    filePath: apiHistoryPath,
    startedAt,
    endedAt,
    cwd: "",
    gitBranch: "",
    toolVersion: "",
    model,
    provider: inferProvider(model),
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens: totalCacheRead,
    totalCacheCreationTokens: totalCacheCreation,
    totalCostUsd,
    turnCount: turnCount || 1,
    messages,
  };
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const rooCodeScanner: ScannerPlugin = {
  name: "roo-code",
  displayName: "Roo Code",
  description:
    "VS Code globalStorage/rooveterinaryinc.roo-cline/tasks/ — JSON API conversation history",

  async detect(): Promise<boolean> {
    return dirExists(getTasksDir());
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const tasksDir = getTasksDir();
    if (!(await dirExists(tasksDir))) return [];

    const entries = await readdir(tasksDir, { withFileTypes: true });
    const taskDirs = entries
      .filter((e) => e.isDirectory())
      .map((e) => ({ path: join(tasksDir, e.name), id: e.name }));

    const BATCH_SIZE = 30;
    const sessions: ToolSession[] = [];

    for (let i = 0; i < taskDirs.length; i += BATCH_SIZE) {
      const batch = taskDirs.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        batch.map((t) => parseRooTask(t.path, t.id, options)),
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
