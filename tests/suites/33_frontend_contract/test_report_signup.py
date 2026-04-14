"""
Test Suite 33 (addendum) — POST /v1/platform/report-signup
===========================================================
Validates the public report-signup endpoint:
  POST /v1/platform/report-signup

No auth required. Idempotent — same email twice returns ok:true both times.
Rate limit: 5 signups per IP per hour (CF-Connecting-IP header).
Note: CF-Connecting-IP is set by Cloudflare and cannot be spoofed from test
      clients; the rate-limit tests are documented but skipped (see RS.7).

No mocks. All tests hit the live API.

Labels: RS.1 – RS.12
"""

import random
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import chk, section

SIGNUP_URL = f"{API_URL}/v1/platform/report-signup"


def _rand_email(prefix: str = "rs") -> str:
    return f"{prefix}-{random.randint(100000, 999999)}@example.com"


# ═══════════════════════════════════════════════════════════════════════════════
#  Section A: Happy Path  (RS.1 – RS.3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportSignupHappyPath:
    """Valid email submissions must return 200 { ok: true }."""

    def test_rs01_valid_email_returns_200(self):
        section("A --- POST /platform/report-signup Happy Path")
        email = _rand_email("rs01")
        r = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        chk("RS.1  valid email -> 200",
            r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200

    def test_rs02_valid_email_body_ok_true(self):
        email = _rand_email("rs02")
        r = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        assert r.status_code == 200
        data = r.json()
        chk("RS.2  body.ok == true",
            data.get("ok") is True, f"body: {data}")
        assert data.get("ok") is True

    def test_rs03_email_is_case_insensitive_and_trimmed(self):
        """Backend normalises email to lowercase + stripped — upper-case variant must succeed."""
        email = _rand_email("RS03").upper()
        r = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        chk("RS.3  upper-case email accepted -> 200",
            r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Section B: Invalid Email Formats  (RS.4 – RS.6)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportSignupInvalidEmail:
    """Malformed email values must return 400 { ok: false, error: 'invalid_email' }."""

    @pytest.mark.parametrize("bad_email,label", [
        ("notanemail",           "no @ symbol"),
        ("@nodomain.com",        "missing local part"),
        ("user@",                "missing domain"),
        ("user@domain",          "no TLD"),
        ("user @domain.com",     "space in local part"),
        ("user@domain .com",     "space in domain"),
        ("",                     "empty string"),
    ])
    def test_rs04_invalid_email_format_returns_400(self, bad_email, label):
        r = requests.post(SIGNUP_URL, json={"email": bad_email}, timeout=10)
        chk(f"RS.4  invalid email ({label}) -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    @pytest.mark.parametrize("bad_email,label", [
        ("notanemail", "no @"),
        ("@nodomain.com", "no local part"),
        ("user@", "no domain"),
    ])
    def test_rs05_invalid_email_body_error_is_invalid_email(self, bad_email, label):
        r = requests.post(SIGNUP_URL, json={"email": bad_email}, timeout=10)
        assert r.status_code == 400
        data = r.json()
        chk(f"RS.5  error == 'invalid_email' for {label!r}",
            data.get("error") == "invalid_email", f"body: {data}")
        assert data.get("error") == "invalid_email"

    @pytest.mark.parametrize("bad_email,label", [
        ("notanemail", "no @"),
        ("user@", "no domain"),
    ])
    def test_rs06_invalid_email_body_ok_false(self, bad_email, label):
        r = requests.post(SIGNUP_URL, json={"email": bad_email}, timeout=10)
        assert r.status_code == 400
        data = r.json()
        chk(f"RS.6  body.ok == false for {label!r}",
            data.get("ok") is False, f"body: {data}")
        assert data.get("ok") is False


# ═══════════════════════════════════════════════════════════════════════════════
#  Section C: Missing / Non-String Email Field  (RS.7 – RS.10)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportSignupMissingField:
    """Missing or wrong-type email must return 400 { ok: false, error: 'email_required' }."""

    def test_rs07_missing_email_field_returns_400(self):
        section("C --- Missing / Non-String Email")
        r = requests.post(SIGNUP_URL, json={}, timeout=10)
        chk("RS.7  missing email field -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_rs08_missing_email_body_error_is_email_required(self):
        r = requests.post(SIGNUP_URL, json={}, timeout=10)
        assert r.status_code == 400
        data = r.json()
        chk("RS.8  error == 'email_required' when field missing",
            data.get("error") == "email_required", f"body: {data}")
        assert data.get("error") == "email_required"

    @pytest.mark.parametrize("non_string_email,label", [
        (12345,      "integer"),
        (3.14,       "float"),
        (True,       "boolean"),
        (["a@b.com"], "array"),
        ({"v": "a@b.com"}, "object"),
        (None,       "null"),
    ])
    def test_rs09_non_string_email_type_returns_400(self, non_string_email, label):
        r = requests.post(SIGNUP_URL,
                          json={"email": non_string_email},
                          timeout=10)
        chk(f"RS.9  email as {label} -> 400",
            r.status_code == 400, f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 400

    def test_rs10_invalid_json_body_returns_400(self):
        r = requests.post(SIGNUP_URL,
                          data="not-json",
                          headers={"Content-Type": "application/json"},
                          timeout=10)
        chk("RS.10 invalid JSON body -> 400",
            r.status_code == 400, f"got {r.status_code}")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
#  Section D: Idempotency  (RS.11)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportSignupIdempotency:
    """Submitting the same email twice must return ok:true both times."""

    def test_rs11_same_email_twice_returns_ok_true_both_times(self):
        section("D --- Idempotency")
        email = _rand_email("rs11")

        r1 = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        chk("RS.11a first submission -> 200 ok:true",
            r1.status_code == 200 and r1.json().get("ok") is True,
            f"first: {r1.status_code} {r1.text[:80]}")
        assert r1.status_code == 200

        r2 = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        chk("RS.11b second (duplicate) submission -> 200 ok:true",
            r2.status_code == 200 and r2.json().get("ok") is True,
            f"second: {r2.status_code} {r2.text[:80]}")
        assert r2.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Section E: No Auth Required  (RS.12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportSignupNoAuth:
    """Endpoint is public — a valid request must succeed without any auth header."""

    def test_rs12_no_auth_header_succeeds(self):
        section("E --- No Auth Required")
        email = _rand_email("rs12")
        # Explicitly pass no Authorization header
        r = requests.post(SIGNUP_URL, json={"email": email}, timeout=10)
        chk("RS.12 public endpoint — no auth header -> 200 ok:true",
            r.status_code == 200 and r.json().get("ok") is True,
            f"got {r.status_code}: {r.text[:120]}")
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
#  Note: Rate-limit test (RS.13) is intentionally skipped.
#
#  The rate limit is enforced on CF-Connecting-IP which is set by Cloudflare's
#  edge network and cannot be controlled from external test clients. There is no
#  way to trigger the 5-per-hour limit reliably without Cloudflare forwarding
#  consecutive requests from the same IP within the same test run, which is
#  non-deterministic in CI. If you need to exercise this path, use a Cloudflare
#  Worker unit test with a mocked KV binding.
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skip(
    reason=(
        "CF-Connecting-IP is injected by Cloudflare edge and cannot be controlled "
        "from external test clients. Rate-limit behaviour requires 5 requests from "
        "the same IP within one hour — not reliably triggerable in CI without "
        "dedicated IP management. Test the rate-limit path via Worker unit tests."
    )
)
def test_rs13_rate_limit_sixth_request_returns_429():
    """6th POST from same IP within one hour must return 429 { ok: false, error: 'rate_limited' }."""
    email_base = _rand_email("rs13rl")
    for i in range(5):
        requests.post(SIGNUP_URL,
                      json={"email": f"{i}-{email_base}"},
                      timeout=10)
    r = requests.post(SIGNUP_URL,
                      json={"email": f"6th-{email_base}"},
                      timeout=10)
    assert r.status_code == 429
    data = r.json()
    assert data.get("ok") is False
    assert data.get("error") == "rate_limited"
