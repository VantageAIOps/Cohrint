import { execSync } from "node:child_process";
import type { AgentAdapter, AgentConfig, SpawnArgs } from "./types.js";

export const codexAdapter: AgentAdapter = {
  name: "codex",
  displayName: "Codex CLI",
  binary: "codex",
  defaultModel: "gpt-4o",
  provider: "openai",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,

  async detect(): Promise<boolean> {
    try {
      execSync("which codex", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },

  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "codex";
    const baseArgs = config?.args ?? [];
    return {
      command: cmd,
      args: [...baseArgs, prompt],
    };
  },

  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "codex";
    const extraArgs = config?.args ?? [];
    // Codex CLI supports --session <id> to resume a specific conversation.
    // Fall back to --continue if no session ID is available.
    // TODO: verify --session flag once Codex CLI stabilises its API.
    const resumeArgs = sessionId ? ["--session", sessionId] : ["--continue"];
    return {
      command: cmd,
      args: [...resumeArgs, ...extraArgs, prompt],
    };
  },
};
