import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const geminiAdapter: AgentAdapter = {
  name: "gemini",
  displayName: "Gemini CLI",
  binary: "gemini",
  defaultModel: "gemini-2.0-flash",
  provider: "google",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,

  async detect(): Promise<boolean> {
    try {
      execSync("which gemini", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "gemini";
    const baseArgs = config?.args ?? ["-p"];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "gemini";
    return {
      command: cmd,
      args: ["--continue", "-p", prompt],
    };
  },
};
