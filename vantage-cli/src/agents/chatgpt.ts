import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const chatgptAdapter: AgentAdapter = {
  name: "chatgpt",
  displayName: "ChatGPT CLI",
  binary: "chatgpt-cli",
  defaultModel: "gpt-4o",
  provider: "openai",

  async detect(): Promise<boolean> {
    try {
      execSync("which chatgpt-cli", { stdio: "ignore" });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, _config?: AgentConfig): SpawnArgs {
    return {
      command: "chatgpt-cli",
      args: [prompt],
    };
  },
};
