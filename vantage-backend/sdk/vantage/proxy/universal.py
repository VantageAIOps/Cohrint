"""
vantage/proxy/universal.py
--------------------------
Universal AI proxy — wraps OpenAI, Anthropic, Google, Cohere,
Mistral, LiteLLM, LangChain, and raw HTTP calls with one decorator.

USAGE (any model):
    import vantage
    vantage.init(api_key="vnt_...", org="acme", team="product")

    # OpenAI
    from vantage.proxy import openai
    client = openai.OpenAI(api_key="sk-...")

    # Anthropic
    from vantage.proxy import anthropic
    client = anthropic.Anthropic(api_key="sk-ant-...")

    # ANY litellm-compatible model (Copilot, Gemini, Mistral, etc.)
    from vantage.proxy import litellm
    response = litellm.completion(model="gpt-4o", messages=[...])
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional
from functools import wraps

from vantage.models.event import VantageEvent, TokenUsage, CostInfo, QualityMetrics
from vantage.models.pricing import calculate_cost, find_cheapest
from vantage.utils.queue import EventQueue


# ── Thread/async context storage ────────────────────────────────────────────
import contextvars

_CTX_TAGS:    contextvars.ContextVar[dict] = contextvars.ContextVar("vantage_tags",    default={})
_CTX_SESSION: contextvars.ContextVar[str]  = contextvars.ContextVar("vantage_session", default="")
_CTX_USER:    contextvars.ContextVar[str]  = contextvars.ContextVar("vantage_user",    default="")
_CTX_FEATURE: contextvars.ContextVar[str]  = contextvars.ContextVar("vantage_feature", default="")
_CTX_PROJECT: contextvars.ContextVar[str]  = contextvars.ContextVar("vantage_project", default="")


# ── Context manager for scoped tagging ──────────────────────────────────────
@contextmanager
def trace(
    feature: str = "",
    user_id: str = "",
    session_id: str = "",
    project: str = "",
    team: str = "",
    **tags,
):
    """
    Scope all AI calls within this block with metadata.

    Usage:
        with vantage.trace(feature="chat", user_id="u_123", project="my-app"):
            response = openai.chat.completions.create(...)
    """
    token_tags    = _CTX_TAGS.set({**_CTX_TAGS.get({}), **tags, **({"team": team} if team else {})})
    token_session = _CTX_SESSION.set(session_id or str(uuid.uuid4()))
    token_user    = _CTX_USER.set(user_id)
    token_feature = _CTX_FEATURE.set(feature)
    token_project = _CTX_PROJECT.set(project)
    try:
        yield
    finally:
        _CTX_TAGS.reset(token_tags)
        _CTX_SESSION.reset(token_session)
        _CTX_USER.reset(token_user)
        _CTX_FEATURE.reset(token_feature)
        _CTX_PROJECT.reset(token_project)


# ── Core capture function ────────────────────────────────────────────────────
def _build_event(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    latency_ms: float,
    ttft_ms: float,
    status_code: int,
    error: Optional[str],
    prompt_text: str,
    response_text: str,
    system_prompt: str,
    endpoint: str,
    extra_tags: dict,
    org_id: str,
    environment: str,
) -> VantageEvent:
    costs = calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens)
    cheaper = find_cheapest(model, prompt_tokens, completion_tokens)

    # Fingerprint prompt for dedup/caching analysis
    prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:12] if system_prompt else ""

    return VantageEvent(
        event_id    = str(uuid.uuid4()),
        timestamp   = time.time(),
        org_id      = org_id,
        environment = environment,
        # Identity
        provider  = provider,
        model     = model,
        endpoint  = endpoint,
        # Context
        session_id  = _CTX_SESSION.get(""),
        user_id     = _CTX_USER.get(""),
        feature     = _CTX_FEATURE.get(""),
        project     = _CTX_PROJECT.get(""),
        tags        = {**_CTX_TAGS.get({}), **extra_tags},
        # Performance
        latency_ms = round(latency_ms, 2),
        ttft_ms    = round(ttft_ms, 2),
        status_code = status_code,
        error       = error,
        # Tokens
        usage = TokenUsage(
            prompt_tokens     = prompt_tokens,
            completion_tokens = completion_tokens,
            total_tokens      = prompt_tokens + completion_tokens,
            cached_tokens     = cached_tokens,
            system_prompt_tokens = len(system_prompt.split()) * 4 // 3,  # rough estimate
        ),
        # Cost
        cost = CostInfo(
            input_cost_usd        = costs["input"],
            output_cost_usd       = costs["output"],
            total_cost_usd        = costs["total"],
            cheapest_model        = cheaper["model"] if cheaper else "",
            cheapest_cost_usd     = cheaper["cost"] if cheaper else 0.0,
            potential_saving_usd  = max(0, costs["total"] - (cheaper["cost"] if cheaper else costs["total"])),
        ),
        # Previews (truncated for privacy)
        request_preview  = prompt_text[:600] if prompt_text else "",
        response_preview = response_text[:600] if response_text else "",
        system_preview   = system_prompt[:200] if system_prompt else "",
        prompt_hash      = prompt_hash,
        # Quality — filled async by analysis worker
        quality = QualityMetrics(),
    )
