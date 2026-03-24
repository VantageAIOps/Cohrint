import type { AgentAdapter } from "./types.js";
import { claudeAdapter } from "./claude.js";
import { codexAdapter } from "./codex.js";
import { geminiAdapter } from "./gemini.js";
import { aiderAdapter } from "./aider.js";
import { chatgptAdapter } from "./chatgpt.js";

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

export async function detectAll(): Promise<{ agent: AgentAdapter; detected: boolean }[]> {
  const results = await Promise.all(
    ALL_AGENTS.map(async (agent) => ({
      agent,
      detected: await agent.detect(),
    }))
  );
  return results;
}
