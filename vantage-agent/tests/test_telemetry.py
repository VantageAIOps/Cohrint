"""
test_telemetry.py — Unit tests for OTelExporter (telemetry.py).

All HTTP calls are mocked — no real network access.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_EVENT = {
    "model": "claude-sonnet-4-6",
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_cost_usd": 0.00123,
    "cost_usd": 0.00123,
    "latency_ms": 420,
    "session_id": "sess-abc123",
}


def _make_exporter(**env_overrides):
    """Return an OTelExporter with env controlled by kwargs."""
    import os
    env = {
        "VANTAGE_OTEL_ENABLED": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://api.vantageaiops.com",
        "VANTAGE_API_KEY": "",
        "VANTAGE_ORG_ID": "",
        **env_overrides,
    }
    with patch.dict(os.environ, env, clear=False):
        from vantage_agent.telemetry import OTelExporter
        return OTelExporter()


# ---------------------------------------------------------------------------
# Test 1 — disabled by default (no HTTP call)
# ---------------------------------------------------------------------------

def test_disabled_by_default_no_http_call():
    import os
    # Ensure env var is NOT set to true
    env = {"VANTAGE_OTEL_ENABLED": "false"}
    with patch.dict(os.environ, env, clear=False):
        from vantage_agent.telemetry import OTelExporter
        exporter = OTelExporter()
        with patch("httpx.post") as mock_post:
            exporter.export(SAMPLE_EVENT)
            mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — VANTAGE_OTEL_ENABLED=true activates exporter
# ---------------------------------------------------------------------------

def test_enabled_makes_http_calls():
    import os
    env = {"VANTAGE_OTEL_ENABLED": "true", "VANTAGE_API_KEY": "vnt_test"}
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            exporter.export(SAMPLE_EVENT)
            assert mock_post.call_count == 2  # metrics + logs


# ---------------------------------------------------------------------------
# Test 3 — Metrics payload has correct OTLP structure
# ---------------------------------------------------------------------------

def test_metrics_payload_structure():
    import os
    env = {"VANTAGE_OTEL_ENABLED": "true", "VANTAGE_API_KEY": "vnt_test"}
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()
        payload = exporter._build_metrics_payload(SAMPLE_EVENT)

    assert "resourceMetrics" in payload
    rm = payload["resourceMetrics"][0]
    # resource attributes include service.name
    attr_keys = [a["key"] for a in rm["resource"]["attributes"]]
    assert "service.name" in attr_keys

    metrics = rm["scopeMetrics"][0]["metrics"]
    metric_names = [m["name"] for m in metrics]
    assert "llm.tokens.input" in metric_names
    assert "llm.tokens.output" in metric_names
    assert "llm.cost.usd" in metric_names

    # Check dataPoint values
    for m in metrics:
        if m["name"] == "llm.tokens.input":
            dp = m["sum"]["dataPoints"][0]
            assert dp["asInt"] == 100
        if m["name"] == "llm.tokens.output":
            dp = m["sum"]["dataPoints"][0]
            assert dp["asInt"] == 50
        if m["name"] == "llm.cost.usd":
            dp = m["sum"]["dataPoints"][0]
            assert abs(dp["asDouble"] - 0.00123) < 1e-9


# ---------------------------------------------------------------------------
# Test 4 — Logs payload has correct OTLP structure
# ---------------------------------------------------------------------------

def test_logs_payload_structure():
    import os
    env = {"VANTAGE_OTEL_ENABLED": "true"}
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()
        payload = exporter._build_logs_payload(SAMPLE_EVENT)

    assert "resourceLogs" in payload
    rl = payload["resourceLogs"][0]
    service_attr = next(a for a in rl["resource"]["attributes"] if a["key"] == "service.name")
    assert service_attr["value"]["stringValue"] == "vantageai-agent"

    log_record = rl["scopeLogs"][0]["logRecords"][0]
    body = json.loads(log_record["body"]["stringValue"])
    assert body["model"] == "claude-sonnet-4-6"
    assert body["prompt_tokens"] == 100
    assert body["completion_tokens"] == 50
    assert body["session_id"] == "sess-abc123"

    model_attr = next(a for a in log_record["attributes"] if a["key"] == "model")
    assert model_attr["value"]["stringValue"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Test 5 — Silently ignores network errors
# ---------------------------------------------------------------------------

def test_silently_ignores_network_errors():
    import os
    env = {"VANTAGE_OTEL_ENABLED": "true", "VANTAGE_API_KEY": "vnt_test"}
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()
        with patch("httpx.post", side_effect=ConnectionError("network down")):
            # Should not raise
            exporter.export(SAMPLE_EVENT)


# ---------------------------------------------------------------------------
# Test 6 — export_async returns immediately (non-blocking)
# ---------------------------------------------------------------------------

def test_export_async_returns_immediately():
    import os
    env = {"VANTAGE_OTEL_ENABLED": "true", "VANTAGE_API_KEY": "vnt_test"}
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()

        started_at = time.monotonic()
        with patch("httpx.post") as mock_post:
            # Simulate slow network
            def slow_post(*args, **kwargs):
                time.sleep(0.5)
                return MagicMock(status_code=200)
            mock_post.side_effect = slow_post
            exporter.export_async(SAMPLE_EVENT)
            elapsed = time.monotonic() - started_at
        # Should return well before the 500ms sleep completes
        assert elapsed < 0.2, f"export_async blocked for {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Test 7 — Custom OTEL_EXPORTER_OTLP_ENDPOINT is respected
# ---------------------------------------------------------------------------

def test_custom_endpoint_is_respected():
    import os
    custom = "https://my-collector.example.com"
    env = {
        "VANTAGE_OTEL_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": custom,
        "VANTAGE_API_KEY": "vnt_test",
    }
    with patch.dict(os.environ, env, clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        exporter = tel_mod.OTelExporter()
        assert exporter.endpoint == custom

        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            exporter.export(SAMPLE_EVENT)
            calls = mock_post.call_args_list
            assert len(calls) == 2
            for call in calls:
                url = call.args[0] if call.args else call.kwargs.get("url", "")
                assert url.startswith(custom)


# ---------------------------------------------------------------------------
# Test 8 — Missing env vars fall back to defaults
# ---------------------------------------------------------------------------

def test_missing_env_vars_use_defaults():
    import os
    # Remove the vars entirely if present
    keys_to_remove = ["VANTAGE_OTEL_ENABLED", "OTEL_EXPORTER_OTLP_ENDPOINT",
                      "VANTAGE_API_KEY", "VANTAGE_ORG_ID"]
    clean_env = {k: "" for k in keys_to_remove}
    # We can't truly "unset" with patch.dict easily, so set to empty/false
    with patch.dict(os.environ, {"VANTAGE_OTEL_ENABLED": "false",
                                  "OTEL_EXPORTER_OTLP_ENDPOINT": "",
                                  "VANTAGE_API_KEY": "",
                                  "VANTAGE_ORG_ID": ""},
                    clear=False):
        from importlib import reload
        import vantage_agent.telemetry as tel_mod
        reload(tel_mod)
        # Patch os.environ.get to simulate truly missing vars
        original_get = os.environ.get

        def patched_get(key, default=None):
            if key in keys_to_remove:
                return default
            return original_get(key, default)

        with patch.object(os, "environ") as mock_env:
            mock_env.get = patched_get
            exporter = tel_mod.OTelExporter()

        assert exporter.enabled is False
        assert exporter.endpoint == "https://api.vantageaiops.com"
        assert exporter.api_key == ""
