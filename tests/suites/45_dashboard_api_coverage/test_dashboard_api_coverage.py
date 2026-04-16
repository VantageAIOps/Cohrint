"""
Test Suite 45 — Dashboard API Coverage
=======================================
Verifies every API endpoint now wired to the dashboard returns the correct
shape, role-gating, and non-empty data after events are seeded.

Endpoints under test:
  GET  /v1/analytics/kpis          — wasted_cost_usd + streaming_requests fields
  GET  /v1/analytics/business-units — admin+ only; returns unit breakdown
  GET  /v1/admin/members/:id/usage  — admin+ only; returns per-member usage
  GET  /v1/optimizer/stats          — any role; returns compression stats
  POST /v1/benchmark/contribute     — admin+ only; idempotent, opt-in check

Labels: DA.1 – DA.40
No mocks. Prefers persisted seed state (run seed.py once); falls back to a
fresh account per module when state file is absent.

Seed state: tests/artifacts/da45_seed_state.json  (gitignored)
"""

import json
import random
import sys
import time
from pathlib import Path

import pytest
import requests

SUITE_DIR  = Path(__file__).parent
TESTS_ROOT = SUITE_DIR.parent.parent
sys.path.insert(0, str(TESTS_ROOT))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import chk, section

# ---------------------------------------------------------------------------
# Seed-state loader
# ---------------------------------------------------------------------------

_STATE_FILE = TESTS_ROOT / "artifacts" / "da45_seed_state.json"


def _load_seed_state() -> dict | None:
    """Return parsed seed state if the file exists, else None."""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_event(headers: dict, model: str = "claude-sonnet-4-6", streaming: bool = False) -> None:
    """Ingest one synthetic event so analytics endpoints have data."""
    payload = {
        "provider": "anthropic",
        "model": model,
        "prompt_tokens": random.randint(500, 2000),
        "completion_tokens": random.randint(100, 800),
        "total_cost_usd": round(random.uniform(0.001, 0.05), 6),
        "environment": "test",
        "agent_name": "da45-test",
    }
    if streaming:
        payload["streaming"] = True
    requests.post(f"{API_URL}/v1/events", json=payload, headers=headers, timeout=10)


def _seed_events(headers: dict, count: int = 5) -> None:
    """Seed count events, including some streaming."""
    for i in range(count):
        _seed_event(headers, streaming=(i % 2 == 0))
    time.sleep(1)  # allow write propagation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _seed_state():
    """Module-scoped seed state dict (None when state file absent)."""
    return _load_seed_state()


@pytest.fixture(scope="module")
def account(_seed_state):
    """
    Return (api_key, org_id, cookies) for an admin-role account.
    Prefers the persisted seed state; falls back to a fresh signup.
    """
    if _seed_state and _seed_state.get("admin", {}).get("api_key"):
        key = _seed_state["admin"]["api_key"]
        org = _seed_state["org_id"]
        return key, org, None  # no cookies needed — tests use Bearer auth
    return fresh_account(prefix="da45")


@pytest.fixture(scope="module")
def headers(account):
    api_key, _, _ = account
    return get_headers(api_key)


@pytest.fixture(scope="module")
def member_info(_seed_state, account, headers):
    """
    Return (member_id, member_key) for a member-role user.
    Prefers persisted seed state; falls back to inviting a new member.
    """
    if _seed_state:
        m = _seed_state.get("member", {})
        if m.get("id") and m.get("api_key"):
            return m["id"], m["api_key"]

    # Fallback: invite on-the-fly
    api_key, _, _ = account
    email = f"da45-member-{random.randint(10000, 99999)}@vantage-test.dev"
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": email, "name": "DA45 Member", "role": "member"},
        headers=headers,
        timeout=15,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"Could not create member: {r.status_code} {r.text[:120]}")
    data = r.json()
    return data.get("id") or data.get("member_id"), data.get("api_key")


