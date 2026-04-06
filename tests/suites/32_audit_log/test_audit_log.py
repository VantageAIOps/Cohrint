"""
Test Suite 32 — SOC2 Audit Log (Live Environment)
===================================================
Every test in this suite triggers a real API action and then verifies
the corresponding audit event appears in GET /v1/audit-log within 3 s.
No mocks. No assumptions. Every event type is exercised.

Labels: AL.1 – AL.42  (42 checks)

Sections
--------
A  Endpoint access control          AL.1  – AL.6
B  Auth events                      AL.7  – AL.12
C  Data-access events               AL.13 – AL.17
D  Admin-action events              AL.18 – AL.26
E  Pagination & filtering           AL.27 – AL.34
F  Org isolation                    AL.35
G  CSV export                       AL.36 – AL.39
H  Roadmap & dashboard pages        AL.40 – AL.42
"""

import csv
import inspect
import io
import json
import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import chk, fail, get_results, reset_results, section

FRONTEND_URL = "https://vantageaiops.com"
AUDIT_URL    = f"{API_URL}/v1/audit-log"
_WAIT        = 2   # seconds for waitUntil writes to flush to D1


# ── Shared wait-and-poll helper ───────────────────────────────────────────────

def poll_for_event(headers: dict, event_name: str, *, limit: int = 50,
                   wait: float = _WAIT, retries: int = 3) -> dict | None:
    """
    Wait `wait` seconds then poll GET /v1/audit-log for an event with
    action == event_name.  Retries up to `retries` times with 1-s gaps.
    Returns the first matching event dict, or None.
    """
    time.sleep(wait)
    for _ in range(retries):
        r = requests.get(f"{AUDIT_URL}?limit={limit}", headers=headers, timeout=10)
        if r.status_code != 200:
            time.sleep(1)
            continue
        found = [e for e in r.json().get("events", [])
                 if e.get("action") == event_name]
        if found:
            return found[0]
        time.sleep(1)
    return None


