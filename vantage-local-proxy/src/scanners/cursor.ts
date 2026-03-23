/**
 * Cursor Local File Scanner
 *
 * Cursor syncs usage via API session tokens but caches data locally.
 *
 * Paths checked:
 *   macOS:   ~/Library/Application Support/Cursor/User/globalStorage/
 *   Linux:   ~/.config/Cursor/User/globalStorage/
 *   Windows: %APPDATA%/Cursor/User/globalStorage/
 *
 * Cursor stores usage in:
 *   - storage.json (main state file)
 *   - cursor-usage.json (usage cache)
 *   - state.vscdb (SQLite state database)
 *
 * We also check for CSV exports in ~/Downloads/cursor-usage*.csv
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

function getCursorDirs(): string[] {
  const home = homedir();
  const platform = process.platform;

  const dirs: string[] = [];
  if (platform === "darwin") {
    dirs.push(join(home, "Library", "Application Support", "Cursor", "User", "globalStorage"));
    dirs.push(join(home, "Library", "Application Support", "Cursor"));
  } else if (platform === "linux") {
    dirs.push(join(home, ".config", "Cursor", "User", "globalStorage"));
    dirs.push(join(home, ".config", "Cursor"));
  } else {
    const appData = process.env.APPDATA ?? join(home, "AppData", "Roaming");
    dirs.push(join(appData, "Cursor", "User", "globalStorage"));
    dirs.push(join(appData, "Cursor"));
  }
  return dirs;
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

function inferProvider(model: string): string {
  if (model.startsWith("claude")) return "anthropic";
  if (model.startsWith("gpt") || model.startsWith("o1") || model.startsWith("o3") || model.includes("cursor")) return "openai";
  if (model.startsWith("gemini")) return "google";
  return "openai"; // Cursor defaults to OpenAI-compatible
}

// ── Parse CSV usage exports ──────────────────────────────────────────────────

function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;
  for (const char of line) {
    if (char === '"') {
      inQuotes = !inQuotes;
    } else if (char === "," && !inQuotes) {
      fields.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  fields.push(current.trim());
  return fields;
}

async function parseCsvFile(
  filePath: string,
  options?: ScanOptions,
): Promise<ToolSession | null> {
  let raw: string;
  try {
    raw = await readFile(filePath, "utf-8");
  } catch {
    return null;
  }

  const lines = raw.split("\n").filter((l) => l.trim());
  if (lines.length < 2) return null;

  const headers = parseCsvLine(lines[0]).map((h) => h.toLowerCase().replace(/\s+/g, "_"));
  const messages: ParsedMessage[] = [];
  let model = "cursor-default";
  let startedAt = "";
  let endedAt = "";

  for (let i = 1; i < lines.length; i++) {
    const fields = parseCsvLine(lines[i]);
    const row: Record<string, string> = {};
    headers.forEach((h, idx) => {
      row[h] = fields[idx] ?? "";
    });

    const ts = row.timestamp ?? row.date ?? row.created_at ?? "";
    if (ts) {
      if (!startedAt || ts < startedAt) startedAt = ts;
      if (!endedAt || ts > endedAt) endedAt = ts;
    }

    const rowModel = row.model ?? model;
    if (row.model) model = rowModel;

    const inputTokens = parseInt(row.input_tokens ?? row.prompt_tokens ?? "0", 10) || 0;
    const outputTokens = parseInt(row.output_tokens ?? row.completion_tokens ?? "0", 10) || 0;
    const costUsd = parseFloat(row.cost ?? row.cost_usd ?? "0") || 0;

    const finalCost = costUsd || calculateCost(rowModel, inputTokens, outputTokens).totalCostUsd;

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: ts || new Date().toISOString(),
        role: "assistant",
        model: rowModel,
        inputTokens,
        outputTokens,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
        costUsd: finalCost,
      });
    }
  }

  if (messages.length === 0) return null;

  if (!startedAt) {
    const s = await stat(filePath);
    startedAt = s.birthtime.toISOString();
    endedAt = s.mtime.toISOString();
  }

  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  return {
    tool: "cursor",
    sessionId: filePath.split("/").pop()?.replace(/\.(csv|json)$/, "") ?? "cursor-usage",
    filePath,
    startedAt,
    endedAt,
    cwd: "",
    gitBranch: "",
    toolVersion: "",
    model,
    provider: inferProvider(model),
    totalInputTokens: messages.reduce((s, m) => s + m.inputTokens, 0),
    totalOutputTokens: messages.reduce((s, m) => s + m.outputTokens, 0),
    totalCacheReadTokens: 0,
    totalCacheCreationTokens: 0,
    totalCostUsd: messages.reduce((s, m) => s + m.costUsd, 0),
    turnCount: messages.length,
    messages,
  };
}

// ── Parse JSON usage cache ───────────────────────────────────────────────────

async function parseJsonUsage(
  filePath: string,
  options?: ScanOptions,
): Promise<ToolSession | null> {
  let raw: string;
  try {
    raw = await readFile(filePath, "utf-8");
  } catch {
    return null;
  }

  let data: Record<string, unknown>;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }

  // Look for usage data in various Cursor JSON formats
  const usageEntries = (data.usage ?? data.requests ?? data.completions ?? []) as Record<string, unknown>[];
  if (!Array.isArray(usageEntries) || usageEntries.length === 0) return null;

  const messages: ParsedMessage[] = [];
  let model = "cursor-default";
  let startedAt = "";
  let endedAt = "";

  for (const entry of usageEntries) {
    const entryModel = String(entry.model ?? model);
    if (entry.model) model = entryModel;

    const ts = String(entry.timestamp ?? entry.created_at ?? entry.date ?? "");
    if (ts) {
      if (!startedAt || ts < startedAt) startedAt = ts;
      if (!endedAt || ts > endedAt) endedAt = ts;
    }

    const inputTokens = Number(entry.input_tokens ?? entry.prompt_tokens ?? 0);
    const outputTokens = Number(entry.output_tokens ?? entry.completion_tokens ?? 0);
    const costUsd = Number(entry.cost ?? entry.cost_usd ?? 0) ||
      calculateCost(entryModel, inputTokens, outputTokens).totalCostUsd;

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: ts || new Date().toISOString(),
        role: "assistant",
        model: entryModel,
        inputTokens,
        outputTokens,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
        costUsd,
      });
    }
  }

  if (messages.length === 0) return null;

  if (!startedAt) {
    const s = await stat(filePath);
    startedAt = s.birthtime.toISOString();
    endedAt = s.mtime.toISOString();
  }

  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  return {
    tool: "cursor",
    sessionId: filePath.split("/").pop()?.replace(/\.(csv|json)$/, "") ?? "cursor-usage",
    filePath,
    startedAt,
    endedAt,
    cwd: "",
    gitBranch: "",
    toolVersion: "",
    model,
    provider: inferProvider(model),
    totalInputTokens: messages.reduce((s, m) => s + m.inputTokens, 0),
    totalOutputTokens: messages.reduce((s, m) => s + m.outputTokens, 0),
    totalCacheReadTokens: 0,
    totalCacheCreationTokens: 0,
    totalCostUsd: messages.reduce((s, m) => s + m.costUsd, 0),
    turnCount: messages.length,
    messages,
  };
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const cursorScanner: ScannerPlugin = {
  name: "cursor",
  displayName: "Cursor",
  description: "Cursor globalStorage + CSV exports — API sync usage cache",

  async detect(): Promise<boolean> {
    for (const dir of getCursorDirs()) {
      if (await pathExists(dir)) return true;
    }
    // Also check for CSV exports
    const downloads = join(homedir(), "Downloads");
    try {
      const entries = await readdir(downloads);
      if (entries.some((e) => e.startsWith("cursor-usage") && e.endsWith(".csv"))) {
        return true;
      }
    } catch {
      // Downloads not readable
    }
    return false;
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const sessions: ToolSession[] = [];

    // Scan Cursor globalStorage for JSON usage files
    for (const dir of getCursorDirs()) {
      if (!(await pathExists(dir))) continue;
      try {
        const entries = await readdir(dir, { withFileTypes: true });
        for (const entry of entries) {
          if (!entry.isFile()) continue;
          const filePath = join(dir, entry.name);
          if (entry.name.endsWith(".csv")) {
            const s = await parseCsvFile(filePath, options);
            if (s) sessions.push(s);
          } else if (
            entry.name.endsWith(".json") &&
            (entry.name.includes("usage") || entry.name.includes("cursor"))
          ) {
            const s = await parseJsonUsage(filePath, options);
            if (s) sessions.push(s);
          }
        }
      } catch {
        // Not readable
      }
    }

    // Check Downloads for CSV exports
    const downloads = join(homedir(), "Downloads");
    try {
      const entries = await readdir(downloads);
      for (const name of entries) {
        if (name.startsWith("cursor-usage") && name.endsWith(".csv")) {
          const s = await parseCsvFile(join(downloads, name), options);
          if (s) sessions.push(s);
        }
      }
    } catch {
      // Downloads not readable
    }

    sessions.sort((a, b) => (b.startedAt > a.startedAt ? 1 : -1));
    if (options?.limit) return sessions.slice(0, options.limit);
    return sessions;
  },
};
