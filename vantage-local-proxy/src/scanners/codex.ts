/**
 * Codex CLI Local File Scanner
 *
 * Path:   ~/.codex/sessions/{year}/{month}/{day}/rollout-*.jsonl
 * Format: JSONL — session_meta, turn_context, response_item, event_msg
 *
 * session_meta  → model_provider, cli_version, cwd
 * turn_context  → model, effort, cwd
 * response_item → payload.type=message, payload.role, payload.content
 *
 * Note: Codex CLI does NOT log token usage in local JSONL files.
 * We estimate tokens from message content length using word-count heuristics.
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

// ── Types ────────────────────────────────────────────────────────────────────

interface CodexEntry {
  timestamp: string;
  type: "session_meta" | "turn_context" | "response_item" | "event_msg" | string;
  payload: Record<string, unknown>;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getSessionsDir(): string {
  return join(homedir(), ".codex", "sessions");
}

/** Rough token estimate: ~0.75 tokens per word for English text */
function estimateTokens(text: string): number {
  if (!text) return 0;
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.ceil(words * 1.33);
}

async function dirExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isDirectory();
  } catch {
    return false;
  }
}

/** Recursively find all .jsonl files under a directory */
async function findJsonlFiles(dir: string): Promise<string[]> {
  const files: string[] = [];
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...(await findJsonlFiles(fullPath)));
      } else if (entry.name.endsWith(".jsonl")) {
        files.push(fullPath);
      }
    }
  } catch {
    // Not readable
  }
  return files;
}

function extractText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (typeof c === "object" && c !== null) {
          return (c as Record<string, unknown>).text ?? "";
        }
        return String(c);
      })
      .join(" ");
  }
  return "";
}

// ── Parse a single Codex session JSONL ───────────────────────────────────────

async function parseCodexSession(
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

  let sessionId = "";
  let cwd = "";
  let toolVersion = "";
  let model = "";
  let provider = "openai";
  let startedAt = "";
  let endedAt = "";

  const messages: ParsedMessage[] = [];

  for (const line of lines) {
    let entry: CodexEntry;
    try {
      entry = JSON.parse(line);
    } catch {
      continue;
    }

    if (entry.timestamp) {
      if (!startedAt || entry.timestamp < startedAt) startedAt = entry.timestamp;
      if (!endedAt || entry.timestamp > endedAt) endedAt = entry.timestamp;
    }

    const p = entry.payload;

    switch (entry.type) {
      case "session_meta": {
        sessionId = String(p.id ?? "");
        cwd = String(p.cwd ?? "");
        toolVersion = String(p.cli_version ?? "");
        provider = String(p.model_provider ?? "openai");
        break;
      }
      case "turn_context": {
        if (p.model) model = String(p.model);
        if (p.cwd && !cwd) cwd = String(p.cwd);
        break;
      }
      case "event_msg": {
        if (p.type === "user_message" && p.message) {
          const text = String(p.message);
          const tokens = estimateTokens(text);
          if (options?.includeMessages !== false) {
            messages.push({
              timestamp: entry.timestamp,
              role: "user",
              model,
              inputTokens: tokens,
              outputTokens: 0,
              cacheReadTokens: 0,
              cacheCreationTokens: 0,
              costUsd: 0,
            });
          }
        }
        break;
      }
      case "response_item": {
        if (p.type === "message" && p.role === "assistant") {
          // Codex doesn't log usage — estimate from content
          // Content is typically absent for assistant in JSONL, but check
        }
        // Check for output_text type content
        const pContent = p.content;
        if (p.role !== "developer" && p.role !== "user" && pContent) {
          const text = extractText(pContent);
          if (text) {
            const outputTokens = estimateTokens(text);
            const costResult = calculateCost(model || "gpt-4o", 0, outputTokens);
            if (options?.includeMessages !== false) {
              messages.push({
                timestamp: entry.timestamp,
                role: "assistant",
                model: model || "unknown",
                inputTokens: 0,
                outputTokens,
                cacheReadTokens: 0,
                cacheCreationTokens: 0,
                costUsd: costResult.totalCostUsd,
              });
            }
          }
        }
        break;
      }
    }
  }

  if (!sessionId) {
    sessionId = basename(filePath, ".jsonl");
  }

  if (!startedAt) return null;

  // Apply time filters
  if (options?.since && endedAt && endedAt < options.since) return null;
  if (options?.until && startedAt && startedAt > options.until) return null;

  const totalInputTokens = messages.reduce((s, m) => s + m.inputTokens, 0);
  const totalOutputTokens = messages.reduce((s, m) => s + m.outputTokens, 0);
  const totalCostUsd = messages.reduce((s, m) => s + m.costUsd, 0);
  const turnCount = messages.filter((m) => m.role === "assistant").length;

  return {
    tool: "codex-cli",
    sessionId,
    filePath,
    startedAt,
    endedAt,
    cwd,
    gitBranch: "",
    toolVersion,
    model: model || "unknown",
    provider,
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens: 0,
    totalCacheCreationTokens: 0,
    totalCostUsd,
    turnCount: turnCount || messages.length,
    messages,
  };
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const codexScanner: ScannerPlugin = {
  name: "codex-cli",
  displayName: "Codex CLI",
  description: "~/.codex/sessions/ — JSONL session logs (token counts estimated)",

  async detect(): Promise<boolean> {
    return dirExists(getSessionsDir());
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const dir = getSessionsDir();
    if (!(await dirExists(dir))) return [];

    const files = await findJsonlFiles(dir);
    const BATCH_SIZE = 50;
    const sessions: ToolSession[] = [];

    for (let i = 0; i < files.length; i += BATCH_SIZE) {
      const batch = files.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        batch.map((f) => parseCodexSession(f, options)),
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
