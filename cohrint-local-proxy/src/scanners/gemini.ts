/**
 * Gemini CLI Local File Scanner
 *
 * Path:   ~/.gemini/tmp/{id}/chats/{id}.json
 * Format: JSON — array of chat turns with model, token counts
 *
 * Each chat JSON typically contains:
 *   { messages: [{ role, parts, model }], metadata: { ... } }
 *
 * Gemini CLI also stores session data in:
 *   ~/.gemini/history/  (conversation history)
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

function getGeminiDir(): string {
  return join(homedir(), ".gemini");
}

function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.split(/\s+/).filter(Boolean).length * 1.33);
}

async function dirExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isDirectory();
  } catch {
    return false;
  }
}

async function fileExists(path: string): Promise<boolean> {
  try {
    const s = await stat(path);
    return s.isFile();
  } catch {
    return false;
  }
}

/** Find all JSON files recursively under a directory */
async function findJsonFiles(dir: string): Promise<string[]> {
  const files: string[] = [];
  try {
    const entries = await readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...(await findJsonFiles(fullPath)));
      } else if (entry.name.endsWith(".json")) {
        files.push(fullPath);
      }
    }
  } catch {
    // Not readable
  }
  return files;
}

function extractTextFromParts(parts: unknown[]): string {
  return parts
    .map((p) => {
      if (typeof p === "string") return p;
      if (typeof p === "object" && p !== null) {
        const obj = p as Record<string, unknown>;
        return String(obj.text ?? obj.content ?? "");
      }
      return "";
    })
    .join(" ");
}

// ── Parse a single Gemini chat JSON ──────────────────────────────────────────

async function parseGeminiChat(
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

  // Handle both array format and object format
  let chatMessages: Record<string, unknown>[] = [];
  let metadata: Record<string, unknown> = {};

  if (Array.isArray(data)) {
    chatMessages = data as Record<string, unknown>[];
  } else {
    chatMessages = (data.messages ?? data.history ?? data.turns ?? []) as Record<string, unknown>[];
    metadata = (data.metadata ?? data.config ?? {}) as Record<string, unknown>;
  }

  if (chatMessages.length === 0) return null;

  const messages: ParsedMessage[] = [];
  let model = String(metadata.model ?? "gemini-2.0-flash");
  let startedAt = "";
  let endedAt = "";

  for (const msg of chatMessages) {
    const role = String(msg.role ?? "user");
    const msgModel = String(msg.model ?? model);
    if (msg.model) model = msgModel;

    // Extract timestamp
    const ts = String(
      msg.timestamp ?? msg.createTime ?? msg.create_time ?? "",
    );
    if (ts) {
      if (!startedAt || ts < startedAt) startedAt = ts;
      if (!endedAt || ts > endedAt) endedAt = ts;
    }

    // Extract token counts — Gemini may provide usageMetadata
    const usageMeta = msg.usageMetadata as Record<string, number> | undefined;
    let inputTokens = usageMeta?.promptTokenCount ?? 0;
    let outputTokens = usageMeta?.candidatesTokenCount ?? 0;

    // Fallback: estimate from text
    if (!inputTokens && !outputTokens) {
      const parts = (msg.parts ?? msg.content ?? []) as unknown[];
      const text = Array.isArray(parts)
        ? extractTextFromParts(parts)
        : typeof parts === "string"
          ? parts
          : "";
      const tokens = estimateTokens(text);
      if (role === "user" || role === "human") {
        inputTokens = tokens;
      } else {
        outputTokens = tokens;
      }
    }

    const normalizedRole = role === "model" || role === "assistant" ? "assistant" : "user";
    const costResult =
      normalizedRole === "assistant"
        ? calculateCost(msgModel, inputTokens, outputTokens)
        : { totalCostUsd: 0 };

    if (options?.includeMessages !== false) {
      messages.push({
        timestamp: ts || new Date().toISOString(),
        role: normalizedRole,
        model: msgModel,
        inputTokens,
        outputTokens,
        cacheReadTokens: 0,
        cacheCreationTokens: 0,
        costUsd: costResult.totalCostUsd,
      });
    }
  }

  // Get file stat for timestamp fallback
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

  const totalInputTokens = messages.reduce((s, m) => s + m.inputTokens, 0);
  const totalOutputTokens = messages.reduce((s, m) => s + m.outputTokens, 0);
  const totalCostUsd = messages.reduce((s, m) => s + m.costUsd, 0);
  const turnCount = messages.filter((m) => m.role === "assistant").length;

  // Session ID from directory name
  const pathParts = filePath.split("/");
  const sessionId =
    pathParts[pathParts.length - 1]?.replace(".json", "") ?? "unknown";

  return {
    tool: "gemini-cli",
    sessionId,
    filePath,
    startedAt,
    endedAt,
    cwd: String(metadata.cwd ?? ""),
    gitBranch: "",
    toolVersion: String(metadata.version ?? ""),
    model,
    provider: "google",
    totalInputTokens,
    totalOutputTokens,
    totalCacheReadTokens: 0,
    totalCacheCreationTokens: 0,
    totalCostUsd,
    turnCount: turnCount || 1,
    messages,
  };
}

// ── Plugin ───────────────────────────────────────────────────────────────────

export const geminiScanner: ScannerPlugin = {
  name: "gemini-cli",
  displayName: "Gemini CLI",
  description: "~/.gemini/tmp/*/chats/*.json — JSON chat history",

  async detect(): Promise<boolean> {
    const geminiDir = getGeminiDir();
    const tmpDir = join(geminiDir, "tmp");
    const historyDir = join(geminiDir, "history");
    return (await dirExists(tmpDir)) || (await dirExists(historyDir));
  },

  async scan(options?: ScanOptions): Promise<ToolSession[]> {
    const geminiDir = getGeminiDir();
    const searchDirs = [
      join(geminiDir, "tmp"),
      join(geminiDir, "history"),
    ];

    const allFiles: string[] = [];
    for (const dir of searchDirs) {
      if (await dirExists(dir)) {
        allFiles.push(...(await findJsonFiles(dir)));
      }
    }

    const BATCH_SIZE = 50;
    const sessions: ToolSession[] = [];

    for (let i = 0; i < allFiles.length; i += BATCH_SIZE) {
      const batch = allFiles.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(
        batch.map((f) => parseGeminiChat(f, options)),
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
