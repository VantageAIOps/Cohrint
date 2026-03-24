import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const chatgptAdapter: AgentAdapter = {
  name: "chatgpt",
  displayName: "ChatGPT CLI",
  binary: "chatgpt-cli",
  defaultModel: "gpt-4o",
  provider: "openai",
  interactiveArgs: [],
  exitCommand: "/quit",

  async detect(): Promise<boolean> {
    try {
      execSync("which chatgpt-cli", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "chatgpt-cli";
    const baseArgs = config?.args ?? [];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },
};
