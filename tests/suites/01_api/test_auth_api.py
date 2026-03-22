"""
test_auth_api.py — Auth API endpoint tests
===========================================
Suite 1: Tests all authentication API endpoints.
Labels: 1.1 - 1.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import signup_api, get_headers, get_session_cookie, session_get, fresh_account
from helpers.data import rand_email, rand_org, rand_name, rand_tag
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_signup():
    section("1. Auth API — Signup")

    # 1.1 Valid signup returns 201 + api_key + org_id
    email = rand_email("api1")
    org   = rand_org("api1")
    name  = rand_name()
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": email, "name": name, "org": org}, timeout=15)
    chk("1.1  POST /signup → 201", r.status_code == 201,
        f"got {r.status_code}: {r.text[:100]}")

    if r.status_code == 201:
        d = r.json()
        chk("1.2  Response has api_key", "api_key" in d)
        chk("1.3  Response has org_id",  "org_id"  in d)
        chk("1.4  api_key starts with vnt_", d.get("api_key", "").startswith("vnt_"),
            f"got: {d.get('api_key', '')[:10]}")
        chk("1.5  Response has hint",    "hint" in d)
        api_key = d["api_key"]
    else:
        fail("1.2  Skipping downstream signup checks (signup failed)")
        fail("1.3  Skipping")
        fail("1.4  Skipping")
        fail("1.5  Skipping")
        api_key = None

    # 1.6 Duplicate email → 409
    if api_key:
        r2 = requests.post(f"{API_URL}/v1/auth/signup",
                           json={"email": email, "name": rand_name(), "org": rand_org()},
                           timeout=15)
        chk("1.6  Duplicate email → 409", r2.status_code == 409,
            f"got {r2.status_code}")

    # 1.7 Missing fields → 400
    r3 = requests.post(f"{API_URL}/v1/auth/signup", json={}, timeout=15)
    chk("1.7  Missing fields → 400", r3.status_code == 400,
        f"got {r3.status_code}")

    # 1.8 Missing email → 400
    r4 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"name": rand_name(), "org": rand_org()}, timeout=15)
    chk("1.8  Missing email → 400", r4.status_code == 400,
        f"got {r4.status_code}")

    return api_key


def test_session(api_key):
    section("1. Auth API — Session")

    # 1.9 POST /session with valid key → 200 + cookie
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": api_key}, timeout=15)
    chk("1.9  POST /session valid key → 200", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")
    chk("1.10 POST /session sets cookie", bool(r.cookies), f"cookies: {dict(r.cookies)}")
    cookies = r.cookies if r.ok else None

    # 1.11 POST /session with invalid key → 401
    r2 = requests.post(f"{API_URL}/v1/auth/session",
                       json={"api_key": "vnt_invalidkey123"}, timeout=15)
    chk("1.11 POST /session invalid key → 401", r2.status_code == 401,
        f"got {r2.status_code}")

    # 1.12 GET /session with valid cookie → 200 + org_id
    if cookies:
        r3 = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
        chk("1.12 GET /session with cookie → 200", r3.status_code == 200,
            f"got {r3.status_code}")
        if r3.ok:
            sd = r3.json()
            chk("1.13 GET /session returns org_id", "org_id" in sd)
            chk("1.14 GET /session returns email", "email" in sd)
    else:
        fail("1.12 GET /session — no cookies available")
        fail("1.13 Skipping")
        fail("1.14 Skipping")
        cookies = None

    # 1.15 GET /session without cookie → 401
    r4 = requests.get(f"{API_URL}/v1/auth/session", timeout=15)
    chk("1.15 GET /session no cookie → 401", r4.status_code == 401,
        f"got {r4.status_code}")

    return cookies


def test_logout(api_key, cookies):
    section("1. Auth API — Logout")

    if not cookies:
        warn("1.16 Skipping logout tests — no cookies")
        return

    # 1.16 POST /logout clears session
    r = requests.post(f"{API_URL}/v1/auth/logout", cookies=cookies, timeout=15)
    chk("1.16 POST /logout → 200", r.status_code == 200,
        f"got {r.status_code}")

    # 1.17 After logout, GET /session → 401
    r2 = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
    chk("1.17 After logout GET /session → 401", r2.status_code == 401,
        f"got {r2.status_code}")


def test_rotate(api_key):
    section("1. Auth API — Key Rotation")

    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.post(f"{API_URL}/v1/auth/rotate", headers=headers, timeout=15)
    chk("1.18 POST /rotate → 200", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    if r.ok:
        d = r.json()
        new_key = d.get("api_key") or d.get("new_key") or d.get("key")
        chk("1.19 POST /rotate returns new key", bool(new_key),
            f"response: {d}")
        if new_key:
            chk("1.20 New key starts with vnt_", new_key.startswith("vnt_"),
                f"got: {new_key[:10]}")
            # New key should work for session
            r2 = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": new_key}, timeout=15)
            chk("1.21 New rotated key works for session", r2.status_code == 200,
                f"got {r2.status_code}")
    else:
        fail("1.19 POST /rotate failed — skipping downstream checks")
        fail("1.20 Skipping")
        fail("1.21 Skipping")


def test_recovery(api_key):
    section("1. Auth API — Key Recovery")

    # 1.22 POST /recover with valid email → 200 (always, even if email unknown)
    r = requests.post(f"{API_URL}/v1/auth/recover",
                      json={"email": rand_email("recover-test")}, timeout=15)
    chk("1.22 POST /recover unknown email → 200", r.status_code == 200,
        f"got {r.status_code}")

    # 1.23 POST /recover with missing email → 400
    r2 = requests.post(f"{API_URL}/v1/auth/recover", json={}, timeout=15)
    chk("1.23 POST /recover missing email → 400", r2.status_code in (400, 422),
        f"got {r2.status_code}")

    # 1.24 GET /recover/redeem with missing token → 400
    r3 = requests.get(f"{API_URL}/v1/auth/recover/redeem",
                      headers={"Accept": "application/json"}, timeout=15, allow_redirects=False)
    chk("1.24 GET /recover/redeem no token → 400/404", r3.status_code in (400, 404, 422),
        f"got {r3.status_code}")

    # 1.25 GET /recover/redeem with fake token → 400/404
    r4 = requests.get(f"{API_URL}/v1/auth/recover/redeem?token=fakeinvalidtoken123",
                      headers={"Accept": "application/json"}, timeout=15, allow_redirects=False)
    chk("1.25 GET /recover/redeem fake token → 400/404", r4.status_code in (400, 404, 410),
        f"got {r4.status_code}")


def main():
    section("Suite 1 — Auth API Tests")
    info(f"API: {API_URL}")

    api_key = test_signup()
    if not api_key:
        fail("Cannot continue without valid api_key from signup")
        sys.exit(1)

    cookies = test_session(api_key)
    test_logout(api_key, cookies)

    # Create fresh account for rotation test (logout may have invalidated session)
    try:
        fresh = signup_api()
        test_rotate(fresh["api_key"])
        test_recovery(fresh["api_key"])
    except Exception as e:
        fail(f"Could not create fresh account for rotation/recovery tests: {e}")

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
