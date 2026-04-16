"""
Test Suite 49 — Agent Traces + DAG API
========================================

Tests the trace list and trace detail (span tree) endpoints.

  A. Trace List    (TL.1–TL.6)  — GET /v1/analytics/traces
  B. Trace Detail  (TD.1–TD.8)  — GET /v1/analytics/traces/:traceId
  C. Auth          (AU.1–AU.3)  — unauth rejection, org isolation

Uses da45 persistent seed accounts. Never creates fresh accounts.
All tests hit https://api.cohrint.com (no mocking).

NOTE: Tests that require an actual trace_id seed new events if the da45
org has no trace data, using the existing events API.
"""

import json
import sys
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import API_URL
from helpers.output import section, chk, warn

SEED_FILE = Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json"
if not SEED_FILE.exists():
    pytest.skip("da45_seed_state.json not found — run seed.py first", allow_module_level=True)

_seed = json.loads(SEED_FILE.read_text())
ADMIN_KEY  = _seed["admin"]["api_key"]
MEMBER_KEY = _seed["member"]["api_key"]

BASE = API_URL.rstrip("/")


def _api(method: str, path: str, key: str = ADMIN_KEY, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {key}"
    return getattr(requests, method)(f"{BASE}{path}", headers=headers, timeout=15, **kwargs)


def _seed_trace() -> str:
    """Seed two linked events (root + child) and return the trace_id."""
    trace_id = str(uuid.uuid4())
    root_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())

    _api("post", "/v1/events/batch", json={"events": [
        {
            "event_id": root_id,
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cost_total_usd": 0.003,
            "latency_ms": 800,
            "trace_id": trace_id,
            "agent_name": "orchestrator",
            "span_depth": 0,
        },
        {
            "event_id": child_id,
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "prompt_tokens": 60,
            "completion_tokens": 30,
            "cost_total_usd": 0.001,
            "latency_ms": 400,
            "trace_id": trace_id,
            "parent_event_id": root_id,
            "agent_name": "sub-agent",
            "span_depth": 1,
        },
    ]})
    return trace_id


# Seed a trace once for the session
_TRACE_ID = _seed_trace()


# ── A. Trace List ───────────────────────────────────────────────────────────────

class TestTraceList:
    def test_TL01_returns_200(self):
        """TL.1 — GET /v1/analytics/traces returns 200."""
        section("TL.1 — Trace list 200")
        r = _api("get", "/v1/analytics/traces?period=7")
        chk("200", r.status_code == 200)
        chk("has traces key", "traces" in r.json())

    def test_TL02_traces_is_list(self):
        """TL.2 — traces is an array."""
        section("TL.2 — traces is list")
        r = _api("get", "/v1/analytics/traces?period=7")
        chk("list", isinstance(r.json().get("traces"), list))

    def test_TL03_trace_shape(self):
        """TL.3 — Each trace has expected fields."""
        section("TL.3 — Trace shape")
        r = _api("get", "/v1/analytics/traces?period=7")
        traces = r.json().get("traces", [])
        if not traces:
            warn("No traces in last 7 days — shape check skipped")
            return
        t = traces[0]
        chk("trace_id present", "trace_id" in t)
        chk("spans present", "spans" in t)
        chk("cost present", "cost" in t)
        chk("started_at present", "started_at" in t)

    def test_TL04_seeded_trace_appears(self):
        """TL.4 — Seeded trace_id appears in the list."""
        section("TL.4 — Seeded trace in list")
        r = _api("get", "/v1/analytics/traces?period=1")
        ids = [t.get("trace_id") for t in r.json().get("traces", [])]
        chk("seeded trace in list", _TRACE_ID in ids)

    def test_TL05_period_param(self):
        """TL.5 — period=30 accepted, returns larger or equal result set."""
        section("TL.5 — period=30")
        r1 = _api("get", "/v1/analytics/traces?period=1")
        r30 = _api("get", "/v1/analytics/traces?period=30")
        chk("both 200", r1.status_code == 200 and r30.status_code == 200)
        chk("30d >= 1d", len(r30.json().get("traces", [])) >= len(r1.json().get("traces", [])))

    def test_TL06_member_can_list(self):
        """TL.6 — Member role can list traces."""
        section("TL.6 — Member lists traces")
        r = _api("get", "/v1/analytics/traces?period=7", key=MEMBER_KEY)
        chk("200", r.status_code == 200)


