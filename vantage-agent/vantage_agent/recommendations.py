"""
Agent-Aware Live Recommendation Engine
Provides specific, actionable tips tailored to the agent being used.

Cost recommendations module for vantage-agent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional
import time


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class SessionMetrics:
    prompt_count: int
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    total_cached_tokens: int
    agent: Optional[str] = None
    model: Optional[str] = None
    avg_latency_ms: Optional[float] = None
    avg_cost_per_prompt: Optional[float] = None
    last_prompt_cost_usd: Optional[float] = None
    last_prompt_tokens: Optional[int] = None
    session_duration_min: Optional[float] = None
    session_start_time: Optional[float] = None  # epoch seconds


Priority = Literal["critical", "high", "medium", "low"]
Category = Literal["model", "cache", "prompt", "workflow", "budget"]


@dataclass
class Recommendation:
    id: str
    priority: Priority
    agent: str          # specific agent name or "all"
    category: Category
    title: str
    action: str         # specific command or action to take
    savings_estimate: str
    condition: Callable[[SessionMetrics], bool] = field(repr=False)


# ── Agent-Specific Tip Database ──────────────────────────────────────────────

AGENT_TIPS: list[Recommendation] = [
    # ── Claude Code ──
    Recommendation(
        id="claude-use-sonnet",
        priority="high",
        agent="claude",
        category="model",
        title="Switch to Sonnet for this session",
        action="Run: /model sonnet — Opus costs 5x more. Use Opus only for complex multi-file architecture.",
        savings_estimate="~60% cost reduction",
        condition=lambda m: (
            m.agent == "claude"
            and "opus" in (m.model or "")
            and (m.avg_cost_per_prompt or 0) < 0.10
        ),
    ),
    Recommendation(
        id="claude-use-haiku",
        priority="medium",
        agent="claude",
        category="model",
        title="Use Haiku for simple edits",
        action="Run: /model haiku — Best for formatting, linting, docstrings, and simple fixes.",
        savings_estimate="~80% cost reduction vs Sonnet",
        condition=lambda m: (
            m.agent == "claude"
            and (m.last_prompt_tokens or 0) < 500
            and m.prompt_count > 3
        ),
    ),
    Recommendation(
        id="claude-compact",
        priority="high",
        agent="claude",
        category="cache",
        title="Run /compact to reduce context",
        action="Run: /compact — Your session has grown large. Compact before next edit to save tokens.",
        savings_estimate="~40% on subsequent prompts",
        condition=lambda m: (
            m.agent == "claude"
            and m.total_input_tokens > 50000
            and m.prompt_count > 5
        ),
    ),
    Recommendation(
        id="claude-clear-session",
        priority="medium",
        agent="claude",
        category="workflow",
        title="Start fresh with /clear",
        action="Run: /clear — Mixing unrelated tasks wastes context. Start a clean session for the new topic.",
        savings_estimate="~30-50% per session",
        condition=lambda m: (
            m.agent == "claude"
            and (m.session_duration_min or 0) > 30
            and m.prompt_count > 15
        ),
    ),
    Recommendation(
        id="claude-use-bang",
        priority="low",
        agent="claude",
        category="workflow",
        title="Use ! prefix for shell commands",
        action="Type: ! ls, ! git status — Direct execution skips Claude's reasoning about what command to run.",
        savings_estimate="~30-50% on command-heavy tasks",
        condition=lambda m: (
            m.agent == "claude"
            and m.prompt_count > 3
        ),
    ),
    Recommendation(
        id="claude-prompt-caching",
        priority="high",
        agent="claude",
        category="cache",
        title="Enable prompt caching for large context",
        action="Prompt caching gives 90% savings on repeated context. Structure system prompts for cache reuse.",
        savings_estimate="~90% on cached tokens",
        condition=lambda m: (
            m.agent == "claude"
            and m.total_cached_tokens < m.total_input_tokens * 0.1
            and m.total_input_tokens > 20000
        ),
    ),

    # ── Gemini CLI ──
    Recommendation(
        id="gemini-use-flash",
        priority="high",
        agent="gemini",
        category="model",
        title="Use Flash instead of Pro",
        action="Gemini Flash beats Pro on coding benchmarks (78% vs 76.2%) at 10x lower cost. Default to Flash.",
        savings_estimate="~90% cost reduction",
        condition=lambda m: (
            m.agent == "gemini"
            and "pro" in (m.model or "")
        ),
    ),
    Recommendation(
        id="gemini-free-tier",
        priority="critical",
        agent="gemini",
        category="budget",
        title="You may be on the free tier",
        action="Gemini CLI gets 60 RPM / 1,000 requests/day FREE. Verify your billing — you might not need to pay at all.",
        savings_estimate="~100% for light usage",
        condition=lambda m: (
            m.agent == "gemini"
            and m.total_cost_usd < 1.00
            and m.prompt_count < 50
        ),
    ),
    Recommendation(
        id="gemini-context-cache",
        priority="medium",
        agent="gemini",
        category="cache",
        title="Enable context caching",
        action="Run: /compress or configure context caching in ~/.gemini/settings.json. Reduces costs by 75% for repeated codebase queries.",
        savings_estimate="~75% on subsequent queries",
        condition=lambda m: (
            m.agent == "gemini"
            and m.total_input_tokens > 30000
            and m.total_cached_tokens < m.total_input_tokens * 0.2
        ),
    ),
    Recommendation(
        id="gemini-batch",
        priority="low",
        agent="gemini",
        category="workflow",
        title="Batch non-urgent analysis tasks",
        action="Use batch API for code analysis, bulk test generation. Accepts 24h latency for 50% discount.",
        savings_estimate="~50% on batch-eligible tasks",
        condition=lambda m: (
            m.agent == "gemini"
            and m.prompt_count > 10
        ),
    ),

    # ── Codex CLI ──
    Recommendation(
        id="codex-use-mini",
        priority="high",
        agent="codex",
        category="model",
        title="Use codex-mini for routine tasks",
        action="codex-mini-latest ($1.50/$6.00 per 1M) is purpose-built for code. Reserve full GPT for complex reasoning.",
        savings_estimate="~70% cost reduction",
        condition=lambda m: (
            m.agent == "codex"
            and (
                "gpt-4" in (m.model or "")
                or "gpt-5" in (m.model or "")
                or "o3" in (m.model or "")
            )
        ),
    ),
    Recommendation(
        id="codex-selective-context",
        priority="medium",
        agent="codex",
        category="prompt",
        title="Be selective with file context",
        action="Don't send entire files. Specify function names or line ranges. Each file adds thousands of tokens.",
        savings_estimate="~40-60% on large repos",
        condition=lambda m: (
            m.agent == "codex"
            and (m.last_prompt_tokens or 0) > 8000
        ),
    ),
    Recommendation(
        id="codex-prompt-cache",
        priority="medium",
        agent="codex",
        category="cache",
        title="Leverage OpenAI prompt caching",
        action="Structure prompts with consistent system messages. Cached input tokens cost 50% less on OpenAI.",
        savings_estimate="~50% on cached tokens",
        condition=lambda m: (
            m.agent == "codex"
            and m.total_cached_tokens < m.total_input_tokens * 0.15
        ),
    ),

    # ── Aider ──
    Recommendation(
        id="aider-use-diff",
        priority="critical",
        agent="aider",
        category="prompt",
        title="Switch to diff edit format",
        action="Run: /chat-mode diff — The 'whole' format returns entire files for every edit. 'diff' only returns changed lines.",
        savings_estimate="~60-80% output token reduction",
        condition=lambda m: (
            m.agent == "aider"
            and m.total_output_tokens > m.total_input_tokens * 2
        ),
    ),
    Recommendation(
        id="aider-deepseek",
        priority="high",
        agent="aider",
        category="model",
        title="Try DeepSeek for budget tasks",
        action="DeepSeek V3 ($1.27/1M) achieves 55% benchmark accuracy vs Sonnet's 60%. Great for routine edits.",
        savings_estimate="~75% cost reduction vs Sonnet",
        condition=lambda m: (
            m.agent == "aider"
            and "claude" in (m.model or "")
            and (m.avg_cost_per_prompt or 0) > 0.02
        ),
    ),
    Recommendation(
        id="aider-selective-add",
        priority="medium",
        agent="aider",
        category="workflow",
        title="Only /add files you need edited",
        action="Run: /add specific_file.py — Don't add entire directories. Each file consumes tokens on every prompt.",
        savings_estimate="~30-50% context reduction",
        condition=lambda m: (
            m.agent == "aider"
            and m.total_input_tokens > 40000
        ),
    ),
    Recommendation(
        id="aider-repo-map",
        priority="medium",
        agent="aider",
        category="cache",
        title="Optimize repo-map token budget",
        action="Use --map-tokens to cap repo-map size. Default varies by model — lower it for cheaper sessions.",
        savings_estimate="~20-40% input token reduction",
        condition=lambda m: (
            m.agent == "aider"
            and m.prompt_count > 5
        ),
    ),

    # ── ChatGPT / Cursor ──
    Recommendation(
        id="cursor-use-auto",
        priority="critical",
        agent="chatgpt",
        category="model",
        title="Use Auto mode in Cursor",
        action="Switch to Auto mode — it's unlimited and free. Only use premium models for tasks Auto can't handle.",
        savings_estimate="~100% on Auto-eligible tasks",
        condition=lambda m: (
            m.agent == "chatgpt"
            and m.total_cost_usd > 0.10
        ),
    ),
    Recommendation(
        id="cursor-cmd-k",
        priority="high",
        agent="chatgpt",
        category="workflow",
        title="Use Cmd+K instead of Composer",
        action="Cmd+K is lean and fast. Composer reads multiple files and burns 5-10x more tokens per operation.",
        savings_estimate="~80% per edit operation",
        condition=lambda m: (
            m.agent == "chatgpt"
            and (m.avg_cost_per_prompt or 0) > 0.05
        ),
    ),
    Recommendation(
        id="cursor-at-refs",
        priority="medium",
        agent="chatgpt",
        category="prompt",
        title="Use @ references instead of pasting code",
        action="Type @filename to reference code. Don't paste blocks into chat — @ saves tokens and is more precise.",
        savings_estimate="~30-50% token reduction",
        condition=lambda m: (
            m.agent == "chatgpt"
            and (m.last_prompt_tokens or 0) > 3000
        ),
    ),

    # ── Universal Tips (all agents) ──
    Recommendation(
        id="all-high-cost-alert",
        priority="critical",
        agent="all",
        category="budget",
        title="Session cost is high",
        action="Your session has spent ${cost}. Consider switching to a cheaper model or starting a fresh session.",
        savings_estimate="Prevent budget overrun",
        condition=lambda m: m.total_cost_usd > 5.00,
    ),
    Recommendation(
        id="all-cost-per-prompt",
        priority="high",
        agent="all",
        category="budget",
        title="Average cost per prompt is high",
        action="At ${avg}/prompt, consider a cheaper model. Run /compare to find the best price/quality ratio.",
        savings_estimate="Varies by model switch",
        condition=lambda m: (
            (m.avg_cost_per_prompt or 0) > 0.20
            and m.prompt_count > 3
        ),
    ),
    Recommendation(
        id="all-large-prompt",
        priority="medium",
        agent="all",
        category="prompt",
        title="Last prompt was very large",
        action="Your last prompt used ${tokens} tokens. Break large requests into smaller, focused prompts.",
        savings_estimate="~20-40% by reducing context",
        condition=lambda m: (m.last_prompt_tokens or 0) > 10000,
    ),
    Recommendation(
        id="all-low-cache",
        priority="medium",
        agent="all",
        category="cache",
        title="Cache utilization is low",
        action="Only ${pct}% of tokens are cached. Standardize system prompts and reuse context for better cache hits.",
        savings_estimate="~30-50% with better caching",
        condition=lambda m: (
            m.total_input_tokens > 10000
            and m.total_cached_tokens < m.total_input_tokens * 0.15
        ),
    ),
]


# ── Agent name normalization ──────────────────────────────────────────────────

def normalize_agent_name(agent: str) -> str:
    """Map agent aliases to canonical names."""
    if not agent:
        return "unknown"
    lower = agent.lower()
    if "claude" in lower:
        return "claude"
    if "gemini" in lower:
        return "gemini"
    if "codex" in lower or "openai" in lower:
        return "codex"
    if "aider" in lower:
        return "aider"
    if "cursor" in lower or "chatgpt" in lower or "gpt" in lower:
        return "chatgpt"
    return lower


# ── Core functions ────────────────────────────────────────────────────────────

_PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def get_recommendations(
    metrics: SessionMetrics,
    max_tips: int = 3,
) -> list[Recommendation]:
    """
    Return up to *max_tips* recommendations sorted by priority (critical first).
    Filters by agent and evaluates each tip's condition against a fully-filled
    copy of the metrics so conditions never receive None.
    """
    duration_min = metrics.session_duration_min
    if duration_min is None:
        if metrics.session_start_time is not None:
            duration_min = (time.time() - metrics.session_start_time) / 60.0
        else:
            duration_min = 0.0

    avg_cost = metrics.avg_cost_per_prompt
    if avg_cost is None:
        avg_cost = (
            metrics.total_cost_usd / metrics.prompt_count
            if metrics.prompt_count > 0
            else 0.0
        )

    agent_name = normalize_agent_name(metrics.agent or "unknown")

    # Build a filled copy with all optional fields resolved so conditions are safe.
    filled = SessionMetrics(
        prompt_count=metrics.prompt_count,
        total_cost_usd=metrics.total_cost_usd,
        total_input_tokens=metrics.total_input_tokens,
        total_output_tokens=metrics.total_output_tokens,
        total_cached_tokens=metrics.total_cached_tokens,
        agent=agent_name,
        model=metrics.model or "unknown",
        avg_latency_ms=metrics.avg_latency_ms or 0.0,
        avg_cost_per_prompt=avg_cost,
        last_prompt_cost_usd=metrics.last_prompt_cost_usd if metrics.last_prompt_cost_usd is not None else avg_cost,
        last_prompt_tokens=metrics.last_prompt_tokens or 0,
        session_duration_min=duration_min,
        session_start_time=metrics.session_start_time,
    )

    applicable: list[Recommendation] = []
    for tip in AGENT_TIPS:
        if tip.agent != "all" and tip.agent != agent_name:
            continue
        try:
            if tip.condition(filled):
                applicable.append(tip)
        except Exception:
            pass

    applicable.sort(key=lambda t: _PRIORITY_ORDER.get(t.priority, 99))

    pct = str(
        round(
            (filled.total_cached_tokens / max(filled.total_input_tokens, 1)) * 100
        )
    )

    result: list[Recommendation] = []
    for tip in applicable[:max_tips]:
        resolved_action = (
            tip.action
            .replace("${cost}", f"${filled.total_cost_usd:.2f}")
            .replace("${avg}", f"${(filled.avg_cost_per_prompt or 0):.3f}")
            .replace("${tokens}", f"{(filled.last_prompt_tokens or 0):,}")
            .replace("${pct}", pct)
        )
        result.append(
            Recommendation(
                id=tip.id,
                priority=tip.priority,
                agent=tip.agent,
                category=tip.category,
                title=tip.title,
                action=resolved_action,
                savings_estimate=tip.savings_estimate,
                condition=tip.condition,
            )
        )

    return result


def get_inline_tip(metrics: SessionMetrics) -> Optional[str]:
    """Return a single one-liner tip with emoji prefix, or None if none apply."""
    tips = get_recommendations(metrics, max_tips=1)
    if not tips:
        return None
    tip = tips[0]
    if tip.priority == "critical":
        icon = "🔴"
    elif tip.priority == "high":
        icon = "🟡"
    else:
        icon = "💡"
    return f"{icon} {tip.title}: {tip.action} ({tip.savings_estimate})"


def format_recommendations(tips: list[Recommendation]) -> str:
    """Render recommendations in a box-drawing CLI block."""
    if not tips:
        return ""

    lines = ["\n  ┌─ Live Recommendations ─────────────────────────────"]
    for tip in tips:
        if tip.priority == "critical":
            icon = "🔴"
        elif tip.priority == "high":
            icon = "🟡"
        elif tip.priority == "medium":
            icon = "💡"
        else:
            icon = "ℹ"
        cat = f"[{tip.category.upper()}]"
        lines.append(f"  │ {icon} {cat} {tip.title}")
        lines.append(f"  │   → {tip.action}")
        lines.append(f"  │   Savings: {tip.savings_estimate}")
        lines.append("  │")
    lines.append("  └────────────────────────────────────────────────────\n")
    return "\n".join(lines)
