import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const aiderAdapter: AgentAdapter = {
  name: "aider",
  displayName: "Aider",
  binary: "aider",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",
  interactiveArgs: [],
  exitCommand: "/quit",

  async detect(): Promise<boolean> {
    try {
      execSync("which aider", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "aider";
    const baseArgs = config?.args ?? ["--message"];
    return {
      command: cmd,
      args: [...baseArgs, prompt, "--yes"],
    };
  },
};
