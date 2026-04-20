import { readFileSync, writeFileSync, mkdirSync, existsSync, renameSync, chmodSync } from "fs";
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

export function configExists(): boolean {
  return existsSync(getConfigPath());
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
    console.warn(`[vantage] Config corrupted, using defaults: ${err instanceof Error ? err.message : String(err)}`);
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
  try {
    const dir = getConfigDir();
    _secureDir(dir);
    const configPath = getConfigPath();
    const tmpPath = configPath + ".tmp";
    writeFileSync(tmpPath, JSON.stringify(config, null, 2), { encoding: "utf-8", mode: 0o600 });
    renameSync(tmpPath, configPath);
    _secureFile(configPath);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[vantage] Failed to save config: ${msg}`);
    throw err;
  }
}
