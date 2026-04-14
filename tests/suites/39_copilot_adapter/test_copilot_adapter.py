"""
Test Suite 39 — GitHub Copilot Adapter (Live Environment)
==========================================================
Validates the three Copilot connection endpoints:
  POST   /v1/copilot/connect
  DELETE /v1/copilot/connect
  GET    /v1/copilot/status

All tests hit the live API at https://api.vantageaiops.com.
No mocks. A fresh account is created per module via fresh_account().

Labels: CP.1 – CP.26
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

CONNECT_URL = f"{API_URL}/v1/copilot/connect"
STATUS_URL  = f"{API_URL}/v1/copilot/status"

# Clearly-invalid PAT that passes the prefix check but will be rejected by GitHub
_FAKE_PAT = "ghp_" + "x" * 36


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Authentication Gates  (CP.1 – CP.4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopilotAuth:
    """All three endpoints must reject unauthenticated requests with 401."""

    def test_cp01_post_connect_no_auth_returns_401(self):
        section("A --- Copilot Auth Gates")
        r = requests.post(CONNECT_URL,
                          json={"github_org": "test-org", "token": _FAKE_PAT},
                          timeout=10)
        chk("CP.1  POST /copilot/connect no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_cp02_delete_connect_no_auth_returns_401(self):
        r = requests.delete(f"{CONNECT_URL}?github_org=test-org", timeout=10)
        chk("CP.2  DELETE /copilot/connect no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_cp03_get_status_no_auth_returns_401(self):
        r = requests.get(STATUS_URL, timeout=10)
        chk("CP.3  GET /copilot/status no auth -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401

    def test_cp04_bad_key_returns_401(self):
        r = requests.get(STATUS_URL,
                         headers={"Authorization": "Bearer vnt_bad_key"},
                         timeout=10)
        chk("CP.4  GET /copilot/status bad key -> 401",
            r.status_code == 401, f"got {r.status_code}")
        assert r.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Input Validation on POST /connect  (CP.5 – CP.12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopilotConnectValidation:
    """Field-level validation for POST /v1/copilot/connect."""

    def test_cp05_missing_github_org_returns_400(self, headers):
        section("B --- POST /copilot/connect Validation")
        r = requests.post(CONNECT_URL,
                          json={"token": _FAKE_PAT},
                          headers=headers, timeout=10)
        chk("CP.5  missing github_org -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_cp06_missing_token_returns_400(self, headers):
        r = requests.post(CONNECT_URL,
                          json={"github_org": "test-org"},
                          headers=headers, timeout=10)
        chk("CP.6  missing token -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_cp07_empty_body_returns_400(self, headers):
        r = requests.post(CONNECT_URL,
                          json={},
                          headers=headers, timeout=10)
        chk("CP.7  empty body -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    @pytest.mark.parametrize("bad_org,label", [
        ("org with spaces", "spaces"),
        ("a" * 40, "41 chars — exceeds 39 char limit"),
        ("org/slash", "slash"),
        ("org@email", "at-sign"),
        ("", "empty string"),
    ])
    def test_cp08_invalid_github_org_format_returns_400(self, headers, bad_org, label):
        r = requests.post(CONNECT_URL,
                          json={"github_org": bad_org, "token": _FAKE_PAT},
                          headers=headers, timeout=10)
        chk(f"CP.8  invalid github_org ({label}) -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    @pytest.mark.parametrize("bad_token,label", [
        ("ghs_" + "x" * 36, "ghs_* service token"),
        ("ghcr_" + "x" * 36, "ghcr_* token"),
        ("github_app_" + "x" * 20, "github_app_ prefix"),
        ("plain_no_prefix_at_all_xxxxxxxxxxx", "no known prefix"),
        ("ghp_short", "ghp_ but too short (< 20 chars after prefix)"),
    ])
    def test_cp09_invalid_token_prefix_returns_400(self, headers, bad_token, label):
        r = requests.post(CONNECT_URL,
                          json={"github_org": "valid-org", "token": bad_token},
                          headers=headers, timeout=10)
        chk(f"CP.9  invalid token ({label}) -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_cp10_ghs_token_error_message_mentions_not_supported(self, headers):
        """ghs_* service tokens must produce an error message that explains they are not supported."""
        r = requests.post(CONNECT_URL,
                          json={"github_org": "valid-org",
                                "token": "ghs_" + "x" * 36},
                          headers=headers, timeout=10)
        chk("CP.10 ghs_* -> 400", r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400
        body_text = r.text.lower()
        chk("CP.10b error mentions ghs_* not supported",
            "ghs_" in body_text or "not supported" in body_text or "service token" in body_text,
            f"error body: {r.text[:200]}")

    def test_cp11_invalid_json_body_returns_400(self, headers):
        r = requests.post(CONNECT_URL,
                          data="not-json",
                          headers={**headers, "Content-Type": "application/json"},
                          timeout=10)
        chk("CP.11 invalid JSON body -> 400",
            r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400

    def test_cp12_valid_token_format_but_bad_github_credentials_returns_400_or_404(
        self, headers
    ):
        """
        A well-formed PAT that fails the live GitHub validation call should return
        400 (invalid/expired) or 404 (org not found). It must NOT return 201.
        The backend makes a real GitHub API call, so this test exercises the
        full validation pipeline with a known-bad credential.
        """
        r = requests.post(CONNECT_URL,
                          json={"github_org": "vantageai-nonexistent-org-xyz",
                                "token": _FAKE_PAT},
                          headers=headers, timeout=20)
        chk("CP.12 real GitHub call with fake PAT -> 400 or 404 (not 201)",
            r.status_code in (400, 404), f"got {r.status_code}: {r.text[:200]}")
        assert r.status_code in (400, 404)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Role Enforcement on POST /connect  (CP.13)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopilotConnectRoles:
    """Only owner/admin may POST or DELETE /copilot/connect."""

    def test_cp13_member_role_post_connect_returns_403(self, member_key):
        section("C --- Role Enforcement")
        r = requests.post(CONNECT_URL,
                          json={"github_org": "valid-org", "token": _FAKE_PAT},
                          headers=get_headers(member_key), timeout=10)
        chk("CP.13 member POST /copilot/connect -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403

    def test_cp14_member_role_delete_connect_returns_403(self, member_key):
        r = requests.delete(f"{CONNECT_URL}?github_org=some-org",
                            headers=get_headers(member_key), timeout=10)
        chk("CP.14 member DELETE /copilot/connect -> 403",
            r.status_code == 403, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: GET /status  (CP.15 – CP.19)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopilotStatus:
    """GET /v1/copilot/status response contract."""

    def test_cp15_admin_get_status_returns_200(self, headers):
        section("D --- GET /copilot/status")
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        chk("CP.15 admin GET /copilot/status -> 200",
            r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200

    def test_cp16_status_response_has_connections_key(self, headers):
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        assert r.status_code == 200
        data = r.json()
        chk("CP.16 response has 'connections' key",
            "connections" in data, f"keys: {list(data.keys())}")
        assert "connections" in data

    def test_cp17_connections_is_array(self, headers):
        r = requests.get(STATUS_URL, headers=headers, timeout=10)
        data = r.json()
        connections = data.get("connections")
        chk("CP.17 connections is a list",
            isinstance(connections, list), f"type: {type(connections)}")
        assert isinstance(connections, list)

    def test_cp18_member_get_status_returns_200_with_connections(self, member_key):
        """Members can read status (non-admin view — last_error is stripped)."""
        r = requests.get(STATUS_URL, headers=get_headers(member_key), timeout=10)
        chk("CP.18 member GET /copilot/status -> 200",
            r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200
        data = r.json()
        assert "connections" in data

    def test_cp19_member_status_omits_last_error_field(self, member_key):
        """Non-admin view must not expose last_error per the backend contract."""
        r = requests.get(STATUS_URL, headers=get_headers(member_key), timeout=10)
        assert r.status_code == 200
        connections = r.json().get("connections", [])
        for conn in connections:
            chk("CP.19 member view omits last_error",
                "last_error" not in conn,
                f"last_error present in member view: {conn}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: DELETE /connect  (CP.20 – CP.22)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopilotDelete:
    """DELETE /v1/copilot/connect validation."""

    def test_cp20_delete_missing_github_org_param_returns_400(self, headers):
        section("E --- DELETE /copilot/connect")
        r = requests.delete(CONNECT_URL, headers=headers, timeout=10)
        chk("CP.20 DELETE missing github_org param -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_cp21_delete_nonexistent_org_returns_404(self, headers):
        """An org that was never connected must return 404."""
        nonexistent = f"never-connected-org-{random.randint(10000, 99999)}"
        r = requests.delete(f"{CONNECT_URL}?github_org={nonexistent}",
                            headers=headers, timeout=10)
        chk("CP.21 DELETE non-existent org -> 404",
            r.status_code == 404, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 404

    def test_cp22_delete_empty_github_org_param_returns_400(self, headers):
        r = requests.delete(f"{CONNECT_URL}?github_org=",
                            headers=headers, timeout=10)
        chk("CP.22 DELETE empty github_org param -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  Pytest fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def account():
    return fresh_account(prefix="cp39")

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
    """Create a member in the test org and return their raw API key."""
    api_key, _, _ = account
    email = f"cp-member-{random.randint(10000, 99999)}@example.com"
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": email, "name": "Copilot Member", "role": "member"},
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
    acct = fresh_account(prefix="cp39run")
    hdrs = get_headers(acct[0])

    mem_r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": f"cp-member-{random.randint(10000,99999)}@example.com",
              "name": "CP Member", "role": "member"},
        headers=hdrs, timeout=15,
    )
    member_k = mem_r.json().get("api_key") if mem_r.status_code == 201 else None

    classes = [
        TestCopilotAuth, TestCopilotConnectValidation,
        TestCopilotConnectRoles, TestCopilotStatus, TestCopilotDelete,
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
