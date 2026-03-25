/**
 * Agent-Aware Live Recommendation Engine
 * Provides specific, actionable tips tailored to the agent being used.
 */

export interface SessionMetrics {
  agent?: string;
  model?: string;
  promptCount: number;
  totalCostUsd: number;
  totalInputTokens: number;
  totalOutputTokens: number;
  totalCachedTokens: number;
  avgLatencyMs?: number;
  avgCostPerPrompt?: number;
  lastPromptCostUsd?: number;
  lastPromptTokens?: number;
  sessionDurationMin?: number;
  sessionStartTime?: number;
}

export interface Recommendation {
  id: string;
  priority: "critical" | "high" | "medium" | "low";
  agent: string;      // specific agent or "all"
  category: "model" | "cache" | "prompt" | "workflow" | "budget";
  title: string;
  action: string;     // specific command or action to take
  savingsEstimate: string;  // e.g. "~30% cost reduction"
  condition: (m: SessionMetrics) => boolean;
}

// ── Agent-Specific Tip Database ─────────────────────────────────────────

const AGENT_TIPS: Recommendation[] = [
  // ── Claude Code ──
  {
    id: "claude-use-sonnet",
    priority: "high",
    agent: "claude",
    category: "model",
    title: "Switch to Sonnet for this session",
    action: "Run: /model sonnet — Opus costs 5x more. Use Opus only for complex multi-file architecture.",
    savingsEstimate: "~60% cost reduction",
    condition: (m) => m.agent === "claude" && (m.model ?? "").includes("opus") && m.avgCostPerPrompt < 0.50,
  },
  {
    id: "claude-use-haiku",
    priority: "medium",
    agent: "claude",
    category: "model",
    title: "Use Haiku for simple edits",
    action: "Run: /model haiku — Best for formatting, linting, docstrings, and simple fixes.",
    savingsEstimate: "~80% cost reduction vs Sonnet",
    condition: (m) => m.agent === "claude" && m.lastPromptTokens < 500 && m.promptCount > 3,
  },
  {
    id: "claude-compact",
    priority: "high",
    agent: "claude",
    category: "cache",
    title: "Run /compact to reduce context",
    action: "Run: /compact — Your session has grown large. Compact before next edit to save tokens.",
    savingsEstimate: "~40% on subsequent prompts",
    condition: (m) => m.agent === "claude" && m.totalInputTokens > 50000 && m.promptCount > 5,
  },
  {
    id: "claude-clear-session",
    priority: "medium",
    agent: "claude",
    category: "workflow",
    title: "Start fresh with /clear",
    action: "Run: /clear — Mixing unrelated tasks wastes context. Start a clean session for the new topic.",
    savingsEstimate: "~30-50% per session",
    condition: (m) => m.agent === "claude" && m.sessionDurationMin > 30 && m.promptCount > 15,
  },
  {
    id: "claude-use-bang",
    priority: "low",
    agent: "claude",
    category: "workflow",
    title: "Use ! prefix for shell commands",
    action: "Type: ! ls, ! git status — Direct execution skips Claude's reasoning about what command to run.",
    savingsEstimate: "~30-50% on command-heavy tasks",
    condition: (m) => m.agent === "claude" && m.promptCount > 3,
  },
  {
    id: "claude-prompt-caching",
    priority: "high",
    agent: "claude",
    category: "cache",
    title: "Enable prompt caching for large context",
    action: "Prompt caching gives 90% savings on repeated context. Structure system prompts for cache reuse.",
    savingsEstimate: "~90% on cached tokens",
    condition: (m) => m.agent === "claude" && m.totalCachedTokens < m.totalInputTokens * 0.1 && m.totalInputTokens > 20000,
  },

  // ── Gemini CLI ──
  {
    id: "gemini-use-flash",
    priority: "high",
    agent: "gemini",
    category: "model",
    title: "Use Flash instead of Pro",
    action: "Gemini Flash beats Pro on coding benchmarks (78% vs 76.2%) at 10x lower cost. Default to Flash.",
    savingsEstimate: "~90% cost reduction",
    condition: (m) => m.agent === "gemini" && (m.model ?? "").includes("pro"),
  },
  {
    id: "gemini-free-tier",
    priority: "critical",
    agent: "gemini",
    category: "budget",
    title: "You may be on the free tier",
    action: "Gemini CLI gets 60 RPM / 1,000 requests/day FREE. Verify your billing — you might not need to pay at all.",
    savingsEstimate: "~100% for light usage",
    condition: (m) => m.agent === "gemini" && m.totalCostUsd < 1.00 && m.promptCount < 50,
  },
  {
    id: "gemini-context-cache",
    priority: "medium",
    agent: "gemini",
    category: "cache",
    title: "Enable context caching",
    action: "Run: /compress or configure context caching in ~/.gemini/settings.json. Reduces costs by 75% for repeated codebase queries.",
    savingsEstimate: "~75% on subsequent queries",
    condition: (m) => m.agent === "gemini" && m.totalInputTokens > 30000 && m.totalCachedTokens < m.totalInputTokens * 0.2,
  },
  {
    id: "gemini-batch",
    priority: "low",
    agent: "gemini",
    category: "workflow",
    title: "Batch non-urgent analysis tasks",
    action: "Use batch API for code analysis, bulk test generation. Accepts 24h latency for 50% discount.",
    savingsEstimate: "~50% on batch-eligible tasks",
    condition: (m) => m.agent === "gemini" && m.promptCount > 10,
  },

  // ── Codex CLI ──
  {
    id: "codex-use-mini",
    priority: "high",
    agent: "codex",
    category: "model",
    title: "Use codex-mini for routine tasks",
    action: "codex-mini-latest ($1.50/$6.00 per 1M) is purpose-built for code. Reserve full GPT for complex reasoning.",
    savingsEstimate: "~70% cost reduction",
    condition: (m) => m.agent === "codex" && ((m.model ?? "").includes("gpt-4") || (m.model ?? "").includes("gpt-5") || (m.model ?? "").includes("o3")),
  },
  {
    id: "codex-selective-context",
    priority: "medium",
    agent: "codex",
    category: "prompt",
    title: "Be selective with file context",
    action: "Don't send entire files. Specify function names or line ranges. Each file adds thousands of tokens.",
    savingsEstimate: "~40-60% on large repos",
    condition: (m) => m.agent === "codex" && m.lastPromptTokens > 8000,
  },
  {
    id: "codex-prompt-cache",
    priority: "medium",
    agent: "codex",
    category: "cache",
    title: "Leverage OpenAI prompt caching",
    action: "Structure prompts with consistent system messages. Cached input tokens cost 50% less on OpenAI.",
    savingsEstimate: "~50% on cached tokens",
    condition: (m) => m.agent === "codex" && m.totalCachedTokens < m.totalInputTokens * 0.15,
  },

  // ── Aider ──
  {
    id: "aider-use-diff",
    priority: "critical",
    agent: "aider",
    category: "prompt",
    title: "Switch to diff edit format",
    action: "Run: /chat-mode diff — The 'whole' format returns entire files for every edit. 'diff' only returns changed lines.",
    savingsEstimate: "~60-80% output token reduction",
    condition: (m) => m.agent === "aider" && m.totalOutputTokens > m.totalInputTokens * 2,
  },
  {
    id: "aider-deepseek",
    priority: "high",
    agent: "aider",
    category: "model",
    title: "Try DeepSeek for budget tasks",
    action: "DeepSeek V3 ($1.27/1M) achieves 55% benchmark accuracy vs Sonnet's 60%. Great for routine edits.",
    savingsEstimate: "~75% cost reduction vs Sonnet",
    condition: (m) => m.agent === "aider" && (m.model ?? "").includes("claude") && m.avgCostPerPrompt > 0.02,
  },
  {
    id: "aider-selective-add",
    priority: "medium",
    agent: "aider",
    category: "workflow",
    title: "Only /add files you need edited",
    action: "Run: /add specific_file.py — Don't add entire directories. Each file consumes tokens on every prompt.",
    savingsEstimate: "~30-50% context reduction",
    condition: (m) => m.agent === "aider" && m.totalInputTokens > 40000,
  },
  {
    id: "aider-repo-map",
    priority: "medium",
    agent: "aider",
    category: "cache",
    title: "Optimize repo-map token budget",
    action: "Use --map-tokens to cap repo-map size. Default varies by model — lower it for cheaper sessions.",
    savingsEstimate: "~20-40% input token reduction",
    condition: (m) => m.agent === "aider" && m.promptCount > 5,
  },

  // ── ChatGPT / Cursor ──
  {
    id: "cursor-use-auto",
    priority: "critical",
    agent: "chatgpt",
    category: "model",
    title: "Use Auto mode in Cursor",
    action: "Switch to Auto mode — it's unlimited and free. Only use premium models for tasks Auto can't handle.",
    savingsEstimate: "~100% on Auto-eligible tasks",
    condition: (m) => m.agent === "chatgpt" && m.totalCostUsd > 0.10,
  },
  {
    id: "cursor-cmd-k",
    priority: "high",
    agent: "chatgpt",
    category: "workflow",
    title: "Use Cmd+K instead of Composer",
    action: "Cmd+K is lean and fast. Composer reads multiple files and burns 5-10x more tokens per operation.",
    savingsEstimate: "~80% per edit operation",
    condition: (m) => m.agent === "chatgpt" && m.avgCostPerPrompt > 0.05,
  },
  {
    id: "cursor-at-refs",
    priority: "medium",
    agent: "chatgpt",
    category: "prompt",
    title: "Use @ references instead of pasting code",
    action: "Type @filename to reference code. Don't paste blocks into chat — @ saves tokens and is more precise.",
    savingsEstimate: "~30-50% token reduction",
    condition: (m) => m.agent === "chatgpt" && m.lastPromptTokens > 3000,
  },

  // ── Universal Tips (all agents) ──
  {
    id: "all-high-cost-alert",
    priority: "critical",
    agent: "all",
    category: "budget",
    title: "Session cost is high",
    action: "Your session has spent ${cost}. Consider switching to a cheaper model or starting a fresh session.",
    savingsEstimate: "Prevent budget overrun",
    condition: (m) => m.totalCostUsd > 5.00,
  },
  {
    id: "all-cost-per-prompt",
    priority: "high",
    agent: "all",
    category: "budget",
    title: "Average cost per prompt is high",
    action: "At ${avg}/prompt, consider a cheaper model. Run /compare to find the best price/quality ratio.",
    savingsEstimate: "Varies by model switch",
    condition: (m) => m.avgCostPerPrompt > 0.20 && m.promptCount > 3,
  },
  {
    id: "all-large-prompt",
    priority: "medium",
    agent: "all",
    category: "prompt",
    title: "Last prompt was very large",
    action: "Your last prompt used ${tokens} tokens. Break large requests into smaller, focused prompts.",
    savingsEstimate: "~20-40% by reducing context",
    condition: (m) => m.lastPromptTokens > 10000,
  },
  {
    id: "all-low-cache",
    priority: "medium",
    agent: "all",
    category: "cache",
    title: "Cache utilization is low",
    action: "Only ${pct}% of tokens are cached. Standardize system prompts and reuse context for better cache hits.",
    savingsEstimate: "~30-50% with better caching",
    condition: (m) => m.totalInputTokens > 10000 && m.totalCachedTokens < m.totalInputTokens * 0.15,
  },
];

