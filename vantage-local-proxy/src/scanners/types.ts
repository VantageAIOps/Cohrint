/**
 * Local File Scanner — Layer 2 of VantageAI's 4-layer architecture.
 *
 * Every AI coding tool stores session data in local files.
 * These types define the unified interface for parsing them all.
 */

// ── Per-message token/cost snapshot ──────────────────────────────────────────

export interface ParsedMessage {
  /** ISO-8601 timestamp of this message */
  timestamp: string;
  /** Role: user | assistant | system | tool */
  role: "user" | "assistant" | "system" | "tool";
  /** Model used (e.g. "claude-opus-4-6", "gpt-4o") */
  model: string;
  /** Input/prompt tokens */
  inputTokens: number;
  /** Output/completion tokens */
  outputTokens: number;
  /** Cache-read tokens (already cached, cheaper) */
  cacheReadTokens: number;
  /** Cache-creation tokens (newly cached) */
  cacheCreationTokens: number;
  /** Calculated cost in USD for this message */
  costUsd: number;
}

// ── Session-level aggregate ──────────────────────────────────────────────────

export interface ToolSession {
  /** Which AI tool produced this session */
  tool: ToolName;
  /** Unique session ID (from the tool's own ID scheme) */
  sessionId: string;
  /** Absolute path to the source file */
  filePath: string;
  /** When the session started (ISO-8601) */
  startedAt: string;
  /** When the session ended (ISO-8601), or null if still active */
  endedAt: string | null;
  /** Working directory for this session */
  cwd: string;
  /** Git branch active during session */
  gitBranch: string;
  /** Tool version string */
  toolVersion: string;
  /** Primary model used */
  model: string;
  /** Provider (anthropic, openai, google, etc.) */
  provider: string;
  /** Total input tokens across all messages */
  totalInputTokens: number;
  /** Total output tokens across all messages */
  totalOutputTokens: number;
  /** Total cache-read tokens */
  totalCacheReadTokens: number;
  /** Total cache-creation tokens */
  totalCacheCreationTokens: number;
  /** Total cost in USD */
  totalCostUsd: number;
  /** Number of assistant turns (API calls) */
  turnCount: number;
  /** Individual messages with per-turn breakdown */
  messages: ParsedMessage[];
}

// ── Scan result ──────────────────────────────────────────────────────────────

export interface ScanResult {
  /** When the scan ran (ISO-8601) */
  scannedAt: string;
  /** How long the scan took (ms) */
  durationMs: number;
  /** Which tools were scanned */
  toolsScanned: ToolName[];
  /** Which tools had data found */
  toolsFound: ToolName[];
  /** All sessions discovered */
  sessions: ToolSession[];
  /** Aggregated totals */
  totals: ScanTotals;
  /** Per-tool summaries */
  byTool: Record<string, ToolSummary>;
  /** Errors encountered (non-fatal) */
  errors: ScanError[];
}

export interface ScanTotals {
  totalSessions: number;
  totalTurns: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCostUsd: number;
}

export interface ToolSummary {
  tool: ToolName;
  sessions: number;
  turns: number;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  models: string[];
  oldestSession: string;
  newestSession: string;
}

export interface ScanError {
  tool: ToolName;
  file: string;
  error: string;
}

// ── Scanner plugin interface ─────────────────────────────────────────────────

export interface ScannerPlugin {
  /** Tool name */
  name: ToolName;
  /** Human-readable display name */
  displayName: string;
  /** Description of where data lives */
  description: string;
  /** Check if this tool's data directory exists */
  detect(): Promise<boolean>;
  /** Scan all sessions, optionally filtered by time range */
  scan(options?: ScanOptions): Promise<ToolSession[]>;
}

export interface ScanOptions {
  /** Only include sessions after this date (ISO-8601) */
  since?: string;
  /** Only include sessions before this date (ISO-8601) */
  until?: string;
  /** Maximum sessions to return (newest first) */
  limit?: number;
  /** Include per-message breakdown (default: true) */
  includeMessages?: boolean;
}

// ── Supported tools ──────────────────────────────────────────────────────────

export type ToolName =
  | "claude-code"
  | "codex-cli"
  | "gemini-cli"
  | "cursor"
  | "roo-code"
  | "opencode"
  | "amp";
