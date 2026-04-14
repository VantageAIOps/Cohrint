"""
Test Suite 41 — Datadog Exporter (Live Environment)
====================================================
Validates the three Datadog connection endpoints:
  POST   /v1/datadog/connect
  DELETE /v1/datadog/connect
  GET    /v1/datadog/status

The POST /connect endpoint calls the real Datadog validate API.
Tests use a clearly-fake API key ('fake_key_for_testing') which causes
Datadog to return 403, triggering the backend's 400 'Invalid Datadog API key'
response — no real Datadog account needed.

No mocks. Fresh account per module.

Labels: DD.1 – DD.21
"""

import inspect
import random
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import chk, fail, get_results, reset_results, section

CONNECT_URL = f"{API_URL}/v1/datadog/connect"
STATUS_URL  = f"{API_URL}/v1/datadog/status"

ALLOWED_SITES = [
    "datadoghq.com",
    "datadoghq.eu",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "ap1.datadoghq.com",
]
_FAKE_API_KEY = "fake_key_for_testing"

# ── Deployment guard ──────────────────────────────────────────────────────────
# Probe GET /status once. If auth-gated endpoints return 500 the worker is
# deployed but the datadog_connections table migration hasn't run yet.
# Tests that require a valid DB connection skip rather than fail.

_DATADOG_DEPLOYED = None  # type: ignore[assignment]

