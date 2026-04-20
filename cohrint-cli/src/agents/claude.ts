import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";
import { sanitizeAgentCommand, sanitizeAgentArgs } from "../sanitize.js";
import { detectBinary } from "./registry.js";

export const claudeAdapter: AgentAdapter = {
  name: "claude",
  displayName: "Claude Code",
  binary: "claude",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,
  async detect() {
    return detectBinary("claude");
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "claude");
    const extraFlags = sanitizeAgentArgs(config?.extraFlags, "agent.extraFlags");
    return {
      command: cmd,
      args: ["--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = sanitizeAgentCommand(config?.command, "claude");
    const extraArgs = sanitizeAgentArgs(config?.args).filter((a) => a !== "-p");
    const extraFlags = sanitizeAgentArgs(config?.extraFlags, "agent.extraFlags");
    const resumeArgs = sessionId
      ? ["--resume", sessionId, ...extraArgs, "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt]
      : ["--continue", ...extraArgs, "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt];
    return {
      command: cmd,
      args: resumeArgs,
    };
  },
};
