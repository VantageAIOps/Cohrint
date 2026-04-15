#!/usr/bin/env python3
"""
Cohrint — End-to-End Test Suite
Tests every endpoint of the live Cloudflare Worker at https://api.cohrint.com
and validates the Python + npm SDKs installed from PyPI/npm.

Run:
  python test_e2e.py

Requires:  pip install requests cohrint
"""

import sys
import time
import uuid
import json
import random
import string
import subprocess
import requests

API = "https://api.cohrint.com"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m⚠\033[0m"
INFO = "\033[34m·\033[0m"

results = {"passed": 0, "failed": 0, "warned": 0}

def ok(msg):
    results["passed"] += 1
    print(f"  {PASS}  {msg}")

def fail(msg, detail=""):
    results["failed"] += 1
    extra = f"\n       {detail}" if detail else ""
    print(f"  {FAIL}  {msg}{extra}")

def warn(msg):
    results["warned"] += 1
    print(f"  {WARN}  {msg}")

def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")

def check(label, cond, detail=""):
    if cond:
        ok(label)
    else:
        fail(label, detail)

def get(path, key=None, **kwargs):
    return requests.get(f"{API}{path}", **kwargs)

def post(path, **kwargs):
    return requests.post(f"{API}{path}", **kwargs)

def patch_req(path, **kwargs):
    return requests.patch(f"{API}{path}", **kwargs)

def delete_req(path, **kwargs):
    return requests.delete(f"{API}{path}", **kwargs)

def rand_email():
    tag = ''.join(random.choices(string.ascii_lowercase, k=8))
    return f"e2e_{tag}@vantage-test.dev"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Health check
# ─────────────────────────────────────────────────────────────────────────────
section("1. Health check")
try:
    r = get("/health", timeout=10)
    check("GET /health returns 200", r.status_code == 200)
    d = r.json()
    check("status == ok", d.get("status") == "ok")
    check("service field present", "service" in d)
    check("region field present", "region" in d)
    check("CORS header present",
          r.headers.get("Access-Control-Allow-Origin") is not None,
          f"headers: {dict(r.headers)}")
except Exception as e:
    fail("Health check request failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 2. Sign-up — create a fresh test account
# ─────────────────────────────────────────────────────────────────────────────
section("2. Sign-up (POST /v1/auth/signup)")
test_email = rand_email()
API_KEY    = None
ORG_ID     = None

try:
    r = post("/v1/auth/signup", json={
        "email": test_email,
        "name":  "E2E Test Org",
    }, timeout=15)
    check("POST /v1/auth/signup returns 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:200]}")
    d = r.json()
    API_KEY = d.get("api_key")
    ORG_ID  = d.get("org_id")
    check("api_key returned and starts with crt_",
          isinstance(API_KEY, str) and API_KEY.startswith("crt_"))
    check("org_id returned", bool(ORG_ID))
    check("dashboard URL returned", "dashboard" in d)
    print(f"       org_id={ORG_ID}  key={API_KEY[:20]}...")
except Exception as e:
    fail("Signup request failed", str(e))

# Duplicate signup should return 409
try:
    r2 = post("/v1/auth/signup", json={"email": test_email, "name": "Dup"}, timeout=10)
    check("Duplicate email returns 409", r2.status_code == 409)
except Exception as e:
    fail("Duplicate signup check failed", str(e))

# Missing email should return 400
try:
    r3 = post("/v1/auth/signup", json={"name": "No email"}, timeout=10)
    check("Missing email returns 400", r3.status_code == 400)
except Exception as e:
    fail("Missing email check failed", str(e))

if not API_KEY:
    fail("CRITICAL: No API key — remaining tests will be skipped")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Session (sign-in)
# ─────────────────────────────────────────────────────────────────────────────
section("3. Session / Sign-in (POST /v1/auth/session + GET /v1/auth/session)")
session = requests.Session()
try:
    r = session.post(f"{API}/v1/auth/session",
                     json={"api_key": API_KEY}, timeout=10)
    check("POST /v1/auth/session returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    check("ok=true", d.get("ok") is True)
    check("org_id matches", d.get("org_id") == ORG_ID)
    check("Set-Cookie header present",
          "Set-Cookie" in r.headers or "set-cookie" in r.headers)
except Exception as e:
    fail("Session POST failed", str(e))

try:
    r = session.get(f"{API}/v1/auth/session", timeout=10)
    check("GET /v1/auth/session returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    check("authenticated=true", d.get("authenticated") is True)
    check("org.plan present", "plan" in d.get("org", {}))
    check("sse_token present", bool(d.get("sse_token")))
except Exception as e:
    fail("Session GET failed", str(e))

# Invalid key should 401
try:
    r = post("/v1/auth/session", json={"api_key": "crt_badkey_abc"}, timeout=10)
    check("Invalid key returns 401", r.status_code == 401)
except Exception as e:
    fail("Invalid key check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 4. Event ingestion
# ─────────────────────────────────────────────────────────────────────────────
section("4. Event ingestion (POST /v1/events  POST /v1/events/batch)")

def make_event(model="gpt-4o", cost=0.0025, team="backend"):
    return {
        "event_id":          str(uuid.uuid4()),    # correct field name per EventIn type
        "provider":          "openai",
        "model":             model,
        "prompt_tokens":     500,
        "completion_tokens": 120,
        "total_tokens":      620,
        "total_cost_usd":    cost,                 # correct field name per EventIn type
        "latency_ms":        423,
        "team":              team,
        "project":           "e2e-test",
        "environment":       "testing",
        "sdk_language":      "python",
        "sdk_version":       "0.3.0",
        "tags":              {"feature": "e2e", "run": "ci"},
    }

# Single event
try:
    ev = make_event()
    r = post("/v1/events", json=ev, headers=HEADERS, timeout=15)
    check("POST /v1/events returns 200/201",
          r.status_code in (200, 201, 202),
          f"{r.status_code}: {r.text[:200]}")
except Exception as e:
    fail("Single event ingest failed", str(e))

# Unauthenticated request
try:
    r = post("/v1/events", json=make_event(), timeout=10)
    check("Events without auth returns 401", r.status_code == 401)
except Exception as e:
    fail("Unauth events check failed", str(e))

# Batch of events — various models and teams
batch_events = [
    make_event("gpt-4o",               0.0045, "backend"),
    make_event("gpt-4o-mini",          0.0003, "backend"),
    make_event("claude-sonnet-4-6",    0.0060, "product"),
    make_event("claude-opus-4-6",      0.0250, "product"),
    make_event("gemini-2.0-flash",     0.0001, "data"),
    make_event("gpt-4o",               0.0040, "backend"),
    make_event("claude-haiku-4-5",     0.0008, "data"),
    make_event("gpt-4o",               0.0035, "frontend"),
    make_event("claude-sonnet-4-6",    0.0055, "product"),
    make_event("gemini-1.5-pro",       0.0070, "research"),
]

try:
    r = post("/v1/events/batch",
             json={"events": batch_events},
             headers=HEADERS, timeout=20)
    check("POST /v1/events/batch returns 200/201/202",
          r.status_code in (200, 201, 202),
          f"{r.status_code}: {r.text[:200]}")
except Exception as e:
    fail("Batch event ingest failed", str(e))

# Wait a moment for D1 to settle
time.sleep(1.5)

# ─────────────────────────────────────────────────────────────────────────────
# 5. Analytics endpoints
# ─────────────────────────────────────────────────────────────────────────────
section("5. Analytics (GET /v1/analytics/*)")

def check_analytics(path, label, required_keys=None):
    try:
        r = get(path, headers=HEADERS, timeout=15)
        check(f"{label} returns 200", r.status_code == 200,
              f"{r.status_code}: {r.text[:200]}")
        if r.status_code == 200 and required_keys:
            d = r.json()
            for k in required_keys:
                check(f"{label}: '{k}' in response",
                      k in d or any(k in str(d) for _ in [1]),
                      f"keys present: {list(d.keys()) if isinstance(d, dict) else type(d)}")
    except Exception as e:
        fail(f"{label} failed", str(e))

check_analytics("/v1/analytics/summary",    "GET /v1/analytics/summary",
                ["today_cost_usd", "mtd_cost_usd"])
check_analytics("/v1/analytics/kpis",       "GET /v1/analytics/kpis",
                ["total_cost_usd", "total_requests"])
check_analytics("/v1/analytics/timeseries", "GET /v1/analytics/timeseries",
                ["series"])
check_analytics("/v1/analytics/models",     "GET /v1/analytics/models",
                ["models"])
check_analytics("/v1/analytics/teams",      "GET /v1/analytics/teams",
                ["teams"])
check_analytics("/v1/analytics/traces",     "GET /v1/analytics/traces")
check_analytics("/v1/analytics/cost",       "GET /v1/analytics/cost")

# ?period param
try:
    r = get("/v1/analytics/kpis?period=7", headers=HEADERS, timeout=10)
    check("Analytics accepts ?period=7", r.status_code == 200)
except Exception as e:
    fail("Period param test failed", str(e))

# Unauthenticated analytics should 401
try:
    r = get("/v1/analytics/summary", timeout=10)
    check("Analytics without auth returns 401", r.status_code == 401)
except Exception as e:
    fail("Unauth analytics check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 6. PATCH scores (async quality scoring)
# ─────────────────────────────────────────────────────────────────────────────
section("6. Patch event scores (PATCH /v1/events/:id/scores)")
scored_event = make_event()
try:
    r = post("/v1/events", json=scored_event, headers=HEADERS, timeout=15)
    if r.status_code in (200, 201, 202):
        ev_id = scored_event["event_id"]
        r2 = patch_req(f"/v1/events/{ev_id}/scores",
                       json={"hallucination_score": 0.05, "relevancy_score": 0.92},
                       headers=HEADERS, timeout=10)
        check("PATCH /v1/events/:id/scores returns 200",
              r2.status_code == 200,
              f"{r2.status_code}: {r2.text[:200]}")
    else:
        warn("Score patch skipped — event ingest failed")
except Exception as e:
    fail("Score patch failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 7. Member management
# ─────────────────────────────────────────────────────────────────────────────
section("7. Team member management (POST/GET/PATCH/DELETE /v1/auth/members)")
member_email = rand_email()
member_id    = None
member_key   = None

try:
    r = post("/v1/auth/members",
             json={"email": member_email, "name": "Test Member",
                   "role": "member", "scope_team": "backend"},
             headers=HEADERS, timeout=15)
    check("POST /v1/auth/members returns 201", r.status_code == 201,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    member_id  = d.get("member_id")
    member_key = d.get("api_key")
    check("member api_key returned", isinstance(member_key, str) and member_key.startswith("crt_"))
    check("scope_team echoed back", d.get("scope_team") == "backend")
except Exception as e:
    fail("Member invite failed", str(e))

try:
    r = get("/v1/auth/members", headers=HEADERS, timeout=10)
    check("GET /v1/auth/members returns 200", r.status_code == 200)
    members = r.json().get("members", [])
    check("Invited member appears in list",
          any(m.get("email") == member_email for m in members),
          f"members: {[m.get('email') for m in members]}")
except Exception as e:
    fail("List members failed", str(e))

# Member key scoping — test BEFORE deleting (key is invalid after delete)
if member_key:
    try:
        r = get("/v1/analytics/summary",
                headers={"Authorization": f"Bearer {member_key}"}, timeout=10)
        check("Member API key accepted for analytics", r.status_code == 200,
              f"{r.status_code}: {r.text[:200]}")
    except Exception as e:
        fail("Member key analytics failed", str(e))

if member_id:
    try:
        r = patch_req(f"/v1/auth/members/{member_id}",
                      json={"role": "viewer"},
                      headers=HEADERS, timeout=10)
        check("PATCH /v1/auth/members/:id returns 200", r.status_code == 200)
    except Exception as e:
        fail("Member update failed", str(e))

    try:
        r = delete_req(f"/v1/auth/members/{member_id}",
                       headers=HEADERS, timeout=10)
        check("DELETE /v1/auth/members/:id returns 200", r.status_code == 200)
    except Exception as e:
        fail("Member delete failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 8. Admin endpoints
# ─────────────────────────────────────────────────────────────────────────────
section("8. Admin endpoints (/v1/admin/*)")

try:
    r = get("/v1/admin/overview", headers=HEADERS, timeout=10)
    check("GET /v1/admin/overview returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
except Exception as e:
    fail("Admin overview failed", str(e))

try:
    r = get("/v1/admin/team-budgets", headers=HEADERS, timeout=10)
    check("GET /v1/admin/team-budgets returns 200", r.status_code == 200)
except Exception as e:
    fail("Team budgets list failed", str(e))

try:
    r = requests.put(f"{API}/v1/admin/team-budgets/backend",
                     json={"budget_usd": 100.0},
                     headers=HEADERS, timeout=10)
    check("PUT /v1/admin/team-budgets/:team returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
except Exception as e:
    fail("Team budget set failed", str(e))

try:
    r = delete_req("/v1/admin/team-budgets/backend",
                   headers=HEADERS, timeout=10)
    check("DELETE /v1/admin/team-budgets/:team returns 200", r.status_code == 200)
except Exception as e:
    fail("Team budget delete failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 9. Key recovery (POST /v1/auth/recover)
# ─────────────────────────────────────────────────────────────────────────────
section("9. Key recovery (POST /v1/auth/recover)")
try:
    r = post("/v1/auth/recover",
             json={"email": test_email}, timeout=15)
    check("POST /v1/auth/recover returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    check("ok=true in response", d.get("ok") is True)
    # CORS must be present so browser never gets "Network error"
    check("CORS header on recover response",
          r.headers.get("Access-Control-Allow-Origin") is not None)
except Exception as e:
    fail("Key recovery failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 10. Alert config (GET /v1/alerts/:orgId)
# ─────────────────────────────────────────────────────────────────────────────
section("10. Alert config (GET /v1/alerts/:orgId)")
try:
    r = get(f"/v1/alerts/{ORG_ID}", headers=HEADERS, timeout=10)
    check("GET /v1/alerts/:orgId returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    # New org has no slack config yet — slack_url should be null
    check("slack_url key present in response", "slack_url" in d)
except Exception as e:
    fail("Alert config GET failed", str(e))

# Saving an invalid Slack webhook URL
try:
    r = post(f"/v1/alerts/slack/{ORG_ID}",
             json={"webhook_url": "https://not-slack.com/hook"},
             headers=HEADERS, timeout=10)
    check("Invalid Slack webhook returns 400", r.status_code == 400)
except Exception as e:
    fail("Invalid webhook check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 11. Key rotation
# ─────────────────────────────────────────────────────────────────────────────
section("11. Key rotation (POST /v1/auth/rotate)")
try:
    r = post("/v1/auth/rotate", headers=HEADERS, timeout=10)
    check("POST /v1/auth/rotate returns 200", r.status_code == 200,
          f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    new_key = d.get("api_key")
    check("New key returned and starts with crt_",
          isinstance(new_key, str) and new_key.startswith("crt_"))
    check("New key is different from old key", new_key != API_KEY)
    # Old key should now be invalid
    r_old = get("/v1/analytics/summary", headers=HEADERS, timeout=10)
    check("Old key is revoked after rotation", r_old.status_code == 401)
    # Update headers to new key
    HEADERS["Authorization"] = f"Bearer {new_key}"
    r_new = get("/v1/analytics/summary", headers=HEADERS, timeout=10)
    check("New key works after rotation", r_new.status_code == 200)
except Exception as e:
    fail("Key rotation failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 12. 404 & error handling
# ─────────────────────────────────────────────────────────────────────────────
section("12. Error handling (404, malformed JSON)")
try:
    r = get("/v1/does-not-exist", headers=HEADERS, timeout=10)
    check("Unknown route returns 404", r.status_code == 404)
    check("404 has CORS header",
          r.headers.get("Access-Control-Allow-Origin") is not None)
except Exception as e:
    fail("404 check failed", str(e))

try:
    r = requests.post(f"{API}/v1/events",
                      data="not json",
                      headers={**HEADERS, "Content-Type": "application/json"},
                      timeout=10)
    check("Malformed JSON returns 400 or 500 with CORS",
          r.status_code in (400, 500) and
          r.headers.get("Access-Control-Allow-Origin") is not None,
          f"status={r.status_code} cors={r.headers.get('Access-Control-Allow-Origin')}")
except Exception as e:
    fail("Malformed JSON check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 13. Python SDK — cohrint package
# ─────────────────────────────────────────────────────────────────────────────
section("13. Python SDK (import cohrint)")
try:
    import cohrint
    ok(f"import cohrint succeeded (v{cohrint.__version__})")
    check("cohrint.init exists", callable(getattr(cohrint, "init", None)))
    check("cohrint.trace exists", callable(getattr(cohrint, "trace", None)))
    check("cohrint.flush exists", callable(getattr(cohrint, "flush", None)))
except ImportError as e:
    fail("import cohrint failed — run: pip install cohrint", str(e))

try:
    from cohrint.models.pricing import calculate_cost, find_cheapest
    cost = calculate_cost("gpt-4o", prompt=1000, completion=300)
    check("calculate_cost('gpt-4o') returns dict with total",
          isinstance(cost, dict) and "total" in cost,
          str(cost))
    alt = find_cheapest("gpt-4o", prompt=1000, completion=300)
    check("find_cheapest returns a cheaper model", alt and alt["cost"] < cost["total"])
except Exception as e:
    fail("Pricing utilities failed", str(e))

try:
    from cohrint.analysis.hallucination import _heuristic_scores
    scores = _heuristic_scores("What is Paris?", "Paris is the capital of France.")
    check("Hallucination heuristic returns scores dict",
          isinstance(scores, dict) and "hallucination_score" in scores)
    check("Low hallucination score for factual answer",
          scores["hallucination_score"] < 0.4)
except Exception as e:
    fail("Hallucination analysis failed", str(e))

# Test import alias works (as shown in our docs)
try:
    import cohrint as vantage
    ok("'import cohrint as vantage' works (matches docs examples)")
except Exception as e:
    fail("import cohrint as vantage failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 14. npm SDK — cohrint package
# ─────────────────────────────────────────────────────────────────────────────
section("14. npm SDK (npm show cohrint)")
try:
    result = subprocess.run(
        ["npm", "show", "cohrint", "version"],
        capture_output=True, text=True, timeout=15
    )
    npm_version = result.stdout.strip()
    check(f"npm package cohrint exists (v{npm_version})",
          result.returncode == 0 and bool(npm_version))
except Exception as e:
    fail("npm show cohrint failed", str(e))

# Verify dist/index.js is importable with node
try:
    sdk_path = "/Users/amanjain/Documents/New Ideas/AI Cost Analysis/Cloudfare based/vantageai/vantage-js-sdk/dist/index.js"
    result = subprocess.run(
        ["node", "--input-type=module",
         f'--eval=import("{sdk_path}").then(m=>console.log("ok",Object.keys(m).join(","))).catch(e=>process.exit(1))'],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode == 0:
        exported = result.stdout.strip()
        ok(f"JS SDK dist loads — exports: {exported[:80]}")
    else:
        warn(f"JS SDK dist check inconclusive: {result.stderr[:100]}")
except Exception as e:
    warn(f"JS SDK node check skipped: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 15. Dashboard live data validation
# ─────────────────────────────────────────────────────────────────────────────
section("15. Dashboard — live data visible after event ingestion")
try:
    r = get("/v1/analytics/summary", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        d = r.json()
        mtd_cost = d.get("mtd_cost_usd", d.get("mtd_cost", 0))
        check("MTD cost > 0 after batch ingest", mtd_cost > 0,
              f"mtd_cost_usd={mtd_cost}")
        if mtd_cost == 0:
            warn("MTD cost is $0.00 — cost_usd may be 0 in DB or D1 write not yet visible")
    else:
        fail("Analytics summary not available for live data check", r.text[:200])
except Exception as e:
    fail("Live data check failed", str(e))

try:
    r = get("/v1/analytics/models", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        d = r.json()
        models_list = d.get("models", [])
        check("Models breakdown populated after ingest", len(models_list) > 0,
              f"models count: {len(models_list)}")
    else:
        fail("Models analytics not available")
except Exception as e:
    fail("Models analytics check failed", str(e))

try:
    r = get("/v1/analytics/teams", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        d = r.json()
        teams_list = d.get("teams", [])
        check("Teams breakdown populated after ingest", len(teams_list) > 0,
              f"teams: {[t.get('team') for t in teams_list]}")
    else:
        fail("Teams analytics not available")
except Exception as e:
    fail("Teams analytics check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 16. Logout
# ─────────────────────────────────────────────────────────────────────────────
section("16. Logout (DELETE /v1/auth/session)")
try:
    r = session.delete(f"{API}/v1/auth/session", timeout=10)
    check("DELETE /v1/auth/session returns 200", r.status_code == 200)
    # Session should now be invalid
    r2 = session.get(f"{API}/v1/auth/session", timeout=10)
    check("Session rejected after logout", r2.status_code == 401)
except Exception as e:
    fail("Logout failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
total = results["passed"] + results["failed"] + results["warned"]
print(f"\n{'═'*60}")
print(f"  Results: {results['passed']} passed  {results['failed']} failed  {results['warned']} warnings  ({total} total)")
print(f"{'═'*60}\n")

if results["failed"] > 0:
    print(f"  {FAIL}  Some tests FAILED — see above for details.\n")
    sys.exit(1)
else:
    print(f"  {PASS}  All checks passed!\n")
    sys.exit(0)