/**
 * Get relevant recommendations for the current session.
 * Returns top N tips sorted by priority, filtered by agent.
 */
export function getRecommendations(metrics: SessionMetrics, maxTips: number = 3): Recommendation[] {
  // Fill in computed/optional fields so conditions never see undefined
  const durationMin = metrics.sessionDurationMin ?? (metrics.sessionStartTime ? (Date.now() - metrics.sessionStartTime) / 60000 : 0);
  const avgCost = metrics.avgCostPerPrompt ?? (metrics.promptCount > 0 ? metrics.totalCostUsd / metrics.promptCount : 0);
  const filled: SessionMetrics = {
    ...metrics,
    agent: metrics.agent ?? "unknown",
    model: metrics.model ?? "unknown",
    avgCostPerPrompt: avgCost,
    avgLatencyMs: metrics.avgLatencyMs ?? 0,
    lastPromptCostUsd: metrics.lastPromptCostUsd ?? avgCost,
    lastPromptTokens: metrics.lastPromptTokens ?? 0,
    sessionDurationMin: durationMin,
  };
  const agentName = normalizeAgentName(filled.agent ?? "unknown");
  const applicable = AGENT_TIPS.filter(tip => {
    if (tip.agent !== "all" && tip.agent !== agentName) return false;
    try { return tip.condition(filled); } catch { return false; }
  });

  const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  applicable.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);

  return applicable.slice(0, maxTips).map(tip => ({
    ...tip,
    action: tip.action
      .replace("${cost}", `$${filled.totalCostUsd.toFixed(2)}`)
      .replace("${avg}", `$${(filled.avgCostPerPrompt ?? 0).toFixed(3)}`)
      .replace("${tokens}", (filled.lastPromptTokens ?? 0).toLocaleString())
      .replace("${pct}", Math.round((filled.totalCachedTokens / Math.max(filled.totalInputTokens, 1)) * 100).toString()),
  }));
}

