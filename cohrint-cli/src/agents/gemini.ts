import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";
import { sanitizeAgentCommand, sanitizeAgentArgs } from "../sanitize.js";
import { detectBinary } from "./registry.js";

export const geminiAdapter: AgentAdapter = {
  name: "gemini",
  displayName: "Gemini CLI",
  binary: "gemini",
  defaultModel: "gemini-2.0-flash",
  provider: "google",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,
  async detect() {
    return detectBinary("gemini");
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "gemini");
    const baseArgs =
      config?.args !== undefined ? sanitizeAgentArgs(config.args) : ["-p"];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, _sessionId?: string): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "gemini");
    const extraArgs = sanitizeAgentArgs(config?.args).filter((a) => a !== "-p");
    return {
      command: cmd,
      args: ["--resume", "latest", ...extraArgs, "-p", prompt],
    };
  },
};
