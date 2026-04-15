"""
Suite 34 — OTel session rollup
Tests that OTel ingest creates/accumulates otel_sessions rows
and that GET /v1/sessions returns correct data.
Covers: claude-code, gemini-cli, codex-cli service.name variants.
Hits live API at https://api.cohrint.com.
"""
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import API_URL as API_BASE
from helpers.api import fresh_account

API_KEY, _ORG_ID, _COOKIES = fresh_account(prefix="os34")
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


# ── Payload builders ──────────────────────────────────────────────────────────

def ts_nano() -> str:
    return str(int(time.time() * 1e9))


def otel_payload(session_id: str, tokens_in: int = 100, tokens_out: int = 20) -> dict:
    """Claude Code OTLP metrics payload (gen_ai.client.token.usage)."""
    now_ns = str(int(time.time() * 1e9))
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",  "value": {"stringValue": "claude-code"}},
                    {"key": "session.id",    "value": {"stringValue": session_id}},
                    {"key": "user.email",    "value": {"stringValue": "test@cohrint.com"}},
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
            params={"developer_email": "test@cohrint.com"},
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200
        data = sessions_res.json()
        for s in data["sessions"]:
            assert s["developer_email"] == "test@cohrint.com"

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


# ── Gemini CLI payload builder ────────────────────────────────────────────────

def gemini_otel_payload(session_id: str, tokens_in: int = 9000, tokens_out: int = 2200,
                        thought: int = 800, cache: int = 1500) -> dict:
    """
    Gemini CLI OTLP metrics payload — uses gemini_cli.token.usage metric name
    with type attribute (input/output/thought/cache).
    Matches real gemini-cli telemetry format verified in suite 17.
    """
    now = ts_nano()
    def dp(tok_type: str, val: int) -> dict:
        return {
            "asDouble": val,
            "startTimeUnixNano": now,
            "timeUnixNano": now,
            "attributes": [
                {"key": "type",  "value": {"stringValue": tok_type}},
                {"key": "model", "value": {"stringValue": "gemini-2.0-flash"}},
            ],
        }
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "gemini-cli"}},
                    {"key": "user.email",   "value": {"stringValue": "test@cohrint.com"}},
                    {"key": "session.id",   "value": {"stringValue": session_id}},
                    {"key": "terminal.type","value": {"stringValue": "iTerm.app"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "gemini-cli", "version": "1.0.0"},
                "metrics": [
                    {
                        "name": "gemini_cli.token.usage",
                        "sum": {"dataPoints": [
                            dp("input",   tokens_in),
                            dp("output",  tokens_out),
                            dp("thought", thought),
                            dp("cache",   cache),
                        ], "isMonotonic": True},
                    },
                    {
                        "name": "gemini_cli.api.request.count",
                        "sum": {"dataPoints": [{
                            "asDouble": 3,
                            "startTimeUnixNano": now, "timeUnixNano": now,
                            "attributes": [
                                {"key": "model",       "value": {"stringValue": "gemini-2.0-flash"}},
                                {"key": "status_code", "value": {"stringValue": "200"}},
                            ],
                        }], "isMonotonic": True},
                    },
                ],
            }],
        }]
    }


# ── Codex CLI payload builder ─────────────────────────────────────────────────

