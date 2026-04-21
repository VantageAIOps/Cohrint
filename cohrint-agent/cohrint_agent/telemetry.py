"""
telemetry.py — Non-blocking OTel metrics/logs exporter for cohrint-agent.

Controlled by:
  COHRINT_OTEL_ENABLED=true           — activates export (default: off)
  OTEL_EXPORTER_OTLP_ENDPOINT         — collector base URL (default: https://api.cohrint.com)
  COHRINT_API_KEY                     — Bearer token for auth

All errors are silently swallowed — this is best-effort, fire-and-forget telemetry.
"""
from __future__ import annotations

import json
import os
import queue as _queue
import threading
import time
from typing import Any


_DEFAULT_ENDPOINT = "https://api.cohrint.com"

# Shared bounded worker so a 500-event flush can't spawn 500 threads
# against a stalled collector (T-CONCUR.otel_worker). Previous impl
# spawned one daemon thread per event, exhausting the OS thread limit
# on slow endpoints. A single worker serialises exports through a
# bounded queue; when the queue fills the event is dropped (telemetry
# is best-effort anyway).
_EXPORT_QUEUE_MAX = 1024
_export_queue: "_queue.Queue[tuple[str, dict[str, Any], dict[str, str]]] | None" = None
_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()


def _ensure_worker() -> "_queue.Queue[tuple[str, dict[str, Any], dict[str, str]]]":
    global _export_queue, _worker_thread
    with _worker_lock:
        if _export_queue is None:
            _export_queue = _queue.Queue(maxsize=_EXPORT_QUEUE_MAX)
        if _worker_thread is None or not _worker_thread.is_alive():
            q = _export_queue

            def _run() -> None:
                while True:
                    try:
                        url, payload, headers = q.get()
                    except Exception:
                        continue
                    try:
                        import httpx
                        httpx.post(url, json=payload, headers=headers, timeout=5)
                    except Exception:
                        pass

            _worker_thread = threading.Thread(
                target=_run, name="otel-exporter", daemon=True
            )
            _worker_thread.start()
        return _export_queue


def _str_attr(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _int_attr(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"asInt": value}}


class OTelExporter:
    """Exports LLM usage as OTLP metrics + logs to the Cohrint backend."""

    def __init__(self) -> None:
        self.enabled = os.environ.get("COHRINT_OTEL_ENABLED", "false").lower() == "true"
        self.endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")
        self.api_key = os.environ.get("COHRINT_API_KEY", "")
        self.org_id = os.environ.get("COHRINT_ORG_ID", "")
        # Refuse to ship Bearer tokens over plaintext HTTP. An attacker who
        # sets OTEL_EXPORTER_OTLP_ENDPOINT=http://evil.example would otherwise
        # receive every Authorization header in the clear
        # (T-SAFETY.otel_https).
        from .update_check import _assert_https_api_base
        if self.enabled and not _assert_https_api_base(self.endpoint):
            self.enabled = False

    def _headers(self) -> dict[str, str]:
        from . import __version__
        h = {"Content-Type": "application/json", "User-Agent": f"cohrint-agent/{__version__}"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _build_metrics_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        model = event.get("model", "unknown")
        input_tokens = int(event.get("prompt_tokens", 0))
        output_tokens = int(event.get("completion_tokens", 0))
        cost_usd = float(event.get("cost_usd", event.get("total_cost_usd", 0.0)))

        resource_attrs = [_str_attr("service.name", "cohrint-agent")]
        if self.org_id:
            resource_attrs.append(_str_attr("org_id", self.org_id))

        model_attr = [_str_attr("model", model)]

        metrics = [
            {
                "name": "llm.tokens.input",
                "sum": {
                    "dataPoints": [{"asInt": input_tokens, "attributes": model_attr}],
                    "isMonotonic": True,
                },
            },
            {
                "name": "llm.tokens.output",
                "sum": {
                    "dataPoints": [{"asInt": output_tokens, "attributes": model_attr}],
                    "isMonotonic": True,
                },
            },
            {
                "name": "llm.cost.usd",
                "sum": {
                    "dataPoints": [{"asDouble": cost_usd, "attributes": model_attr}],
                    "isMonotonic": True,
                },
            },
        ]

        return {
            "resourceMetrics": [
                {
                    "resource": {"attributes": resource_attrs},
                    "scopeMetrics": [{"metrics": metrics}],
                }
            ]
        }

    def _build_logs_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        model = event.get("model", "unknown")
        # Always hash session_id on the telemetry boundary. The tracker
        # already hashes it in anonymized mode, but the `full`/`strict`
        # privacy branches forwarded the raw UUID — enough to reconstruct
        # the whole turn sequence at the collector
        # (T-PRIVACY.otel_session_id_always_hashed).
        raw_sid = event.get("session_id", "") or ""
        import hashlib as _h
        sid_out = _h.sha256(raw_sid.encode("utf-8", errors="replace")).hexdigest() if raw_sid else ""
        log_body = {
            "model": model,
            "prompt_tokens": event.get("prompt_tokens", 0),
            "completion_tokens": event.get("completion_tokens", 0),
            "cost_usd": event.get("cost_usd", event.get("total_cost_usd", 0.0)),
            "latency_ms": event.get("latency_ms", 0),
            "session_id": sid_out,
        }

        resource_attrs = [_str_attr("service.name", "cohrint-agent")]

        return {
            "resourceLogs": [
                {
                    "resource": {"attributes": resource_attrs},
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "body": {"stringValue": json.dumps(log_body)},
                                    "attributes": [_str_attr("model", model)],
                                    "timeUnixNano": str(int(time.time() * 1e9)),
                                }
                            ]
                        }
                    ],
                }
            ]
        }

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        """Best-effort POST — never raises."""
        try:
            import httpx
            httpx.post(
                f"{self.endpoint}{path}",
                json=payload,
                headers=self._headers(),
                timeout=5,
            )
        except Exception:
            pass

    def export(self, event: dict[str, Any]) -> None:
        """Synchronously export metrics + logs. Silently swallows all errors."""
        if not self.enabled:
            return
        try:
            self._post("/v1/otel/v1/metrics", self._build_metrics_payload(event))
            self._post("/v1/otel/v1/logs", self._build_logs_payload(event))
        except Exception:
            pass

    def export_async(self, event: dict[str, Any]) -> None:
        """Fire-and-forget: enqueue for the shared worker thread. Non-blocking.

        Drops silently if the export queue is saturated — better than
        blocking the caller or spawning a new thread per event.
        """
        if not self.enabled:
            return
        try:
            q = _ensure_worker()
            headers = self._headers()
            try:
                q.put_nowait((
                    f"{self.endpoint}/v1/otel/v1/metrics",
                    self._build_metrics_payload(event),
                    headers,
                ))
                q.put_nowait((
                    f"{self.endpoint}/v1/otel/v1/logs",
                    self._build_logs_payload(event),
                    headers,
                ))
            except _queue.Full:
                pass
        except Exception:
            pass
