import { optimizePrompt, type OptimizationResult } from "./optimizer.js";
import { dim, green, yellow } from "./ui.js";

/** Input classification result */
export type InputType =
  | "prompt"         // Natural language prompt — optimize
  | "short-answer"   // y/n/yes/no/1/2/path — passthrough
  | "agent-command"  // /compact, /clear, @file, !cmd — passthrough
  | "vantage-command" // /cost, /summary, /exit-session — handle internally
  | "structured"     // JSON, code, URLs — passthrough (don't corrupt)
  | "unknown";       // Can't classify — passthrough to be safe

/** User's optimization preference for the session */
export type OptMode = "auto" | "always" | "never" | "ask";

export interface ProcessedInput {
  type: InputType;
  original: string;
  forwarded: string;       // What gets sent to agent (may be optimized)
  optimized: boolean;      // Was optimization applied?
  savedTokens: number;     // Tokens saved (0 if not optimized)
  reverted: boolean;       // Did we revert due to error?
}

/** Known agent commands per tool */
const AGENT_COMMANDS: Record<string, string[]> = {
  claude: ["/compact", "/clear", "/diff", "/help", "/status", "/review", "/simplify",
           "/theme", "/model", "/memory", "/hooks", "/permissions", "/doctor", "/login",
           "/logout", "/config", "/cost", "/vim", "/terminal-setup", "/btw", "/mcp",
           "/install-github-app", "/listen"],
  gemini: ["/clear", "/compress", "/chat", "/help", "/stats", "/model", "/tools", "/memory",
           "/restore", "/search", "/mcp"],
  aider: ["/clear", "/help", "/add", "/drop", "/ls", "/diff", "/undo", "/commit",
          "/run", "/test", "/model", "/map", "/tokens", "/settings", "/reset",
          "/architect", "/ask", "/code", "/voice"],
  codex: ["/clear", "/help", "/model", "/approval"],
  chatgpt: ["/clear", "/help", "/model", "/system"],
};

/** Vantage internal commands */
const VANTAGE_COMMANDS = [
  "/exit-session", "/exit", "/cost", "/summary", "/stats", "/budget",
  "/help", "/quit", "/opt-on", "/opt-off", "/opt-ask", "/opt-auto",
  "/opt-never", "/opt-always", "/agents", "/status",
];

/** Short answer patterns — y/n, numbers, paths, single words */
const SHORT_ANSWER_RE = /^(y|n|yes|no|ok|sure|cancel|abort|skip|retry|quit|exit|[0-9]+|\/[^\s]+\.[a-z]+|[a-z]:\\|~\/|\.\.?\/)$/i;

/**
 * Classify user input to decide how to handle it.
 */
export function classifyInput(input: string, agentName: string): InputType {
  const trimmed = input.trim();
  if (!trimmed) return "unknown";

  // Vantage internal commands
  const firstWord = trimmed.split(/\s/)[0].toLowerCase();
  if (VANTAGE_COMMANDS.includes(firstWord)) return "vantage-command";

  // Agent slash commands
  if (trimmed.startsWith("/")) {
    const agentCmds = AGENT_COMMANDS[agentName] || [];
    if (agentCmds.includes(firstWord)) return "agent-command";
  }

  // @ file references and ! shell commands
  if (trimmed.startsWith("@") || trimmed.startsWith("!")) return "agent-command";

  // Short answers (y/n/numbers/paths)
  if (SHORT_ANSWER_RE.test(trimmed)) return "short-answer";

  // Structured data (JSON, code, URL-heavy)
  if (looksStructured(trimmed)) return "structured";

  // Natural language — candidate for optimization
  const wordCount = trimmed.split(/\s+/).length;
  if (wordCount >= 5) return "prompt";

  // Very short (1-4 words) — treat as short answer
  return "short-answer";
}

/** Detect structured data that should not be optimized */
function looksStructured(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true;
  if (trimmed.startsWith("```")) return true;
  if ((text.match(/https?:\/\//g) || []).length > 2) return true;
  if ((text.match(/[{}()\[\];=<>]/g) || []).length > text.length * 0.1) return true;
  return false;
}

/**
 * Process input through the smart pipeline.
 * Returns what should be forwarded to the agent.
 */
export function processInput(
  input: string,
  agentName: string,
  optMode: OptMode,
): ProcessedInput {
  const type = classifyInput(input, agentName);
  const result: ProcessedInput = {
    type,
    original: input,
    forwarded: input,
    optimized: false,
    savedTokens: 0,
    reverted: false,
  };

  // Only optimize "prompt" type inputs
  if (type !== "prompt") return result;

  // Check user preference
  if (optMode === "never") return result;

  // Try optimization
  try {
    const opt = optimizePrompt(input);

    // Skip if no meaningful savings (<3 tokens or <5%)
    if (opt.savedTokens < 3 || opt.savedPercent < 5) return result;

    // Validate: optimized version should not be empty or drastically different
    if (!opt.optimized || opt.optimized.length < input.length * 0.2) {
      // Optimization removed too much — revert
      result.reverted = true;
      console.log(dim("  [opt] Reverted: optimization removed >80% of content"));
      return result;
    }

    // Apply optimization
    result.forwarded = opt.optimized;
    result.optimized = true;
    result.savedTokens = opt.savedTokens;

  } catch (err) {
    // Optimization failed — revert to original, log error
    result.reverted = true;
    const msg = err instanceof Error ? err.message : String(err);
    console.log(dim(`  [opt] Reverted: ${msg}`));
  }

  return result;
}

/** Print optimization status line */
export function printOptStatus(result: ProcessedInput): void {
  if (result.reverted) {
    console.log(dim("  < Optimization reverted -- using original prompt"));
  } else if (result.optimized && result.savedTokens > 0) {
    console.log(green(`  Optimized: saved ${result.savedTokens} tokens`));
  }
  // No message for non-prompt inputs (silent passthrough)
}

/** Check if a command is an agent in-house command */
export function isAgentCommand(agentName: string, input: string): boolean {
  const trimmed = input.trim();
  if (trimmed.startsWith("/")) {
    const cmd = trimmed.split(/\s/)[0].toLowerCase();
    const agentCmds = AGENT_COMMANDS[agentName] || [];
    if (agentCmds.includes(cmd)) return true;
  }
  if (trimmed.startsWith("@")) return true;
  if (trimmed.startsWith("!")) return true;
  return false;
}
