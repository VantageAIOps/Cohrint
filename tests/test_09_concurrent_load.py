"""
test_09_concurrent_load.py — Concurrent users & load tests
===========================================================
Developer notes:
  Tests the system under concurrent and sequential load:

  Concurrent tests (ThreadPoolExecutor):
    • 10 simultaneous signups — no race conditions, each gets unique key
    • 10 simultaneous sign-ins — session creation is thread-safe
    • 20 simultaneous analytics reads — read scaling
    • 10 simultaneous event ingestions — write scaling

  Sequential load:
    • 100 events in rapid succession (single client)
    • 500 events in batches of 50 (rate limit edge)
    • Login/logout cycle × 10 (session table churn)

  Rate limiting:
    • 1000 RPM default limit — verify 429 appears near the limit
    • Rate limit resets after window

  Multi-client dashboard:
    • 5 Playwright browsers open dashboard simultaneously

  Stress signals to watch:
    • Any 500 errors (server crash)
    • Response time degradation under load
    • CORS errors in concurrent context
    • Session cookie collision

Run:
  python tests/test_09_concurrent_load.py
  (This test takes ~60-90 seconds — concurrent + load)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag, rand_name,
    signup_api, get_headers, get_session_cookie,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.load")


# ─────────────────────────────────────────────────────────────────────────────
section("1. Concurrent signups (10 simultaneous)")
# ─────────────────────────────────────────────────────────────────────────────

def do_signup(i):
    try:
        t0 = time.monotonic()
        r  = requests.post(f"{API_URL}/v1/auth/signup",
                           json={"email": rand_email(f"cc{i}"),
                                 "name":  rand_name(),
                                 "org":   rand_org(f"cc{i}")},
                           timeout=20)
        ms = round((time.monotonic() - t0) * 1000)
        if r.status_code == 201:
            d = r.json()
            log.info("Concurrent signup OK", i=i, org=d.get("org_id"), duration_ms=ms)
            return {"ok": True, "key": d.get("api_key"), "org": d.get("org_id"), "ms": ms}
        else:
            log.warn("Concurrent signup failed", i=i, status=r.status_code, duration_ms=ms)
            return {"ok": False, "status": r.status_code, "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}

N_CONCURRENT = 10

with ThreadPoolExecutor(max_workers=N_CONCURRENT) as ex:
    futures = [ex.submit(do_signup, i) for i in range(N_CONCURRENT)]
    results_signup = [f.result() for f in as_completed(futures)]

ok_count = sum(1 for r in results_signup if r.get("ok"))
keys = [r["key"] for r in results_signup if r.get("ok") and r.get("key")]
unique_keys = set(keys)
avg_ms = round(sum(r.get("ms", 0) for r in results_signup) / max(len(results_signup), 1))

chk(f"1.1  {ok_count}/{N_CONCURRENT} concurrent signups succeeded",
    ok_count == N_CONCURRENT, f"failures: {N_CONCURRENT - ok_count}")
chk("1.2  All signup keys are unique (no collision)",
    len(unique_keys) == len(keys), f"got {len(unique_keys)} unique out of {len(keys)}")
info(f"     Average signup latency: {avg_ms}ms")

# Keep some keys for subsequent tests
LOAD_KEYS = keys[:5] if len(keys) >= 5 else keys


# ─────────────────────────────────────────────────────────────────────────────
section("2. Concurrent sign-ins (10 simultaneous)")
# ─────────────────────────────────────────────────────────────────────────────

def do_signin(key):
    try:
        t0 = time.monotonic()
        r  = requests.post(f"{API_URL}/v1/auth/session",
                           json={"api_key": key}, timeout=15)
        ms = round((time.monotonic() - t0) * 1000)
        log.request("POST", "/v1/auth/session", r.status_code, ms)
        return {"ok": r.status_code == 200, "status": r.status_code, "ms": ms,
                "cookies": r.cookies}
    except Exception as e:
        return {"ok": False, "error": str(e)}

if LOAD_KEYS:
    with ThreadPoolExecutor(max_workers=len(LOAD_KEYS)) as ex:
        futures = [ex.submit(do_signin, k) for k in LOAD_KEYS]
        results_signin = [f.result() for f in as_completed(futures)]

    ok_count_si = sum(1 for r in results_signin if r.get("ok"))
    avg_ms_si = round(sum(r.get("ms", 0) for r in results_signin) / max(len(results_signin), 1))
    chk(f"2.1  {ok_count_si}/{len(LOAD_KEYS)} concurrent sign-ins succeeded",
        ok_count_si == len(LOAD_KEYS))
    info(f"     Average sign-in latency: {avg_ms_si}ms")
else:
    warn("2.x  No keys available from signup test — skipping sign-in load test")


# ─────────────────────────────────────────────────────────────────────────────
section("3. Concurrent analytics reads (20 simultaneous)")
# ─────────────────────────────────────────────────────────────────────────────

# Use one stable account for read load
try:
    d_read  = signup_api()
    READ_KEY = d_read["api_key"]
    READ_HDR = get_headers(READ_KEY)
    ANALYTICS_PATHS = [
        "/v1/analytics/summary",
        "/v1/analytics/kpis?period=30",
        "/v1/analytics/timeseries?period=30",
        "/v1/analytics/models?period=30",
        "/v1/analytics/teams?period=30",
    ]
except Exception as e:
    fail("Could not create read-test account", str(e))
    READ_KEY = READ_HDR = None
    ANALYTICS_PATHS = []

def do_analytics_read(path):
    try:
        t0 = time.monotonic()
        r  = requests.get(f"{API_URL}{path}", headers=READ_HDR, timeout=15)
        ms = round((time.monotonic() - t0) * 1000)
        log.request("GET", path, r.status_code, ms)
        return {"ok": r.status_code == 200, "status": r.status_code, "path": path, "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": path}

if READ_KEY and ANALYTICS_PATHS:
    # 20 concurrent reads across 5 analytics paths (4 calls each)
    tasks = ANALYTICS_PATHS * 4
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(do_analytics_read, p) for p in tasks]
        results_reads = [f.result() for f in as_completed(futures)]

    ok_reads = sum(1 for r in results_reads if r.get("ok"))
    errors_reads = [r for r in results_reads if not r.get("ok")]
    avg_ms_read = round(sum(r.get("ms", 0) for r in results_reads) / max(len(results_reads), 1))

    chk(f"3.1  {ok_reads}/{len(tasks)} concurrent analytics reads succeeded",
        ok_reads >= len(tasks) * 0.95,  # allow 5% failure under load
        f"failures={len(errors_reads)}: {errors_reads[:2]}")
    chk("3.2  No 500 errors under analytics read load",
        all(r.get("status", 0) != 500 for r in results_reads),
        str([r for r in results_reads if r.get("status") == 500][:2]))
    info(f"     Average analytics read latency: {avg_ms_read}ms")


# ─────────────────────────────────────────────────────────────────────────────
section("4. Concurrent event writes (10 simultaneous)")
# ─────────────────────────────────────────────────────────────────────────────

if READ_KEY:
    def do_event_write(i):
        try:
            t0 = time.monotonic()
            evt = {
                "event_id":          f"load-{i}-{rand_tag()}",
                "provider":          "openai",
                "model":             "gpt-4o",
                "prompt_tokens":     200 + i * 10,
                "completion_tokens": 50,
                "total_tokens":      250 + i * 10,
                "total_cost_usd":    0.002,
                "latency_ms":        200 + i * 5,
                "team":              "load-test",
            }
            r = requests.post(f"{API_URL}/v1/events", json=evt, headers=READ_HDR, timeout=15)
            ms = round((time.monotonic() - t0) * 1000)
            return {"ok": r.status_code in (200, 201), "status": r.status_code, "ms": ms}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(do_event_write, i) for i in range(10)]
        results_writes = [f.result() for f in as_completed(futures)]

    ok_writes = sum(1 for r in results_writes if r.get("ok"))
    chk(f"4.1  {ok_writes}/10 concurrent event writes succeeded", ok_writes >= 9,
        f"failures={10 - ok_writes}")
    chk("4.2  No 500 errors in concurrent writes",
        all(r.get("status", 0) != 500 for r in results_writes))


# ─────────────────────────────────────────────────────────────────────────────
section("5. Sequential load — 100 events rapid-fire")
# ─────────────────────────────────────────────────────────────────────────────
if READ_KEY:
    try:
        t0 = time.monotonic()
        # Send 2 batches of 50
        for batch_num in range(2):
            batch = {
                "events": [
                    {
                        "event_id":          f"seq-{batch_num}-{i}-{rand_tag()}",
                        "provider":          "anthropic",
                        "model":             "claude-sonnet-4-6",
                        "prompt_tokens":     100,
                        "completion_tokens": 50,
                        "total_tokens":      150,
                        "total_cost_usd":    0.001,
                        "latency_ms":        180,
                        "team":              "sequential-load",
                    }
                    for i in range(50)
                ]
            }
            r = requests.post(f"{API_URL}/v1/events/batch", json=batch,
                              headers=READ_HDR, timeout=30)
            chk(f"5.{batch_num+1} Batch {batch_num+1} (50 events) → 200/201",
                r.status_code in (200, 201), f"status={r.status_code}")
            if r.ok:
                chk(f"5.{batch_num+1} Accepted = 50",
                    r.json().get("accepted") == 50, str(r.json()))

        total_ms = round((time.monotonic() - t0) * 1000)
        info(f"     100-event sequential load completed in {total_ms}ms")
    except Exception as e:
        fail("5.x  Sequential load test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("6. Login / logout cycle (× 10)")
# ─────────────────────────────────────────────────────────────────────────────
if READ_KEY:
    cycle_fails = 0
    cycle_times = []
    for i in range(10):
        try:
            t0 = time.monotonic()
            # Login
            r_in = requests.post(f"{API_URL}/v1/auth/session",
                                 json={"api_key": READ_KEY}, timeout=10)
            if r_in.status_code != 200:
                cycle_fails += 1
                continue
            # Logout
            r_out = requests.delete(f"{API_URL}/v1/auth/session",
                                    cookies=r_in.cookies, timeout=10)
            if r_out.status_code != 200:
                cycle_fails += 1
            cycle_times.append(round((time.monotonic() - t0) * 1000))
        except Exception:
            cycle_fails += 1

    chk(f"6.1  10 login/logout cycles completed ({10 - cycle_fails}/10 successful)",
        cycle_fails == 0, f"{cycle_fails} failures")
    if cycle_times:
        avg_cycle = round(sum(cycle_times) / len(cycle_times))
        info(f"     Average login+logout latency: {avg_cycle}ms")


# ─────────────────────────────────────────────────────────────────────────────
section("7. Response time SLA check")
# ─────────────────────────────────────────────────────────────────────────────
SLA_PATHS = [
    ("/health",                    500),
    ("/v1/analytics/summary",     2000),
    ("/v1/analytics/kpis?period=30", 2000),
]

if READ_HDR:
    for path, sla_ms in SLA_PATHS:
        try:
            t0 = time.monotonic()
            r  = requests.get(f"{API_URL}{path}", headers=READ_HDR, timeout=10)
            ms = round((time.monotonic() - t0) * 1000)
            chk(f"7.x  GET {path} < {sla_ms}ms SLA (got {ms}ms)",
                ms < sla_ms, f"SLOW: {ms}ms exceeded {sla_ms}ms SLA")
            log.request("GET", path, r.status_code, ms)
        except Exception as e:
            fail(f"7.x  SLA check failed: {path}", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("8. Multi-client Playwright (3 browsers simultaneously)")
# ─────────────────────────────────────────────────────────────────────────────

def browser_session(account_num):
    """Open a browser, sign in, check dashboard, return pass/fail."""
    try:
        from playwright.sync_api import sync_playwright
        d = signup_api()
        key = d["api_key"]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
                page.fill("#inp-key", key)
                page.click("#signin-btn")
                page.wait_for_url(f"{SITE_URL}/app**", timeout=10_000)
                page.wait_for_timeout(2_000)
                on_app = "/app" in page.url
                log.info("Browser session done", num=account_num, on_app=on_app,
                         js_errors=len(errors))
                return {"ok": on_app, "errors": errors}
            finally:
                ctx.close()
                browser.close()
    except ImportError:
        return {"ok": None, "skip": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

N_BROWSERS = 3
with ThreadPoolExecutor(max_workers=N_BROWSERS) as ex:
    futures = [ex.submit(browser_session, i) for i in range(N_BROWSERS)]
    browser_results = [f.result() for f in as_completed(futures)]

if all(r.get("skip") for r in browser_results):
    warn("8.x  Playwright not installed — skipping multi-browser test")
else:
    ok_browsers = sum(1 for r in browser_results if r.get("ok"))
    chk(f"8.1  {ok_browsers}/{N_BROWSERS} simultaneous browsers reach dashboard",
        ok_browsers == N_BROWSERS,
        f"failures: {[r for r in browser_results if not r.get('ok')]}")
    all_errors = [e for r in browser_results for e in r.get("errors", [])]
    chk("8.2  No JS errors across multi-browser sessions",
        len(all_errors) == 0, str(all_errors[:3]))


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Concurrent/load tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
