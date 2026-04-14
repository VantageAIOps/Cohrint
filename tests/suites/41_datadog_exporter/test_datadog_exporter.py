"""
Test Suite 41 — Datadog Exporter (Live Environment)
=====================================================
Validates the three Datadog connection endpoints:
  POST   /v1/datadog/connect
  DELETE /v1/datadog/connect
  GET    /v1/datadog/status

All tests hit the live API at https://api.vantageaiops.com.
No mocks. Labels: DD.1 – DD.14
"""

import sys
from pathlib import Path
import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import chk, get_results, reset_results, section

CONNECT_URL = f"{API_URL}/v1/datadog/connect"
STATUS_URL  = f"{API_URL}/v1/datadog/status"

_FAKE_API_KEY = "fake_key_for_testing_00000000000000"
_ALLOWED_SITES = [
    "datadoghq.com", "datadoghq.eu",
    "us3.datadoghq.com", "us5.datadoghq.com", "ap1.datadoghq.com",
]


class TestDatadogAuth:
    def test_dd01_post_connect_no_auth(self):
        section("A --- Datadog Auth Gates")
        r = requests.post(CONNECT_URL, json={"api_key": _FAKE_API_KEY}, timeout=10)
        chk("DD.1  POST /datadog/connect no auth -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_dd02_delete_connect_no_auth(self):
        r = requests.delete(CONNECT_URL, timeout=10)
        chk("DD.2  DELETE /datadog/connect no auth -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_dd03_get_status_no_auth(self):
        r = requests.get(STATUS_URL, timeout=10)
        chk("DD.3  GET /datadog/status no auth -> 401", r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401


class TestDatadogRoles:
    @pytest.fixture(scope="class")
    def account(self):
        return fresh_account()

    def _member_key(self, account):
        key = account.get("member_key") or account.get("viewer_key")
        if not key:
            pytest.skip("No member/viewer key in fresh_account()")
        return key

    def test_dd04_post_connect_viewer_403(self, account):
        section("B --- Datadog Role Enforcement")
        r = requests.post(CONNECT_URL, json={"api_key": _FAKE_API_KEY},
                          headers=get_headers(self._member_key(account)), timeout=10)
        chk("DD.4  POST /datadog/connect viewer -> 403", r.status_code == 403, f"got {r.status_code}")
        assert r.status_code == 403

    def test_dd05_delete_connect_viewer_403(self, account):
        r = requests.delete(CONNECT_URL, headers=get_headers(self._member_key(account)), timeout=10)
        chk("DD.5  DELETE /datadog/connect viewer -> 403", r.status_code == 403, f"got {r.status_code}")
        assert r.status_code == 403

    def test_dd06_get_status_viewer_403(self, account):
        r = requests.get(STATUS_URL, headers=get_headers(self._member_key(account)), timeout=10)
        chk("DD.6  GET /datadog/status viewer -> 403", r.status_code == 403, f"got {r.status_code}")
        assert r.status_code == 403


class TestDatadogInputValidation:
    @pytest.fixture(scope="class")
    def account(self):
        return fresh_account()

    def test_dd07_missing_api_key_400(self, account):
        section("C --- Datadog Input Validation")
        r = requests.post(CONNECT_URL, json={}, headers=get_headers(account["org_key"]), timeout=10)
        chk("DD.7  POST /datadog/connect missing api_key -> 400", r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400

    def test_dd08_empty_api_key_400(self, account):
        r = requests.post(CONNECT_URL, json={"api_key": ""}, headers=get_headers(account["org_key"]), timeout=10)
        chk("DD.8  POST /datadog/connect empty api_key -> 400", r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400

    def test_dd09_invalid_site_400(self, account):
        r = requests.post(CONNECT_URL, json={"api_key": _FAKE_API_KEY, "site": "notadomain.xyz"},
                          headers=get_headers(account["org_key"]), timeout=10)
        chk("DD.9  POST /datadog/connect invalid site -> 400", r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400
        assert "error" in r.json()

    @pytest.mark.parametrize("site", _ALLOWED_SITES)
    def test_dd10_allowed_sites_pass_allowlist(self, account, site):
        """Each allowed site passes site validation — fake key fails at Datadog's API check (not ours)."""
        r = requests.post(CONNECT_URL, json={"api_key": _FAKE_API_KEY, "site": site},
                          headers=get_headers(account["org_key"]), timeout=15)
        chk(f"DD.10 site={site} -> API-key error, not site-rejection", r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400
        error_msg = (r.json().get("error") or "").lower()
        assert "site" not in error_msg, f"site={site} is allowed but got site-rejection: {r.json()}"


class TestDatadogNotConnected:
    @pytest.fixture(scope="class")
    def account(self):
        return fresh_account()

    def test_dd13_status_not_connected(self, account):
        section("D --- Datadog Not Connected")
        r = requests.get(STATUS_URL, headers=get_headers(account["org_key"]), timeout=10)
        chk("DD.13 GET /datadog/status no connection -> 200 {connected:false} or 404",
            r.status_code in (200, 404), f"got {r.status_code}")
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert r.json().get("connected") is False

    def test_dd14_delete_not_connected_404(self, account):
        r = requests.delete(CONNECT_URL, headers=get_headers(account["org_key"]), timeout=10)
        chk("DD.14 DELETE /datadog/connect not connected -> 404", r.status_code == 404, f"got {r.status_code}")
        assert r.status_code == 404


def test_zz_results():
    results = get_results()
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    print(f"\n{'='*60}\nSuite 41 — Datadog Exporter: {passed}/{total} checks passed\n{'='*60}")
    failed = [k for k, v in results.items() if not v]
    if failed:
        print("FAILED:\n" + "\n".join(f"  ✗ {f}" for f in failed))
    reset_results()
