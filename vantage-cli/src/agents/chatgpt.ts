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
  supportsContinue: true,

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

  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "chatgpt-cli";
    const extraArgs = config?.args ?? [];
    // chatgpt-cli does not expose a documented --continue or --session flag.
    // TODO: update resumeArgs once the chatgpt-cli project settles on a session resume API.
    // For now we pass --continue as a best-effort fallback.
    const resumeArgs = sessionId ? ["--conversation", sessionId] : ["--continue"];
    return {
      command: cmd,
      args: [...resumeArgs, ...extraArgs, prompt],
    };
  },
};
