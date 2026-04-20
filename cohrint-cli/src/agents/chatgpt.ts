import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";
import { sanitizeAgentCommand, sanitizeAgentArgs } from "../sanitize.js";
import { detectBinary } from "./registry.js";

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
    return detectBinary("chatgpt-cli");
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "chatgpt-cli");
    const baseArgs = sanitizeAgentArgs(config?.args);
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "chatgpt-cli");
    const extraArgs = sanitizeAgentArgs(config?.args);
    const resumeArgs = sessionId ? ["--conversation", sessionId] : ["--continue"];
    return {
      command: cmd,
      args: [...resumeArgs, ...extraArgs, prompt],
    };
  },
};
