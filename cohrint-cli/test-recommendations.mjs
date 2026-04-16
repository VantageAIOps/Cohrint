#!/usr/bin/env node
/**
 * test-recommendations.mjs — CLI harness for Suite 35 unit tests
 * Usage: node test-recommendations.mjs <cmd> <json-payload>
 *   cmd: "recommendations" | "inline_tip" | "normalize" | "format"
 * Outputs JSON to stdout.
 */

const AGENT_TIPS = [
  // ── Claude Code ──
  { id: "claude-use-sonnet", priority: "high", agent: "claude", category: "model",
    title: "Switch to Sonnet for this session",
    action: "Run: /model sonnet — Opus costs 5x more. Use Opus only for complex multi-file architecture.",
    savingsEstimate: "~60% cost reduction",
    // Only fire when hallucination_score is not high — cheaper model with bad quality = worse outcome
    condition: (m) => m.agent === "claude" && (m.model ?? "").includes("opus")
      && (m.avgCostPerPrompt ?? 0) < 0.1
      && (m.avgHallucinationScore == null || m.avgHallucinationScore < 0.2) },
  { id: "claude-use-haiku", priority: "medium", agent: "claude", category: "model",
    title: "Use Haiku for simple edits",
    action: "Run: /model haiku — Best for formatting, linting, docstrings, and simple fixes.",
    savingsEstimate: "~80% cost reduction vs Sonnet",
    // Require actual low token usage AND low cost signal — not just "more than 3 prompts"
    // Do not fire when quality scores indicate accuracy issues (hallucination > 0.15)
    condition: (m) => m.agent === "claude" && (m.lastPromptTokens ?? 0) < 500
      && m.promptCount > 3 && (m.avgCostPerPrompt ?? 0) < 0.05
      && (m.avgHallucinationScore == null || m.avgHallucinationScore < 0.15) },
  { id: "claude-compact", priority: "high", agent: "claude", category: "cache",
    title: "Run /compact to reduce context",
    action: "Run: /compact — Your session has grown large. Compact before next edit to save tokens.",
    savingsEstimate: "~40% on subsequent prompts",
    condition: (m) => m.agent === "claude" && m.totalInputTokens > 50000 && m.promptCount > 5 },
  { id: "claude-clear-session", priority: "medium", agent: "claude", category: "workflow",
    title: "Start fresh with /clear",
    action: "Run: /clear — Mixing unrelated tasks wastes context. Start a clean session for the new topic.",
    savingsEstimate: "~30-50% per session",
    condition: (m) => m.agent === "claude" && (m.sessionDurationMin ?? 0) > 30 && m.promptCount > 15 },
  { id: "claude-use-bang", priority: "low", agent: "claude", category: "workflow",
    title: "Use ! prefix for shell commands",
    action: "Type: ! ls, ! git status — Direct execution skips Claude's reasoning about what command to run.",
    savingsEstimate: "~30-50% on command-heavy tasks",
    // Only meaningful when prompts are frequent AND average cost suggests shell-heavy workflow
    condition: (m) => m.agent === "claude" && m.promptCount > 10
      && (m.avgCostPerPrompt ?? 0) > 0.01 && (m.avgCostPerPrompt ?? 0) < 0.05 },
  { id: "claude-prompt-caching", priority: "high", agent: "claude", category: "cache",
    title: "Enable prompt caching for large context",
    action: "Prompt caching gives 90% savings on repeated context. Structure system prompts for cache reuse.",
    savingsEstimate: "~90% on cached tokens",
    condition: (m) => m.agent === "claude" && m.totalCachedTokens < m.totalInputTokens * 0.1 && m.totalInputTokens > 20000 },
  // ── Gemini CLI ──
  { id: "gemini-use-flash", priority: "high", agent: "gemini", category: "model",
    title: "Use Flash instead of Pro",
    action: "Gemini Flash beats Pro on coding benchmarks (78% vs 76.2%) at 10x lower cost. Default to Flash.",
    savingsEstimate: "~90% cost reduction",
    condition: (m) => m.agent === "gemini" && (m.model ?? "").includes("pro") },
  { id: "gemini-free-tier", priority: "medium", agent: "gemini", category: "budget",
    // Downgraded from critical — this is informational, not an active problem
    title: "You may qualify for Gemini free tier",
    action: "Gemini CLI gets 60 RPM / 1,000 requests/day FREE. Verify your billing — you might not need to pay at all.",
    savingsEstimate: "~100% for light usage",
    // Tighten condition: only fire after enough usage to know it's real spend, not trial
    condition: (m) => m.agent === "gemini" && m.totalCostUsd > 0.10 && m.totalCostUsd < 1 && m.promptCount >= 10 && m.promptCount < 50 },
  { id: "gemini-context-cache", priority: "medium", agent: "gemini", category: "cache",
    title: "Enable context caching",
    action: "Run: /compress or configure context caching in ~/.gemini/settings.json.",
    savingsEstimate: "~75% on subsequent queries",
    condition: (m) => m.agent === "gemini" && m.totalInputTokens > 30000 && m.totalCachedTokens < m.totalInputTokens * 0.2 },
  { id: "gemini-batch", priority: "low", agent: "gemini", category: "workflow",
    title: "Batch non-urgent analysis tasks",
    action: "Use batch API for code analysis, bulk test generation.",
    savingsEstimate: "~50% on batch-eligible tasks",
    condition: (m) => m.agent === "gemini" && m.promptCount > 10 },
  // ── Codex CLI ──
  { id: "codex-use-mini", priority: "high", agent: "codex", category: "model",
    title: "Use codex-mini for routine tasks",
    action: "codex-mini-latest is purpose-built for code. Reserve full GPT for complex reasoning.",
    savingsEstimate: "~70% cost reduction",
    condition: (m) => m.agent === "codex" && ((m.model ?? "").includes("gpt-4") || (m.model ?? "").includes("gpt-5") || (m.model ?? "").includes("o3")) },
  { id: "codex-selective-context", priority: "medium", agent: "codex", category: "prompt",
    title: "Be selective with file context",
    action: "Don't send entire files. Specify function names or line ranges.",
    savingsEstimate: "~40-60% on large repos",
    condition: (m) => m.agent === "codex" && (m.lastPromptTokens ?? 0) > 8000 },
  { id: "codex-prompt-cache", priority: "medium", agent: "codex", category: "cache",
    title: "Leverage OpenAI prompt caching",
    action: "Structure prompts with consistent system messages. Cached input tokens cost 50% less on OpenAI.",
    savingsEstimate: "~50% on cached tokens",
    condition: (m) => m.agent === "codex" && m.totalCachedTokens < m.totalInputTokens * 0.15 },
  // ── Aider ──
  { id: "aider-use-diff", priority: "critical", agent: "aider", category: "prompt",
    title: "Switch to diff edit format",
    action: "Run: /chat-mode diff — The 'whole' format returns entire files for every edit.",
    savingsEstimate: "~60-80% output token reduction",
    condition: (m) => m.agent === "aider" && m.totalOutputTokens > m.totalInputTokens * 2 },
  { id: "aider-deepseek", priority: "high", agent: "aider", category: "model",
    title: "Try DeepSeek for budget tasks",
    action: "DeepSeek V3 achieves 55% benchmark accuracy vs Sonnet's 60%. Great for routine edits.",
    savingsEstimate: "~75% cost reduction vs Sonnet",
    // Don't recommend cheaper model when hallucination is already high
    condition: (m) => m.agent === "aider" && (m.model ?? "").includes("claude")
      && (m.avgCostPerPrompt ?? 0) > 0.02
      && (m.avgHallucinationScore == null || m.avgHallucinationScore < 0.2) },
  { id: "aider-selective-add", priority: "medium", agent: "aider", category: "workflow",
    title: "Only /add files you need edited",
    action: "Run: /add specific_file.py — Don't add entire directories.",
    savingsEstimate: "~30-50% context reduction",
    condition: (m) => m.agent === "aider" && m.totalInputTokens > 40000 },
  { id: "aider-repo-map", priority: "medium", agent: "aider", category: "cache",
    title: "Optimize repo-map token budget",
    action: "Use --map-tokens to cap repo-map size.",
    savingsEstimate: "~20-40% input token reduction",
    condition: (m) => m.agent === "aider" && m.promptCount > 5 },
  // ── ChatGPT / Cursor ──
  { id: "cursor-use-auto", priority: "critical", agent: "chatgpt", category: "model",
    title: "Use Auto mode in Cursor",
    action: "Switch to Auto mode — it's unlimited and free.",
    savingsEstimate: "~100% on Auto-eligible tasks",
    condition: (m) => m.agent === "chatgpt" && m.totalCostUsd > 0.1 },
  { id: "cursor-cmd-k", priority: "high", agent: "chatgpt", category: "workflow",
    title: "Use Cmd+K instead of Composer",
    action: "Cmd+K is lean and fast. Composer reads multiple files and burns 5-10x more tokens.",
    savingsEstimate: "~80% per edit operation",
    condition: (m) => m.agent === "chatgpt" && (m.avgCostPerPrompt ?? 0) > 0.05 },
  { id: "cursor-at-refs", priority: "medium", agent: "chatgpt", category: "prompt",
    title: "Use @ references instead of pasting code",
    action: "Type @filename to reference code.",
    savingsEstimate: "~30-50% token reduction",
    condition: (m) => m.agent === "chatgpt" && (m.lastPromptTokens ?? 0) > 3000 },
  // ── GitHub Copilot ──
  { id: "copilot-use-inline", priority: "high", agent: "copilot", category: "workflow",
    title: "Prefer inline completions over Chat",
    action: "Inline completions use far fewer tokens than Copilot Chat. Reserve Chat for complex multi-file tasks.",
    savingsEstimate: "~60-80% per interaction",
    condition: (m) => m.agent === "copilot" && (m.avgCostPerPrompt ?? 0) > 0.03 },
  { id: "copilot-clear-signatures", priority: "medium", agent: "copilot", category: "prompt",
    title: "Write explicit function signatures",
    action: "Clear parameter names and return types give Copilot full context without needing large prompts.",
    savingsEstimate: "~30-40% token reduction",
    condition: (m) => m.agent === "copilot" && (m.lastPromptTokens ?? 0) > 2000 },
  { id: "copilot-scope-comments", priority: "medium", agent: "copilot", category: "prompt",
    title: "Use single-line scope comments",
    action: "A one-line // comment above the function is sufficient context. Multi-paragraph descriptions waste tokens.",
    savingsEstimate: "~20-30% on prompt tokens",
    condition: (m) => m.agent === "copilot" && m.promptCount > 5 && (m.avgCostPerPrompt ?? 0) > 0.01 },
  // ── Universal Tips ──
  { id: "all-high-cost-alert", priority: "critical", agent: "all", category: "budget",
    title: "Session cost is high",
    action: "Your session has spent ${cost}. Consider switching to a cheaper model or starting a fresh session.",
    savingsEstimate: "Prevent budget overrun",
    condition: (m) => m.totalCostUsd > 5 },
  { id: "all-cost-per-prompt", priority: "high", agent: "all", category: "budget",
    title: "Average cost per prompt is high",
    action: "At ${avg}/prompt, consider a cheaper model.",
    savingsEstimate: "Varies by model switch",
    condition: (m) => (m.avgCostPerPrompt ?? 0) > 0.2 && m.promptCount > 3 },
  { id: "all-large-prompt", priority: "medium", agent: "all", category: "prompt",
    title: "Last prompt was very large",
    action: "Your last prompt used ${tokens} tokens. Break large requests into smaller, focused prompts.",
    savingsEstimate: "~20-40% by reducing context",
    condition: (m) => (m.lastPromptTokens ?? 0) > 10000 },
  // Merged cache tip: only the agent-specific cache tip fires when applicable;
  // all-low-cache fires ONLY for agents without a dedicated cache tip (prevents double-tip)
  { id: "all-low-cache", priority: "medium", agent: "all", category: "cache",
    title: "Cache utilization is low",
    action: "Only ${pct}% of tokens are cached. Standardize system prompts for better cache hits.",
    savingsEstimate: "~30-50% with better caching",
    condition: (m) => m.totalInputTokens > 10000 && m.totalCachedTokens < m.totalInputTokens * 0.15
      // Suppress when an agent-specific cache tip already covers this (avoids duplicate advice)
      && !["claude", "gemini", "codex", "copilot", "aider", "chatgpt"].includes(m.agent) },
  // ── Quality / Hallucination alerts ──
  { id: "all-high-hallucination", priority: "critical", agent: "all", category: "quality",
    title: "High hallucination rate detected",
    action: "Your avg hallucination score is ${hallucination}. Add explicit grounding instructions and verify outputs before use. Avoid switching to a cheaper model until this is resolved.",
    savingsEstimate: "Prevents downstream errors",
    condition: (m) => (m.avgHallucinationScore ?? 0) > 0.2 },
  { id: "all-low-faithfulness", priority: "high", agent: "all", category: "quality",
    title: "Low faithfulness to source material",
    action: "Avg faithfulness score is ${faithfulness}. Add 'Answer only from the provided context.' to your system prompt.",
    savingsEstimate: "Reduces hallucinated references",
    condition: (m) => m.avgFaithfulnessScore != null && m.avgFaithfulnessScore < 0.7 },
  { id: "all-high-toxicity", priority: "critical", agent: "all", category: "quality",
    title: "Elevated toxicity detected",
    action: "Avg toxicity score is ${toxicity}. Review outputs and tighten system prompt safety constraints.",
    savingsEstimate: "Compliance risk reduction",
    condition: (m) => (m.avgToxicityScore ?? 0) > 0.15 },
];