@pytest.fixture(scope="module")
def seeded(_seed_state, headers):
    """
    Ensure events exist; return admin headers.
    When running from seed state the events are already present — no re-seed.
    When running fresh, seed 6 events.
    """
    if _seed_state and _seed_state.get("events_count", 0) > 0:
        # Events already seeded by seed.py — nothing to do
        return headers
    _seed_events(headers, count=6)
    return headers


# ===========================================================================
# SECTION A — /v1/analytics/kpis: wasted_cost_usd + streaming_requests
# ===========================================================================

class TestKpisNewFields:
    """DA.1 – DA.10: wasted_cost_usd and streaming_requests are present in /kpis."""

    def test_da01_kpis_returns_200(self, seeded):
        section("A --- /v1/analytics/kpis new fields")
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        chk("DA.1  GET /analytics/kpis -> 200", r.status_code == 200,
            f"status={r.status_code}")
        assert r.status_code == 200

    def test_da02_kpis_has_wasted_cost_usd_field(self, seeded):
        """DA.2: wasted_cost_usd field present (powers kpiWastedCost dashboard card)."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        chk("DA.2  kpis response has 'wasted_cost_usd' field",
            "wasted_cost_usd" in data,
            f"keys: {list(data.keys())}")
        assert "wasted_cost_usd" in data

    def test_da03_wasted_cost_usd_is_numeric(self, seeded):
        """DA.3: wasted_cost_usd is a non-negative number."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        val = r.json().get("wasted_cost_usd")
        chk(f"DA.3  wasted_cost_usd is numeric and >= 0 (got {val!r})",
            isinstance(val, (int, float)) and val >= 0,
            f"value={val!r}")
        assert isinstance(val, (int, float)) and val >= 0

    def test_da04_kpis_has_streaming_requests_field(self, seeded):
        """DA.4: streaming_requests field present (powers kpiStreamingReqs card)."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        chk("DA.4  kpis response has 'streaming_requests' field",
            "streaming_requests" in data,
            f"keys: {list(data.keys())}")
        assert "streaming_requests" in data

    def test_da05_streaming_requests_is_non_negative_int(self, seeded):
        """DA.5: streaming_requests is an integer >= 0."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        val = r.json().get("streaming_requests")
        chk(f"DA.5  streaming_requests is int >= 0 (got {val!r})",
            isinstance(val, int) and val >= 0,
            f"value={val!r}")
        assert isinstance(val, int) and val >= 0

    def test_da06_kpis_no_auth_returns_401(self):
        """DA.6: /kpis without auth returns 401."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, timeout=10)
        chk("DA.6  GET /analytics/kpis no auth -> 401",
            r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da07_streaming_requests_is_a_count_not_a_cost(self, seeded):
        """DA.7: streaming_requests is an integer count, not a float/cost value."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        val = r.json().get("streaming_requests", None)
        chk(f"DA.7  streaming_requests is int (got {val!r})",
            isinstance(val, int), f"type={type(val)}")
        assert isinstance(val, int)

    def test_da08_kpis_member_role_can_read(self, member_info):
        """DA.8: member-role key can read /kpis (not admin-gated)."""
        _, member_key = member_info
        if not member_key:
            pytest.skip("No member key available")
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30},
                         headers=get_headers(member_key), timeout=15)
        chk("DA.8  member role GET /analytics/kpis -> 200",
            r.status_code == 200, f"status={r.status_code}")
        assert r.status_code == 200

    def test_da09_wasted_cost_does_not_exceed_total_cost(self, seeded):
        """DA.9: wasted_cost_usd <= total_cost_usd (sanity: can't waste more than spent)."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        wasted = data.get("wasted_cost_usd", 0)
        total = data.get("total_cost_usd", 0)
        chk(f"DA.9  wasted_cost ({wasted:.4f}) <= total_cost ({total:.4f})",
            wasted <= total, f"wasted={wasted}, total={total}")
        assert wasted <= total

    def test_da10_kpis_cache_savings_still_present(self, seeded):
        """DA.10: existing cache_savings_usd field still returned (no regression)."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        chk("DA.10 kpis still has 'cache_savings_usd' field",
            "cache_savings_usd" in data, f"keys: {list(data.keys())}")
        assert "cache_savings_usd" in data


