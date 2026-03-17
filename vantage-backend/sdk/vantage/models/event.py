"""
vantage/models/event.py
-----------------------
Core data models. Every AI call becomes a VantageEvent.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class TokenUsage:
    prompt_tokens:        int   = 0
    completion_tokens:    int   = 0
    total_tokens:         int   = 0
    cached_tokens:        int   = 0
    system_prompt_tokens: int   = 0

    @property
    def cache_hit_rate(self) -> float:
        if self.prompt_tokens == 0: return 0.0
        return round(self.cached_tokens / self.prompt_tokens, 4)

    @property
    def system_overhead_pct(self) -> float:
        if self.prompt_tokens == 0: return 0.0
        return round(self.system_prompt_tokens / self.prompt_tokens * 100, 1)


@dataclass
class CostInfo:
    input_cost_usd:       float = 0.0
    output_cost_usd:      float = 0.0
    total_cost_usd:       float = 0.0
    cheapest_model:       str   = ""
    cheapest_cost_usd:    float = 0.0
    potential_saving_usd: float = 0.0

    @property
    def saving_pct(self) -> float:
        if self.total_cost_usd == 0: return 0.0
        return round(self.potential_saving_usd / self.total_cost_usd * 100, 1)


@dataclass
class QualityMetrics:
    """
    Populated asynchronously by the Claude Opus 4.6 analysis worker.
    Not available at capture time — filled within 2-10 seconds.
    """
    # Hallucination
    hallucination_score:    float = -1.0   # 0.0 (none) → 1.0 (severe). -1 = not yet scored
    hallucination_type:     str   = ""     # factual | entity | attribution | citation | none
    hallucination_detail:   str   = ""     # brief explanation from judge

    # Quality dimensions (0-10 each)
    coherence_score:        float = -1.0
    relevance_score:        float = -1.0
    completeness_score:     float = -1.0
    factuality_score:       float = -1.0
    toxicity_score:         float = -1.0   # 0 = clean, 1 = toxic

    # Composite
    overall_quality:        float = -1.0   # weighted average

    # Prompt
    prompt_clarity_score:   float = -1.0   # how clear/well-formed the prompt was
    prompt_efficiency_score:float = -1.0   # tokens used vs info conveyed

    # Evaluated by
    evaluated_by:  str = ""   # e.g. "claude-opus-4-6"
    eval_latency_ms: float = 0.0


@dataclass
class VantageEvent:
    # Identity
    event_id:    str
    timestamp:   float
    org_id:      str
    environment: str = "production"

    # Request context
    provider:   str = ""
    model:      str = ""
    endpoint:   str = ""
    session_id: str = ""
    user_id:    str = ""
    feature:    str = ""
    project:    str = ""
    tags:       dict = field(default_factory=dict)

    # Performance
    latency_ms:  float = 0.0
    ttft_ms:     float = 0.0
    status_code: int   = 200
    error:       Optional[str] = None

    # Data
    usage:  TokenUsage = field(default_factory=TokenUsage)
    cost:   CostInfo   = field(default_factory=CostInfo)
    quality: QualityMetrics = field(default_factory=QualityMetrics)

    # Previews
    request_preview:  str = ""
    response_preview: str = ""
    system_preview:   str = ""
    prompt_hash:      str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Flatten nested objects for DB insertion
        u, c, q = d.pop("usage"), d.pop("cost"), d.pop("quality")
        return {**d, **{f"usage_{k}": v for k,v in u.items()},
                     **{f"cost_{k}": v for k,v in c.items()},
                     **{f"quality_{k}": v for k,v in q.items()}}

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400 or self.error is not None

    @property
    def efficiency_score(self) -> float:
        """0-100 score based on token efficiency and prompt overhead."""
        if self.usage.total_tokens == 0: return 0.0
        overhead_penalty = min(50, self.usage.system_overhead_pct)
        cache_bonus      = self.usage.cache_hit_rate * 20
        return round(max(0, min(100, 100 - overhead_penalty + cache_bonus)), 1)
