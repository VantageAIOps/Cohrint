import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const aiderAdapter: AgentAdapter = {
  name: "aider",
  displayName: "Aider",
  binary: "aider",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",

  async detect(): Promise<boolean> {
    try {
      execSync("which aider", { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, _config?: AgentConfig): SpawnArgs {
    return {
      command: "aider",
      args: ["--message", prompt, "--yes"],
    };
  },
};