def codex_otel_payload(session_id: str, tokens_in: int = 5000, tokens_out: int = 1200,
                       cost_usd: float = 0.032) -> dict:
    """
    Codex CLI OTLP metrics payload — uses gen_ai.client.token.usage (GenAI conventions)
    plus codex.cost.usage for explicit cost.
    Matches real codex-cli telemetry format verified in suite 17.
    """
    now = ts_nano()
    def dp(tok_type: str, val: int) -> dict:
        return {
            "asDouble": val,
            "startTimeUnixNano": now,
            "timeUnixNano": now,
            "attributes": [
                {"key": "gen_ai.token.type",    "value": {"stringValue": tok_type}},
                {"key": "gen_ai.request.model", "value": {"stringValue": "o3-mini"}},
            ],
        }
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "codex-cli"}},
                    {"key": "user.email",   "value": {"stringValue": "test@cohrint.com"}},
                    {"key": "session.id",   "value": {"stringValue": session_id}},
                    {"key": "terminal.type","value": {"stringValue": "tmux"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "codex-cli", "version": "1.0.0"},
                "metrics": [
                    {
                        "name": "gen_ai.client.token.usage",
                        "sum": {"dataPoints": [
                            dp("input",  tokens_in),
                            dp("output", tokens_out),
                        ], "isMonotonic": True},
                    },
                    {
                        "name": "codex.cost.usage",
                        "sum": {"dataPoints": [{
                            "asDouble": cost_usd,
                            "startTimeUnixNano": now, "timeUnixNano": now,
                            "attributes": [
                                {"key": "model", "value": {"stringValue": "o3-mini"}},
                            ],
                        }], "isMonotonic": True},
                    },
                    {
                        "name": "codex.session.count",
                        "sum": {"dataPoints": [{
                            "asDouble": 1,
                            "startTimeUnixNano": now, "timeUnixNano": now,
                            "attributes": [],
                        }], "isMonotonic": True},
                    },
                ],
            }],
        }]
    }


# ── Gemini session rollup tests ───────────────────────────────────────────────

class TestGeminiSessionRollup:

    def test_gemini_ingest_creates_session_row(self):
        """Gemini CLI OTel ingest with session_id creates a row in otel_sessions."""
        session_id = f"gemini-test-{uuid.uuid4()}"
        res = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=gemini_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        assert res.status_code == 200, f"Gemini OTel ingest failed: {res.text}"

        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200, f"GET /v1/sessions failed: {sessions_res.text}"
        session_ids = [s["session_id"] for s in sessions_res.json()["sessions"]]
        assert session_id in session_ids, f"Gemini session {session_id} not found in {session_ids}"

    def test_gemini_session_provider_is_gemini(self):
        """otel_sessions row for Gemini CLI has provider = gemini_cli."""
        session_id = f"gemini-test-{uuid.uuid4()}"
        requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=gemini_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None, f"Gemini session {session_id} not found"
        assert row["provider"] in ("gemini_cli", "gemini-cli"), \
            f"Expected gemini provider, got: {row['provider']}"

    def test_gemini_tokens_accumulate_across_ingests(self):
        """Two Gemini ingests with same session_id accumulate tokens."""
        session_id = f"gemini-test-{uuid.uuid4()}"

        res1 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=gemini_otel_payload(session_id, tokens_in=1000, tokens_out=200),
            headers=HEADERS, timeout=10,
        )
        assert res1.status_code == 200

        res2 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=gemini_otel_payload(session_id, tokens_in=2000, tokens_out=400),
            headers=HEADERS, timeout=10,
        )
        assert res2.status_code == 200

        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None, f"session {session_id} not found"
        assert row["input_tokens"]  >= 3000, f"expected >=3000 input, got {row['input_tokens']}"
        assert row["output_tokens"] >= 600,  f"expected >=600 output, got {row['output_tokens']}"
        assert row["event_count"]   >= 2,    f"expected >=2 events, got {row['event_count']}"

    def test_gemini_session_model_recorded(self):
        """otel_sessions row for Gemini CLI records gemini-2.0-flash as model."""
        session_id = f"gemini-test-{uuid.uuid4()}"
        requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=gemini_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None
        assert row["model"] == "gemini-2.0-flash", f"Expected gemini-2.0-flash, got: {row['model']}"


# ── Codex CLI session rollup tests ────────────────────────────────────────────

