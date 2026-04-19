import { execSync } from "child_process";
import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";

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
    try {
      execSync("which claude", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    const extraFlags = config?.extraFlags ?? [];
    return {
      command: cmd,
      args: ["--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "claude";
    const extraArgs = config?.args?.filter((a) => a !== "-p") ?? [];
    const extraFlags = config?.extraFlags ?? [];
    const resumeArgs = sessionId
      ? ["--resume", sessionId, ...extraArgs, "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt]
      : ["--continue", ...extraArgs, "--verbose", "--output-format", "stream-json", ...extraFlags, "-p", prompt];
    return {
      command: cmd,
      args: resumeArgs,
    };
  },
};