/**
 * Get a single one-liner tip for inline display after each prompt.
 */
export function getInlineTip(metrics: SessionMetrics): string | null {
  const tips = getRecommendations(metrics, 1);
  if (tips.length === 0) return null;
  const tip = tips[0];
  const icon = tip.priority === "critical" ? "🔴" : tip.priority === "high" ? "🟡" : "💡";
  return `${icon} ${tip.title}: ${tip.action} (${tip.savingsEstimate})`;
}

function normalizeAgentName(agent: string | undefined): string {
  if (!agent) return "unknown";
  const lower = agent.toLowerCase();
  if (lower.includes("claude")) return "claude";
  if (lower.includes("gemini")) return "gemini";
  if (lower.includes("codex") || lower.includes("openai")) return "codex";
  if (lower.includes("aider")) return "aider";
  if (lower.includes("cursor") || lower.includes("chatgpt") || lower.includes("gpt")) return "chatgpt";
  return lower;
}

/**
 * Format recommendations for CLI display.
 */
export function formatRecommendations(tips: Recommendation[]): string {
  if (tips.length === 0) return "";
  const lines = ["\n  ┌─ Live Recommendations ─────────────────────────────"];
  for (const tip of tips) {
    const icon = tip.priority === "critical" ? "🔴" : tip.priority === "high" ? "🟡" : tip.priority === "medium" ? "💡" : "ℹ";
    const cat = `[${tip.category.toUpperCase()}]`;
    lines.push(`  │ ${icon} ${cat} ${tip.title}`);
    lines.push(`  │   → ${tip.action}`);
    lines.push(`  │   Savings: ${tip.savingsEstimate}`);
    lines.push(`  │`);
  }
  lines.push("  └────────────────────────────────────────────────────\n");
  return lines.join("\n");
}
