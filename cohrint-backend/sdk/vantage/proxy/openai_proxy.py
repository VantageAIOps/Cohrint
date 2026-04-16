"""
vantage/proxy/openai_proxy.py
------------------------------
Drop-in replacement for openai.OpenAI / openai.AsyncOpenAI.

BEFORE:
    from openai import OpenAI
    client = OpenAI(api_key="sk-...")

AFTER (literally 2 lines changed):
    import vantage; vantage.init("crt_...")
    from vantage.proxy.openai_proxy import OpenAI
    client = OpenAI(api_key="sk-...")

Supports: chat.completions, embeddings, streaming, async
"""

from __future__ import annotations

import time
from typing import Any, Iterator, AsyncIterator, Optional

from vantage.proxy.universal import _build_event, _compress_if_enabled, _CTX_TAGS, _CTX_FEATURE, _CTX_PROJECT
from vantage.models.event import CohrintEvent

try:
    import openai as _oai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


def _get_queue():
    from vantage import _get_queue as gq
    return gq()


def _get_config():
    from vantage import _get_config as gc
    return gc()


def _extract_messages(messages: list) -> tuple[str, str]:
    """Return (system_prompt, last_user_message)."""
    system = " ".join(m.get("content","") for m in messages if m.get("role")=="system")
    users  = [m for m in messages if m.get("role")=="user"]
    last   = users[-1].get("content","") if users else ""
    return system, (last if isinstance(last, str) else str(last))


class _WrappedChatCompletions:
    def __init__(self, inner):
        self._inner = inner

    def create(self, *, model: str, messages: list, **kwargs) -> Any:
        if not HAS_OPENAI:
            raise ImportError("pip install openai")

        cfg = _get_config()

        # Optimizer: compress last user message if enabled
        messages, optimizer_meta = _compress_if_enabled(messages, cfg)

        system_prompt, user_text = _extract_messages(messages)
        t0  = time.perf_counter()
        ttft = 0.0

        if kwargs.get("stream", False):
            return self._stream(model, messages, system_prompt, user_text, t0, cfg, kwargs, optimizer_meta)

        try:
            resp = self._inner.create(model=model, messages=messages, **kwargs)
            lat  = (time.perf_counter() - t0) * 1000
            self._capture(resp, model, lat, 0.0, system_prompt, user_text, cfg, optimizer_meta)
            return resp
        except Exception as exc:
            lat = (time.perf_counter() - t0) * 1000
            self._capture_error(str(exc), model, lat, cfg)
            raise

    def _stream(self, model, messages, system_prompt, user_text, t0, cfg, kwargs, optimizer_meta=None):
        kwargs_clean = {k: v for k,v in kwargs.items() if k != "stream"}
        ttft_ref = [0.0]
        chunks   = []
        try:
            stream = self._inner.create(
                model=model, messages=messages, stream=True,
                stream_options={"include_usage": True},
                **kwargs_clean,
            )
            for chunk in stream:
                if not ttft_ref[0] and chunk.choices and chunk.choices[0].delta.content:
                    ttft_ref[0] = (time.perf_counter() - t0) * 1000
                chunks.append(chunk)
                yield chunk
        finally:
            lat = (time.perf_counter() - t0) * 1000
            usage_chunk = next((c for c in reversed(chunks) if getattr(c,"usage",None)), None)
            if usage_chunk and usage_chunk.usage:
                u = usage_chunk.usage
                pt, ct = u.prompt_tokens or 0, u.completion_tokens or 0
                cached = getattr(getattr(u,"prompt_tokens_details",None),"cached_tokens",0) or 0
            else:
                pt = sum(len(str(m.get("content",""))) for m in messages) // 4
                ct = sum(len(c.choices[0].delta.content or "") for c in chunks if c.choices) // 4
                cached = 0
            resp_text = "".join(
                c.choices[0].delta.content or "" for c in chunks if c.choices
            )
            self._capture_raw(model, pt, ct, cached, lat, ttft_ref[0], 200, None,
                               user_text, resp_text, system_prompt, cfg, optimizer_meta)

    def _capture(self, resp, model, lat, ttft, system_prompt, user_text, cfg, optimizer_meta=None):
        u = resp.usage
        pt     = u.prompt_tokens     if u else 0
        ct     = u.completion_tokens if u else 0
        cached = getattr(getattr(u,"prompt_tokens_details",None),"cached_tokens",0) or 0
        rt     = resp.choices[0].message.content[:600] if resp.choices else ""
        self._capture_raw(model, pt, ct, cached, lat, ttft, 200, None,
                          user_text, rt, system_prompt, cfg, optimizer_meta)

    def _capture_error(self, error, model, lat, cfg):
        self._capture_raw(model, 0, 0, 0, lat, 0, 500, error[:400], "", "", "", cfg)

    def _capture_raw(self, model, pt, ct, cached, lat, ttft, status, error,
                     user_text, resp_text, system_prompt, cfg, optimizer_meta=None):
        try:
            ev = _build_event(
                provider="openai", model=model,
                prompt_tokens=pt, completion_tokens=ct, cached_tokens=cached,
                latency_ms=lat, ttft_ms=ttft,
                status_code=status, error=error,
                prompt_text=user_text, response_text=resp_text,
                system_prompt=system_prompt,
                endpoint="/chat/completions",
                extra_tags={},
                org_id=cfg["org_id"], environment=cfg["environment"],
                optimizer_meta=optimizer_meta,
            )
            _get_queue().enqueue(ev)
        except Exception:
            pass  # never break the app


