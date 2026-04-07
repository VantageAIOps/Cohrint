/**
 * agent-config.ts — Read native agent config files for model/MCP/permission detection.
 * Currently supports Claude Code (~/.claude/settings.json).
 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

export interface ClaudeConfig {
  model?: string;
  mcpServers?: Record<string, unknown>;
  permissions?: Record<string, unknown>;
}

export function readClaudeConfig(): ClaudeConfig | null {
  const settingsPath = join(homedir(), ".claude", "settings.json");
  if (!existsSync(settingsPath)) return null;
  try {
    const raw = readFileSync(settingsPath, "utf-8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      model: typeof parsed.model === "string" ? parsed.model : undefined,
      mcpServers: typeof parsed.mcpServers === "object" && parsed.mcpServers !== null
        ? parsed.mcpServers as Record<string, unknown>
        : undefined,
      permissions: typeof parsed.permissions === "object" && parsed.permissions !== null
        ? parsed.permissions as Record<string, unknown>
        : undefined,
    };
  } catch {
    return null;
  }
}
