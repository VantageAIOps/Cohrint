/**
 * Scanner Registry — runs all tool scanners in parallel and returns unified results.
 */

import { claudeCodeScanner } from "./claude-code.js";
import { codexScanner } from "./codex.js";
import { geminiScanner } from "./gemini.js";
import { cursorScanner } from "./cursor.js";
import { rooCodeScanner } from "./roo-code.js";
import { openCodeScanner } from "./opencode.js";
import { ampScanner } from "./amp.js";
import type {
  ScannerPlugin,
  ScanOptions,
  ScanResult,
  ScanTotals,
  ToolSummary,
  ScanError,
  ToolSession,
  ToolName,
} from "./types.js";

// ── Registry ─────────────────────────────────────────────────────────────────

export const ALL_SCANNERS: ScannerPlugin[] = [
  claudeCodeScanner,
  codexScanner,
  geminiScanner,
  cursorScanner,
  rooCodeScanner,
  openCodeScanner,
  ampScanner,
];

export function getScannerByName(name: ToolName): ScannerPlugin | undefined {
  return ALL_SCANNERS.find((s) => s.name === name);
}

// ── Unified scan ─────────────────────────────────────────────────────────────

export interface FullScanOptions extends ScanOptions {
  /** Only scan these tools (default: all detected) */
  tools?: ToolName[];
}

export async function scanAll(options?: FullScanOptions): Promise<ScanResult> {
  const t0 = performance.now();
  const errors: ScanError[] = [];

  // Determine which scanners to run
  let scanners = ALL_SCANNERS;
  if (options?.tools?.length) {
    scanners = ALL_SCANNERS.filter((s) => options.tools!.includes(s.name));
  }

  // Detect which tools exist on this machine
  const detectionResults = await Promise.all(
    scanners.map(async (s) => ({
      scanner: s,
      detected: await s.detect().catch(() => false),
    })),
  );

  const activeScanners = detectionResults.filter((r) => r.detected).map((r) => r.scanner);
  const toolsScanned = scanners.map((s) => s.name);

  // Run all active scanners in parallel
  const scanResults = await Promise.all(
    activeScanners.map(async (scanner) => {
      try {
        return { tool: scanner.name, sessions: await scanner.scan(options) };
      } catch (err) {
        errors.push({
          tool: scanner.name,
          file: "",
          error: err instanceof Error ? err.message : String(err),
        });
        return { tool: scanner.name, sessions: [] as ToolSession[] };
      }
    }),
  );

  // Merge all sessions
  const allSessions: ToolSession[] = [];
  const toolsFound: ToolName[] = [];

  for (const result of scanResults) {
    if (result.sessions.length > 0) {
      toolsFound.push(result.tool as ToolName);
      allSessions.push(...result.sessions);
    }
  }

  // Sort all sessions newest-first
  allSessions.sort((a, b) => (b.startedAt > a.startedAt ? 1 : -1));

  // Apply global limit
  const limitedSessions = options?.limit
    ? allSessions.slice(0, options.limit)
    : allSessions;

  // Compute totals
  const totals: ScanTotals = {
    totalSessions: limitedSessions.length,
    totalTurns: limitedSessions.reduce((s, sess) => s + sess.turnCount, 0),
    totalInputTokens: limitedSessions.reduce((s, sess) => s + sess.totalInputTokens, 0),
    totalOutputTokens: limitedSessions.reduce((s, sess) => s + sess.totalOutputTokens, 0),
    totalCostUsd: limitedSessions.reduce((s, sess) => s + sess.totalCostUsd, 0),
  };

  // Compute per-tool summaries
  const byTool: Record<string, ToolSummary> = {};
  for (const sess of limitedSessions) {
    if (!byTool[sess.tool]) {
      byTool[sess.tool] = {
        tool: sess.tool,
        sessions: 0,
        turns: 0,
        inputTokens: 0,
        outputTokens: 0,
        costUsd: 0,
        models: [],
        oldestSession: sess.startedAt,
        newestSession: sess.startedAt,
      };
    }
    const summary = byTool[sess.tool];
    summary.sessions++;
    summary.turns += sess.turnCount;
    summary.inputTokens += sess.totalInputTokens;
    summary.outputTokens += sess.totalOutputTokens;
    summary.costUsd += sess.totalCostUsd;
    if (!summary.models.includes(sess.model)) {
      summary.models.push(sess.model);
    }
    if (sess.startedAt < summary.oldestSession) summary.oldestSession = sess.startedAt;
    if (sess.startedAt > summary.newestSession) summary.newestSession = sess.startedAt;
  }

  return {
    scannedAt: new Date().toISOString(),
    durationMs: Math.round(performance.now() - t0),
    toolsScanned,
    toolsFound,
    sessions: limitedSessions,
    totals,
    byTool,
    errors,
  };
}

// ── Re-exports ───────────────────────────────────────────────────────────────

export type {
  ScannerPlugin,
  ScanOptions,
  ScanResult,
  ScanTotals,
  ToolSummary,
  ScanError,
  ToolSession,
  ParsedMessage,
  ToolName,
} from "./types.js";

export { claudeCodeScanner } from "./claude-code.js";
export { codexScanner } from "./codex.js";
export { geminiScanner } from "./gemini.js";
export { cursorScanner } from "./cursor.js";
export { rooCodeScanner } from "./roo-code.js";
export { openCodeScanner } from "./opencode.js";
export { ampScanner } from "./amp.js";
