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
    const extraFlags = config?.extraFlags ?? [];
    // --output-format stream-json (no --verbose): emits complete content-block
    // objects per line.  Adding --verbose can trigger Anthropic API-style
    // streaming deltas (content_block_delta) that our ClaudeStreamRenderer
    // cannot reassemble, silencing all live tool output.
    // -p must immediately precede the prompt.
    return {
      command: cmd,
      args: ["--output-format", "stream-json", ...extraFlags, "-p", prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "claude";
    const extraArgs = config?.args?.filter(a => a !== "-p") ?? [];
    const extraFlags = config?.extraFlags ?? [];
    // Use --resume with session ID for reliable context (--continue picks up wrong conversation)
    const resumeArgs = sessionId
      ? ["--resume", sessionId, ...extraArgs, "--output-format", "stream-json", ...extraFlags, "-p", prompt]
      : ["--continue", ...extraArgs, "--output-format", "stream-json", ...extraFlags, "-p", prompt];
    return {
      command: cmd,
      args: resumeArgs,
    };
  },
};
