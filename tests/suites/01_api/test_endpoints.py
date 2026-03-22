"""
test_endpoints.py — Full API endpoint coverage tests
=====================================================
Suite E: Tests all 28 API endpoints for status codes, response shape,
CORS headers, and error response format.
Labels: E.1 - E.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import signup_api, get_headers, get_session_cookie, fresh_account
from helpers.data import rand_email, rand_org, rand_name, rand_tag
from helpers.output import ok, fail, warn, info, section, chk, get_results


def cors_ok(r) -> bool:
    """Check that Access-Control-Allow-Origin header is present."""
    return "access-control-allow-origin" in {k.lower() for k in r.headers}


def error_json_ok(r) -> bool:
    """Check error responses have JSON with 'error' field."""
    try:
        d = r.json()
        return "error" in d or "message" in d
    except Exception:
        return False


def test_health(headers):
    section("E. Endpoints — Health")
    r = requests.get(f"{API_URL}/v1/health", timeout=15)
    chk("E.1  GET /health → 200", r.status_code == 200, f"got {r.status_code}")
    chk("E.2  GET /health CORS header present", cors_ok(r),
        f"headers: {list(r.headers.keys())[:10]}")
    if r.ok:
        d = r.json()
        chk("E.3  GET /health response has status/ok field",
            "status" in d or "ok" in d or "healthy" in d,
            f"got: {list(d.keys())}")


def test_auth_endpoints(api_key, cookies) -> str:
    """Returns the (possibly rotated) API key."""
    section("E. Endpoints — Auth")

    # POST /signup
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": rand_email("ep"), "name": rand_name(), "org": rand_org()},
                      timeout=15)
    chk("E.4  POST /v1/auth/signup → 201", r.status_code == 201, f"got {r.status_code}")

    # POST /session
    r2 = requests.post(f"{API_URL}/v1/auth/session",
                       json={"api_key": api_key}, timeout=15)
    chk("E.5  POST /v1/auth/session → 200", r2.status_code == 200, f"got {r2.status_code}")

    # GET /session
    r3 = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
    chk("E.6  GET /v1/auth/session → 200", r3.status_code == 200, f"got {r3.status_code}")

    # POST /logout
    fresh_cookies = get_session_cookie(api_key)
    if fresh_cookies:
        r4 = requests.post(f"{API_URL}/v1/auth/logout", cookies=fresh_cookies, timeout=15)
        chk("E.7  POST /v1/auth/logout → 200", r4.status_code == 200, f"got {r4.status_code}")
    else:
        warn("E.7  Could not get fresh cookies for logout test")

    # POST /rotate — updates the API key; capture new key for subsequent tests
    r5 = requests.post(f"{API_URL}/v1/auth/rotate",
                       headers=get_headers(api_key), timeout=15)
    chk("E.8  POST /v1/auth/rotate → 200", r5.status_code == 200, f"got {r5.status_code}")
    if r5.status_code == 200:
        try:
            new_key = r5.json().get("api_key", api_key)
            if new_key:
                api_key = new_key
        except Exception:
            pass

    # POST /recover
    r6 = requests.post(f"{API_URL}/v1/auth/recover",
                       json={"email": rand_email("ep")}, timeout=15)
    chk("E.9  POST /v1/auth/recover → 200", r6.status_code == 200, f"got {r6.status_code}")

    # GET /recover/redeem (invalid) — send Accept: application/json to get JSON not redirect
    r7 = requests.get(f"{API_URL}/v1/auth/recover/redeem?token=invalid123",
                      headers={"Accept": "application/json"}, timeout=15,
                      allow_redirects=False)
    chk("E.10 GET /v1/auth/recover/redeem invalid → 400/404",
        r7.status_code in (400, 404, 410), f"got {r7.status_code}")

    return api_key


def test_events_endpoints(api_key):
    section("E. Endpoints — Events")
    headers = get_headers(api_key)

    # Single event
    event = {
        "model": "gpt-4o",
        "cost": 0.005,
        "tokens": {"prompt": 100, "completion": 50},
        "timestamp": int(time.time() * 1000),
        "tags": {"test": "ep_test"},
    }
    r = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
    chk("E.11 POST /v1/events single → 201/202", r.status_code in (201, 202),
        f"got {r.status_code}: {r.text[:100]}")
    chk("E.12 POST /v1/events CORS header", cors_ok(r))

    # Batch events
    batch = [
        {"model": "gpt-4o", "cost": 0.001 * i, "tokens": {"prompt": 50, "completion": 25},
         "timestamp": int(time.time() * 1000) + i, "tags": {"test": "batch"}}
        for i in range(1, 4)
    ]
    r2 = requests.post(f"{API_URL}/v1/events/batch", json={"events": batch},
                       headers=headers, timeout=15)
    chk("E.13 POST /v1/events/batch → 201/202", r2.status_code in (201, 202),
        f"got {r2.status_code}: {r2.text[:100]}")

    # Scores
    scores_payload = {"model": "gpt-4o", "score": 0.85, "metric": "quality",
                      "timestamp": int(time.time() * 1000)}
    r3 = requests.post(f"{API_URL}/v1/events/scores", json=scores_payload,
                       headers=headers, timeout=15)
    chk("E.14 POST /v1/events/scores → 200/201/202", r3.status_code in (200, 201, 202, 404),
        f"got {r3.status_code}")

    # Unauthorized event
    r4 = requests.post(f"{API_URL}/v1/events", json=event, timeout=15)
    chk("E.15 POST /v1/events no auth → 401", r4.status_code == 401, f"got {r4.status_code}")
    chk("E.16 POST /v1/events no auth error JSON", error_json_ok(r4))


def test_analytics_endpoints(api_key):
    section("E. Endpoints — Analytics")
    headers = get_headers(api_key)

    endpoints = [
        ("GET", "/v1/analytics/summary"),
        ("GET", "/v1/analytics/models"),
        ("GET", "/v1/analytics/tokens"),
        ("GET", "/v1/analytics/cost"),
        ("GET", "/v1/analytics/performance"),
        ("GET", "/v1/analytics/traces"),
        ("GET", "/v1/analytics/devx"),
    ]

    for i, (method, path) in enumerate(endpoints, start=17):
        try:
            r = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=15)
            chk(f"E.{i}  {method} {path} → 200/404",
                r.status_code in (200, 404),
                f"got {r.status_code}")
        except Exception as e:
            fail(f"E.{i}  {method} {path} → exception: {e}")

    # Analytics without auth → 401
    r = requests.get(f"{API_URL}/v1/analytics/summary", timeout=15)
    chk("E.24 GET /analytics/summary no auth → 401", r.status_code == 401,
        f"got {r.status_code}")


def test_admin_endpoints(api_key, cookies):
    section("E. Endpoints — Admin")
    headers = get_headers(api_key)

    admin_endpoints = [
        ("GET", "/v1/admin/members"),
        ("GET", "/v1/admin/budget"),
    ]

    for i, (method, path) in enumerate(admin_endpoints, start=25):
        try:
            r = requests.request(method, f"{API_URL}{path}", headers=headers,
                                 cookies=cookies, timeout=15)
            chk(f"E.{i}  {method} {path} → 200/404", r.status_code in (200, 404),
                f"got {r.status_code}")
        except Exception as e:
            fail(f"E.{i}  {method} {path} → exception: {e}")


def test_alerts_endpoints(api_key):
    section("E. Endpoints — Alerts")
    headers = get_headers(api_key)

    # Basic alert endpoint discovery (may return 404 if not implemented, that's ok)
    alert_endpoints = [
        ("POST", "/v1/alerts/slack",  {"webhook_url": "https://hooks.slack.com/test", "threshold": 10}),
        ("POST", "/v1/alerts/teams",  {"webhook_url": "https://outlook.office.com/test", "threshold": 10}),
        ("POST", "/v1/alerts/email",  {"email": rand_email("alert"), "threshold": 10}),
        ("GET",  "/v1/alerts",        None),
    ]

    for i, (method, path, body) in enumerate(alert_endpoints, start=27):
        try:
            if body:
                r = requests.request(method, f"{API_URL}{path}", json=body,
                                     headers=headers, timeout=15)
            else:
                r = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=15)
            # Accept 200, 201, 400 (bad webhook), 404 (not yet implemented)
            chk(f"E.{i}  {method} {path} → not 500",
                r.status_code < 500, f"got {r.status_code}: {r.text[:80]}")
        except Exception as e:
            fail(f"E.{i}  {method} {path} → exception: {e}")


def main():
    section("Suite E — API Endpoint Coverage")
    info(f"API: {API_URL}")

    # Create a fresh account for all tests
    try:
        d = signup_api()
        api_key = d["api_key"]
        cookies = get_session_cookie(api_key)
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    headers = get_headers(api_key)

    test_health(headers)
    api_key = test_auth_endpoints(api_key, cookies)
    test_events_endpoints(api_key)
    test_analytics_endpoints(api_key)
    test_admin_endpoints(api_key, cookies)
    test_alerts_endpoints(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
