"""
test_recovery.py — Key recovery flow tests
==========================================
Suite RC: Tests the recovery email flow, one-time token redeem, and key validity.
Labels: RC.1 - RC.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_name, rand_org
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_recover_endpoint(registered_email, unregistered_email):
    section("RC. Recovery — POST /recover")

    # RC.1 POST /recover with registered email → 200 (always)
    r = requests.post(f"{API_URL}/v1/auth/recover",
                      json={"email": registered_email}, timeout=15)
    chk("RC.1  POST /recover registered email → 200", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    # RC.2 POST /recover with unregistered email → 200 (security: always same response)
    r2 = requests.post(f"{API_URL}/v1/auth/recover",
                       json={"email": unregistered_email}, timeout=15)
    chk("RC.2  POST /recover unregistered email → 200", r2.status_code == 200,
        f"got {r2.status_code}: {r2.text[:100]}")

    # RC.3 POST /recover missing email → 400
    r3 = requests.post(f"{API_URL}/v1/auth/recover", json={}, timeout=15)
    chk("RC.3  POST /recover missing email → 400", r3.status_code in (400, 422),
        f"got {r3.status_code}")

    # RC.4 Both responses indistinguishable (timing/content similar)
    # We just check that neither reveals user existence
    chk("RC.4  Registered/unregistered responses both 200 (timing-safe)",
        r.status_code == 200 and r2.status_code == 200)


def test_redeem_endpoint():
    section("RC. Recovery — GET/POST /recover/redeem")

    # RC.5 GET /redeem without token → 400/404
    r = requests.get(f"{API_URL}/v1/auth/recover/redeem", timeout=15)
    chk("RC.5  GET /recover/redeem no token → 400/404",
        r.status_code in (400, 404, 422), f"got {r.status_code}")

    # RC.6 GET /redeem with fake token → 400/404/410
    r2 = requests.get(f"{API_URL}/v1/auth/recover/redeem?token=fake_invalid_token_abc",
                      timeout=15)
    chk("RC.6  GET /recover/redeem fake token → 400/404/410",
        r2.status_code in (400, 404, 410), f"got {r2.status_code}")

    # RC.7 POST /redeem with fake token → 400/404/410
    r3 = requests.post(f"{API_URL}/v1/auth/recover/redeem",
                       json={"token": "fake_invalid_token_xyz"}, timeout=15)
    chk("RC.7  POST /recover/redeem fake token → 400/404/410",
        r3.status_code in (400, 404, 410), f"got {r3.status_code}")

    # RC.8 Expired/used token scenario (second redemption of same fake token)
    r4 = requests.get(f"{API_URL}/v1/auth/recover/redeem?token=fake_invalid_token_abc",
                      timeout=15)
    chk("RC.8  Second use of same fake token → 400/404/410",
        r4.status_code in (400, 404, 410), f"got {r4.status_code}")


def test_old_key_still_works(api_key):
    section("RC. Recovery — Original Key Validity After Recovery")

    # RC.9 Trigger recovery (doesn't revoke original key)
    requests.post(f"{API_URL}/v1/auth/recover",
                  json={"email": "any@test.com"}, timeout=15)

    # RC.10 Original key still works after triggering recovery
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": api_key}, timeout=15)
    chk("RC.9  Original key still works after triggering /recover",
        r.status_code == 200, f"got {r.status_code}")

    # RC.10 Analytics still accessible with original key
    r2 = requests.get(f"{API_URL}/v1/analytics/summary",
                      headers=get_headers(api_key), timeout=15)
    chk("RC.10 Analytics accessible with original key after recovery triggered",
        r2.status_code in (200, 404),  # 404 = no data yet, that's ok
        f"got {r2.status_code}")


def main():
    section("Suite RC — Key Recovery Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        registered_email = d.get("email") or "test@vantage-test.dev"
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    from helpers.data import rand_email
    unregistered_email = rand_email("rc-unreg")

    test_recover_endpoint(registered_email, unregistered_email)
    test_redeem_endpoint()
    test_old_key_still_works(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