function normalizeAgentName(agent) {
  if (!agent) return "unknown";
  const lower = agent.toLowerCase();
  if (lower.includes("claude")) return "claude";
  if (lower.includes("gemini")) return "gemini";
  if (lower.includes("codex") || lower.includes("openai")) return "codex";
  if (lower.includes("aider")) return "aider";
  if (lower.includes("cursor") || lower.includes("chatgpt") || lower.includes("gpt")) return "chatgpt";
  if (lower.includes("copilot")) return "copilot";
  return lower;
}

function getRecommendations(metrics, maxTips = 3) {
  const durationMin = metrics.sessionDurationMin ?? (metrics.sessionStartTime ? (Date.now() - metrics.sessionStartTime) / 60000 : 0);
  const avgCost = metrics.avgCostPerPrompt ?? (metrics.promptCount > 0 ? metrics.totalCostUsd / metrics.promptCount : 0);
  const agentName = normalizeAgentName(metrics.agent ?? "unknown");
  const filled = { ...metrics, agent: agentName, model: metrics.model ?? "unknown",
    avgCostPerPrompt: avgCost, avgLatencyMs: metrics.avgLatencyMs ?? 0,
    lastPromptCostUsd: metrics.lastPromptCostUsd ?? avgCost,
    lastPromptTokens: metrics.lastPromptTokens ?? 0, sessionDurationMin: durationMin,
    // Quality score fields — null when not yet scored
    avgHallucinationScore: metrics.avgHallucinationScore ?? null,
    avgFaithfulnessScore:  metrics.avgFaithfulnessScore  ?? null,
    avgToxicityScore:      metrics.avgToxicityScore       ?? null,
  };
  const applicable = AGENT_TIPS.filter((tip) => {
    if (tip.agent !== "all" && tip.agent !== agentName) return false;
    try { return tip.condition(filled); } catch { return false; }
  });
  const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  applicable.sort((a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]);
  return applicable.slice(0, maxTips).map((tip) => ({
    ...tip,
    action: tip.action
      .replace("${cost}", `$${filled.totalCostUsd.toFixed(2)}`)
      .replace("${avg}", `$${(filled.avgCostPerPrompt ?? 0).toFixed(3)}`)
      .replace("${tokens}", (filled.lastPromptTokens ?? 0).toLocaleString())
      .replace("${pct}", Math.round(filled.totalCachedTokens / Math.max(filled.totalInputTokens, 1) * 100).toString())
      .replace("${hallucination}", (filled.avgHallucinationScore ?? 0).toFixed(2))
      .replace("${faithfulness}", (filled.avgFaithfulnessScore ?? 0).toFixed(2))
      .replace("${toxicity}", (filled.avgToxicityScore ?? 0).toFixed(2))
  }));
}

