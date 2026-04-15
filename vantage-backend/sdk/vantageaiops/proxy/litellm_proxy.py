"""
vantage/proxy/litellm_proxy.py
------------------------------
Wraps litellm.completion() — covers 100+ models including:
  GitHub Copilot, Gemini, Cohere, Mistral, Groq, Together AI,
  AWS Bedrock, Azure OpenAI, Perplexity, and any OpenAI-compatible API.

USAGE:
    import vantage; vantage.init("crt_...")
    from cohrint.proxy import litellm

    # Any model litellm supports
    response = litellm.completion(
        model="gemini/gemini-2.0-flash",
        messages=[{"role": "user", "content": "Hello"}]
    )

    response = litellm.completion(
        model="cohere/command-r-plus",
        messages=[{"role": "user", "content": "Hello"}]
    )

    # GitHub Copilot via Azure
    response = litellm.completion(
        model="azure/gpt-4o",
        messages=[{"role": "user", "content": "Hello"}]
    )
"""

from __future__ import annotations
import time
from typing import Any

from cohrint.proxy.universal import _build_event

try:
    import litellm as _ll
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False


def _get_queue():
    from vantage import _get_queue as gq; return gq()
def _get_config():
    from vantage import _get_config as gc; return gc()


def _parse_model_provider(model: str) -> tuple[str, str]:
    """Parse 'provider/model-name' into (provider, model)."""
    if "/" in model:
        parts = model.split("/", 1)
        return parts[0], parts[1]
    # Infer provider from model name
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        return "openai", model
    if model.startswith("claude-"):
        return "anthropic", model
    if model.startswith("gemini-"):
        return "google", model
    if model.startswith("command-"):
        return "cohere", model
    if model.startswith("mistral-") or model.startswith("mixtral-"):
        return "mistral", model
    if model.startswith("llama-") or model.startswith("meta-"):
        return "meta", model
    if model.startswith("grok-"):
        return "xai", model
    return "unknown", model


def completion(model: str, messages: list, **kwargs) -> Any:
    """
    Vantage-wrapped litellm.completion().
    Drop-in replacement — identical signature.
    """
    if not HAS_LITELLM:
        raise ImportError("pip install litellm")

    cfg = _get_config()
    t0  = time.perf_counter()
    provider, model_name = _parse_model_provider(model)

    system_txt = " ".join(m.get("content","") for m in messages if m.get("role")=="system")
    users      = [m for m in messages if m.get("role")=="user"]
    user_text  = users[-1].get("content","") if users else ""

    try:
        resp = _ll.completion(model=model, messages=messages, **kwargs)
        lat  = (time.perf_counter() - t0) * 1000
        u    = getattr(resp, "usage", None)
        pt   = getattr(u, "prompt_tokens", 0) or 0
        ct   = getattr(u, "completion_tokens", 0) or 0
        rt   = resp.choices[0].message.content[:600] if resp.choices else ""

        ev = _build_event(
            provider=provider, model=model_name,
            prompt_tokens=pt, completion_tokens=ct, cached_tokens=0,
            latency_ms=lat, ttft_ms=0,
            status_code=200, error=None,
            prompt_text=user_text if isinstance(user_text,str) else str(user_text)[:400],
            response_text=rt, system_prompt=system_txt,
            endpoint="/completion", extra_tags={"litellm_model": model},
            org_id=cfg["org_id"], environment=cfg["environment"],
        )
        _get_queue().enqueue(ev)
        return resp

    except Exception as exc:
        lat = (time.perf_counter() - t0) * 1000
        try:
            ev = _build_event(
                provider=provider, model=model_name,
                prompt_tokens=0, completion_tokens=0, cached_tokens=0,
                latency_ms=lat, ttft_ms=0, status_code=500, error=str(exc)[:400],
                prompt_text="", response_text="", system_prompt="",
                endpoint="/completion", extra_tags={},
                org_id=cfg["org_id"], environment=cfg["environment"],
            )
            _get_queue().enqueue(ev)
        except Exception:
            pass
        raise


async def acompletion(model: str, messages: list, **kwargs) -> Any:
    """Async version."""
    if not HAS_LITELLM: raise ImportError("pip install litellm")
    cfg = _get_config()
    t0  = time.perf_counter()
    provider, model_name = _parse_model_provider(model)
    resp = await _ll.acompletion(model=model, messages=messages, **kwargs)
    lat  = (time.perf_counter() - t0) * 1000
    u    = getattr(resp, "usage", None)
    ev   = _build_event(
        provider=provider, model=model_name,
        prompt_tokens=getattr(u,"prompt_tokens",0) or 0,
        completion_tokens=getattr(u,"completion_tokens",0) or 0,
        cached_tokens=0, latency_ms=lat, ttft_ms=0,
        status_code=200, error=None,
        prompt_text="", response_text="", system_prompt="",
        endpoint="/acompletion", extra_tags={"litellm_model": model},
        org_id=cfg["org_id"], environment=cfg["environment"],
    )
    _get_queue().enqueue(ev)
    return resp
