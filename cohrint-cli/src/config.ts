import { readFileSync, writeFileSync, mkdirSync, existsSync, renameSync } from "fs";
import { join } from "path";
import { homedir } from "os";

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

export function loadConfig(): VantageConfig {
  if (!configExists()) {
    return { ...DEFAULT_CONFIG };
  }
  try {
    const raw = readFileSync(getConfigPath(), "utf-8");
    const parsed = JSON.parse(raw);
    return {
      ...DEFAULT_CONFIG,
      ...parsed,
      optimization: {
        ...DEFAULT_CONFIG.optimization,
        ...parsed.optimization ?? {},
      },
      tracking: {
        ...DEFAULT_CONFIG.tracking,
        ...parsed.tracking ?? {},
      },
    };
  } catch (err) {
    console.warn(`[vantage] Config corrupted, using defaults: ${err instanceof Error ? err.message : String(err)}`);
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(config: VantageConfig): void {
  try {
    const dir = getConfigDir();
    mkdirSync(dir, { recursive: true });
    const configPath = getConfigPath();
    const tmpPath = configPath + ".tmp";
    writeFileSync(tmpPath, JSON.stringify(config, null, 2), "utf-8");
    renameSync(tmpPath, configPath);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[vantage] Failed to save config: ${msg}`);
    throw err;
  }
}
