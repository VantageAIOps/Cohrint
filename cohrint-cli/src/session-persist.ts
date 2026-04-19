import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  unlinkSync,
  existsSync,
  renameSync,
} from "fs";
import { join } from "path";
import { homedir } from "os";

export interface PersistedState {
  sessionIds: Record<string, string>;
  allowedTools: string[];
}

function getVantageDir(): string {
  return join(homedir(), ".vantage");
}

function getStatePath(): string {
  return join(getVantageDir(), "session.json");
}

export function saveState(state: PersistedState): void {
  const dir = getVantageDir();
  mkdirSync(dir, { recursive: true });
  const path = getStatePath();
  const tmp = path + ".tmp";
  writeFileSync(tmp, JSON.stringify(state, null, 2), "utf-8");
  renameSync(tmp, path);
}

export function loadState(): PersistedState {
  const path = getStatePath();
  if (!existsSync(path)) return { sessionIds: {}, allowedTools: [] };
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      sessionIds:
        typeof parsed.sessionIds === "object" &&
        parsed.sessionIds !== null &&
        !Array.isArray(parsed.sessionIds)
          ? (parsed.sessionIds as Record<string, string>)
          : {},
      allowedTools: Array.isArray(parsed.allowedTools)
        ? (parsed.allowedTools as string[])
        : [],
    };
  } catch {
    return { sessionIds: {}, allowedTools: [] };
  }
}

export function clearState(): void {
  try {
    unlinkSync(getStatePath());
  } catch {}
}

export function migrateOldSessions(): void {
  const oldDir = join(getVantageDir(), "sessions");
  const oldFile = join(oldDir, "active.json");
  if (!existsSync(oldFile)) return;
  try {
    const raw = readFileSync(oldFile, "utf-8");
    const parsed = JSON.parse(raw);
    // Validate: must be a plain object mapping strings to strings.
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed)
    ) {
      unlinkSync(oldFile);
      return;
    }
    const oldIds: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "string") oldIds[k] = v;
    }
    const current = loadState();
    current.sessionIds = { ...current.sessionIds, ...oldIds };
    saveState(current);
    unlinkSync(oldFile);
  } catch {}
}