function getInlineTip(metrics) {
  const tips = getRecommendations(metrics, 1);
  if (tips.length === 0) return null;
  const tip = tips[0];
  const icon = tip.priority === "critical" ? "🔴" : tip.priority === "high" ? "🟡" : "💡";
  return `${icon} ${tip.title}: ${tip.action} (${tip.savingsEstimate})`;
}

function formatRecommendations(tips) {
  if (tips.length === 0) return "";
  const lines = ["\n  ┌─ Live Recommendations ─────────────────────────────────────"];
  for (const tip of tips) {
    const icon = tip.priority === "critical" ? "🔴" : tip.priority === "high" ? "🟡" : tip.priority === "medium" ? "💡" : "ℹ";
    lines.push(`  │ ${icon} [${tip.category.toUpperCase()}] ${tip.title}`);
    lines.push(`  │   → ${tip.action}`);
    lines.push(`  │   Savings: ${tip.savingsEstimate}`);
    lines.push(`  │`);
  }
  lines.push("  └──────────────────────────────────────────────────────────────\n");
  return lines.join("\n");
}

// ── CLI entrypoint ────────────────────────────────────────────────────────────
const [,, cmd, payloadJson] = process.argv;
const payload = JSON.parse(payloadJson || "{}");
const metrics = payload.metrics ?? {};
const maxTips = payload.maxTips ?? 3;

switch (cmd) {
  case "recommendations": {
    const tips = getRecommendations(metrics, maxTips);
    console.log(JSON.stringify({
      count: tips.length,
      tips,
      ids: tips.map(t => t.id),
      priorities: tips.map(t => t.priority),
      actions: tips.map(t => t.action),
    }));
    break;
  }
  case "inline_tip": {
    const tip = getInlineTip(metrics);
    console.log(JSON.stringify({ tip }));
    break;
  }
  case "normalize": {
    const name = normalizeAgentName(payload.agent ?? metrics.agent ?? "unknown");
    console.log(JSON.stringify({ name }));
    break;
  }
  case "format": {
    const tips = getRecommendations(metrics, maxTips);
    const output = formatRecommendations(tips);
    console.log(JSON.stringify({ output, hasContent: output.length > 0 }));
    break;
  }
  default:
    console.error(JSON.stringify({ error: `Unknown cmd: ${cmd}` }));
    process.exit(1);
}
