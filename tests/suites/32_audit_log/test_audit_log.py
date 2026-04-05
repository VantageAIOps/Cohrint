"""
Test Suite 32 — Audit Log Tests
================================
Suite AL: Validates the SOC2 audit trail — auth events, data access events,
admin action events, org isolation, pagination, filtering, CSV export, and
the public roadmap page.

Labels: AL.1 - AL.24  (24 checks)
"""
import sys
import time
import json
import requests
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import section, chk, get_results, reset_results, fail

FRONTEND_URL = "https://vantageaiops.com"


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Endpoint Access Control
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccessControl:

    def test_al01_owner_can_access_audit_log(self, headers):
        section("A --- Endpoint Access Control")
        r = requests.get(f"{API_URL}/v1/audit-log", headers=headers, timeout=10)
        chk("AL.1 owner key returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al02_response_shape(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log", headers=headers, timeout=10)
        data = r.json()
        chk("AL.2 response has events list", "events" in data, str(data.keys()))
        chk("AL.2b response has total field", "total" in data, str(data.keys()))
        assert "events" in data and "total" in data

    def test_al03_no_auth_returns_401(self):
        r = requests.get(f"{API_URL}/v1/audit-log", timeout=10)
        chk("AL.3 no auth returns 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al04_admin_endpoint_blocked_for_org_key(self, headers):
        r = requests.get(f"{API_URL}/v1/admin/audit-log", headers=headers, timeout=10)
        chk("AL.4 org owner key cannot access admin audit-log", r.status_code in (401, 403),
            f"got {r.status_code}")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Auth Events
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthEvents:

    def test_al05_login_creates_auth_event(self, headers):
        section("B --- Auth Events")
        requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=10)
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        login_events = [e for e in events if e.get("action") == "auth.login"]
        chk("AL.5 auth.login event exists", len(login_events) > 0,
            f"found {len(login_events)} login events in {len(events)} total")
        assert len(login_events) > 0

    def test_al06_auth_event_fields(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=5",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No auth events yet")
        e = events[0]
        chk("AL.6 event_type=auth", e.get("event_type") == "auth", str(e.get("event_type")))
        chk("AL.6b has actor_role", bool(e.get("actor_role")), str(e.get("actor_role")))
        chk("AL.6c has created_at", bool(e.get("created_at")), str(e.get("created_at")))

    def test_al07_event_type_filter_returns_only_auth(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=auth&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No auth events to filter")
        non_auth = [e for e in events if e.get("event_type") != "auth"]
        chk("AL.7 event_type=auth returns only auth events",
            len(non_auth) == 0, f"{len(non_auth)} non-auth events leaked")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Data Access Events
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataAccessEvents:

    def test_al08_analytics_creates_data_access_event(self, headers):
        section("C --- Data Access Events")
        for path in ["/v1/analytics/summary", "/v1/analytics/kpis", "/v1/analytics/models"]:
            requests.get(f"{API_URL}{path}", headers=headers, timeout=10)
        time.sleep(1)
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        da_events = [e for e in events if e.get("action") == "data_access.analytics"]
        chk("AL.8 data_access.analytics events exist", len(da_events) > 0,
            f"found {len(da_events)} data_access events in {len(events)} total")
        assert len(da_events) > 0

    def test_al09_data_access_event_has_endpoint_metadata(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=5",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No data_access events yet")
        e = events[0]
        chk("AL.9 event_type=data_access", e.get("event_type") == "data_access",
            str(e.get("event_type")))
        detail_raw = e.get("detail", "{}")
        try:
            meta = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
            chk("AL.9b detail.endpoint present", "endpoint" in meta, str(meta))
        except Exception:
            chk("AL.9b detail.endpoint present", False, f"parse failed: {detail_raw}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Pagination and Filtering
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaginationFiltering:

    def test_al10_limit_respected(self, headers):
        section("D --- Pagination & Filtering")
        r = requests.get(f"{API_URL}/v1/audit-log?limit=2", headers=headers, timeout=10)
        events = r.json().get("events", [])
        chk("AL.10 limit=2 returns at most 2", len(events) <= 2, f"got {len(events)}")

    def test_al11_offset_advances_page(self, headers):
        r1 = requests.get(f"{API_URL}/v1/audit-log?limit=1&offset=0", headers=headers, timeout=10)
        r2 = requests.get(f"{API_URL}/v1/audit-log?limit=1&offset=1", headers=headers, timeout=10)
        e1 = r1.json().get("events", [{}])
        e2 = r2.json().get("events", [{}])
        if not e1 or not e2:
            pytest.skip("Not enough events to test offset")
        chk("AL.11 offset=1 returns different event",
            e1[0].get("id") != e2[0].get("id"),
            f"id0={e1[0].get('id')} id1={e2[0].get('id')}")

    def test_al12_has_more_flag(self, headers):
        r_all   = requests.get(f"{API_URL}/v1/audit-log?limit=500", headers=headers, timeout=10)
        total   = r_all.json().get("total", 0)
        r_small = requests.get(f"{API_URL}/v1/audit-log?limit=1",   headers=headers, timeout=10)
        has_more = r_small.json().get("has_more", False)
        chk("AL.12 has_more accurate", has_more == (total > 1),
            f"total={total} has_more={has_more}")

    def test_al13_data_access_filter_correct(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?event_type=data_access&limit=20",
                         headers=headers, timeout=10)
        events = r.json().get("events", [])
        if not events:
            pytest.skip("No data_access events to filter")
        wrong = [e for e in events if e.get("event_type") != "data_access"]
        chk("AL.13 data_access filter returns only data_access",
            len(wrong) == 0, f"{len(wrong)} wrong-type events")

    def test_al14_events_newest_first(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?limit=10", headers=headers, timeout=10)
        events = r.json().get("events", [])
        if len(events) < 2:
            pytest.skip("Need 2+ events to test ordering")
        ts = [e.get("created_at", "") for e in events]
        chk("AL.14 events newest-first", ts == sorted(ts, reverse=True),
            f"first={ts[0]} last={ts[-1]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Org Isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgIsolation:

    def test_al15_org_isolation(self, account, member_account):
        section("E --- Org Isolation")
        api_key_a, org_id_a, _ = account
        api_key_b, _, _        = member_account

        # Trigger event in org A
        requests.get(f"{API_URL}/v1/analytics/summary",
                     headers=get_headers(api_key_a), timeout=10)
        time.sleep(1)

        # Org B should not see org A events
        r = requests.get(f"{API_URL}/v1/audit-log?limit=100",
                         headers=get_headers(api_key_b), timeout=10)
        events = r.json().get("events", [])
        leaked = [e for e in events if e.get("org_id") == org_id_a]
        chk("AL.15 org B cannot see org A events",
            len(leaked) == 0, f"{len(leaked)} org A events leaked")
        assert len(leaked) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: CSV Export
# ═══════════════════════════════════════════════════════════════════════════════

class TestCsvExport:

    def test_al16_csv_returns_200(self, headers):
        section("F --- CSV Export")
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv", headers=headers, timeout=10)
        chk("AL.16 CSV returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al17_csv_content_type(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv", headers=headers, timeout=10)
        ct = r.headers.get("content-type", "")
        chk("AL.17 Content-Type is text/csv", "text/csv" in ct, f"got {ct}")

    def test_al18_csv_header_row(self, headers):
        r = requests.get(f"{API_URL}/v1/audit-log?format=csv&limit=5", headers=headers, timeout=10)
        lines = r.text.strip().split("\n")
        chk("AL.18 CSV has header row", len(lines) >= 1, f"got {len(lines)} lines")
        chk("AL.18b header contains event_type",
            "event_type" in lines[0], f"header: {lines[0][:100]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: Roadmap Page
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoadmapPage:

    def test_al19_roadmap_accessible(self):
        section("G --- Roadmap Page")
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.19 roadmap.html returns 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al20_roadmap_contains_live(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.20 roadmap contains 'Live'", "Live" in r.text)

    def test_al21_roadmap_contains_q2_2026(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.21 roadmap contains 'Q2 2026'", "Q2 2026" in r.text)

    def test_al22_roadmap_no_100_percent_claim(self):
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.22 roadmap has no '100% coverage' claim",
            "100% coverage" not in r.text and "Zero gaps" not in r.text,
            "Found inaccurate claim on roadmap page")

    def test_al23_app_loads(self):
        r = requests.get(f"{FRONTEND_URL}/app.html", timeout=15)
        chk("AL.23 app.html loads", r.status_code == 200, f"got {r.status_code}")

    def test_al24_app_contains_security_nav(self):
        r = requests.get(f"{FRONTEND_URL}/app.html", timeout=15)
        chk("AL.24 app.html has Security nav item",
            "security" in r.text.lower(),
            "Security nav item not found in dashboard source")


# ── Runner ────────────────────────────────────────────────────────────────────

def run():
    reset_results()
    api_key, org_id, cookies     = fresh_account(prefix="al32run")
    api_key_b, org_id_b, cook_b  = fresh_account(prefix="al32runb")
    hdrs  = get_headers(api_key)
    acct  = (api_key, org_id, cookies)
    acct_b = (api_key_b, org_id_b, cook_b)

    import inspect
    for cls in [TestAccessControl, TestAuthEvents, TestDataAccessEvents,
                TestPaginationFiltering, TestOrgIsolation, TestCsvExport,
                TestRoadmapPage]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    method = getattr(obj, name)
                    params = inspect.signature(method).parameters
                    kwargs: dict = {}
                    if "account"        in params: kwargs["account"]        = acct
                    if "member_account" in params: kwargs["member_account"] = acct_b
                    if "headers"        in params: kwargs["headers"]        = hdrs
                    method(**kwargs)
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed")
    return res["failed"]


if __name__ == "__main__":
    import sys
    sys.exit(run())
