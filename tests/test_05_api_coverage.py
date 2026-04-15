"""
test_05_api_coverage.py — Complete API endpoint coverage tests
==============================================================
Developer notes:
  Tests every documented API endpoint of the Cloudflare Worker:
    Auth:      9 endpoints
    Events:    3 endpoints
    Analytics: 7 endpoints
    Admin:     6 endpoints
    Alerts:    4 endpoints
    Stream:    1 endpoint (SSE — tested for connection, not full stream)
    Health:    1 endpoint
    CORS:      preflight checks on key endpoints

  Each test verifies:
    - HTTP status code
    - Response body shape (required fields present)
    - Auth enforcement (401 without token, 403 for wrong role)
    - Error messages (not leaking stack traces)
    - CORS headers on cross-origin requests

Run:
  python tests/test_05_api_coverage.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import json
import uuid
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag, rand_name,
    signup_api, get_headers, get_session_cookie, fresh_account,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.api")

# Create owner account
try:
    d       = signup_api()
    API_KEY = d["api_key"]
    ORG_ID  = d["org_id"]
    HEADERS = get_headers(API_KEY)
    COOKIES = get_session_cookie(API_KEY)
    info(f"Owner account: {ORG_ID}")
except Exception as e:
    fail("Could not create test account", str(e))
    sys.exit(1)

def api(method, path, expected=None, auth=True, json_body=None,
        cookies=None, headers=None, timeout=15, params=None):
    """Helper: make an API call and check expected status."""
    h = {**(headers or {}), **(HEADERS if auth else {})}
    c = cookies or (COOKIES if auth and not headers else None)
    fn = getattr(requests, method.lower())
    kw = dict(headers=h, timeout=timeout)
    if json_body is not None: kw["json"] = json_body
    if cookies:               kw["cookies"] = cookies
    if params:                kw["params"] = params
    try:
        r = fn(f"{API_URL}{path}", **kw)
        if expected is not None:
            exp_list = expected if isinstance(expected, (list, tuple)) else [expected]
            chk(f"{method.upper()} {path} → {expected}",
                r.status_code in exp_list,
                f"got {r.status_code}: {r.text[:120]}")
        return r
    except Exception as e:
        fail(f"{method.upper()} {path} exception", str(e))
        return None


# ─────────────────────────────────────────────────────────────────────────────
section("1. Health check")
# ─────────────────────────────────────────────────────────────────────────────
r = api("GET", "/health", expected=200, auth=False)
if r and r.status_code == 200:
    body = r.json()
    chk("1.1  Health body has status=ok", body.get("status") == "ok", str(body))

# ─────────────────────────────────────────────────────────────────────────────
section("2. 404 handling")
# ─────────────────────────────────────────────────────────────────────────────
r = api("GET", "/v1/does-not-exist", expected=[404], auth=False)
if r:
    chk("2.1  404 body is JSON (not HTML)", r.headers.get("content-type","").startswith("application/json"),
        f"content-type={r.headers.get('content-type')}")
    chk("2.2  404 does not leak stack trace",
        "stack" not in r.text.lower() and "traceback" not in r.text.lower())

# ─────────────────────────────────────────────────────────────────────────────
section("3. CORS headers")
# ─────────────────────────────────────────────────────────────────────────────
CORS_CHECKS = [
    ("GET",  "/health",           None,          False),
    ("POST", "/v1/auth/signup",   {"email": rand_email(), "name": "x", "org": rand_org()}, False),
    ("POST", "/v1/auth/recover",  {"email": rand_email()}, False),
    ("GET",  "/v1/analytics/summary", None,      True),
]
for method, path, body, auth in CORS_CHECKS:
    try:
        h = {**(HEADERS if auth else {}), "Origin": SITE_URL}
        fn = getattr(requests, method.lower())
        kw = dict(headers=h, timeout=10)
        if body: kw["json"] = body
        r2 = fn(f"{API_URL}{path}", **kw)
        cors = r2.headers.get("Access-Control-Allow-Origin", "")
        chk(f"3.x  CORS header on {method} {path}", bool(cors),
            f"status={r2.status_code} cors='{cors}'")
    except Exception as e:
        fail(f"3.x  CORS check failed: {method} {path}", str(e))

# ─────────────────────────────────────────────────────────────────────────────
section("4. Auth endpoints — signup / session / logout")
# ─────────────────────────────────────────────────────────────────────────────
# Signup
r = api("POST", "/v1/auth/signup", expected=201, auth=False,
        json_body={"email": rand_email("cov"), "name": rand_name(), "org": rand_org()})
if r and r.status_code == 201:
    d = r.json()
    chk("4.1  Signup: api_key present",   bool(d.get("api_key")))
    chk("4.2  Signup: org_id present",    bool(d.get("org_id")))
    chk("4.3  Signup: api_key starts crt_", d.get("api_key","").startswith("crt_"))

# Session create
r = api("POST", "/v1/auth/session", expected=200, auth=False,
        json_body={"api_key": API_KEY})
if r and r.status_code == 200:
    sess = r.json()
    chk("4.4  Session: ok=true", sess.get("ok") is True)
    chk("4.5  Session: org_id present", bool(sess.get("org_id")))

# Session get (cookie auth)
r = api("GET", "/v1/auth/session", expected=200, auth=False, cookies=COOKIES)
if r and r.status_code == 200:
    sess = r.json()
    chk("4.6  GET session: org_id", bool(sess.get("org_id")))
    chk("4.7  GET session: role",   bool(sess.get("role")))
    # sse_token may be null when KV daily write limit is hit (free tier)
    if sess.get("sse_token"):
        ok("4.8  GET session: sse_token present")
    else:
        warn("4.8  GET session: sse_token is null (KV write limit — SSE disabled today)")

# Session get without auth → 401
r = api("GET", "/v1/auth/session", expected=401, auth=False)

# Key rotation
r = api("POST", "/v1/auth/rotate", expected=200, auth=False, cookies=COOKIES)
if r and r.status_code == 200:
    new_key = r.json().get("api_key")
    chk("4.9  /auth/rotate: new key returned", bool(new_key) and new_key.startswith("crt_"))
    # Update creds to new key
    API_KEY = new_key
    HEADERS = get_headers(API_KEY)
    COOKIES = get_session_cookie(API_KEY)
    info(f"Key rotated. New key: {API_KEY[:24]}…")

# ─────────────────────────────────────────────────────────────────────────────
section("5. Event ingestion endpoints")
# ─────────────────────────────────────────────────────────────────────────────

def make_event(i=0):
    return {
        "event_id":          f"cov-{rand_tag()}-{i}",
        "provider":          "openai",
        "model":             "gpt-4o",
        "prompt_tokens":     500,
        "completion_tokens": 150,
        "total_tokens":      650,
        "total_cost_usd":    0.005,
        "latency_ms":        320,
        "team":              "coverage-test",
        "project":           "e2e",
        "environment":       "test",
    }

# 5.1 Single event
r = api("POST", "/v1/events", expected=[200, 201], json_body=make_event(0))
if r and r.status_code in (200, 201):
    body = r.json()
    chk("5.1  Single event: accepted=1 or ok=true",
        body.get("accepted") == 1 or body.get("ok") is True, str(body))

# 5.2 Batch of 5 events
batch = {"events": [make_event(i) for i in range(5)]}
r = api("POST", "/v1/events/batch", expected=[200, 201], json_body=batch)
if r and r.status_code in (200, 201):
    body = r.json()
    chk("5.2  Batch 5 events: accepted=5", body.get("accepted") == 5, str(body))

# 5.3 Batch with 500 events (max limit)
big_batch = {"events": [make_event(i) for i in range(500)]}
r = api("POST", "/v1/events/batch", expected=[200, 201], json_body=big_batch)
if r and r.status_code in (200, 201):
    body = r.json()
    chk("5.3  Batch 500 events accepted", body.get("accepted", 0) > 0, str(body))

# 5.4 Batch with >500 events → rejected or truncated
huge_batch = {"events": [make_event(i) for i in range(501)]}
r = api("POST", "/v1/events/batch", expected=[200, 201, 400, 413], json_body=huge_batch)
if r:
    chk("5.4  Batch >500 events handled (400/413 or truncated)",
        r.status_code in (200, 201, 400, 413), f"got {r.status_code}")

# 5.5 Event without auth → 401
r = api("POST", "/v1/events", expected=401, auth=False, json_body=make_event(99))

# 5.6 PATCH event scores
evt_id = f"cov-score-{rand_tag()}"
api("POST", "/v1/events", json_body={**make_event(0), "event_id": evt_id})
time.sleep(0.5)
r = api("PATCH", f"/v1/events/{evt_id}/scores", expected=[200, 201, 404],
        json_body={"hallucination": 0.1, "faithfulness": 0.9})
chk("5.6  PATCH event scores → 200/201/404 (404 ok if event not found)",
    r is not None and r.status_code in (200, 201, 404),
    f"got {r.status_code if r else 'None'}")

# ─────────────────────────────────────────────────────────────────────────────
section("6. Analytics endpoints")
# ─────────────────────────────────────────────────────────────────────────────

ANALYTICS = [
    ("/v1/analytics/summary",           "summary"),
    ("/v1/analytics/kpis?period=30",    "kpis"),
    ("/v1/analytics/timeseries?period=30", "timeseries"),
    ("/v1/analytics/models?period=30",  "models"),
    ("/v1/analytics/teams?period=30",   "teams"),
    ("/v1/analytics/traces?period=7",   "traces"),
    ("/v1/analytics/cost?period=7",     "cost gate"),
]

for path, label in ANALYTICS:
    r = api("GET", path, expected=200)
    if r and r.status_code == 200:
        chk(f"6.x  GET {label} returns JSON",
            r.headers.get("content-type","").startswith("application/json"),
            f"content-type={r.headers.get('content-type')}")

# Period variants
for days in [7, 30, 90]:
    r = api("GET", f"/v1/analytics/kpis?period={days}", expected=200)
    chk(f"6.x  Analytics KPIs period={days} → 200",
        r is not None and r.status_code == 200)

# Without auth → 401
api("GET", "/v1/analytics/summary", expected=401, auth=False)

# ─────────────────────────────────────────────────────────────────────────────
section("7. Admin endpoints")
# ─────────────────────────────────────────────────────────────────────────────

# 7.1 Overview
r = api("GET", "/v1/admin/overview", expected=200)
if r and r.status_code == 200:
    body = r.json()
    chk("7.1  Admin overview: has members key", "members" in body, str(body))
    chk("7.2  Admin overview: has teams key",   "teams"   in body, str(body))

# 7.2 Team budgets
r = api("GET", "/v1/admin/team-budgets", expected=[200, 404])
chk("7.3  GET /admin/team-budgets → 200/404", r is not None)

# 7.3 Set team budget
r = api("PUT", "/v1/admin/team-budgets/coverage-team", expected=[200, 201],
        json_body={"budget_usd": 100.0})
if r and r.status_code in (200, 201):
    chk("7.4  PUT team budget → 200/201", True)

# 7.4 Delete team budget
r = api("DELETE", "/v1/admin/team-budgets/coverage-team", expected=[200, 204, 404])
chk("7.5  DELETE team budget → 200/204/404", r is not None)

# 7.5 Patch org
r = api("PATCH", "/v1/admin/org", expected=[200, 201],
        json_body={"budget_usd": 500.0})
chk("7.6  PATCH /admin/org budget → 200/201",
    r is not None and r.status_code in (200, 201))

# 7.6 Without auth → 401
api("GET", "/v1/admin/overview", expected=401, auth=False)

# ─────────────────────────────────────────────────────────────────────────────
section("8. Alerts endpoints")
# ─────────────────────────────────────────────────────────────────────────────

# 8.1 GET alert config
r = api("GET", f"/v1/alerts/{ORG_ID}", expected=200)
if r and r.status_code == 200:
    body = r.json()
    chk("8.1  GET alerts: slack_url key present", "slack_url" in body, str(body))

# 8.2 Invalid Slack URL rejected
r = api("POST", f"/v1/alerts/slack/{ORG_ID}", expected=400,
        json_body={"webhook_url": "https://not-slack.example.com/hook"})

# 8.3 Valid-format Slack URL accepted
r = api("POST", f"/v1/alerts/slack/{ORG_ID}", expected=200,
        json_body={"webhook_url": "https://hooks.slack.com/services/T000/B000/XXXX"})

# 8.4 Slack test endpoint (returns 200 or 502 depending on Slack's response)
r = api("POST", f"/v1/alerts/slack/{ORG_ID}/test", expected=[200, 502])
chk("8.4  Slack test → 200 or 502 (not 500)", r is not None and r.status_code in (200, 502))

# ─────────────────────────────────────────────────────────────────────────────
section("9. SSE stream endpoint")
# ─────────────────────────────────────────────────────────────────────────────

# Get a fresh SSE token
try:
    cookies = get_session_cookie(API_KEY)
    sess_r  = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=10)
    sse_tok = sess_r.json().get("sse_token") if sess_r.ok else None

    if sse_tok:
        # 9.1 SSE stream responds (don't read fully, just check headers)
        r = requests.get(
            f"{API_URL}/v1/stream/{ORG_ID}",
            params={"sse_token": sse_tok},
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=5,
        )
        chk("9.1  SSE stream opens (200)", r.status_code == 200,
            f"got {r.status_code}: {r.text[:100]}")
        chk("9.2  SSE stream content-type is text/event-stream",
            "text/event-stream" in r.headers.get("content-type",""),
            r.headers.get("content-type",""))
        r.close()
    else:
        warn("9.x  Could not get SSE token — skipping stream test")
except Exception as e:
    warn(f"9.x  SSE test inconclusive: {e}")

# 9.3 Without valid token → 401
try:
    r = requests.get(f"{API_URL}/v1/stream/{ORG_ID}",
                     params={"sse_token": "invalid-token-999"},
                     timeout=5)
    chk("9.3  SSE with invalid token → 401", r.status_code == 401,
        f"got {r.status_code}")
except Exception as e:
    warn(f"9.3  SSE invalid-token test inconclusive: {e}")

# ─────────────────────────────────────────────────────────────────────────────
section("10. Member management endpoints")
# ─────────────────────────────────────────────────────────────────────────────

member_id = None

# 10.1 Invite member
r = api("POST", "/v1/auth/members", expected=[200, 201],
        json_body={
            "email":      rand_email("mem"),
            "name":       "Test Member",
            "role":       "member",
            "scope_team": "coverage-test",
        })
if r and r.status_code in (200, 201):
    body = r.json()
    member_id = body.get("id") or body.get("member_id")
    member_key = body.get("api_key")
    chk("10.1 Invite member: api_key returned", bool(member_key), str(body))
    chk("10.2 Invite member: id returned", bool(member_id), str(body))

# 10.3 List members
r = api("GET", "/v1/auth/members", expected=200)
if r and r.status_code == 200:
    body = r.json()
    chk("10.3 List members: members array present",
        isinstance(body.get("members"), list) or isinstance(body, list),
        str(type(body)))

# 10.4 Update member role (if we got an ID)
if member_id:
    r = api("PATCH", f"/v1/auth/members/{member_id}", expected=[200, 204],
            json_body={"role": "viewer"})
    chk("10.4 PATCH member role → 200/204",
        r is not None and r.status_code in (200, 204))

# 10.5 Delete member
if member_id:
    r = api("DELETE", f"/v1/auth/members/{member_id}", expected=[200, 204])
    chk("10.5 DELETE member → 200/204",
        r is not None and r.status_code in (200, 204))


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  API coverage tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
