/**
 * Claude Code Local File Scanner
 *
 * Path:   ~/.claude/projects/{dir-slug}/{uuid}.jsonl
 * Format: JSONL — one JSON object per line
 *
 * Each assistant message contains:
 *   message.model   → "claude-opus-4-6", "claude-sonnet-4-6", etc.
 *   message.usage   → { input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens }
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join, basename } from "node:path";
import { homedir } from "node:os";
import { calculateCost } from "../pricing.js";
import type {
  ScannerPlugin,
  ScanOptions,
  ToolSession,
  ParsedMessage,
} from "./types.js";

// ── Types for Claude Code JSONL entries ──────────────────────────────────────

interface ClaudeCodeEntry {
  type: "user" | "assistant" | "file-history-snapshot" | string;
  timestamp: string;
  sessionId?: string;
  uuid?: string;
  parentUuid?: string | null;
  cwd?: string;
  version?: string;
  gitBranch?: string;
  message?: {
    role: string;
    model?: string;
    usage?: {
      input_tokens?: number;
      output_tokens?: number;
      cache_creation_input_tokens?: number;
      cache_read_input_tokens?: number;
    };
    content?: unknown;
  };
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getProjectsDir(): string {
  return join(homedir(), ".claude", "projects");
}

function inferProvider(model: string): string {
  if (model.startsWith("claude")) return "anthropic";
  if (model.startsWith("gpt") || model.startsWith("o1") || model.startsWith("o3")) return "openai";
  if (model.startsWith("gemini")) return "google";
  return "unknown";
}

async function dirExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isDirectory();
  } catch {
    return false;
  }
}

async function listJsonlFiles(dir: string): Promise<string[]> {
  const files: string[] = [];
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isFile() && entry.name.endsWith(".jsonl")) {
        files.push(join(dir, entry.name));
      } else if (entry.isDirectory()) {
        // Don't recurse into subdirectories (they're memory/settings dirs)
      }
    }
  } catch {
    // Directory not readable
  }
  return files;
}

// ── Parse a single JSONL file into a ToolSession ─────────────────────────────

async function parseSessionFile(
  filePath: string,
  options?: ScanOptions,
): Promise<ToolSession | null> {
  let content: string;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    return null;
  }

  const lines = content.split("\n").filter((l) => l.trim());
  if (lines.length === 0) return null;

  const messages: ParsedMessage[] = [];
  let sessionId = basename(filePath, ".jsonl");
  let cwd = "";
  let gitBranch = "";
  let toolVersion = "";
  let startedAt = "";
  let endedAt = "";
  let primaryModel = "";
  const modelCounts: Record<string, number> = {};

  for (const line of lines) {
    let entry: ClaudeCodeEntry;
    try {
      entry = JSON.parse(line);
    } catch {
      continue;
    }

    // Track session metadata from any entry
    if (entry.sessionId && !sessionId.includes("-")) {
      sessionId = entry.sessionId;
    }
    if (entry.cwd && !cwd) cwd = entry.cwd;
    if (entry.gitBranch && !gitBranch) gitBranch = entry.gitBranch;
    if (entry.version && !toolVersion) toolVersion = entry.version;

    // Track timestamps
    if (entry.timestamp) {
      if (!startedAt || entry.timestamp < startedAt) startedAt = entry.timestamp;
      if (!endedAt || entry.timestamp > endedAt) endedAt = entry.timestamp;
    }

    // Only assistant messages have usage data
    if (entry.type !== "assistant" || !entry.message?.usage) continue;

    const usage = entry.message.usage;
    const model = entry.message.model ?? "unknown";
    const inputTokens = (usage.input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0);
    const outputTokens = usage.output_tokens ?? 0;
    const cacheRead = usage.cache_read_input_tokens ?? 0;
    const cacheCreation = usage.cache_creation_input_tokens ?? 0;

    // Calculate cost using pricing engine
    const totalPromptTokens = inputTokens + cacheRead;
    const { totalCostUsd } = calculateCost(model, totalPromptTokens, outputTokens, cacheRead);

    modelCounts[model] = (modelCounts[model] ?? 0) + 1;

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: entry.timestamp,
        role: "assistant",
        model,
        inputTokens: totalPromptTokens,
        outputTokens,
        cacheReadTokens: cacheRead,
        cacheCreationTokens: cacheCreation,
        costUsd: totalCostUsd,
      });
    }
  }

  // No assistant messages found — skip empty sessions
  if (Object.keys(modelCounts).length === 0) return null;

  // Apply time filters
  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  // Determine primary model (most used)
  primaryModel = Object.entries(modelCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "unknown";

  // Aggregate totals
  const totalInputTokens = messages.reduce((s, m) => s + m.inputTokens, 0);
  const totalOutputTokens = messages.reduce((s, m) => s + m.outputTokens, 0);
  const totalCacheRead = messages.reduce((s, m) => s + m.cacheReadTokens, 0);
  const totalCacheCreation = messages.reduce((s, m) => s + m.cacheCreationTokens, 0);
  const totalCostUsd = messages.reduce((s, m) => s + m.costUsd, 0);

  return {
    tool: "claude-code",
    sessionId,
    filePath,
    startedAt,
    endedAt,
    cwd,
    gitBranch,
    toolVersion,
    model: primaryModel,
    provider: inferProvider(primaryModel),
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens: totalCacheRead,
    totalCacheCreationTokens: totalCacheCreation,
    totalCostUsd,
    turnCount: messages.length,
    messages,
  };
}

// ── Plugin export ────────────────────────────────────────────────────────────

export const claudeCodeScanner: ScannerPlugin = {
  name: "claude-code",
  displayName: "Claude Code",
  description: "~/.claude/projects/{dir}/{uuid}.jsonl — JSONL with full token/cost per message",

  async detect(): Promise<boolean> {
    return dirExists(getProjectsDir());
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const projectsDir = getProjectsDir();
    if (!(await dirExists(projectsDir))) return [];

    // List all project subdirectories
    const projectDirs = await readdir(projectsDir, { withFileTypes: true });
    const allFiles: string[] = [];

    for (const dir of projectDirs) {
      if (!dir.isDirectory()) continue;
      const subdir = join(projectsDir, dir.name);
      const files = await listJsonlFiles(subdir);
      allFiles.push(...files);
    }

    // Parse all JSONL files in parallel (batched to avoid fd exhaustion)
    const BATCH_SIZE = 50;
    const sessions: ToolSession[] = [];

    for (let i = 0; i < allFiles.length; i += BATCH_SIZE) {
      const batch = allFiles.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        batch.map((f) => parseSessionFile(f, options)),
      );
      for (const s of results) {
        if (s) sessions.push(s);
      }
    }

    // Sort newest first
    sessions.sort((a, b) => (b.startedAt > a.startedAt ? 1 : -1));

    // Apply limit
    if (options?.limit && sessions.length > options.limit) {
      return sessions.slice(0, options.limit);
    }

    return sessions;
  },
};
