"""
vantage/proxy/universal.py
--------------------------
Universal AI proxy — wraps OpenAI, Anthropic, Google, Cohere,
Mistral, LiteLLM, LangChain, and raw HTTP calls with one decorator.

USAGE (any model):
    import vantage
    vantage.init(api_key="crt_...", org="acme", team="product")

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

from vantage.models.event import CohrintEvent, TokenUsage, CostInfo, QualityMetrics, OptimizerMeta
from vantage.models.pricing import calculate_cost, find_cheapest
from vantage.utils.queue import EventQueue


# ── Thread/async context storage ────────────────────────────────────────────
import contextvars

_CTX_TAGS:    contextvars.ContextVar[dict] = contextvars.ContextVar("vantage_tags",    default={})
_CTX_SESSION: contextvars.ContextVar[str]  = contextvars.ContextVar("cohrint_session", default="")
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


# ── Optimizer integration ────────────────────────────────────────────────────
_compressor = None

def _get_compressor():
    """Lazy-init the prompt compressor from vantage-optimizer module."""
    global _compressor
    if _compressor is None:
        try:
            import sys, os
            # Add vantage-optimizer to path if available
            optimizer_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'vantage-optimizer')
            if os.path.isdir(optimizer_path) and optimizer_path not in sys.path:
                sys.path.insert(0, os.path.dirname(optimizer_path))
            from vantage_optimizer.compressor import PromptCompressor
            _compressor = PromptCompressor()
        except ImportError:
            from vantage_optimizer.compressor import SimpleCompressor
            _compressor = SimpleCompressor()
    return _compressor


def _compress_if_enabled(messages: list, cfg: dict) -> tuple:
    """
    Compress the last user message if optimizer is enabled.
    Returns (messages, optimizer_meta_dict).
    Messages are NOT mutated in-place — a shallow copy is returned.
    """
    if not cfg.get("optimizer_enabled", False):
        return messages, {}

    # Find the last user message
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indices:
        return messages, {}

    last_idx = user_indices[-1]
    user_content = messages[last_idx].get("content", "")
    if not isinstance(user_content, str) or len(user_content.split()) < 20:
        return messages, {}  # skip short prompts

    try:
        import time as _t
        t0 = _t.perf_counter()
        compressor = _get_compressor()
        rate = cfg.get("compression_rate", 0.5)
        result = compressor.compress(user_content, rate=rate)
        compression_ms = (_t.perf_counter() - t0) * 1000

        compressed_text = result.get("compressed_prompt", user_content)
        original_tokens = result.get("original_tokens", 0)
        compressed_tokens = result.get("compressed_tokens", 0)

        # Build new messages list (don't mutate original)
        new_messages = [*messages[:last_idx],
                        {**messages[last_idx], "content": compressed_text},
                        *messages[last_idx + 1:]]

        meta = {
            "enabled": True,
            "original_tokens": original_tokens,
            "compressed_tokens": compressed_tokens,
            "tokens_saved": original_tokens - compressed_tokens,
            "compression_ratio": result.get("ratio", 1.0),
            "compression_ms": round(compression_ms, 2),
        }
        return new_messages, meta
    except Exception:
        return messages, {}


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
    optimizer_meta: Optional[dict] = None,
) -> CohrintEvent:
    costs = calculate_cost(model, prompt_tokens, completion_tokens, cached_tokens)
    cheaper = find_cheapest(model, prompt_tokens, completion_tokens)

    # Fingerprint prompt for dedup/caching analysis
    prompt_hash = hashlib.md5(system_prompt.encode()).hexdigest()[:12] if system_prompt else ""

    return CohrintEvent(
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
        # Optimizer — populated when optimizer is enabled
        optimizer = OptimizerMeta(**optimizer_meta) if optimizer_meta else OptimizerMeta(),
    )
