import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  existsSync,
  renameSync,
  chmodSync,
  unlinkSync,
  openSync,
  closeSync,
  statSync,
} from "fs";
import { join } from "path";
import { homedir } from "os";
import { sanitizeConfig } from "./sanitize.js";

export interface AgentConfig {
  command?: string;
  args?: string[];
  extraFlags?: string[];
  permissionMode?: string;
  allowedTools?: string[];
  [key: string]: unknown;
}

export interface VantageConfig {
  defaultAgent: string;
  agents: Record<string, AgentConfig>;
  vantageApiKey: string;
  vantageApiBase: string;
  privacy: string;
  optimization: {
    enabled: boolean;
  };
  tracking: {
    enabled: boolean;
    batchSize: number;
    flushInterval: number;
  };
  debug?: boolean;
}

export const DEFAULT_CONFIG: VantageConfig = {
  defaultAgent: "claude",
  agents: {},
  vantageApiKey: "",
  vantageApiBase: "https://api.cohrint.com",
  privacy: "anonymized",
  optimization: {
    enabled: true,
  },
  tracking: {
    enabled: true,
    batchSize: 10,
    flushInterval: 30000,
  },
};

export function getConfigDir(): string {
  return join(homedir(), ".vantage");
}

export function getConfigPath(): string {
  return join(getConfigDir(), "config.json");
}

function getConfigLockPath(): string {
  return join(getConfigDir(), "config.lock");
}

export function configExists(): boolean {
  return existsSync(getConfigPath());
}

const LOCK_TIMEOUT_MS = 3_000;
const LOCK_STALE_MS = 60_000;
const LOCK_RETRY_MS = 25;

function _busyWait(ms: number): void {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    // bounded by LOCK_TIMEOUT_MS — safe.
  }
}

// Advisory lock to serialize load-modify-save on config.json between concurrent
// CLI instances (e.g., two simultaneous /setup runs). Stale locks older than
// LOCK_STALE_MS are reaped so a prior crash doesn't wedge future writes.
function _acquireConfigLock(): number | null {
  _secureDir(getConfigDir());
  const lockPath = getConfigLockPath();
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  while (true) {
    try {
      return openSync(lockPath, "wx", 0o600);
    } catch (err: unknown) {
      const code = (err as { code?: string } | null)?.code;
      if (code !== "EEXIST") return null;
      try {
        const st = statSync(lockPath);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) {
          try { unlinkSync(lockPath); } catch {}
          continue;
        }
      } catch {}
      if (Date.now() >= deadline) return null;
      _busyWait(LOCK_RETRY_MS);
    }
  }
}

function _releaseConfigLock(fd: number | null): void {
  if (fd === null) return;
  try { closeSync(fd); } catch {}
  try { unlinkSync(getConfigLockPath()); } catch {}
}

function _secureDir(dir: string): void {
  mkdirSync(dir, { recursive: true });
  if (process.platform !== "win32") {
    try { chmodSync(dir, 0o700); } catch {}
  }
}

function _secureFile(path: string): void {
  if (process.platform !== "win32") {
    try { chmodSync(path, 0o600); } catch {}
  }
}

export function loadConfig(): VantageConfig {
  if (!configExists()) {
    return { ...DEFAULT_CONFIG };
  }
  let parsed: Record<string, unknown>;
  try {
    const raw = readFileSync(getConfigPath(), "utf-8");
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch (err) {
    // Only echo the error message for SyntaxError (safe: no path leak). For
    // any filesystem error (EACCES / ENOENT-race via symlink swap / etc.)
    // the error message can include the resolved absolute path, which is
    // noise at best and an info-leak at worst. Log a generic line instead.
    if (err instanceof SyntaxError) {
      console.warn(`[vantage] Config corrupted, using defaults: ${err.message}`);
    } else {
      console.warn(`[vantage] Config unreadable, using defaults`);
    }
    return { ...DEFAULT_CONFIG };
  }
  const merged: VantageConfig = {
    ...DEFAULT_CONFIG,
    ...parsed,
    optimization: {
      ...DEFAULT_CONFIG.optimization,
      ...((parsed.optimization as Record<string, unknown>) ?? {}),
    },
    tracking: {
      ...DEFAULT_CONFIG.tracking,
      ...((parsed.tracking as Record<string, unknown>) ?? {}),
    },
  } as VantageConfig;
  return sanitizeConfig(merged);
}

export function saveConfig(config: VantageConfig): void {
  const dir = getConfigDir();
  _secureDir(dir);
  const configPath = getConfigPath();
  const tmpPath = configPath + ".tmp";
  const lockFd = _acquireConfigLock();
  try {
    // Orphan-tmp cleanup: a prior crash between write and rename would have
    // left the API key sitting in a .tmp file. Unlink before we write ours.
    if (existsSync(tmpPath)) {
      try { unlinkSync(tmpPath); } catch {}
    }
    try {
      // O_EXCL ('wx') closes the TOCTOU window where an attacker could
      // symlink tmpPath to /etc/shadow or similar between our unlink and
      // our open — writeFileSync without 'wx' follows symlinks. 'wx' fails
      // with EEXIST if the path reappears, so we never write through one.
      writeFileSync(tmpPath, JSON.stringify(config, null, 2), { encoding: "utf-8", mode: 0o600, flag: "wx" });
      renameSync(tmpPath, configPath);
      _secureFile(configPath);
    } catch (err) {
      try { unlinkSync(tmpPath); } catch {}
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`[vantage] Failed to save config: ${msg}`);
      throw err;
    }
  } finally {
    _releaseConfigLock(lockFd);
  }
}
