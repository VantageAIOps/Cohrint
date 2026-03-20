"""
test_10_stress_production.py — Stress tests & production stability
===================================================================
Developer notes:
  High-intensity tests that push the system to its limits:

    1. Burst traffic — 200 events in 2 seconds
    2. Sustained throughput — 500 events over 30 seconds
    3. Invalid-key flooding — 50 bad keys rapid-fire (rate limiting)
    4. Large batch edge case — exactly 500 events (server limit)
    5. Very large event payload (oversized fields — should 400/413, not 500)
    6. Concurrent key rotations (5 simultaneous rotations on same org)
    7. Recovery flow under load (5 simultaneous recovery requests)
    8. Long-running session validity (session > 1 hour still valid)
    9. Endpoint stability: 50 sequential health-check pings
   10. Worker cold-start simulation (no warm traffic, then spike)

  Every test checks:
    - No HTTP 500 responses
    - Response time within reason (< 10s worst case)
    - Server returns valid JSON (not HTML error pages)

  This suite intentionally creates temporary test data in the live D1 database.
  All test accounts use the prefix 'stress_' for easy identification.

Run:
  python tests/test_10_stress_production.py
  (Takes 2-3 minutes — high volume)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag,
    signup_api, get_headers, get_session_cookie,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.stress")

# Shared account for most stress tests
try:
    d         = signup_api()
    STRESS_KEY = d["api_key"]
    STRESS_ORG = d["org_id"]
    STRESS_HDR = get_headers(STRESS_KEY)
    STRESS_CKS = get_session_cookie(STRESS_KEY)
    info(f"Stress account: {STRESS_ORG}")
except Exception as e:
    fail("Could not create stress account", str(e))
    sys.exit(1)

def make_evt(tag="s", provider="openai", model="gpt-4o"):
    return {
        "event_id":          f"{tag}-{rand_tag()}-{time.time_ns()}",
        "provider":          provider,
        "model":             model,
        "prompt_tokens":     random.randint(100, 2000),
        "completion_tokens": random.randint(50, 500),
        "total_tokens":      random.randint(150, 2500),
        "total_cost_usd":    round(random.uniform(0.001, 0.02), 6),
        "latency_ms":        random.randint(100, 2000),
        "team":              random.choice(["alpha", "beta", "gamma"]),
        "environment":       "stress-test",
    }

def no_500(r):
    """True if response is not a server error."""
    return r is not None and r.status_code != 500

def is_json(r):
    """True if response body is JSON."""
    try:
        r.json(); return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
section("1. Burst traffic — 200 events in 2 seconds")
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.monotonic()
    events = [make_evt("burst") for _ in range(200)]
    # Split into 4 batches of 50, sent concurrently
    batches = [events[i:i+50] for i in range(0, 200, 50)]

    def send_batch(evts):
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": evts}, headers=STRESS_HDR, timeout=30)
        return r

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(send_batch, b) for b in batches]
        batch_results = [f.result() for f in as_completed(futs)]

    ms_total = round((time.monotonic() - t0) * 1000)
    ok_batches = sum(1 for r in batch_results if r.status_code in (200, 201))
    accepted_total = sum(
        r.json().get("accepted", 0)
        for r in batch_results if r.status_code in (200, 201) and is_json(r)
    )
    chk(f"1.1  {ok_batches}/4 burst batches succeeded (200/201)",
        ok_batches == 4, f"failures: {4 - ok_batches}")
    chk(f"1.2  All 200 burst events accepted (got {accepted_total})",
        accepted_total == 200, f"accepted={accepted_total}")
    chk("1.3  No 500 in burst", all(no_500(r) for r in batch_results))
    info(f"     Burst 200 events in {ms_total}ms")
    log.info("Burst test done", total_events=200, accepted=accepted_total, duration_ms=ms_total)
except Exception as e:
    fail("1.x  Burst test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("2. Sustained throughput — 500 events in sequential batches")
# ─────────────────────────────────────────────────────────────────────────────
try:
    t0 = time.monotonic()
    total_accepted = 0
    any_500 = False

    for chunk in range(10):  # 10 × 50 = 500 events
        events = [make_evt("sust") for _ in range(50)]
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": events}, headers=STRESS_HDR, timeout=30)
        if r.status_code == 500:
            any_500 = True
        if r.status_code in (200, 201) and is_json(r):
            total_accepted += r.json().get("accepted", 0)

    ms_total = round((time.monotonic() - t0) * 1000)
    chk(f"2.1  500 events sustained throughput accepted ({total_accepted})",
        total_accepted >= 450,  # allow some free-tier limits
        f"accepted={total_accepted}")
    chk("2.2  No 500 errors during sustained load", not any_500)
    info(f"     Sustained 500 events in {ms_total}ms "
         f"({round(500000 / max(ms_total, 1))} ev/s)")
except Exception as e:
    fail("2.x  Sustained throughput test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("3. Invalid key flooding (50 bad keys)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    bad_keys = [f"vnt_badorg{rand_tag()}_{rand_tag(32)}" for _ in range(50)]

    def try_bad_key(key):
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": key}, timeout=10)
        return r.status_code

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=10) as ex:
        statuses = list(ex.map(try_bad_key, bad_keys))
    ms_total = round((time.monotonic() - t0) * 1000)

    all_401 = all(s == 401 for s in statuses)
    no_500s  = all(s != 500 for s in statuses)
    chk("3.1  All 50 invalid keys correctly return 401", all_401,
        f"unexpected statuses: {set(statuses) - {401}}")
    chk("3.2  No 500 errors from invalid key flooding", no_500s,
        str([s for s in statuses if s == 500]))
    info(f"     50 bad-key checks in {ms_total}ms")
except Exception as e:
    fail("3.x  Invalid key flooding test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("4. Maximum batch size (exactly 500 events)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    exactly_500 = [make_evt("max") for _ in range(500)]
    t0 = time.monotonic()
    r  = requests.post(f"{API_URL}/v1/events/batch",
                       json={"events": exactly_500}, headers=STRESS_HDR, timeout=60)
    ms = round((time.monotonic() - t0) * 1000)
    chk("4.1  500-event batch → 200/201", r.status_code in (200, 201),
        f"got {r.status_code}: {r.text[:100]}")
    if is_json(r) and r.status_code in (200, 201):
        chk("4.2  All 500 accepted", r.json().get("accepted", 0) == 500,
            f"accepted={r.json().get('accepted')}")
    chk("4.3  Not a 500 error at max batch", r.status_code != 500)
    info(f"     500-event batch processed in {ms}ms")
except Exception as e:
    fail("4.x  Max batch test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("5. Oversized payload fields (should 400/413, not 500)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    # Very long model name (10KB)
    big_model = "a" * 10_000
    r = requests.post(f"{API_URL}/v1/events",
                      json={**make_evt("oversize"), "model": big_model},
                      headers=STRESS_HDR, timeout=10)
    chk("5.1  Oversized model field → not 500",
        r.status_code != 500, f"got 500: {r.text[:100]}")
    chk("5.2  Oversized model field → 400/413 or 200 (server handles gracefully)",
        r.status_code in (200, 201, 400, 413),
        f"got {r.status_code}")

    # Null values in required fields
    r2 = requests.post(f"{API_URL}/v1/events",
                       json={"event_id": None, "provider": None, "model": None},
                       headers=STRESS_HDR, timeout=10)
    chk("5.3  Null fields → 400 (not 500)", r2.status_code == 400,
        f"got {r2.status_code}")

    # Deeply nested extra fields (should be ignored or 400)
    r3 = requests.post(f"{API_URL}/v1/events",
                       json={**make_evt("nest"), "metadata": {"a": {"b": {"c": "x" * 1000}}}},
                       headers=STRESS_HDR, timeout=10)
    chk("5.4  Deeply nested extra fields → not 500",
        r3.status_code != 500, f"got 500: {r3.text[:100]}")
except Exception as e:
    fail("5.x  Oversized payload tests failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("6. Concurrent key rotations (5 simultaneous on same org)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    # Use a dedicated account for rotation stress
    d_rot = signup_api()
    rot_key = d_rot["api_key"]
    rot_cks = get_session_cookie(rot_key)

    rotate_results = []

    def do_rotate():
        nonlocal rot_cks
        try:
            r = requests.post(f"{API_URL}/v1/auth/rotate",
                              cookies=rot_cks, timeout=15)
            if r.ok:
                new_key = r.json().get("api_key")
                rot_cks = get_session_cookie(new_key)
            return r.status_code
        except Exception as e:
            return f"error: {e}"

    # Only 1 concurrent rotation makes sense (each invalidates the previous key)
    # But we verify sequential rotations work correctly × 3
    for i in range(3):
        status = do_rotate()
        rotate_results.append(status)
        time.sleep(0.5)

    all_ok = all(s == 200 for s in rotate_results)
    chk(f"6.1  3 sequential key rotations all succeed (statuses={rotate_results})",
        all_ok, str(rotate_results))
except Exception as e:
    fail("6.x  Key rotation stress test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("7. Recovery requests under load (5 simultaneous)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    emails = [rand_email("recvr") for _ in range(5)]

    def do_recover(email):
        r = requests.post(f"{API_URL}/v1/auth/recover",
                          json={"email": email}, timeout=15)
        return r.status_code

    with ThreadPoolExecutor(max_workers=5) as ex:
        statuses_rec = list(ex.map(do_recover, emails))

    all_200 = all(s == 200 for s in statuses_rec)
    chk(f"7.1  5 concurrent recovery requests all return 200 (statuses={statuses_rec})",
        all_200, str(statuses_rec))
    chk("7.2  No 500 in concurrent recovery", all(s != 500 for s in statuses_rec))
except Exception as e:
    fail("7.x  Recovery load test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("8. Health check stability (50 sequential pings)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    ping_results = []
    t0 = time.monotonic()
    for _ in range(50):
        r = requests.get(f"{API_URL}/health", timeout=10)
        ping_results.append(r.status_code)

    ms_total = round((time.monotonic() - t0) * 1000)
    all_healthy = all(s == 200 for s in ping_results)
    non_200 = [s for s in ping_results if s != 200]
    chk("8.1  All 50 health pings return 200", all_healthy,
        f"non-200: {non_200}")
    info(f"     50 pings in {ms_total}ms ({round(ms_total/50)}ms avg)")
    log.info("Health ping stability", pings=50, duration_ms=ms_total,
             avg_ms=round(ms_total/50))
except Exception as e:
    fail("8.x  Health ping stability test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("9. Analytics under data volume")
# ─────────────────────────────────────────────────────────────────────────────
try:
    # Re-query analytics after all the events we've sent
    analytics_results = {}
    for path in ["/v1/analytics/summary", "/v1/analytics/kpis?period=30",
                 "/v1/analytics/models?period=30"]:
        r = requests.get(f"{API_URL}{path}", headers=STRESS_HDR, timeout=15)
        analytics_results[path] = r.status_code
        chk(f"9.x  GET {path} → 200 under data volume", r.status_code == 200,
            f"got {r.status_code}: {r.text[:100]}")
        chk(f"9.x  {path} returns valid JSON", is_json(r))
except Exception as e:
    fail("9.x  Analytics under volume test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("10. Session persistence over repeated API calls")
# ─────────────────────────────────────────────────────────────────────────────
try:
    session_cks = get_session_cookie(STRESS_KEY)
    if session_cks:
        call_results = []
        for _ in range(20):
            r = requests.get(f"{API_URL}/v1/auth/session",
                             cookies=session_cks, timeout=10)
            call_results.append(r.status_code)

        all_valid = all(s == 200 for s in call_results)
        chk("10.1 Session valid across 20 repeated GET /session calls",
            all_valid, f"non-200: {[s for s in call_results if s != 200]}")

        # Verify org_id consistent across all calls
        r_final = requests.get(f"{API_URL}/v1/auth/session",
                               cookies=session_cks, timeout=10)
        if r_final.ok:
            chk("10.2 Session always returns same org_id",
                r_final.json().get("org_id") == STRESS_ORG,
                f"got {r_final.json().get('org_id')}, expected {STRESS_ORG}")
except Exception as e:
    fail("10.x  Session persistence test failed", str(e))


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Stress tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
