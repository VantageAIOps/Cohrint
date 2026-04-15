"""
test_signin.py — Individual user sign-in tests
===============================================
Suite SI: Tests session creation, cookie handling, logout, and auth errors.
Labels: SI.1 - SI.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_session_create(api_key):
    section("SI. Sign-in — Session Creation")

    # SI.1 POST /session valid key → 200
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": api_key}, timeout=15)
    chk("SI.1  POST /session valid key → 200", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")
    chk("SI.2  POST /session sets cookie", bool(r.cookies),
        f"cookies: {dict(r.cookies)}")

    cookies = r.cookies if r.ok else None
    return cookies


def test_session_get(api_key, cookies):
    section("SI. Sign-in — Session Read")

    if not cookies:
        fail("SI.3  No cookies — skipping session read tests")
        fail("SI.4  Skipping")
        fail("SI.5  Skipping")
        return

    # SI.3 GET /session → 200 + data
    r = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
    chk("SI.3  GET /session with cookie → 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        chk("SI.4  GET /session returns api_key_hint", "hint" in d or "api_key_hint" in d,
            f"keys: {list(d.keys())}")
        chk("SI.5  GET /session returns org_id", "org_id" in d,
            f"keys: {list(d.keys())}")
        chk("SI.6  GET /session returns email", "email" in d,
            f"keys: {list(d.keys())}")

        # SI.7 hint is not the full key
        hint = d.get("hint") or d.get("api_key_hint", "")
        chk("SI.7  Session hint is not full api_key", hint != api_key,
            "hint should be partial/masked, not full key")
    else:
        fail("SI.4  Skipping (GET /session failed)")
        fail("SI.5  Skipping")
        fail("SI.6  Skipping")
        fail("SI.7  Skipping")


def test_auth_errors():
    section("SI. Sign-in — Auth Errors")

    # SI.8 Wrong key → 401
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": "crt_wrongkey_abc123xyz"}, timeout=15)
    chk("SI.8  Wrong key → 401", r.status_code == 401, f"got {r.status_code}")

    # SI.9 Empty key → 401 or 400
    r2 = requests.post(f"{API_URL}/v1/auth/session",
                       json={"api_key": ""}, timeout=15)
    chk("SI.9  Empty key → 400/401", r2.status_code in (400, 401),
        f"got {r2.status_code}")

    # SI.10 Missing key field → 400/401
    r3 = requests.post(f"{API_URL}/v1/auth/session", json={}, timeout=15)
    chk("SI.10 Missing key field → 400/401", r3.status_code in (400, 401),
        f"got {r3.status_code}")

    # SI.11 Malformed bearer → 401
    r4 = requests.get(f"{API_URL}/v1/auth/session",
                      headers={"Authorization": "Bearer not_a_real_key"}, timeout=15)
    chk("SI.11 GET /session malformed bearer → 401", r4.status_code == 401,
        f"got {r4.status_code}")

    # SI.12 No cookie, no auth → 401
    r5 = requests.get(f"{API_URL}/v1/auth/session", timeout=15)
    chk("SI.12 GET /session no auth → 401", r5.status_code == 401,
        f"got {r5.status_code}")


def test_logout(api_key):
    section("SI. Sign-in — Logout")

    # Get fresh cookies
    cookies = get_session_cookie(api_key)
    if not cookies:
        fail("SI.13 Could not get session cookie for logout test")
        fail("SI.14 Skipping")
        fail("SI.15 Skipping")
        return

    # SI.13 POST /logout → 200
    r = requests.post(f"{API_URL}/v1/auth/logout", cookies=cookies, timeout=15)
    chk("SI.13 POST /logout → 200", r.status_code == 200, f"got {r.status_code}")

    # SI.14 After logout, GET /session → 401
    r2 = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
    chk("SI.14 After logout GET /session → 401", r2.status_code == 401,
        f"got {r2.status_code}")

    # SI.15 Can sign in again after logout
    r3 = requests.post(f"{API_URL}/v1/auth/session",
                       json={"api_key": api_key}, timeout=15)
    chk("SI.15 Can sign in again after logout", r3.status_code == 200,
        f"got {r3.status_code}")


def main():
    section("Suite SI — Individual User Sign-in Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    cookies = test_session_create(api_key)
    test_session_get(api_key, cookies)
    test_auth_errors()
    test_logout(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