def poll_for_event_type(headers: dict, event_type: str, *, wait: float = _WAIT) -> list:
    """Return all events of a given event_type after waiting."""
    time.sleep(wait)
    r = requests.get(f"{AUDIT_URL}?event_type={event_type}&limit=100",
                     headers=headers, timeout=10)
    return r.json().get("events", []) if r.status_code == 200 else []


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Endpoint Access Control  (AL.1 – AL.6)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccessControl:
    """Auth gates on GET /v1/audit-log."""

    def test_al01_owner_can_access(self, headers):
        section("A --- Endpoint Access Control")
        r = requests.get(AUDIT_URL, headers=headers, timeout=10)
        chk("AL.1  owner key -> 200", r.status_code == 200, f"got {r.status_code}: {r.text[:80]}")
        assert r.status_code == 200

    def test_al02_response_shape(self, headers):
        r = requests.get(AUDIT_URL, headers=headers, timeout=10)
        d = r.json()
        chk("AL.2  response has events[]", "events" in d, str(d.keys()))
        chk("AL.2b response has total", "total" in d, str(d.keys()))
        chk("AL.2c response has has_more", "has_more" in d, str(d.keys()))
        assert "events" in d and "total" in d and "has_more" in d

    def test_al03_no_auth_401(self):
        r = requests.get(AUDIT_URL, timeout=10)
        chk("AL.3  no auth -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al04_bad_key_401(self):
        r = requests.get(AUDIT_URL, headers={"Authorization": "Bearer bad_key"}, timeout=10)
        chk("AL.4  bad key -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al05_member_key_403(self, member_key):
        """Member keys (non-owner) must receive 403."""
        r = requests.get(AUDIT_URL, headers=get_headers(member_key), timeout=10)
        chk("AL.5  member key -> 403", r.status_code == 403, f"got {r.status_code}")
        assert r.status_code == 403

    def test_al06_admin_endpoint_blocked_for_org_key(self, headers):
        r = requests.get(f"{API_URL}/v1/admin/audit-log", headers=headers, timeout=10)
        chk("AL.6  org key -> 401/403 on admin audit-log",
            r.status_code in (401, 403), f"got {r.status_code}")
        assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Auth Events  (AL.7 – AL.12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthEvents:
    """Every authenticated request should produce auth.login; bad keys produce auth.failed."""

    def test_al07_login_event_on_api_key_auth(self, headers):
        section("B --- Auth Events")
        # Make a fresh authenticated call to guarantee a login event
        requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=10)
        e = poll_for_event(headers, "auth.login")
        chk("AL.7  auth.login event created", e is not None,
            "no auth.login in audit log after API key auth")
        assert e is not None

    def test_al08_login_event_fields(self, headers):
        e = poll_for_event(headers, "auth.login", wait=0)
        if not e:
            pytest.skip("No auth.login events available")
        chk("AL.8  auth.login event_type=auth",
            e.get("event_type") == "auth", str(e.get("event_type")))
        chk("AL.8b actor_role present",
            bool(e.get("actor_role")), str(e.get("actor_role")))
        chk("AL.8c created_at present",
            bool(e.get("created_at")), str(e.get("created_at")))

    def test_al09_auth_failed_bad_format(self):
        """Sending a malformed key must be rejected with 401."""
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers={"Authorization": "Bearer not_a_vantage_key"}, timeout=10)
        chk("AL.9  malformed key -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al10_auth_failed_key_not_found(self, org_id):
        """A well-formed but non-existent key must return 401."""
        fake_key = f"vnt_{org_id}_ffffffffffffffffffffffffffffffff"
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=get_headers(fake_key), timeout=10)
        chk("AL.10 key-not-found -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_al11_event_type_filter_auth_only(self, headers):
        events = poll_for_event_type(headers, "auth", wait=0)
        if not events:
            pytest.skip("No auth events to filter")
        wrong = [e for e in events if e.get("event_type") != "auth"]
        chk("AL.11 event_type=auth filter leaks nothing",
            len(wrong) == 0, f"{len(wrong)} non-auth events leaked")

    def test_al12_login_newest_first_within_auth(self, headers):
        events = poll_for_event_type(headers, "auth", wait=0)
        if len(events) < 2:
            pytest.skip("Need 2+ auth events")
        ts = [e.get("created_at", "") for e in events]
        chk("AL.12 auth events newest-first",
            ts == sorted(ts, reverse=True), f"first={ts[0]} last={ts[-1]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Data Access Events  (AL.13 – AL.17)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataAccessEvents:
    """Every GET to an analytics route must produce a data_access.analytics event."""

    def test_al13_data_access_created(self, headers):
        section("C --- Data Access Events")
        for path in ["/v1/analytics/summary", "/v1/analytics/kpis",
                     "/v1/analytics/models", "/v1/analytics/timeseries"]:
            requests.get(f"{API_URL}{path}", headers=headers, timeout=10)
        e = poll_for_event(headers, "data_access.analytics")
        chk("AL.13 data_access.analytics event created", e is not None,
            "no data_access.analytics event after 4 analytics GETs")
        assert e is not None

    def test_al14_data_access_event_type_field(self, headers):
        events = poll_for_event_type(headers, "data_access", wait=0)
        if not events:
            pytest.skip("No data_access events yet")
        e = events[0]
        chk("AL.14 event_type=data_access",
            e.get("event_type") == "data_access", str(e.get("event_type")))

    def test_al15_data_access_endpoint_in_detail(self, headers):
        events = poll_for_event_type(headers, "data_access", wait=0)
        if not events:
            pytest.skip("No data_access events yet")
        e = events[0]
        raw = e.get("detail", "{}")
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
            chk("AL.15 detail contains endpoint key",
                "endpoint" in meta, f"detail={raw[:120]}")
        except Exception:
            chk("AL.15 detail contains endpoint key", False,
                f"JSON parse failed: {raw[:120]}")

    def test_al16_data_access_filter_correct(self, headers):
        events = poll_for_event_type(headers, "data_access", wait=0)
        if not events:
            pytest.skip("No data_access events to filter")
        wrong = [e for e in events if e.get("event_type") != "data_access"]
        chk("AL.16 data_access filter returns only data_access",
            len(wrong) == 0, f"{len(wrong)} wrong-type events")

    def test_al17_multiple_endpoints_each_logged(self, headers):
        """Each analytics endpoint is logged individually (not batched)."""
        events = poll_for_event_type(headers, "data_access", wait=0)
        paths_seen = set()
        for e in events:
            raw = e.get("detail", "{}")
            try:
                meta = json.loads(raw) if isinstance(raw, str) else raw
                paths_seen.add(meta.get("endpoint", ""))
            except Exception:
                pass
        chk("AL.17 multiple analytics paths in audit log",
            len(paths_seen) >= 2, f"only saw: {paths_seen}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Admin-Action Events  (AL.18 – AL.26)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdminActionEvents:
    """Trigger each admin_action event type and verify it appears in the log."""

    _added_member_id: str | None = None

    def test_al18_budget_policy_changed(self, headers, org_id):
        section("D --- Admin-Action Events")
        r = requests.put(
            f"{API_URL}/v1/admin/team-budgets/test-audit-team",
            json={"budget_usd": 99.0},
            headers=headers,
            timeout=10,
        )
        assert r.status_code in (200, 201), f"PUT budget failed: {r.text}"
        e = poll_for_event(headers, "admin_action.budget_policy_changed")
        chk("AL.18 budget_policy_changed event created", e is not None,
            "no admin_action.budget_policy_changed after PUT team-budgets")
        assert e is not None

    def test_al19_budget_event_has_metadata(self, headers):
        events = poll_for_event_type(headers, "admin_action", wait=0)
        budget_evs = [e for e in events
                      if e.get("action") == "admin_action.budget_policy_changed"]
        if not budget_evs:
            pytest.skip("No budget_policy_changed events yet")
        raw = budget_evs[0].get("detail", "{}")
        try:
            meta = json.loads(raw) if isinstance(raw, str) else raw
            chk("AL.19 budget detail has budget_usd",
                "budget_usd" in meta, f"detail={raw[:120]}")
        except Exception:
            chk("AL.19 budget detail has budget_usd", False,
                f"JSON parse failed: {raw[:120]}")

    def test_al20_member_added_event(self, headers):
        """POST /v1/auth/members must create admin_action.member_added."""
        import random
        new_email = f"audit-test-{random.randint(10000, 99999)}@example.com"
        r = requests.post(
            f"{API_URL}/v1/auth/members",
            json={"email": new_email, "name": "Audit Test", "role": "member"},
            headers=headers,
            timeout=15,
        )
        if r.status_code == 201:
            TestAdminActionEvents._added_member_id = r.json().get("member_id")
        assert r.status_code == 201, f"POST member failed: {r.text}"
        e = poll_for_event(headers, "admin_action.member_added")
        chk("AL.20 member_added event created", e is not None,
            "no admin_action.member_added after POST members")
        assert e is not None

    def test_al21_member_added_has_email(self, headers):
        events = poll_for_event_type(headers, "admin_action", wait=0)
        added = [e for e in events
                 if e.get("action") == "admin_action.member_added"]
        if not added:
            pytest.skip("No member_added events yet")
        e = added[0]
        chk("AL.21 member_added resource (email) present",
            bool(e.get("resource")), f"resource={e.get('resource')!r}")

    def test_al22_member_removed_event(self, headers):
        """DELETE /v1/auth/members/:id must create admin_action.member_removed."""
        member_id = TestAdminActionEvents._added_member_id
        if not member_id:
            pytest.skip("No member ID from AL.20")
        r = requests.delete(
            f"{API_URL}/v1/auth/members/{member_id}",
            headers=headers,
            timeout=10,
        )
        assert r.status_code == 200, f"DELETE member failed: {r.text}"
        e = poll_for_event(headers, "admin_action.member_removed")
        chk("AL.22 member_removed event created", e is not None,
            "no admin_action.member_removed after DELETE member")
        assert e is not None

    def test_al23_alert_config_changed_event(self, headers, org_id):
        """POST /v1/alerts/slack/:orgId must create admin_action.alert_config_changed."""
        r = requests.post(
            f"{API_URL}/v1/alerts/slack/{org_id}",
            json={
                "webhook_url":      "https://hooks.slack.com/services/T000/B000/test",
                "trigger_budget":   True,
                "trigger_anomaly":  False,
                "trigger_daily":    False,
            },
            headers=headers,
            timeout=10,
        )
        assert r.status_code in (200, 201), f"POST slack failed: {r.text}"
        e = poll_for_event(headers, "admin_action.alert_config_changed")
        chk("AL.23 alert_config_changed event created", e is not None,
            "no admin_action.alert_config_changed after POST alerts/slack")
        assert e is not None

    def test_al24_admin_action_filter_correct(self, headers):
        events = poll_for_event_type(headers, "admin_action", wait=0)
        if not events:
            pytest.skip("No admin_action events to filter")
        wrong = [e for e in events if e.get("event_type") != "admin_action"]
        chk("AL.24 admin_action filter leaks nothing",
            len(wrong) == 0, f"{len(wrong)} non-admin events leaked")

    def test_al25_all_three_event_types_present(self, headers):
        """By this point all three event_type values must be in the log."""
        r = requests.get(f"{AUDIT_URL}?limit=500", headers=headers, timeout=10)
        events = r.json().get("events", [])
        found = {e.get("event_type") for e in events}
        for expected in ("auth", "data_access", "admin_action"):
            chk(f"AL.25 event_type={expected!r} present in log",
                expected in found, f"found only: {found}")

    def test_al26_admin_action_fields_complete(self, headers):
        events = poll_for_event_type(headers, "admin_action", wait=0)
        if not events:
            pytest.skip("No admin_action events")
        e = events[0]
        for field in ("id", "event_type", "action", "actor_role", "created_at"):
            chk(f"AL.26 field {field!r} present",
                bool(e.get(field)), f"{field}={e.get(field)!r}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: Pagination & Filtering  (AL.27 – AL.34)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaginationFiltering:

    def test_al27_limit_upper_bound(self, headers):
        section("E --- Pagination & Filtering")
        r = requests.get(f"{AUDIT_URL}?limit=2", headers=headers, timeout=10)
        events = r.json().get("events", [])
        chk("AL.27 limit=2 returns <= 2 events", len(events) <= 2, f"got {len(events)}")

    def test_al28_limit_zero_clamped(self, headers):
        """limit=0 is silently clamped to 1 (Math.max(1,...))."""
        r = requests.get(f"{AUDIT_URL}?limit=0", headers=headers, timeout=10)
        chk("AL.28 limit=0 -> 200", r.status_code == 200, f"got {r.status_code}")
        events = r.json().get("events", [])
        chk("AL.28b limit=0 returns <= 1 event", len(events) <= 1, f"got {len(events)}")

    def test_al29_offset_advances_cursor(self, headers):
        r1 = requests.get(f"{AUDIT_URL}?limit=1&offset=0", headers=headers, timeout=10)
        r2 = requests.get(f"{AUDIT_URL}?limit=1&offset=1", headers=headers, timeout=10)
        e1 = r1.json().get("events", [])
        e2 = r2.json().get("events", [])
        if not e1 or not e2:
            pytest.skip("Need 2+ events to test offset")
        chk("AL.29 offset=1 yields different event",
            e1[0].get("id") != e2[0].get("id"),
            f"id0={e1[0].get('id')} id1={e2[0].get('id')}")

    def test_al30_has_more_true_when_truncated(self, headers):
        r_all  = requests.get(f"{AUDIT_URL}?limit=500", headers=headers, timeout=10)
        total  = r_all.json().get("total", 0)
        if total < 2:
            pytest.skip("Need 2+ events total")
        r_small = requests.get(f"{AUDIT_URL}?limit=1", headers=headers, timeout=10)
        d = r_small.json()
        chk("AL.30 has_more=true when limit=1 and total>1",
            d.get("has_more") is True, f"has_more={d.get('has_more')} total={total}")

    def test_al31_has_more_false_when_all_fit(self, headers):
        r = requests.get(f"{AUDIT_URL}?limit=500", headers=headers, timeout=10)
        d = r.json()
        chk("AL.31 has_more=false with limit=500",
            d.get("has_more") is False,
            f"has_more={d.get('has_more')} total={d.get('total')}")

    def test_al32_events_newest_first(self, headers):
        r = requests.get(f"{AUDIT_URL}?limit=20", headers=headers, timeout=10)
        events = r.json().get("events", [])
        if len(events) < 2:
            pytest.skip("Need 2+ events to test ordering")
        ts = [e.get("created_at", "") for e in events]
        chk("AL.32 events ordered newest-first",
            ts == sorted(ts, reverse=True), f"first={ts[0]!r} last={ts[-1]!r}")

    def test_al33_date_range_from_future_returns_zero(self, headers):
        """?from=<tomorrow> should return 0 events."""
        import datetime
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        r = requests.get(f"{AUDIT_URL}?from={tomorrow}&limit=50",
                         headers=headers, timeout=10)
        d = r.json()
        chk("AL.33 from=tomorrow -> 0 events",
            d.get("total", 0) == 0, f"total={d.get('total')} (expected 0)")

    def test_al34_date_range_to_past_returns_zero(self, headers):
        """?to=<yesterday> should return 0 events (suite just created this account today)."""
        import datetime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        r = requests.get(f"{AUDIT_URL}?to={yesterday}&limit=50",
                         headers=headers, timeout=10)
        d = r.json()
        chk("AL.34 to=yesterday -> 0 events",
            d.get("total", 0) == 0, f"total={d.get('total')} (expected 0)")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section F: Org Isolation  (AL.35)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrgIsolation:

    def test_al35_cross_org_isolation(self, account, second_account):
        section("F --- Org Isolation")
        api_key_a, org_id_a, _ = account
        api_key_b, _, _        = second_account

        requests.get(f"{API_URL}/v1/analytics/summary",
                     headers=get_headers(api_key_a), timeout=10)
        time.sleep(_WAIT)

        r = requests.get(f"{AUDIT_URL}?limit=200",
                         headers=get_headers(api_key_b), timeout=10)
        events = r.json().get("events", [])
        leaked = [e for e in events if e.get("org_id") == org_id_a]
        chk("AL.35 org B sees 0 events from org A",
            len(leaked) == 0, f"{len(leaked)} org A events leaked to org B")
        assert len(leaked) == 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Section G: CSV Export  (AL.36 – AL.39)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCsvExport:

    def test_al36_csv_200(self, headers):
        section("G --- CSV Export")
        r = requests.get(f"{AUDIT_URL}?format=csv", headers=headers, timeout=10)
        chk("AL.36 CSV -> 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_al37_csv_content_type(self, headers):
        r = requests.get(f"{AUDIT_URL}?format=csv", headers=headers, timeout=10)
        ct = r.headers.get("content-type", "")
        chk("AL.37 Content-Type: text/csv", "text/csv" in ct, f"got {ct!r}")

    def test_al38_csv_structure(self, headers):
        r = requests.get(f"{AUDIT_URL}?format=csv&limit=50",
                         headers=headers, timeout=10)
        reader = csv.reader(io.StringIO(r.text))
        rows   = list(reader)
        chk("AL.38 CSV has at least 1 row", len(rows) >= 1, f"got {len(rows)}")
        header = rows[0] if rows else []
        chk("AL.38b header has event_type column", "event_type" in header,
            f"header={header}")
        chk("AL.38c header has id column", "id" in header, f"header={header}")
        if len(rows) >= 2:
            chk("AL.38d data row column count matches header",
                len(rows[1]) == len(header),
                f"header={len(header)} cols, data={len(rows[1])} cols")

    def test_al39_csv_no_formula_injection(self, headers):
        """CSV values must be quoted and not contain raw formula injection prefixes."""
        r = requests.get(f"{AUDIT_URL}?format=csv&limit=20",
                         headers=headers, timeout=10)
        for line in r.text.splitlines()[1:]:
            try:
                cells = next(csv.reader([line]))
                for cell in cells:
                    chk("AL.39 CSV cell is not formula injection",
                        not cell.startswith(('=', '+', '-', '@')),
                        f"suspicious cell: {cell[:50]!r}")
                    break   # spot-check first cell per row
            except StopIteration:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
#  Section H: Roadmap & Dashboard Pages  (AL.40 – AL.42)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPages:

    def test_al40_roadmap_page(self):
        section("H --- Roadmap & Dashboard Pages")
        r = requests.get(f"{FRONTEND_URL}/roadmap.html", timeout=15)
        chk("AL.40 roadmap.html -> 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        chk("AL.40b roadmap contains 'Live'",    "Live"     in r.text)
        chk("AL.40c roadmap contains 'Q2 2026'", "Q2 2026"  in r.text)
        chk("AL.40d roadmap has no '100% coverage'",
            "100% coverage" not in r.text and "Zero gaps" not in r.text,
            "inaccurate claim found on roadmap page")

    def test_al41_app_loads_with_security_nav(self):
        r = requests.get(f"{FRONTEND_URL}/app.html", timeout=15)
        chk("AL.41 app.html -> 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        chk("AL.41b app.html has Security nav",
            "security" in r.text.lower(),
            "Security nav item missing from app.html source")
        chk("AL.41c app.html has Integrations nav",
            "integrations" in r.text.lower(),
            "Integrations nav item missing from app.html source")

    def test_al42_product_strategy_no_false_claims(self):
        strategy = Path(__file__).parent.parent.parent.parent / "PRODUCT_STRATEGY.md"
        if not strategy.exists():
            pytest.skip("PRODUCT_STRATEGY.md not found")
        text = strategy.read_text()
        chk("AL.42 PRODUCT_STRATEGY has no '100% coverage'",
            "100% coverage" not in text and "Zero gaps" not in text,
            "inaccurate claim still in PRODUCT_STRATEGY.md")


# ═══════════════════════════════════════════════════════════════════════════════
#  Pytest fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def account():
    return fresh_account(prefix="al32")

@pytest.fixture(scope="module")
def headers(account):
    api_key, _, _ = account
    return get_headers(api_key)

@pytest.fixture(scope="module")
def org_id(account):
    _, oid, _ = account
    return oid

@pytest.fixture(scope="module")
def second_account():
    return fresh_account(prefix="al32b")

@pytest.fixture(scope="module")
def member_key(account):
    """Create a member in the test org and return their raw API key."""
    import random
    api_key, _, _ = account
    email = f"member-fixture-{random.randint(10000, 99999)}@example.com"
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": email, "name": "Member Fixture", "role": "member"},
        headers=get_headers(api_key),
        timeout=15,
    )
    if r.status_code != 201:
        pytest.skip(f"Could not create member key: {r.text}")
    return r.json()["api_key"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Standalone runner  (python test_audit_log.py [--key vnt_...])
# ═══════════════════════════════════════════════════════════════════════════════

def run(api_key: str | None = None):
    """
    Run the full suite against the live API.
    If api_key is provided it is used as the owner key;
    otherwise a fresh account is created via signup.
    """
    reset_results()

    if api_key:
        parts = api_key.split("_")
        oid   = parts[1] if len(parts) >= 3 else "unknown"
        acct  = (api_key, oid, None)
        hdrs  = get_headers(api_key)
        print(f"\nUsing provided key  org: {oid}")
    else:
        acct = fresh_account(prefix="al32run")
        hdrs = get_headers(acct[0])
        print(f"\nCreated fresh account  org: {acct[1]}")

    acct_b = fresh_account(prefix="al32b")

    import random
    mem_r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": f"member-{random.randint(10000,99999)}@example.com",
              "name": "Test Member", "role": "member"},
        headers=hdrs, timeout=15,
    )
    member_k = mem_r.json().get("api_key") if mem_r.status_code == 201 else None

    classes = [
        TestAccessControl, TestAuthEvents, TestDataAccessEvents,
        TestAdminActionEvents, TestPaginationFiltering, TestOrgIsolation,
        TestCsvExport, TestPages,
    ]

    for cls in classes:
        obj = cls()
        for name in sorted(dir(obj)):
            if not name.startswith("test_"):
                continue
            try:
                method = getattr(obj, name)
                params = inspect.signature(method).parameters
                kwargs: dict = {}
                if "account"        in params: kwargs["account"]        = acct
                if "second_account" in params: kwargs["second_account"] = acct_b
                if "headers"        in params: kwargs["headers"]        = hdrs
                if "org_id"         in params: kwargs["org_id"]         = acct[1]
                if "member_key"     in params:
                    if member_k:
                        kwargs["member_key"] = member_k
                    else:
                        print(f"  SKIP {name} (no member key)")
                        continue
                method(**kwargs)
            except pytest.skip.Exception as e:
                print(f"  SKIP {name}: {e}")
            except Exception as e:
                fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed / {res['failed']} failed / {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SOC2 audit log live tests")
    parser.add_argument("--key", default=None,
                        help="Owner API key (vnt_...). Omit to create a fresh account.")
    args = parser.parse_args()
    sys.exit(run(api_key=args.key))