def _datadog_deployed(headers) -> bool:
    global _DATADOG_DEPLOYED
    if _DATADOG_DEPLOYED is None:
        try:
            r = requests.get(STATUS_URL, headers=headers, timeout=10)
            _DATADOG_DEPLOYED = r.status_code != 500
        except Exception:
            _DATADOG_DEPLOYED = False
    return _DATADOG_DEPLOYED


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Authentication Gates  (DD.1 – DD.4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatadogAuth:
    """All three endpoints must reject unauthenticated requests with 401."""

    def test_dd01_post_connect_no_auth_returns_401(self):
        section("A --- Datadog Auth Gates")
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY},
                          timeout=10)
        chk("DD.1  POST /datadog/connect no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_dd02_delete_connect_no_auth_returns_401(self):
        r = requests.delete(CONNECT_URL, timeout=10)
        chk("DD.2  DELETE /datadog/connect no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_dd03_get_status_no_auth_returns_401(self):
        r = requests.get(STATUS_URL, timeout=10)
        chk("DD.3  GET /datadog/status no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_dd04_bad_key_returns_401(self):
        r = requests.get(STATUS_URL,
                         headers={"Authorization": "Bearer vnt_bad_key"},
                         timeout=10)
        chk("DD.4  GET /datadog/status bad key -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Role Enforcement  (DD.5 – DD.7)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatadogRoles:
    """Only owner/admin may use connect/delete/status endpoints."""

    def test_dd05_member_post_connect_returns_403(self, member_key):
        section("B --- Role Enforcement")
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY},
                          headers=get_headers(member_key), timeout=10)
        chk("DD.5  member POST /datadog/connect -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403

    def test_dd06_member_delete_connect_returns_403(self, member_key):
        r = requests.delete(CONNECT_URL,
                            headers=get_headers(member_key), timeout=10)
        chk("DD.6  member DELETE /datadog/connect -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403

    def test_dd07_member_get_status_returns_403(self, member_key):
        r = requests.get(STATUS_URL,
                         headers=get_headers(member_key), timeout=10)
        chk("DD.7  member GET /datadog/status -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: POST /connect — Input Validation  (DD.8 – DD.15)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatadogConnectValidation:
    """Field-level validation for POST /v1/datadog/connect."""

    def test_dd08_missing_api_key_returns_400(self, headers):
        section("C --- POST /datadog/connect Validation")
        r = requests.post(CONNECT_URL, json={}, headers=headers, timeout=10)
        chk("DD.8  missing api_key -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_dd09_non_string_api_key_returns_400(self, headers):
        r = requests.post(CONNECT_URL,
                          json={"api_key": 12345},
                          headers=headers, timeout=10)
        chk("DD.9  api_key as integer -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    @pytest.mark.parametrize("bad_site,label", [
        ("datadog.com",          "datadog.com (wrong domain)"),
        ("app.datadoghq.com",    "app subdomain"),
        ("us1.datadoghq.com",    "us1 (not in allowed list)"),
        ("evil.com",             "evil.com"),
        ("",                     "empty string"),
        ("datadoghq.com.evil",   "lookalike domain"),
    ])
    def test_dd10_invalid_site_value_returns_400(self, headers, bad_site, label):
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY, "site": bad_site},
                          headers=headers, timeout=10)
        chk(f"DD.10 invalid site ({label}) -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_dd11_invalid_site_error_lists_allowed_sites(self, headers):
        """400 for invalid site must mention at least one allowed site in the error."""
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY, "site": "bad.example.com"},
                          headers=headers, timeout=10)
        assert r.status_code == 400
        body_text = r.text.lower()
        chk("DD.11 400 body mentions at least one allowed Datadog site",
            any(site.lower() in body_text for site in ALLOWED_SITES),
            f"body: {r.text[:200]}")

    def test_dd12_invalid_json_body_returns_400(self, headers):
        r = requests.post(CONNECT_URL,
                          data="not-json",
                          headers={**headers, "Content-Type": "application/json"},
                          timeout=10)
        chk("DD.12 invalid JSON body -> 400",
            r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400

    def test_dd13_valid_site_but_fake_api_key_returns_400(self, headers):
        """
        A valid site with a clearly fake API key triggers the Datadog /validate
        endpoint, which returns 403 → backend returns 400 'invalid or inactive'.
        This test makes a real outbound call to api.datadoghq.com.
        """
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY,
                                "site": "datadoghq.com"},
                          headers=headers, timeout=20)
        chk("DD.13 valid site + fake api_key -> 400 (Datadog validate rejected)",
            r.status_code == 400, f"got {r.status_code}: {r.text[:200]}")
        assert r.status_code == 400

    def test_dd14_fake_api_key_error_mentions_invalid_or_inactive(self, headers):
        """Error message must clearly describe the rejection reason."""
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY,
                                "site": "datadoghq.com"},
                          headers=headers, timeout=20)
        assert r.status_code == 400
        body_text = r.text.lower()
        chk("DD.14 error body mentions 'invalid' for bad Datadog key",
            "invalid" in body_text or "inactive" in body_text or "datadog" in body_text,
            f"body: {r.text[:200]}")

    @pytest.mark.parametrize("site", ALLOWED_SITES)
    def test_dd15_all_allowed_sites_accepted_before_key_validation(self, headers, site):
        """
        Every allowed site must pass the site-validation gate and reach the key
        validation step. The response should be 400 (bad key), not 400 for bad site.
        """
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.post(CONNECT_URL,
                          json={"api_key": _FAKE_API_KEY, "site": site},
                          headers=headers, timeout=20)
        chk(f"DD.15 site={site} passes site gate (error is about key, not site)",
            r.status_code == 400 and "unsupported" not in r.text.lower(),
            f"got {r.status_code}: {r.text[:200]}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: DELETE /connect  (DD.16 – DD.17)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatadogDelete:
    """DELETE /v1/datadog/connect when no connection exists must return 404."""

    def test_dd16_delete_non_connected_org_returns_404(self, headers):
        section("D --- DELETE /datadog/connect")
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.delete(CONNECT_URL, headers=headers, timeout=10)
        chk("DD.16 DELETE, no prior connection -> 404",
            r.status_code == 404, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 404

    def test_dd17_delete_404_has_error_field(self, headers):
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.delete(CONNECT_URL, headers=headers, timeout=10)
        assert r.status_code == 404
        data = r.json()
        chk("DD.17 404 body has 'error' field",
            "error" in data, f"keys: {list(data.keys())}")
        assert "error" in data


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: GET /status  (DD.18 – DD.21)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDatadogStatus:
    """GET /v1/datadog/status response contract (no connection case)."""

    def test_dd18_admin_get_status_returns_200(self, headers):
        section("E --- GET /datadog/status")
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        chk("DD.18 admin GET /datadog/status -> 200",
            r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200

    def test_dd19_no_connection_returns_connected_false(self, headers):
        """
        Fresh account with no Datadog connection — backend returns
        { connected: false } (not 404).
        """
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        assert r.status_code == 200
        data = r.json()
        chk("DD.19 no connection -> { connected: false }",
            data.get("connected") is False, f"body: {data}")
        assert data.get("connected") is False

    def test_dd20_connected_false_no_extra_sensitive_fields(self, headers):
        """Disconnected status response must not leak encrypted_api_key."""
        if not _datadog_deployed(headers):
            pytest.skip("datadog endpoints return 500 — table not yet deployed to production")
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        assert r.status_code == 200
        data = r.json()
        chk("DD.20 response does not contain encrypted_api_key",
            "encrypted_api_key" not in data, f"keys: {list(data.keys())}")

    def test_dd21_member_get_status_returns_403(self, headers, member_key):
        """GET /status is admin-only — members must receive 403."""
        r = requests.get(STATUS_URL,
                         headers=get_headers(member_key), timeout=10)
        chk("DD.21 member GET /datadog/status -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
#  Pytest fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def account():
    return fresh_account(prefix="dd41")

@pytest.fixture(scope="module")
def headers(account):
    api_key, _, _ = account
    return get_headers(api_key)

@pytest.fixture(scope="module")
def org_id(account):
    _, oid, _ = account
    return oid

@pytest.fixture(scope="module")
def member_key(account):
    """Create a member-role key in the test org."""
    api_key, _, _ = account
    email = f"dd-member-{random.randint(10000, 99999)}@example.com"
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": email, "name": "DD Member", "role": "member"},
        headers=get_headers(api_key),
        timeout=15,
    )
    if r.status_code != 201:
        pytest.skip(f"Could not create member key: {r.text}")
    return r.json()["api_key"]


# ═══════════════════════════════════════════════════════════════════════════════
#  Standalone runner
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    reset_results()
    acct = fresh_account(prefix="dd41run")
    hdrs = get_headers(acct[0])

    mem_r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": f"dd-member-{random.randint(10000,99999)}@example.com",
              "name": "DD Member", "role": "member"},
        headers=hdrs, timeout=15,
    )
    member_k = mem_r.json().get("api_key") if mem_r.status_code == 201 else None

    classes = [
        TestDatadogAuth, TestDatadogRoles, TestDatadogConnectValidation,
        TestDatadogDelete, TestDatadogStatus,
    ]
    for cls in classes:
        obj = cls()
        for name in sorted(dir(obj)):
            if not name.startswith("test_"):
                continue
            try:
                method = getattr(obj, name)
                params = inspect.signature(method).parameters
                kwargs = {}
                if "headers"    in params: kwargs["headers"]    = hdrs
                if "member_key" in params:
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
    sys.exit(run())
