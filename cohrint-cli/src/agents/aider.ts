import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";
import { sanitizeAgentCommand, sanitizeAgentArgs } from "../sanitize.js";
import { detectBinary } from "./registry.js";

export const aiderAdapter: AgentAdapter = {
  name: "aider",
  displayName: "Aider",
  binary: "aider",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",
  interactiveArgs: [],
  exitCommand: "/quit",
  // Aider manages conversation history via git and in-repo files — there is no session ID concept.
  // Each invocation automatically continues from the current git/file state.
  supportsContinue: false,
  async detect() {
    return detectBinary("aider");
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "aider");
    const baseArgs =
      config?.args !== undefined ? sanitizeAgentArgs(config.args) : ["--message"];
    return {
      command: cmd,
      args: [...baseArgs, prompt, "--yes"],
    };
  },
};
