import { execSync } from "child_process";
import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";
import { sanitizeAgentCommand } from "../sanitize.js";

export const chatgptAdapter: AgentAdapter = {
  name: "chatgpt",
  displayName: "ChatGPT CLI",
  binary: "chatgpt-cli",
  defaultModel: "gpt-4o",
  provider: "openai",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,
  async detect() {
    try {
      execSync("which chatgpt-cli", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "chatgpt-cli");
    const baseArgs = config?.args ?? [];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "chatgpt-cli");
    const extraArgs = config?.args ?? [];
    const resumeArgs = sessionId ? ["--conversation", sessionId] : ["--continue"];
    return {
      command: cmd,
      args: [...resumeArgs, ...extraArgs, prompt],
    };
  },
};
