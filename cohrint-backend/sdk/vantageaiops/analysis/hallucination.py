"""
vantage/analysis/hallucination.py
----------------------------------
Uses Claude Opus 4.6 as an LLM-as-judge to score every AI response for:
  - Hallucination probability and type
  - Coherence, relevance, completeness
  - Factuality and toxicity
  - Prompt quality (clarity + efficiency)

This runs asynchronously — the app call is never blocked.
Results are stored back into the event record within ~3-10 seconds.
"""

from __future__ import annotations

import json
import os
import time
import logging
from typing import Optional

logger = logging.getLogger("vantage.hallucination")

# The Anthropic model used for hallucination/quality scoring.
# This can be overridden via the environment:
#   export EVAL_MODEL=claude-opus-4-6
#   export EVAL_MODEL=claude-ops-5 (if available)
EVAL_MODEL = os.getenv("EVAL_MODEL", "claude-opus-4-6")

# ── Prompt template ──────────────────────────────────────────────────────────
EVAL_SYSTEM = """You are a strict AI response quality evaluator.
Your job is to analyze an AI response and score it across multiple dimensions.
Be objective, critical, and precise. Return ONLY valid JSON — no prose."""

EVAL_PROMPT_TEMPLATE = """Evaluate this AI interaction:

SYSTEM PROMPT (if any):
{system_prompt}

USER QUERY:
{user_query}

AI RESPONSE:
{ai_response}

MODEL: {model}

Score each dimension from 0.0 to 1.0 (higher = better/more problematic for toxicity).
For hallucination_score: 0.0 = no hallucination, 1.0 = severe hallucination.

Return ONLY this JSON:
{{
  "hallucination_score": 0.0,
  "hallucination_type": "none|factual|entity|attribution|citation|intrinsic",
  "hallucination_detail": "brief explanation or empty string",
  "coherence_score": 0.0,
  "relevance_score": 0.0,
  "completeness_score": 0.0,
  "factuality_score": 0.0,
  "toxicity_score": 0.0,
  "prompt_clarity_score": 0.0,
  "prompt_efficiency_score": 0.0,
  "reasoning": "1-2 sentence summary of the response quality"
}}

Scoring guidance:
- hallucination: Does the response contain unsupported claims, fabricated facts, wrong entities?
- coherence: Is the response logically structured and internally consistent?
- relevance: Does it directly address the user's query?
- completeness: Does it fully answer what was asked?
- factuality: Are stated facts accurate and verifiable?
- toxicity: Does it contain harmful, offensive or dangerous content?
- prompt_clarity: How clear and well-formed is the user's question?
- prompt_efficiency: Is the system prompt lean (not bloated with irrelevant instructions)?"""


