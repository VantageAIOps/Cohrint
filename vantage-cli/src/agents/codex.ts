import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const codexAdapter: AgentAdapter = {
  name: "codex",
  displayName: "Codex CLI",
  binary: "codex",
  defaultModel: "gpt-4o",
  provider: "openai",

  async detect(): Promise<boolean> {
    try {
      execSync("which codex", { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, _config?: AgentConfig): SpawnArgs {
    return {
      command: "codex",
      args: [prompt],
    };
  },
};
