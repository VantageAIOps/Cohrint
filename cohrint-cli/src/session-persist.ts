import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  unlinkSync,
  existsSync,
  renameSync,
  chmodSync,
} from "fs";
import { join } from "path";
import { homedir } from "os";
import { isValidSessionId } from "./runner.js";

export interface PersistedState {
  sessionIds: Record<string, string>;
  allowedTools: string[];
}

const ALLOWED_TOOL_RX = /^[A-Za-z_][A-Za-z0-9_():,*\s/\-.]{0,256}$/;
const MAX_TOOLS = 128;

function getVantageDir(): string {
  return join(homedir(), ".vantage");
}

function getStatePath(): string {
  return join(getVantageDir(), "session.json");
}

export function saveState(state: PersistedState): void {
  const dir = getVantageDir();
  mkdirSync(dir, { recursive: true });
  try { chmodSync(dir, 0o700); } catch {}
  const path = getStatePath();
  const tmp = path + ".tmp";
  if (existsSync(tmp)) {
    try { unlinkSync(tmp); } catch {}
  }
  try {
    writeFileSync(tmp, JSON.stringify(state, null, 2), { encoding: "utf-8", mode: 0o600 });
    renameSync(tmp, path);
    try { chmodSync(path, 0o600); } catch {}
  } catch (err) {
    try { unlinkSync(tmp); } catch {}
    throw err;
  }
}

export function loadState(): PersistedState {
  const path = getStatePath();
  if (!existsSync(path)) return { sessionIds: {}, allowedTools: [] };
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const rawIds =
      typeof parsed.sessionIds === "object" &&
      parsed.sessionIds !== null &&
      !Array.isArray(parsed.sessionIds)
        ? (parsed.sessionIds as Record<string, unknown>)
        : {};
    const sessionIds: Record<string, string> = {};
    for (const [k, v] of Object.entries(rawIds)) {
      if (typeof k !== "string" || k.length > 64) continue;
      if (isValidSessionId(v)) sessionIds[k] = v as string;
    }
    const rawTools = Array.isArray(parsed.allowedTools) ? parsed.allowedTools : [];
    const allowedTools: string[] = [];
    for (const t of rawTools) {
      if (typeof t !== "string") continue;
      if (!ALLOWED_TOOL_RX.test(t)) continue;
      allowedTools.push(t);
      if (allowedTools.length >= MAX_TOOLS) break;
    }
    return { sessionIds, allowedTools };
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