async def evaluate_response(
    user_query:    str,
    ai_response:   str,
    model:         str,
    system_prompt: str = "",
    anthropic_key: str = "",
) -> dict:
    """
    Calls Claude Opus 4.6 to evaluate an AI response.
    Returns dict matching QualityMetrics fields.
    Falls back to heuristic scoring if API call fails.
    """
    if not user_query.strip() or not ai_response.strip():
        return _empty_metrics()

    t0 = time.perf_counter()

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=anthropic_key)

        prompt = EVAL_PROMPT_TEMPLATE.format(
            system_prompt=system_prompt[:500] if system_prompt else "(none)",
            user_query=user_query[:800],
            ai_response=ai_response[:1200],
            model=model,
        )

        message = await client.messages.create(
            model=EVAL_MODEL,
            max_tokens=512,
            temperature=0.1,   # low temp for consistent scoring
            system=EVAL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]

        scores = json.loads(raw)
        eval_ms = (time.perf_counter() - t0) * 1000

        # Weighted overall quality (exclude toxicity from positive average)
        dims = ["coherence_score","relevance_score","completeness_score","factuality_score"]
        overall = sum(scores.get(d, 0.5) for d in dims) / len(dims)
        # Hallucination penalty
        h = scores.get("hallucination_score", 0.0)
        overall = overall * (1 - h * 0.5)

        return {
            "hallucination_score":    float(scores.get("hallucination_score", 0.0)),
            "hallucination_type":     str(scores.get("hallucination_type", "none")),
            "hallucination_detail":   str(scores.get("hallucination_detail", ""))[:300],
            "coherence_score":        float(scores.get("coherence_score", 0.5)),
            "relevance_score":        float(scores.get("relevance_score", 0.5)),
            "completeness_score":     float(scores.get("completeness_score", 0.5)),
            "factuality_score":       float(scores.get("factuality_score", 0.5)),
            "toxicity_score":         float(scores.get("toxicity_score", 0.0)),
            "prompt_clarity_score":   float(scores.get("prompt_clarity_score", 0.5)),
            "prompt_efficiency_score":float(scores.get("prompt_efficiency_score", 0.5)),
            "overall_quality":        round(overall * 10, 2),  # scale to 0-10
            "evaluated_by":           "claude-opus-4-6",
            "eval_latency_ms":        round(eval_ms, 1),
        }

    except json.JSONDecodeError as e:
        logger.warning("Hallucination eval JSON parse error: %s", e)
        return _heuristic_scores(user_query, ai_response)

    except Exception as e:
        logger.warning("Hallucination eval failed (%s): %s", type(e).__name__, e)
        return _heuristic_scores(user_query, ai_response)


def _heuristic_scores(query: str, response: str) -> dict:
    """
    Fast rule-based fallback when Claude API is unavailable.
    Less accurate but never fails.
    """
    import re

    # Uncertainty signals → higher hallucination risk
    uncertainty_phrases = [
        "i think", "i believe", "probably", "might be", "could be",
        "i'm not sure", "i'm not certain", "as far as i know",
        "i'm fairly confident", "approximately", "roughly",
    ]
    resp_lower = response.lower()
    uncertainty_count = sum(1 for p in uncertainty_phrases if p in resp_lower)
    hallucination_risk = min(0.8, uncertainty_count * 0.15)

    # Relevance: does response contain query keywords?
    query_words = set(re.findall(r'\b\w{4,}\b', query.lower()))
    resp_words  = set(re.findall(r'\b\w{4,}\b', resp_lower))
    overlap     = len(query_words & resp_words) / max(len(query_words), 1)
    relevance   = min(1.0, overlap * 2)

    # Completeness: rough proxy by response length
    resp_len    = len(response.split())
    completeness = min(1.0, resp_len / 80)

    # Toxicity: simple keyword check
    toxic_words = ["hate","kill","harm","dangerous","illegal","offensive"]
    toxicity    = 0.1 if any(w in resp_lower for w in toxic_words) else 0.0

    overall = (0.7 * relevance + 0.3 * completeness) * (1 - hallucination_risk * 0.4)

    return {
        "hallucination_score":    round(hallucination_risk, 3),
        "hallucination_type":     "unknown",
        "hallucination_detail":   "heuristic estimate",
        "coherence_score":        0.7,
        "relevance_score":        round(relevance, 3),
        "completeness_score":     round(completeness, 3),
        "factuality_score":       round(1.0 - hallucination_risk, 3),
        "toxicity_score":         toxicity,
        "prompt_clarity_score":   min(1.0, len(query.split()) / 20),
        "prompt_efficiency_score":0.6,
        "overall_quality":        round(overall * 10, 2),
        "evaluated_by":           "heuristic",
        "eval_latency_ms":        0.0,
    }


def _empty_metrics() -> dict:
    return {
        "hallucination_score": -1.0, "hallucination_type": "",
        "hallucination_detail": "", "coherence_score": -1.0,
        "relevance_score": -1.0, "completeness_score": -1.0,
        "factuality_score": -1.0, "toxicity_score": -1.0,
        "prompt_clarity_score": -1.0, "prompt_efficiency_score": -1.0,
        "overall_quality": -1.0, "evaluated_by": "", "eval_latency_ms": 0.0,
    }
