/**
 * session-persist.ts — Persist agent session IDs across CLI restarts.
 * Stores a simple JSON map { agentName: sessionId } in ~/.vantage/sessions/active.json
 */
import { readFileSync, writeFileSync, mkdirSync, unlinkSync, existsSync, renameSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

export function getSessionDir(): string {
  return join(homedir(), ".vantage", "sessions");
}

function getActivePath(): string {
  return join(getSessionDir(), "active.json");
}

export function saveSessionIds(sessions: Record<string, string>): void {
  const dir = getSessionDir();
  mkdirSync(dir, { recursive: true });
  const path = getActivePath();
  const tmp = path + ".tmp";
  writeFileSync(tmp, JSON.stringify(sessions, null, 2), "utf-8");
  renameSync(tmp, path);
}

export function loadSessionIds(): Record<string, string> {
  const path = getActivePath();
  if (!existsSync(path)) return {};
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, string>;
    }
    return {};
  } catch {
    return {};
  }
}

export function clearSessionIds(): void {
  const path = getActivePath();
  try {
    unlinkSync(path);
  } catch {
    // File doesn't exist — that's fine
  }
}