class _WrappedChat:
    def __init__(self, inner): self.completions = _WrappedChatCompletions(inner.completions)


class _WrappedEmbeddings:
    def __init__(self, inner): self._inner = inner

    def create(self, *, model: str, input: Any, **kwargs) -> Any:
        if not HAS_OPENAI: raise ImportError("pip install openai")
        cfg = _get_config()
        t0  = time.perf_counter()
        try:
            resp = self._inner.create(model=model, input=input, **kwargs)
            lat  = (time.perf_counter() - t0) * 1000
            u    = resp.usage
            ev   = _build_event(
                provider="openai", model=model,
                prompt_tokens=u.prompt_tokens if u else 0,
                completion_tokens=0, cached_tokens=0,
                latency_ms=lat, ttft_ms=0,
                status_code=200, error=None,
                prompt_text=str(input)[:200] if isinstance(input,str) else "",
                response_text="[embedding]", system_prompt="",
                endpoint="/embeddings", extra_tags={"type":"embedding"},
                org_id=cfg["org_id"], environment=cfg["environment"],
            )
            _get_queue().enqueue(ev)
            return resp
        except Exception as exc:
            raise


class OpenAI:
    """Drop-in for openai.OpenAI — wraps transparently."""
    def __init__(self, **kwargs):
        if not HAS_OPENAI: raise ImportError("pip install openai")
        self._client = _oai.OpenAI(**kwargs)
        self.chat       = _WrappedChat(self._client.chat)
        self.embeddings = _WrappedEmbeddings(self._client.embeddings)

    def __getattr__(self, name): return getattr(self._client, name)


class AsyncOpenAI:
    """Drop-in for openai.AsyncOpenAI."""
    def __init__(self, **kwargs):
        if not HAS_OPENAI: raise ImportError("pip install openai")
        self._client = _oai.AsyncOpenAI(**kwargs)

    async def _wrapped_create(self, model, messages, **kwargs):
        cfg = _get_config()
        t0  = time.perf_counter()
        system_prompt, user_text = _extract_messages(messages)
        resp = await self._client.chat.completions.create(model=model, messages=messages, **kwargs)
        lat  = (time.perf_counter() - t0) * 1000
        u    = resp.usage
        ev   = _build_event(
            provider="openai", model=model,
            prompt_tokens=u.prompt_tokens if u else 0,
            completion_tokens=u.completion_tokens if u else 0,
            cached_tokens=0, latency_ms=lat, ttft_ms=0,
            status_code=200, error=None,
            prompt_text=user_text, response_text="",
            system_prompt=system_prompt,
            endpoint="/chat/completions", extra_tags={},
            org_id=cfg["org_id"], environment=cfg["environment"],
        )
        _get_queue().enqueue(ev)
        return resp

    def __getattr__(self, name): return getattr(self._client, name)