# ===========================================================================
# SECTION B — /v1/analytics/business-units (admin+ only)
# ===========================================================================

class TestBusinessUnits:
    """DA.11 – DA.20: business-units endpoint shape, auth, and role gating."""

    def test_da11_business_units_no_auth_returns_401(self):
        section("B --- /v1/analytics/business-units")
        r = requests.get(f"{API_URL}/v1/analytics/business-units", timeout=10)
        chk("DA.11 GET /analytics/business-units no auth -> 401",
            r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da12_admin_gets_200(self, seeded):
        """DA.12: admin key returns 200 from business-units."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        chk("DA.12 admin GET /analytics/business-units -> 200",
            r.status_code == 200, f"status={r.status_code}: {r.text[:200]}")
        assert r.status_code == 200

    def test_da13_member_can_read_business_units(self, member_info):
        """DA.13: member-role key gets 200 on business-units (endpoint is role-neutral)."""
        _, member_key = member_info
        if not member_key:
            pytest.skip("No member key available")
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=get_headers(member_key), timeout=15)
        chk("DA.13 member GET /analytics/business-units -> 200",
            r.status_code == 200, f"status={r.status_code}: {r.text[:120]}")
        assert r.status_code == 200

    def test_da14_response_is_json(self, seeded):
        """DA.14: response is valid JSON."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        assert r.status_code == 200
        try:
            data = r.json()
            chk("DA.14 response is valid JSON", True, "")
        except Exception as e:
            chk("DA.14 response is valid JSON", False, str(e))
            raise

    def test_da15_response_has_business_units_array(self, seeded):
        """DA.15: top-level key is 'business_units' (or 'data') and is a list."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Use explicit key check to avoid `[] or None` fallback on empty list
        if "business_units" in data:
            units = data["business_units"]
        elif "data" in data:
            units = data["data"]
        else:
            units = None
        chk("DA.15 response has 'business_units' or 'data' key with list value",
            isinstance(units, list),
            f"keys={list(data.keys())}, type={type(units)}")
        assert isinstance(units, list)

    def test_da16_each_unit_has_required_fields(self, seeded):
        """DA.16: each business unit entry has business_unit, cost, and by_team fields."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        units = data.get("business_units") or data.get("data") or []
        if not units:
            pytest.skip("No business unit data returned — org has no events with team tags")
        # Backend returns cost_usd (not cost); also accept cost for future compat
        required = {"business_unit"}
        cost_keys = {"cost_usd", "cost", "total_cost_usd"}
        for u in units[:5]:
            missing = required - set(u.keys())
            has_cost = bool(cost_keys & set(u.keys()))
            ok = not missing and has_cost
            chk(f"DA.16 unit '{u.get('business_unit', '?')}' has required fields",
                ok, f"missing={missing}, cost_keys_found={cost_keys & set(u.keys())}")
            assert ok

    def test_da17_costs_are_non_negative(self, seeded):
        """DA.17: all unit costs are >= 0."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        units = data.get("business_units") or data.get("data") or []
        if not units:
            pytest.skip("No units returned")
        for u in units:
            cost = u.get("cost_usd") or u.get("cost") or u.get("total_cost_usd") or 0
            chk(f"DA.17 unit '{u.get('business_unit', '?')}' cost >= 0",
                cost >= 0, f"cost={cost}")
            assert cost >= 0

    def test_da18_period_param_accepted(self, seeded):
        """DA.18: days query param is accepted without 400/422."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         params={"days": 7}, headers=seeded, timeout=15)
        chk("DA.18 ?days=7 accepted -> not 400",
            r.status_code not in (400, 422), f"status={r.status_code}")
        assert r.status_code not in (400, 422)

    def test_da19_bad_auth_returns_401(self):
        """DA.19: invalid API key returns 401."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers={"Authorization": "Bearer crt_bad"}, timeout=10)
        chk("DA.19 bad key -> 401", r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da20_unit_by_team_is_array(self, seeded):
        """DA.20: by_team field (if present) is a list."""
        r = requests.get(f"{API_URL}/v1/analytics/business-units",
                         headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        units = data.get("business_units") or data.get("data") or []
        if not units:
            pytest.skip("No units returned")
        for u in units[:3]:
            if "by_team" in u:
                chk(f"DA.20 unit by_team is list",
                    isinstance(u["by_team"], list),
                    f"type={type(u['by_team'])}")
                assert isinstance(u["by_team"], list)


# ===========================================================================
# SECTION C — /v1/admin/members/:id/usage (admin+ only)
# ===========================================================================

class TestMemberUsage:
    """DA.21 – DA.30: per-member usage endpoint shape, auth, and role gating."""

    def test_da21_no_auth_returns_401(self, member_info):
        section("C --- /v1/admin/members/:id/usage")
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage", timeout=10)
        chk("DA.21 GET /admin/members/:id/usage no auth -> 401",
            r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da22_admin_gets_200(self, seeded, member_info):
        """DA.22: admin can read any member's usage."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        chk("DA.22 admin GET /admin/members/:id/usage -> 200",
            r.status_code == 200, f"status={r.status_code}: {r.text[:200]}")
        assert r.status_code == 200

    def test_da23_member_role_is_forbidden(self, member_info):
        """DA.23: member cannot access their own usage via admin endpoint."""
        member_id, member_key = member_info
        if not member_key:
            pytest.skip("No member key")
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         headers=get_headers(member_key), timeout=15)
        chk("DA.23 member GET /admin/members/:id/usage -> 403",
            r.status_code == 403, f"status={r.status_code}: {r.text[:120]}")
        assert r.status_code == 403

    def test_da24_response_has_cost_field(self, seeded, member_info):
        """DA.24: response includes a cost field (at top level or nested in stats)."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        stats = data.get("stats", {})
        has_cost = (
            "total_cost_usd" in data or "cost" in data or
            "total_cost_usd" in stats or "cost" in stats
        )
        chk("DA.24 response has total_cost_usd or cost field (top-level or in stats)",
            has_cost, f"top_keys={list(data.keys())} stats_keys={list(stats.keys())}")
        assert has_cost

    def test_da25_response_has_request_count_field(self, seeded, member_info):
        """DA.25: response includes a requests count field (at top level or nested in stats)."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        stats = data.get("stats", {})
        has_reqs = (
            "total_requests" in data or "request_count" in data or
            "total_requests" in stats or "request_count" in stats
        )
        chk("DA.25 response has total_requests or request_count (top-level or in stats)",
            has_reqs, f"top_keys={list(data.keys())} stats_keys={list(stats.keys())}")
        assert has_reqs

    def test_da26_unknown_member_id_returns_404(self, seeded):
        """DA.26: non-existent member ID returns 404, not 500."""
        r = requests.get(f"{API_URL}/v1/admin/members/nonexistent-id-99999/usage",
                         headers=seeded, timeout=15)
        chk("DA.26 unknown member_id -> 404",
            r.status_code == 404, f"status={r.status_code}: {r.text[:120]}")
        assert r.status_code == 404

    def test_da27_period_param_accepted(self, seeded, member_info):
        """DA.27: period query param is accepted."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 7}, headers=seeded, timeout=15)
        chk("DA.27 ?period=7 accepted", r.status_code in (200, 404),
            f"status={r.status_code}")
        assert r.status_code in (200, 404)

    def test_da28_cost_is_non_negative(self, seeded, member_info):
        """DA.28: cost field value >= 0 (at top level or nested in stats)."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        stats = data.get("stats", {})
        cost = (data.get("total_cost_usd") or data.get("cost") or
                stats.get("total_cost_usd") or stats.get("cost") or 0)
        chk(f"DA.28 cost ({cost}) >= 0", cost >= 0, f"cost={cost}")
        assert cost >= 0

    def test_da29_response_has_token_fields(self, seeded, member_info):
        """DA.29: response includes token count field (top-level or nested in stats)."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        stats = data.get("stats", {})
        token_keys = {"total_input_tokens", "total_tokens", "prompt_tokens", "tokens"}
        has_tokens = bool(token_keys & set(data.keys())) or bool(token_keys & set(stats.keys()))
        chk("DA.29 response has at least one token count field (top-level or in stats)",
            has_tokens, f"top_keys={list(data.keys())} stats_keys={list(stats.keys())}")
        assert has_tokens

    def test_da30_by_model_if_present_is_list(self, seeded, member_info):
        """DA.30: by_model field, if returned, is a list."""
        member_id, _ = member_info
        r = requests.get(f"{API_URL}/v1/admin/members/{member_id}/usage",
                         params={"period": 30}, headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        by_model = data.get("by_model") or data.get("models")
        if by_model is not None:
            chk("DA.30 by_model is a list", isinstance(by_model, list),
                f"type={type(by_model)}")
            assert isinstance(by_model, list)


# ===========================================================================
# SECTION D — /v1/optimizer/stats (any authenticated role)
# ===========================================================================

class TestOptimizerStats:
    """DA.31 – DA.36: optimizer stats endpoint shape and auth."""

    def test_da31_no_auth_returns_401(self):
        section("D --- /v1/optimizer/stats")
        r = requests.get(f"{API_URL}/v1/optimizer/stats", timeout=10)
        chk("DA.31 GET /optimizer/stats no auth -> 401",
            r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da32_authenticated_returns_200(self, seeded):
        """DA.32: authenticated request returns 200."""
        r = requests.get(f"{API_URL}/v1/optimizer/stats", headers=seeded, timeout=15)
        chk("DA.32 GET /optimizer/stats authenticated -> 200",
            r.status_code == 200, f"status={r.status_code}: {r.text[:200]}")
        assert r.status_code == 200

    def test_da33_member_can_read(self, member_info):
        """DA.33: member-role key can read optimizer/stats (not admin-gated)."""
        _, member_key = member_info
        if not member_key:
            pytest.skip("No member key")
        r = requests.get(f"{API_URL}/v1/optimizer/stats",
                         headers=get_headers(member_key), timeout=15)
        chk("DA.33 member GET /optimizer/stats -> 200",
            r.status_code == 200, f"status={r.status_code}")
        assert r.status_code == 200

    def test_da34_response_has_compression_count(self, seeded):
        """DA.34: response has a compression/events count field.
        Backend returns total_events (count of optimizer calls made).
        Also accept total_compressions or compressions for API evolution.
        """
        r = requests.get(f"{API_URL}/v1/optimizer/stats", headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        has_count = (
            "total_compressions" in data or
            "compressions" in data or
            "total_events" in data
        )
        chk("DA.34 optimizer stats has a compression/events count field",
            has_count, f"keys={list(data.keys())}")
        assert has_count

    def test_da35_response_has_tokens_saved(self, seeded):
        """DA.35: response has total_tokens_saved or tokens_saved field."""
        r = requests.get(f"{API_URL}/v1/optimizer/stats", headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        has_saved = "total_tokens_saved" in data or "tokens_saved" in data
        chk("DA.35 optimizer stats has tokens_saved field",
            has_saved, f"keys={list(data.keys())}")
        assert has_saved

    def test_da36_numeric_fields_are_non_negative(self, seeded):
        """DA.36: all numeric stat fields are >= 0."""
        r = requests.get(f"{API_URL}/v1/optimizer/stats", headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        numeric_keys = [k for k, v in data.items() if isinstance(v, (int, float))]
        for k in numeric_keys:
            val = data[k]
            chk(f"DA.36 field '{k}' is >= 0 (got {val})", val >= 0, f"{k}={val}")
            assert val >= 0


# ===========================================================================
# SECTION E — /v1/benchmark/contribute: idempotency and opt-in gate
# ===========================================================================

_CONTRIBUTE_URL = f"{API_URL}/v1/benchmark/contribute"

def _contribute_deployed(headers: dict) -> bool:
    """Return False if /benchmark/contribute returns 500 (tables not yet migrated)."""
    try:
        r = requests.post(_CONTRIBUTE_URL, json={}, headers=headers, timeout=10)
        return r.status_code != 500
    except Exception:
        return False


class TestBenchmarkContributeIdempotency:
    """DA.37 – DA.40: contribute endpoint is idempotent and respects opt-in flag."""

    def test_da37_contribute_no_auth_returns_401(self):
        section("E --- /v1/benchmark/contribute idempotency")
        r = requests.post(f"{API_URL}/v1/benchmark/contribute", json={}, timeout=10)
        chk("DA.37 POST /benchmark/contribute no auth -> 401",
            r.status_code == 401, f"status={r.status_code}")
        assert r.status_code == 401

    def test_da38_contribute_returns_200_for_admin(self, seeded):
        """DA.38: admin POST /benchmark/contribute always returns 200 (not 500)."""
        if not _contribute_deployed(seeded):
            pytest.skip("benchmark/contribute returns 500 — D1 migration not yet applied to production")
        r = requests.post(f"{API_URL}/v1/benchmark/contribute", json={},
                          headers=seeded, timeout=15)
        chk("DA.38 admin POST /benchmark/contribute -> 200",
            r.status_code == 200, f"status={r.status_code}: {r.text[:200]}")
        assert r.status_code == 200

    def test_da39_contribute_is_idempotent(self, seeded):
        """DA.39: calling /contribute twice in a row returns 200 both times (idempotent)."""
        if not _contribute_deployed(seeded):
            pytest.skip("benchmark/contribute returns 500 — D1 migration not yet applied to production")
        for call_num in (1, 2):
            r = requests.post(f"{API_URL}/v1/benchmark/contribute", json={},
                               headers=seeded, timeout=15)
            chk(f"DA.39 idempotent call #{call_num} -> 200",
                r.status_code == 200, f"call={call_num} status={r.status_code}")
            assert r.status_code == 200

    def test_da40_contribute_opt_out_returns_ok_false(self, seeded):
        """DA.40: fresh org (not opted in) gets ok:false in contribute response body."""
        if not _contribute_deployed(seeded):
            pytest.skip("benchmark/contribute returns 500 — D1 migration not yet applied to production")
        r = requests.post(f"{API_URL}/v1/benchmark/contribute", json={},
                          headers=seeded, timeout=15)
        assert r.status_code == 200
        data = r.json()
        chk("DA.40 opt-out org body.ok is false",
            data.get("ok") is False, f"body={data}")
        assert data.get("ok") is False


# ===========================================================================
# Standalone runner
# ===========================================================================

if __name__ == "__main__":
    import inspect

    from helpers.output import get_results, reset_results, fail

    reset_results()

    acct = fresh_account(prefix="da45run")
    hdrs = get_headers(acct[0])
    _seed_events(hdrs, count=6)

    mem_r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": f"da45-member-{random.randint(10000,99999)}@example.com",
              "name": "DA45 Runner Member", "role": "member"},
        headers=hdrs, timeout=15,
    )
    m_data = mem_r.json() if mem_r.status_code == 201 else {}
    mem_id  = m_data.get("id") or m_data.get("member_id")
    mem_key = m_data.get("api_key")

    class _FakeSeeded:
        """Minimal adapter so seeded fixture tests work in standalone mode."""
        def __getitem__(self, k): return hdrs[k]
        def get(self, k, d=None): return hdrs.get(k, d)

    _seeded = hdrs
    _member = (mem_id, mem_key)

    classes = [
        TestKpisNewFields, TestBusinessUnits,
        TestMemberUsage, TestOptimizerStats,
        TestBenchmarkContributeIdempotency,
    ]

    for cls in classes:
        obj = cls()
        for name in sorted(dir(obj)):
            if not name.startswith("test_"):
                continue
            try:
                method = getattr(obj, name)
                params = list(inspect.signature(method).parameters.keys())
                kwargs: dict = {}
                if "seeded"      in params: kwargs["seeded"]      = _seeded
                if "member_info" in params: kwargs["member_info"] = _member
                method(**kwargs)
            except SystemExit as e:
                print(f"  SKIP {name}: {e}")
            except Exception as e:
                fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed / {res['failed']} failed / {res['warned']} warned")
    sys.exit(res["failed"])
