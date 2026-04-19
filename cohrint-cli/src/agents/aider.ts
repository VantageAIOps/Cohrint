import { execSync } from "child_process";
import type { AgentAdapter, SpawnArgs } from "./registry.js";
import type { AgentConfig } from "../config.js";

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
    try {
      execSync("which aider", { stdio: "ignore", timeout: 5000 });
      return true;
    } catch {
      return false;
    }
  },
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs {
    const cmd = config?.command || "aider";
    const baseArgs = config?.args ?? ["--message"];
    return {
      command: cmd,
      args: [...baseArgs, prompt, "--yes"],
    };
  },
};
