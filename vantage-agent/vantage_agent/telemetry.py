"""
telemetry.py — Non-blocking OTel metrics/logs exporter for vantage-agent.

Controlled by:
  VANTAGE_OTEL_ENABLED=true           — activates export (default: off)
  OTEL_EXPORTER_OTLP_ENDPOINT         — collector base URL (default: https://api.vantageaiops.com)
  VANTAGE_API_KEY                     — Bearer token for auth

All errors are silently swallowed — this is best-effort, fire-and-forget telemetry.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


_DEFAULT_ENDPOINT = "https://api.vantageaiops.com"


def _str_attr(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _int_attr(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"asInt": value}}


class OTelExporter:
    """Exports LLM usage as OTLP metrics + logs to the VantageAI backend."""

    def __init__(self) -> None:
        self.enabled = os.environ.get("VANTAGE_OTEL_ENABLED", "false").lower() == "true"
        self.endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")
        self.api_key = os.environ.get("VANTAGE_API_KEY", "")
        self.org_id = os.environ.get("VANTAGE_ORG_ID", "")

    def _headers(self) -> dict[str, str]:
        from . import __version__
        h = {"Content-Type": "application/json", "User-Agent": f"vantage-agent/{__version__}"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _build_metrics_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        model = event.get("model", "unknown")
        input_tokens = int(event.get("prompt_tokens", 0))
        output_tokens = int(event.get("completion_tokens", 0))
        cost_usd = float(event.get("cost_usd", event.get("total_cost_usd", 0.0)))

        resource_attrs = [_str_attr("service.name", "vantageai-agent")]
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
        log_body = {
            "model": model,
            "prompt_tokens": event.get("prompt_tokens", 0),
            "completion_tokens": event.get("completion_tokens", 0),
            "cost_usd": event.get("cost_usd", event.get("total_cost_usd", 0.0)),
            "latency_ms": event.get("latency_ms", 0),
            "session_id": event.get("session_id", ""),
        }

        resource_attrs = [_str_attr("service.name", "vantageai-agent")]

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
        """Fire-and-forget: export in a daemon thread. Returns immediately."""
        if not self.enabled:
            return
        t = threading.Thread(target=self.export, args=(event,), daemon=True)
        t.start()
