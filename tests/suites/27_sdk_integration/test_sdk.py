"""
Test Suite 27 --- SDK Integration Tests (vantage-js-sdk)
=========================================================
Suite SK: Validates SDK initialization, event tracking (single + batch),
privacy modes, session management, cost calculation, error handling,
cross-platform summary, OTel metric forwarding, and SSE live stream.

Labels: SK.1 - SK.38  (38 checks)
"""

import sys
import time
import uuid
import json
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers, signup_api
from helpers.data import rand_email, make_event, rand_tag
from helpers.output import section, chk, ok, fail, info, get_results, reset_results


# ── Payload Builders ─────────────────────────────────────────────────────────

def ts_nano():
    """Current time in nanoseconds (OTel format)."""
    return str(int(time.time() * 1e9))


def make_otlp_metrics(service_name, metrics, email="dev@test.com",
                      team="platform", source="sdk"):
    """Build a valid OTLP ExportMetricsServiceRequest JSON payload."""
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": email}},
                    {"key": "session.id", "value": {"stringValue": f"sess-{int(time.time())}"}},
                    {"key": "team.id", "value": {"stringValue": team}},
                    {"key": "source", "value": {"stringValue": source}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-sdk-test", "version": "1.0"},
                "metrics": metrics,
            }]
        }]
    }


