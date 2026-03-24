#!/usr/bin/env node
// Test harness for input classifier — called by pytest

// ── Input classification logic (mirrors input-classifier.ts) ──

const AGENT_COMMANDS = {
  claude: ["/compact", "/clear", "/diff", "/help", "/status", "/review", "/simplify",
           "/theme", "/model", "/memory", "/hooks", "/permissions", "/doctor"],
  gemini: ["/clear", "/compress", "/chat", "/help", "/stats", "/model", "/tools", "/memory"],
  aider: ["/clear", "/help", "/add", "/drop", "/ls", "/diff", "/undo", "/commit",
          "/run", "/test", "/model", "/map", "/tokens", "/settings"],
  codex: ["/clear", "/help", "/model", "/approval"],
  chatgpt: ["/clear", "/help", "/model", "/system"],
};

const VANTAGE_COMMANDS = [
  "/exit-session", "/exit", "/cost", "/summary", "/stats", "/budget",
  "/help", "/quit", "/opt-on", "/opt-off", "/opt-ask", "/opt-auto",
];

const SHORT_ANSWER_RE = /^(y|n|yes|no|ok|sure|cancel|abort|skip|retry|quit|exit|[0-9]+|\/[^\s]+\.[a-z]+|[a-z]:\\|~\/|\.\.?\/)$/i;

function looksStructured(text) {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true;
  if (trimmed.startsWith("```")) return true;
  if ((text.match(/https?:\/\//g) || []).length > 2) return true;
  if ((text.match(/[{}()\[\];=<>]/g) || []).length > text.length * 0.1) return true;
  return false;
}

function classifyInput(input, agentName) {
  const trimmed = input.trim();
  if (!trimmed) return "unknown";

  const firstWord = trimmed.split(/\s/)[0].toLowerCase();
  if (VANTAGE_COMMANDS.includes(firstWord)) return "vantage-command";

  if (trimmed.startsWith("/")) {
    const agentCmds = AGENT_COMMANDS[agentName] || [];
    if (agentCmds.includes(firstWord)) return "agent-command";
  }

  if (trimmed.startsWith("@") || trimmed.startsWith("!")) return "agent-command";
  if (SHORT_ANSWER_RE.test(trimmed)) return "short-answer";
  if (looksStructured(trimmed)) return "structured";

  const wordCount = trimmed.split(/\s+/).length;
  if (wordCount >= 5) return "prompt";
  return "short-answer";
}

// Optimizer (simplified version matching the real one)
const FILLER_PHRASES = [
  "i'd like you to", "i want you to", "i need you to",
  "could you please", "can you please", "please note that",
  "it is important to note that", "in order to", "due to the fact that",
];

function compress(text) {
  let out = text;
  for (const phrase of FILLER_PHRASES) {
    const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`\\b${escaped}\\b`, 'gi'), '');
  }
  out = out.replace(/\b(please|kindly|basically|essentially|actually|literally|obviously|clearly|simply|just|very|really|quite)\b/gi, '');
  out = out.replace(/\s{2,}/g, ' ').trim();
  return out;
}

function countTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.trim().split(/\s+/).filter(Boolean).length * 1.3);
}

function processInput(input, agentName, optMode) {
  const type = classifyInput(input, agentName);
  const result = { type, original: input, forwarded: input, optimized: false, savedTokens: 0, reverted: false };

  if (type !== "prompt") return result;
  if (optMode === "never") return result;

  try {
    const compressed = compress(input);
    const origTok = countTokens(input);
    const compTok = countTokens(compressed);
    const saved = origTok - compTok;
    const pct = origTok > 0 ? Math.round(saved / origTok * 100) : 0;

    if (saved < 3 || pct < 5) return result;
    if (!compressed || compressed.length < input.length * 0.2) {
      result.reverted = true;
      return result;
    }

    result.forwarded = compressed;
    result.optimized = true;
    result.savedTokens = saved;
  } catch {
    result.reverted = true;
  }

  return result;
}

// CLI interface
const cmd = process.argv[2];
const arg1 = process.argv[3] || "";
const arg2 = process.argv[4] || "claude";
const arg3 = process.argv[5] || "auto";

if (cmd === "classify") {
  console.log(JSON.stringify({ input: arg1, agent: arg2, type: classifyInput(arg1, arg2) }));
} else if (cmd === "process") {
  console.log(JSON.stringify(processInput(arg1, arg2, arg3)));
} else {
  console.log("Usage: node test-classifier.mjs <classify|process> <input> [agent] [optMode]");
}
