import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  unlinkSync,
  existsSync,
  renameSync,
  chmodSync,
  openSync,
  closeSync,
  statSync,
} from "fs";
import { join } from "path";
import { homedir } from "os";
import { isValidSessionId } from "./runner.js";

export interface PersistedState {
  sessionIds: Record<string, string>;
  allowedTools: string[];
}

// Tight regex: no whitespace, bounded length. A prior permissive variant (with
// `\s` and 256-char ceiling) allowed a crafted session.json to smuggle flag
// fragments like "Bash --permission-mode bypassPermissions" into --allowedTools.
const ALLOWED_TOOL_RX = /^[A-Za-z_][A-Za-z0-9_():,*/\-.]{0,79}$/;
const MAX_TOOLS = 128;
const LOCK_TIMEOUT_MS = 3_000;
const LOCK_STALE_MS = 60_000;
const LOCK_RETRY_MS = 25;

function getVantageDir(): string {
  return join(homedir(), ".vantage");
}

function getStatePath(): string {
  return join(getVantageDir(), "session.json");
}

function getLockPath(): string {
  return join(getVantageDir(), "session.lock");
}

function sleepSync(ms: number): void {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    // busy-wait; lock waits are capped at LOCK_TIMEOUT_MS (3s) so this is bounded.
  }
}

// Advisory lock to serialize read-modify-write on session.json across concurrent
// CLI instances. Without this, two `cohrint` processes racing to persist their
// session IDs could silently stomp each other (last-writer-wins).
function acquireLock(): number | null {
  const dir = getVantageDir();
  mkdirSync(dir, { recursive: true });
  const lockPath = getLockPath();
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  while (true) {
    try {
      const fd = openSync(lockPath, "wx", 0o600);
      return fd;
    } catch (err: unknown) {
      const code = (err as { code?: string } | null)?.code;
      if (code !== "EEXIST") return null;
      // Reap stale locks (process crashed before releasing).
      try {
        const st = statSync(lockPath);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) {
          try { unlinkSync(lockPath); } catch {}
          continue;
        }
      } catch {}
      if (Date.now() >= deadline) return null;
      sleepSync(LOCK_RETRY_MS);
    }
  }
}

function releaseLock(fd: number | null): void {
  if (fd === null) return;
  try { closeSync(fd); } catch {}
  try { unlinkSync(getLockPath()); } catch {}
}

export function withStateLock<T>(fn: () => T): T {
  const fd = acquireLock();
  try {
    return fn();
  } finally {
    releaseLock(fd);
  }
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
    // O_EXCL ('wx') — see config.ts saveConfig for the TOCTOU rationale.
    writeFileSync(tmp, JSON.stringify(state, null, 2), { encoding: "utf-8", mode: 0o600, flag: "wx" });
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
      // Mirror loadState's guard — a crafted legacy file could smuggle a
      // string like "--resume" that later splices into spawn argv as the
      // sessionId positional. Only accept canonical UUIDs.
      if (typeof k !== "string" || k.length > 64) continue;
      if (isValidSessionId(v)) oldIds[k] = v as string;
    }
    withStateLock(() => {
      const current = loadState();
      current.sessionIds = { ...current.sessionIds, ...oldIds };
      saveState(current);
    });
    unlinkSync(oldFile);
  } catch {}
}