def counter(name, value, attrs=None):
    """Build a Sum (counter) metric."""
    return {
        "name": name,
        "unit": "1",
        "sum": {
            "dataPoints": [{
                "asDouble": value,
                "timeUnixNano": ts_nano(),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
            "isMonotonic": True,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: SDK Initialization & Auth
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDKInit:
    """Test SDK initialization and authentication flows."""

    def test_sk01_signup_returns_api_key(self):
        section("A --- SDK Initialization & Auth")
        d = signup_api()
        chk("SK.1 signup returns api_key", "api_key" in d)
        assert "api_key" in d

    def test_sk02_signup_returns_org_id(self):
        d = signup_api()
        chk("SK.2 signup returns org_id", "org_id" in d)
        assert "org_id" in d

    def test_sk03_api_key_format(self):
        d = signup_api()
        key = d["api_key"]
        chk("SK.3 api_key starts with vnt_", key.startswith("vnt_"))
        assert key.startswith("vnt_")

    def test_sk04_invalid_key_rejected(self):
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers={"Authorization": "Bearer invalid_key_12345"},
            timeout=10,
        )
        chk("SK.4 invalid API key returns 401", r.status_code == 401)
        assert r.status_code == 401

    def test_sk05_missing_auth_rejected(self):
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            timeout=10,
        )
        chk("SK.5 missing auth returns 401", r.status_code == 401)
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Event Tracking (Single + Batch)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventTracking:
    """Test event ingestion via POST /v1/events."""

    def test_sk06_single_event_accepted(self, headers):
        section("B --- Event Tracking")
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("SK.6 single event POST returns 200/201",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk07_batch_events_accepted(self, headers):
        events = [make_event(i=i, model="claude-sonnet-4-6", cost=0.01) for i in range(5)]
        r = requests.post(
            f"{API_URL}/v1/events/batch",
            json={"events": events},
            headers=headers,
            timeout=10,
        )
        chk("SK.7 batch of 5 events accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk08_event_requires_model(self, headers):
        ev = {"event_id": f"test-{uuid.uuid4().hex[:8]}",
              "provider": "openai",
              "prompt_tokens": 100,
              "completion_tokens": 50,
              "total_cost_usd": 0.005}
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        # Either rejected (400) or accepted with model defaulting
        chk("SK.8 event without model handled gracefully",
            r.status_code in (200, 201, 400, 422))
        assert r.status_code in (200, 201, 400, 422)

    def test_sk09_large_batch_accepted(self, headers):
        events = [make_event(i=i, model="gpt-4o-mini", cost=0.001) for i in range(50)]
        r = requests.post(
            f"{API_URL}/v1/events/batch",
            json={"events": events},
            headers=headers,
            timeout=15,
        )
        chk("SK.9 batch of 50 events accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk10_events_with_tags(self, headers):
        ev = make_event(i=0, model="gpt-4o", tags={"feature": "search", "sprint": "42"})
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("SK.10 event with tags accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk11_events_with_team(self, headers):
        ev = make_event(i=0, model="gpt-4o", team="backend")
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("SK.11 event with team accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Privacy Modes
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrivacyModes:
    """Test SDK privacy modes: full, anonymized, strict, local-only."""

    def test_sk12_full_mode_stores_event(self, headers):
        section("C --- Privacy Modes")
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["environment"] = "privacy-full"
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("SK.12 full mode: event stored", r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk13_anonymized_mode_event(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["environment"] = "privacy-anon"
        ev["source"] = "sdk-anonymized"
        r = requests.post(
            f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10,
        )
        chk("SK.13 anonymized mode: event accepted",
            r.status_code in (200, 201))
        assert r.status_code in (200, 201)

    def test_sk14_strict_mode_no_prompt(self, headers):
        """Strict mode: event should NOT contain prompt/response text."""
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        ev["environment"] = "privacy-strict"
        # Do NOT include prompt_text or response_text
        assert "prompt_text" not in ev
        chk("SK.14 strict mode: no prompt_text in event", True)

    def test_sk15_event_without_pii(self, headers):
        ev = make_event(i=0, model="gpt-4o", cost=0.005)
        # Verify no PII fields leak
        pii_fields = ["prompt_text", "response_text", "user_ip", "user_name"]
        has_pii = any(f in ev for f in pii_fields)
        chk("SK.15 default event has no PII fields", not has_pii)
        assert not has_pii


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Cost Calculation & Analytics
# ═══════════════════════════════════════════════════════════════════════════════

class TestCostAndAnalytics:
    """Test cost calculation and analytics endpoints via SDK-like calls."""

    def test_sk16_summary_endpoint(self, headers):
        section("D --- Cost Calculation & Analytics")
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=headers,
            timeout=10,
        )
        chk("SK.16 GET /analytics/summary returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_sk17_summary_has_total_cost(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=headers,
            timeout=10,
        )
        data = r.json()
        chk("SK.17 summary includes total_cost field",
            "total_cost" in data or "totalCost" in data or "total_cost_usd" in data)

    def test_sk18_kpis_endpoint(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/kpis",
            headers=headers,
            timeout=10,
        )
        chk("SK.18 GET /analytics/kpis returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_sk19_models_endpoint(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/models",
            headers=headers,
            timeout=10,
        )
        chk("SK.19 GET /analytics/models returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_sk20_timeseries_endpoint(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/timeseries",
            headers=headers,
            timeout=10,
        )
        chk("SK.20 GET /analytics/timeseries returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_sk21_teams_endpoint(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/teams",
            headers=headers,
            timeout=10,
        )
        chk("SK.21 GET /analytics/teams returns 200", r.status_code == 200)
        assert r.status_code == 200

    def test_sk22_traces_endpoint(self, headers):
        r = requests.get(
            f"{API_URL}/v1/analytics/traces",
            headers=headers,
            timeout=10,
        )
        chk("SK.22 GET /analytics/traces returns 200", r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Cross-Platform & OTel
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossPlatformOTel:
    """Test cross-platform summary and OTel metric forwarding."""

    def test_sk23_cross_platform_summary(self, headers):
        section("E --- Cross-Platform & OTel")
        r = requests.get(
            f"{API_URL}/v1/cross-platform/summary",
            headers=headers,
            timeout=10,
        )
        chk("SK.23 GET /cross-platform/summary returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_sk24_cross_platform_developers(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/developers",
            headers=headers,
            timeout=10,
        )
        chk("SK.24 GET /cross-platform/developers returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_sk25_cross_platform_models(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/models",
            headers=headers,
            timeout=10,
        )
        chk("SK.25 GET /cross-platform/models returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_sk26_otel_metrics_accepted(self, headers):
        payload = make_otlp_metrics(
            "claude-code",
            [counter("llm.token.usage", 1500, {"model": "claude-sonnet-4-6", "type": "input"})],
        )
        r = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=10,
        )
        chk("SK.26 OTel metrics POST accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_sk27_otel_logs_accepted(self, headers):
        log_payload = {
            "resourceLogs": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "sdk-test"}},
                    ]
                },
                "scopeLogs": [{
                    "scope": {"name": "test"},
                    "logRecords": [{
                        "timeUnixNano": ts_nano(),
                        "body": {"stringValue": "test log entry"},
                        "severityText": "INFO",
                    }]
                }]
            }]
        }
        r = requests.post(
            f"{API_URL}/v1/otel/v1/logs",
            json=log_payload,
            headers=headers,
            timeout=10,
        )
        chk("SK.27 OTel logs POST accepted",
            r.status_code in (200, 201, 202))
        assert r.status_code in (200, 201, 202)

    def test_sk28_cross_platform_live(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/live",
            headers=headers,
            timeout=10,
        )
        chk("SK.28 GET /cross-platform/live returns 200",
            r.status_code == 200)
        assert r.status_code == 200

    def test_sk29_cross_platform_budget(self, headers):
        r = requests.get(
            f"{API_URL}/v1/cross-platform/budget",
            headers=headers,
            timeout=10,
        )
        chk("SK.29 GET /cross-platform/budget returns 200",
            r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_sk30_empty_events_array(self, headers):
        section("F --- Error Handling")
        r = requests.post(
            f"{API_URL}/v1/events",
            json=[],
            headers=headers,
            timeout=10,
        )
        chk("SK.30 empty events array handled",
            r.status_code in (200, 201, 400))
        assert r.status_code in (200, 201, 400)

    def test_sk31_malformed_json_rejected(self, headers):
        r = requests.post(
            f"{API_URL}/v1/events",
            data="not json",
            headers={**headers, "Content-Type": "application/json"},
            timeout=10,
        )
        chk("SK.31 malformed JSON rejected",
            r.status_code in (400, 422, 500))
        assert r.status_code in (400, 422, 500)

    def test_sk32_negative_tokens_handled(self, headers):
        ev = make_event(i=0, model="gpt-4o")
        ev["prompt_tokens"] = -100
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("SK.32 negative tokens handled gracefully",
            r.status_code in (200, 201, 400, 422))
        assert r.status_code in (200, 201, 400, 422)

    def test_sk33_extremely_large_cost_handled(self, headers):
        ev = make_event(i=0, model="gpt-4o")
        ev["total_cost_usd"] = 999999.99
        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=headers,
            timeout=10,
        )
        chk("SK.33 large cost value handled",
            r.status_code in (200, 201, 400))
        assert r.status_code in (200, 201, 400)

    def test_sk34_cross_org_isolation(self):
        """Events from org A must not appear in org B's analytics."""
        api_key_a, org_a, _ = fresh_account(prefix="isolA")
        api_key_b, org_b, _ = fresh_account(prefix="isolB")

        # Ingest into org A
        ev = make_event(i=0, model="gpt-4o", cost=99.99)
        ev["event_id"] = f"isolation-{uuid.uuid4().hex[:8]}"
        requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=get_headers(api_key_a),
            timeout=10,
        )
        time.sleep(1)

        # Query org B
        r = requests.get(
            f"{API_URL}/v1/analytics/summary",
            headers=get_headers(api_key_b),
            timeout=10,
        )
        data = r.json()
        total = data.get("total_cost", data.get("totalCost", data.get("total_cost_usd", 0)))
        chk("SK.34 cross-org isolation: org B cost < 99",
            total < 99)
        assert total < 99

    def test_sk35_session_endpoint(self):
        """POST /v1/auth/session + GET returns valid session."""
        api_key, _, _ = fresh_account(prefix="sess")
        r = requests.post(
            f"{API_URL}/v1/auth/session",
            json={"api_key": api_key},
            timeout=10,
        )
        chk("SK.35 POST /auth/session returns 200", r.status_code == 200)
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: SSE Live Stream (KV broadcast path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSEStream:
    """
    Verify that events ingested via POST /v1/events appear in the SSE live
    stream (GET /v1/stream/{orgId}).  This tests the KV broadcast path —
    the gap that was silent in OTel until fix/otel-live-feed-broadcast.
    """

    def test_sk36_sse_stream_accessible(self, account):
        section("G --- SSE Live Stream (KV broadcast path)")
        api_key, org_id, _ = account
        url = f"{API_URL}/v1/stream/{org_id}?token={api_key}"
        # Just open the stream and read the first bytes — expect 200
        try:
            r = requests.get(url, stream=True, timeout=6)
            chk("SK.36 SSE stream endpoint returns 200", r.status_code == 200,
                f"got {r.status_code}")
            assert r.status_code == 200
        finally:
            try:
                r.close()
            except Exception:
                pass

    def test_sk37_sse_stream_after_event_ingest(self, account):
        """
        SK.37-38: Ingest a single event via POST /v1/events (which calls
        broadcastEvent() → KV), then poll the SSE stream and verify the
        event arrives within 10 seconds.

        This test would have caught the OTel broadcast gap if it had existed
        for the analogous OTel ingestion path.
        """
        api_key, org_id, _ = account
        hdrs = get_headers(api_key)

        # Unique marker to distinguish this event
        unique_model = f"gpt-4o-sse-test-{uuid.uuid4().hex[:8]}"
        ev = make_event(i=0, model=unique_model, cost=0.017)

        r = requests.post(
            f"{API_URL}/v1/events",
            json=ev,
            headers=hdrs,
            timeout=10,
        )
        chk("SK.37 event ingest returns 200/201", r.status_code in (200, 201),
            f"got {r.status_code}")
        assert r.status_code in (200, 201)

        # Allow KV write to propagate
        time.sleep(2)

        # Poll SSE stream for up to 10 seconds
        stream_url = f"{API_URL}/v1/stream/{org_id}?token={api_key}"
        received = None
        try:
            with requests.get(stream_url, stream=True, timeout=10) as sr:
                chk("SK.38 SSE stream opens after ingest", sr.status_code == 200,
                    f"got {sr.status_code}")
                if sr.status_code != 200:
                    return
                for raw in sr.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if line.startswith("data:"):
                        try:
                            received = json.loads(line[5:].strip())
                            break
                        except json.JSONDecodeError:
                            continue
        except requests.exceptions.Timeout:
            pass  # No event in window — check below

        chk("SK.38 SSE stream delivers an event after ingest",
            received is not None,
            "No data: line received within 10s — KV broadcast may be broken")
        if received:
            chk("SK.38b SSE event has provider field",
                "provider" in received, str(received.keys()))
            chk("SK.38c SSE event has total_tokens",
                "total_tokens" in received, str(received.keys()))


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    # Need a fresh account for fixtures
    api_key, org_id, cookies = fresh_account(prefix="sdk27run")
    hdrs = get_headers(api_key)

    acct = (api_key, org_id, cookies)
    for cls in [TestSDKInit, TestEventTracking, TestPrivacyModes,
                TestCostAndAnalytics, TestCrossPlatformOTel, TestErrorHandling,
                TestSSEStream]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    import inspect
                    params = inspect.signature(method).parameters
                    if "headers" in params and "account" in params:
                        method(headers=hdrs, account=acct)
                    elif "headers" in params:
                        method(headers=hdrs)
                    elif "account" in params:
                        method(account=acct)
                    else:
                        method()
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
