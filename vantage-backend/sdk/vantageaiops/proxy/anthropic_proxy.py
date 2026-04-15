"""
vantage/proxy/anthropic_proxy.py
---------------------------------
Drop-in for anthropic.Anthropic.

BEFORE:
    import anthropic
    client = anthropic.Anthropic(api_key="sk-ant-...")

AFTER:
    import vantage; vantage.init("crt_...")
    from cohrint.proxy.anthropic_proxy import Anthropic
    client = Anthropic(api_key="sk-ant-...")
"""

from __future__ import annotations
import time
from typing import Any

from cohrint.proxy.universal import _build_event, _extract_messages

try:
    import anthropic as _ant
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def _get_queue():
    from vantage import _get_queue as gq; return gq()
def _get_config():
    from vantage import _get_config as gc; return gc()


class _WrappedMessages:
    def __init__(self, inner): self._inner = inner

    def create(self, *, model: str, messages: list, **kwargs) -> Any:
        if not HAS_ANTHROPIC: raise ImportError("pip install anthropic")
        cfg = _get_config()
        t0  = time.perf_counter()
        ttft_ref = [0.0]

        system_raw = kwargs.get("system", "")
        system_txt = (system_raw if isinstance(system_raw, str)
                      else " ".join(b.get("text","") for b in system_raw
                                    if isinstance(b,dict) and b.get("type")=="text"))
        users     = [m for m in messages if m.get("role") == "user"]
        user_text = ""
        if users:
            c = users[-1].get("content","")
            user_text = c if isinstance(c, str) else " ".join(
                b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text")

        if kwargs.get("stream", False):
            return self._stream(model, messages, system_txt, user_text, t0, cfg, kwargs)

        try:
            resp = self._inner.create(model=model, messages=messages, **kwargs)
            lat  = (time.perf_counter() - t0) * 1000
            u    = resp.usage
            rt   = resp.content[0].text[:600] if resp.content else ""
            ev   = _build_event(
                provider="anthropic", model=model,
                prompt_tokens=getattr(u,"input_tokens",0),
                completion_tokens=getattr(u,"output_tokens",0),
                cached_tokens=getattr(u,"cache_read_input_tokens",0),
                latency_ms=lat, ttft_ms=0,
                status_code=200, error=None,
                prompt_text=user_text, response_text=rt,
                system_prompt=system_txt,
                endpoint="/messages", extra_tags={},
                org_id=cfg["org_id"], environment=cfg["environment"],
            )
            _get_queue().enqueue(ev)
            return resp
        except Exception as exc:
            lat = (time.perf_counter() - t0) * 1000
            try:
                ev = _build_event(
                    provider="anthropic", model=model,
                    prompt_tokens=0, completion_tokens=0, cached_tokens=0,
                    latency_ms=lat, ttft_ms=0, status_code=500, error=str(exc)[:400],
                    prompt_text="", response_text="", system_prompt="",
                    endpoint="/messages", extra_tags={},
                    org_id=cfg["org_id"], environment=cfg["environment"],
                )
                _get_queue().enqueue(ev)
            except Exception:
                pass
            raise

    def _stream(self, model, messages, system_txt, user_text, t0, cfg, kwargs):
        kwargs_s = {k:v for k,v in kwargs.items() if k != "stream"}
        ttft_ref = [0.0]
        it, ot, cr = 0, 0, 0
        resp_parts = []
        with self._inner.messages.stream(model=model, messages=messages, **kwargs_s) as s:
            for event in s:
                if not ttft_ref[0] and hasattr(event,"type") and event.type=="content_block_delta":
                    ttft_ref[0] = (time.perf_counter() - t0) * 1000
                if hasattr(event,"type") and event.type=="message_start" and hasattr(event,"message"):
                    u  = event.message.usage
                    it = getattr(u,"input_tokens",0)
                    cr = getattr(u,"cache_read_input_tokens",0)
                if hasattr(event,"type") and event.type=="message_delta" and hasattr(event,"usage"):
                    ot = getattr(event.usage,"output_tokens",0)
                if hasattr(event,"type") and event.type=="content_block_delta":
                    resp_parts.append(getattr(getattr(event,"delta",None),"text",""))
                yield event
        lat = (time.perf_counter() - t0) * 1000
        try:
            ev = _build_event(
                provider="anthropic", model=model,
                prompt_tokens=it, completion_tokens=ot, cached_tokens=cr,
                latency_ms=lat, ttft_ms=ttft_ref[0],
                status_code=200, error=None,
                prompt_text=user_text,
                response_text="".join(resp_parts)[:600],
                system_prompt=system_txt,
                endpoint="/messages", extra_tags={},
                org_id=cfg["org_id"], environment=cfg["environment"],
            )
            _get_queue().enqueue(ev)
        except Exception:
            pass


class Anthropic:
    """Drop-in for anthropic.Anthropic."""
    def __init__(self, **kwargs):
        if not HAS_ANTHROPIC: raise ImportError("pip install anthropic")
        self._client  = _ant.Anthropic(**kwargs)
        self.messages = _WrappedMessages(self._client.messages)
    def __getattr__(self, name): return getattr(self._client, name)
