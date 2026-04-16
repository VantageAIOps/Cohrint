"""
vantage/analysis/efficiency.py
================================
Computes a 0-100 efficiency score for every AI call.
Identifies system prompt bloat, context waste, and model mismatch.
Uses rule-based scoring + Claude Opus 4.6 for deep analysis.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class EfficiencyReport:
    score:               int           # 0-100
    grade:               str           # A / B / C / D / F
    system_prompt_ratio: float         # system tokens / total prompt tokens
    cache_hit_rate:      float         # cached / prompt tokens
    output_ratio:        float         # completion / total tokens
    issues:              list[str]
    savings_tips:        list[str]
    estimated_saving_pct: float        # % cost reduction if all tips applied


def compute_efficiency(
    prompt_tokens:       int,
    completion_tokens:   int,
    system_prompt_tokens: int,
    cached_tokens:       int,
    model:               str,
    provider:            str,
    latency_ms:          float,
    total_cost_usd:      float,
) -> EfficiencyReport:
    """
    Rule-based efficiency scoring. Fast, no external API calls.
    Called synchronously on every event before it's sent.
    """
    score   = 100
    issues  = []
    tips    = []

    # ── System prompt ratio ───────────────────────────────────────────────────
    sys_ratio = system_prompt_tokens / max(prompt_tokens, 1)
    if sys_ratio > 0.60:
        score -= 25
        issues.append(f"System prompt is {sys_ratio:.0%} of input — extremely bloated")
        tips.append("Trim system prompt to <20% of input tokens. Use prompt caching for static parts.")
    elif sys_ratio > 0.40:
        score -= 15
        issues.append(f"System prompt is {sys_ratio:.0%} of input — too large")
        tips.append("Reduce system prompt. Move static instructions to a cached prefix.")
    elif sys_ratio > 0.20:
        score -= 5
        issues.append(f"System prompt is {sys_ratio:.0%} of input — slightly high")

    # ── Cache hit rate ────────────────────────────────────────────────────────
    cache_rate = cached_tokens / max(prompt_tokens, 1)
    if cache_rate == 0 and system_prompt_tokens > 200:
        score -= 15
        issues.append("No prompt caching enabled despite large system prompt")
        tips.append("Enable prompt caching — saves 75-90% of system prompt cost on repeat calls.")
    elif cache_rate > 0.30:
        score += 5  # bonus for good caching
        score  = min(100, score)

    # ── Output / input ratio ──────────────────────────────────────────────────
    total   = prompt_tokens + completion_tokens
    out_ratio = completion_tokens / max(total, 1)
    if out_ratio < 0.03:
        score -= 10
        issues.append("Very short completion — possible prompt that requires more output guidance")
        tips.append("Add 'Provide a detailed response' or increase max_tokens if truncation suspected.")
    elif out_ratio > 0.70:
        score -= 5
        issues.append("Completion is very long relative to input — check if all output is needed")
        tips.append("Use structured output formats (JSON/bullets) to reduce verbose completions.")

    # ── Prompt token count ────────────────────────────────────────────────────
    if prompt_tokens > 50_000:
        score -= 20
        issues.append(f"Very large prompt ({prompt_tokens:,} tokens) — check for context stuffing")
        tips.append("Implement retrieval (RAG) instead of stuffing entire documents into context.")
    elif prompt_tokens > 10_000:
        score -= 8
        tips.append("Consider summarising context before sending to reduce token cost.")

    # ── Model tier appropriateness ────────────────────────────────────────────
    frontier_models = {"gpt-4o", "claude-opus-4-6", "claude-3-opus", "o1", "gemini-1.5-pro"}
    fast_tasks      = {"classify", "embed", "translate", "extract"}
    if model.lower() in frontier_models and completion_tokens < 100:
        score -= 10
        issues.append(f"Using frontier model {model} for a short/simple completion")
        tips.append(f"Switch to a fast/cheap model (gpt-4o-mini, claude-haiku) for this task — same quality, 10-40× cheaper.")

    # ── Latency relative to tokens ────────────────────────────────────────────
    expected_ms_per_token = 15  # rough baseline
    expected_latency = completion_tokens * expected_ms_per_token
    if latency_ms > expected_latency * 3 and latency_ms > 5000:
        score -= 8
        issues.append(f"Unusually high latency ({latency_ms:.0f}ms) for {completion_tokens} completion tokens")
        tips.append("Consider using a faster model or enabling streaming to improve perceived latency.")

    score = max(0, min(100, score))

    # Grade
    if score >= 90: grade = "A"
    elif score >= 75: grade = "B"
    elif score >= 60: grade = "C"
    elif score >= 45: grade = "D"
    else: grade = "F"

    # Estimated savings if tips applied
    saving_pct = 0.0
    if sys_ratio > 0.40:     saving_pct += (sys_ratio - 0.20) * 0.8  # trim system prompt
    if cache_rate == 0:       saving_pct += sys_ratio * 0.85           # enable caching
    if model in frontier_models and completion_tokens < 100:
        saving_pct += 0.85   # switch to smaller model
    saving_pct = min(0.95, saving_pct)

    return EfficiencyReport(
        score                = score,
        grade                = grade,
        system_prompt_ratio  = round(sys_ratio, 3),
        cache_hit_rate       = round(cache_rate, 3),
        output_ratio         = round(out_ratio, 3),
        issues               = issues,
        savings_tips         = tips,
        estimated_saving_pct = round(saving_pct * 100, 1),
    )


def score_to_int(report: EfficiencyReport) -> int:
    return report.score
