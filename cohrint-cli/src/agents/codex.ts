import { execSync } from "child_process";
import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";

export const codexAdapter: AgentAdapter = {
  name: "codex",
  displayName: "Codex CLI",
  binary: "codex",
  defaultModel: "gpt-4o",
  provider: "openai",
  interactiveArgs: [],
  exitCommand: "/quit",
  supportsContinue: true,
  async detect() {
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
      args: ["exec", ...baseArgs, prompt],
    };
  },
  buildContinueCommand(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs {
    const cmd = config?.command || "codex";
    const extraArgs = config?.args ?? [];
    const resumeArgs = sessionId ? ["resume", sessionId] : ["resume", "--last"];
    return {
      command: cmd,
      args: ["exec", ...resumeArgs, ...extraArgs, prompt],
    };
  },
};
