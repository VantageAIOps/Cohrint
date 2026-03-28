import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const claudeAdapter: AgentAdapter = {
  name: "claude",
  displayName: "Claude Code",
  binary: "claude",
  defaultModel: "claude-sonnet-4-6",
  provider: "anthropic",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,

  async detect(): Promise<boolean> {
    try {
      execSync("which claude", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "claude";
    const baseArgs = config?.args ?? ["-p"];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "claude";
    const extraArgs = config?.args?.filter(a => a !== "-p") ?? [];
    // Use --resume with session ID for reliable context (--continue picks up wrong conversation)
    const resumeArgs = sessionId
      ? ["--resume", sessionId, ...extraArgs, "-p", prompt]
      : ["--continue", ...extraArgs, "-p", prompt];
    return {
      command: cmd,
      args: resumeArgs,
    };
  },
};
