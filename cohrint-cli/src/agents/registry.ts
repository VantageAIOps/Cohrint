import { execFile } from "child_process";
import type { AgentConfig } from "../config.js";
import { claudeAdapter } from "./claude.js";
import { codexAdapter } from "./codex.js";
import { geminiAdapter } from "./gemini.js";
import { aiderAdapter } from "./aider.js";
import { chatgptAdapter } from "./chatgpt.js";

// Non-blocking binary detection. Synchronous spawn blocks the Node event loop
// for up to its timeout — on a system with a slow PATH entry (NFS mount,
// automount) the setup wizard would freeze. execFile (async) lets all five
// adapter checks truly run in parallel via Promise.all and yields the loop.
export function detectBinary(name: string): Promise<boolean> {
  if (!/^[A-Za-z0-9_\-.]{1,40}$/.test(name)) {
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    const child = execFile(
      process.platform === "win32" ? "where" : "which",
      [name],
      { timeout: 3_000, windowsHide: true },
      (err) => resolve(!err)
    );
    child.on("error", () => resolve(false));
  });
}

export interface SpawnArgs {
  command: string;
  args: string[];
  env?: Record<string, string>;
}

export interface AgentAdapter {
  name: string;
  displayName: string;
  binary: string;
  defaultModel: string;
  provider: string;
  interactiveArgs: string[];
  exitCommand: string;
  supportsContinue: boolean;
  detect(): Promise<boolean>;
  buildCommand(prompt: string, config?: AgentConfig): SpawnArgs;
  buildContinueCommand?(prompt: string, config?: AgentConfig, sessionId?: string): SpawnArgs;
}

export const ALL_AGENTS: AgentAdapter[] = [
  claudeAdapter,
  codexAdapter,
  geminiAdapter,
  aiderAdapter,
  chatgptAdapter,
];

export function getAgent(name: string): AgentAdapter | undefined {
  return ALL_AGENTS.find(
    (a) => a.name === name || a.displayName.toLowerCase() === name.toLowerCase()
  );
}

export interface DetectResult {
  agent: AgentAdapter;
  detected: boolean;
}

export async function detectAll(): Promise<DetectResult[]> {
  const results = await Promise.all(
    ALL_AGENTS.map(async (agent) => {
      try {
        return { agent, detected: await agent.detect() };
      } catch {
        return { agent, detected: false };
      }
    })
  );
  return results;
}
