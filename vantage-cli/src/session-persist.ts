/**
 * session-persist.ts — Persist session state across CLI restarts.
 * Stores { sessionIds, allowedTools } in ~/.vantage/session.json
 */
import { readFileSync, writeFileSync, mkdirSync, unlinkSync, existsSync, renameSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

export interface SessionState {
  /** Map of agentName → sessionId for --resume */
  sessionIds: Record<string, string>;
  /** Tools the user has permanently allowed (via "always" response) */
  allowedTools: string[];
}

function getVantageDir(): string {
  return join(homedir(), ".vantage");
}

function getStatePath(): string {
  return join(getVantageDir(), "session.json");
}

export function saveState(state: SessionState): void {
  const dir = getVantageDir();
  mkdirSync(dir, { recursive: true });
  const path = getStatePath();
  const tmp = path + ".tmp";
  writeFileSync(tmp, JSON.stringify(state, null, 2), "utf-8");
  renameSync(tmp, path);
}

export function loadState(): SessionState {
  const path = getStatePath();
  if (!existsSync(path)) return { sessionIds: {}, allowedTools: [] };
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      sessionIds: (typeof parsed.sessionIds === "object" && parsed.sessionIds !== null && !Array.isArray(parsed.sessionIds))
        ? parsed.sessionIds as Record<string, string>
        : {},
      allowedTools: Array.isArray(parsed.allowedTools) ? parsed.allowedTools as string[] : [],
    };
  } catch {
    return { sessionIds: {}, allowedTools: [] };
  }
}

export function clearState(): void {
  try { unlinkSync(getStatePath()); } catch { /* ok */ }
}

// Backward compat — remove old sessions dir if it exists
export function migrateOldSessions(): void {
  const oldDir = join(getVantageDir(), "sessions");
  const oldFile = join(oldDir, "active.json");
  if (!existsSync(oldFile)) return;
  try {
    const raw = readFileSync(oldFile, "utf-8");
    const oldIds = JSON.parse(raw) as Record<string, string>;
    const current = loadState();
    current.sessionIds = { ...current.sessionIds, ...oldIds };
    saveState(current);
    unlinkSync(oldFile);
  } catch { /* best effort */ }
}