# ── B. Trace Detail ─────────────────────────────────────────────────────────────

class TestTraceDetail:
    def test_TD01_returns_200_for_seeded(self):
        """TD.1 — GET /v1/analytics/traces/:id returns 200 for seeded trace."""
        section("TD.1 — Trace detail 200")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        chk("200", r.status_code == 200)

    def test_TD02_shape(self):
        """TD.2 — Response has trace_id and spans array."""
        section("TD.2 — Trace detail shape")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        body = r.json()
        chk("trace_id matches", body.get("trace_id") == _TRACE_ID)
        chk("spans is list", isinstance(body.get("spans"), list))

    def test_TD03_two_spans(self):
        """TD.3 — Seeded trace has 2 spans (root + child)."""
        section("TD.3 — Two spans")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        chk("2 spans", len(r.json().get("spans", [])) == 2)

    def test_TD04_span_fields(self):
        """TD.4 — Each span has required DAG fields."""
        section("TD.4 — Span fields")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        spans = r.json().get("spans", [])
        chk("has spans", len(spans) > 0)
        s = spans[0]
        for field in ["id", "parent_id", "agent_name", "model", "provider",
                       "span_depth", "prompt_tokens", "completion_tokens",
                       "cost_usd", "latency_ms", "created_at"]:
            chk(f"span.{field} present", field in s)

    def test_TD05_root_has_null_parent(self):
        """TD.5 — Root span has parent_id=null."""
        section("TD.5 — Root parent is null")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        spans = r.json().get("spans", [])
        roots = [s for s in spans if not s.get("parent_id")]
        chk("exactly one root", len(roots) == 1)
        chk("root depth=0", roots[0].get("span_depth") == 0)

    def test_TD06_child_references_root(self):
        """TD.6 — Child span's parent_id matches root span id."""
        section("TD.6 — Child parent reference")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}")
        spans = r.json().get("spans", [])
        root = next((s for s in spans if not s.get("parent_id")), None)
        child = next((s for s in spans if s.get("parent_id")), None)
        chk("root exists", root is not None)
        chk("child exists", child is not None)
        if root and child:
            chk("child.parent_id == root.id", child["parent_id"] == root["id"])

    def test_TD07_unknown_trace_404(self):
        """TD.7 — Unknown trace_id returns 404."""
        section("TD.7 — Unknown trace 404")
        r = _api("get", f"/v1/analytics/traces/{uuid.uuid4()}")
        chk("404", r.status_code == 404)

    def test_TD08_member_can_read_detail(self):
        """TD.8 — Member role can read trace detail."""
        section("TD.8 — Member reads detail")
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}", key=MEMBER_KEY)
        chk("200", r.status_code == 200)


# ── C. Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_AU01_list_unauth_401(self):
        """AU.1 — Unauth trace list returns 401."""
        r = requests.get(f"{BASE}/v1/analytics/traces", timeout=10)
        chk("401", r.status_code == 401)

    def test_AU02_detail_unauth_401(self):
        """AU.2 — Unauth trace detail returns 401."""
        r = requests.get(f"{BASE}/v1/analytics/traces/{_TRACE_ID}", timeout=10)
        chk("401", r.status_code == 401)

    def test_AU03_cross_org_isolation(self):
        """AU.3 — Trace seeded by admin not visible with wrong key if org differs.
           (Uses superadmin key which is in same org — verifies it CAN see it.)"""
        section("AU.3 — Same-org superadmin sees trace")
        sa_key = _seed["superadmin"]["api_key"]
        r = _api("get", f"/v1/analytics/traces/{_TRACE_ID}", key=sa_key)
        # Same org → should return the trace (200 or with spans)
        chk("200 for same org", r.status_code == 200)