class TestCodexSessionRollup:

    def test_codex_ingest_creates_session_row(self):
        """Codex CLI OTel ingest with session_id creates a row in otel_sessions."""
        session_id = f"codex-test-{uuid.uuid4()}"
        res = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=codex_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        assert res.status_code == 200, f"Codex OTel ingest failed: {res.text}"

        time.sleep(1)

        sessions_res = requests.get(
            f"{API_BASE}/v1/sessions",
            headers=HEADERS, timeout=10,
        )
        assert sessions_res.status_code == 200, f"GET /v1/sessions failed: {sessions_res.text}"
        session_ids = [s["session_id"] for s in sessions_res.json()["sessions"]]
        assert session_id in session_ids, f"Codex session {session_id} not found in {session_ids}"

    def test_codex_session_provider_is_codex(self):
        """otel_sessions row for Codex CLI has provider = codex_cli."""
        session_id = f"codex-test-{uuid.uuid4()}"
        requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=codex_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None, f"Codex session {session_id} not found"
        assert row["provider"] in ("codex_cli", "codex-cli"), \
            f"Expected codex provider, got: {row['provider']}"

    def test_codex_tokens_accumulate_across_ingests(self):
        """Two Codex ingests with same session_id accumulate tokens."""
        session_id = f"codex-test-{uuid.uuid4()}"

        res1 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=codex_otel_payload(session_id, tokens_in=500, tokens_out=100),
            headers=HEADERS, timeout=10,
        )
        assert res1.status_code == 200

        res2 = requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=codex_otel_payload(session_id, tokens_in=1000, tokens_out=200),
            headers=HEADERS, timeout=10,
        )
        assert res2.status_code == 200

        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None, f"session {session_id} not found"
        assert row["input_tokens"]  >= 1500, f"expected >=1500 input, got {row['input_tokens']}"
        assert row["output_tokens"] >= 300,  f"expected >=300 output, got {row['output_tokens']}"
        assert row["event_count"]   >= 2,    f"expected >=2 events, got {row['event_count']}"

    def test_codex_session_model_recorded(self):
        """otel_sessions row for Codex CLI records o3-mini as model."""
        session_id = f"codex-test-{uuid.uuid4()}"
        requests.post(
            f"{API_BASE}/v1/otel/v1/metrics",
            json=codex_otel_payload(session_id),
            headers=HEADERS, timeout=10,
        )
        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        row = next((s for s in sessions_res.json()["sessions"] if s["session_id"] == session_id), None)
        assert row is not None
        assert row["model"] == "o3-mini", f"Expected o3-mini, got: {row['model']}"


# ── Cross-tool session isolation test ────────────────────────────────────────

class TestCrossToolSessionIsolation:

    def test_gemini_and_codex_sessions_are_independent(self):
        """Gemini and Codex sessions with different IDs are stored as separate rows."""
        gemini_sid = f"gemini-test-{uuid.uuid4()}"
        codex_sid  = f"codex-test-{uuid.uuid4()}"

        requests.post(f"{API_BASE}/v1/otel/v1/metrics",
                      json=gemini_otel_payload(gemini_sid), headers=HEADERS, timeout=10)
        requests.post(f"{API_BASE}/v1/otel/v1/metrics",
                      json=codex_otel_payload(codex_sid),  headers=HEADERS, timeout=10)

        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        all_ids = [s["session_id"] for s in sessions_res.json()["sessions"]]
        assert gemini_sid in all_ids, f"Gemini session not found in {all_ids}"
        assert codex_sid  in all_ids, f"Codex session not found in {all_ids}"

    def test_same_session_id_different_tools_accumulates(self):
        """If Gemini and Codex share a session_id, tokens accumulate in one row."""
        shared_sid = f"shared-test-{uuid.uuid4()}"

        requests.post(f"{API_BASE}/v1/otel/v1/metrics",
                      json=gemini_otel_payload(shared_sid, tokens_in=1000, tokens_out=200),
                      headers=HEADERS, timeout=10)
        requests.post(f"{API_BASE}/v1/otel/v1/metrics",
                      json=codex_otel_payload(shared_sid, tokens_in=500, tokens_out=100),
                      headers=HEADERS, timeout=10)

        time.sleep(1)

        sessions_res = requests.get(f"{API_BASE}/v1/sessions", headers=HEADERS, timeout=10)
        assert sessions_res.status_code == 200
        rows = [s for s in sessions_res.json()["sessions"] if s["session_id"] == shared_sid]
        assert len(rows) == 1, f"Expected 1 row for shared session, got {len(rows)}"
        row = rows[0]
        assert row["input_tokens"]  >= 1500, f"expected >=1500 accumulated input, got {row['input_tokens']}"
        assert row["output_tokens"] >= 300,  f"expected >=300 accumulated output, got {row['output_tokens']}"
