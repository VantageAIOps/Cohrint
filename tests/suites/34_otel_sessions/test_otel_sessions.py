"""
Suite 34 — OTel session rollup
Tests that OTel ingest creates/accumulates otel_sessions rows
and that GET /v1/sessions returns correct data.
Hits live API at https://api.vantageaiops.com.
"""
import os
import time
import uuid

import pytest
import requests

API_BASE = os.environ.get("VANTAGE_API_BASE", "https://api.vantageaiops.com")
API_KEY  = os.environ.get("VANTAGE_API_KEY", "")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

if not API_KEY:
    pytest.skip("VANTAGE_API_KEY not set", allow_module_level=True)


def otel_payload(session_id: str, tokens_in: int = 100, tokens_out: int = 20) -> dict:
    """Build a minimal OTLP metrics payload with session.id set."""
    now_ns = str(int(time.time() * 1e9))
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",  "value": {"stringValue": "claude-code"}},
                    {"key": "session.id",    "value": {"stringValue": session_id}},
                    {"key": "user.email",    "value": {"stringValue": "test@vantageaiops.com"}},
                ]
            },
            "scopeMetrics": [{
                "metrics": [{
                    "name": "gen_ai.client.token.usage",
                    "sum": {
                        "dataPoints": [
                            {
                                "attributes": [
                                    {"key": "gen_ai.token.type",    "value": {"stringValue": "input"}},
                                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                ],
                                "asInt": tokens_in,
                                "startTimeUnixNano": now_ns,
                                "timeUnixNano": now_ns,
                            },
                            {
                                "attributes": [
                                    {"key": "gen_ai.token.type",    "value": {"stringValue": "output"}},
                                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                ],
                                "asInt": tokens_out,
                                "startTimeUnixNano": now_ns,
                                "timeUnixNano": now_ns,
                            },
                        ]
                    }
                }]
            }]
        }]
    }


class TestOtelSessionRollup:

    def test_otel_ingest_creates_session_row(self):
        """Sending OTel metrics with a session_id creates a row in otel_sessions."""
        session_id = f"test-{uuid.uuid4()}"
        res = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=otel_payload(session_id, tokens_in=100, tokens_out=20),
            headers=HEADERS,
            timeout=10,
        )
        assert res.status_code == 200, f"OTel ingest failed: {res.text}"

        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers=HEADERS,
            timeout=10,
        )
        assert sessions_res.status_code == 200, f"GET /v1/sessions failed: {sessions_res.text}"
        data = sessions_res.json()
        assert "sessions" in data
        session_ids = [s["session_id"] for s in data["sessions"]]
        assert session_id in session_ids, f"session {session_id} not found in {session_ids}"

    def test_second_ingest_accumulates_tokens(self):
        """Two OTel ingests with the same session_id accumulate tokens, not duplicate."""
        session_id = f"test-{uuid.uuid4()}"

        res1 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=otel_payload(session_id, tokens_in=100, tokens_out=20),
            headers=HEADERS, timeout=10,
        )
        assert res1.status_code == 200

        res2 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=otel_payload(session_id, tokens_in=200, tokens_out=40),
            headers=HEADERS, timeout=10,
        )
        assert res2.status_code == 200

        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200
        sessions = sessions_res.json()["sessions"]
        row = next((s for s in sessions if s["session_id"] == session_id), None)
        assert row is not None, f"session {session_id} not found"
        assert row["input_tokens"]  >= 300, f"expected >=300 input tokens, got {row['input_tokens']}"
        assert row["output_tokens"] >= 60,  f"expected >=60 output tokens, got {row['output_tokens']}"
        assert row["event_count"]   >= 2,   f"expected >=2 events, got {row['event_count']}"

    def test_ingest_without_session_id_does_not_crash(self):
        """OTel ingest with no session.id attribute still returns 200."""
        now_ns = str(int(time.time() * 1e9))
        payload = {
            "resourceMetrics": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "claude-code"}},
                    ]
                },
                "scopeMetrics": [{
                    "metrics": [{
                        "name": "gen_ai.client.token.usage",
                        "sum": {
                            "dataPoints": [{
                                "attributes": [
                                    {"key": "gen_ai.token.type",    "value": {"stringValue": "input"}},
                                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
                                ],
                                "asInt": 50,
                                "startTimeUnixNano": now_ns,
                                "timeUnixNano": now_ns,
                            }]
                        }
                    }]
                }]
            }]
        }
        res = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=payload, headers=HEADERS, timeout=10,
        )
        assert res.status_code == 200

    def test_get_sessions_requires_auth(self):
        """GET /v1/sessions returns 401 without a valid API key."""
        res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers={"Authorization": "Bearer invalid_key"},
            timeout=10,
        )
        assert res.status_code in (401, 403), f"Expected 401/403, got {res.status_code}"

    def test_get_sessions_filter_by_developer_email(self):
        """GET /v1/sessions?developer_email=x filters results correctly."""
        session_id = f"test-{uuid.uuid4()}"
        res = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        assert res.status_code == 200
        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            params={"developer_email": "test@vantageaiops.com"},
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200
        data = sessions_res.json()
        for s in data["sessions"]:
            assert s["developer_email"] == "test@vantageaiops.com"

    def test_get_sessions_limit_respected(self):
        """GET /v1/sessions?limit=2 returns at most 2 sessions."""
        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            params={"limit": "2"},
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200
        data = sessions_res.json()
        assert len(data["sessions"]) <= 2
        assert "total" in data
