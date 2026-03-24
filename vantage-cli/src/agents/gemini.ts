import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const geminiAdapter: AgentAdapter = {
  name: "gemini",
  displayName: "Gemini CLI",
  binary: "gemini",
  defaultModel: "gemini-2.0-flash",
  provider: "google",

  async detect(): Promise<boolean> {
    try {
      execSync("which gemini", { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, _config?: AgentConfig): SpawnArgs {
    return {
      command: "gemini",
      args: ["-p", prompt],
    };
  },
};
