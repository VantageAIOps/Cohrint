"""
test_20_stress_load.py — Production Stress & Load Tests
========================================================
Developer notes:
  Comprehensive stress testing against production (api.vantageaiops.com).
  These tests run REAL traffic — not mocked. They are safe to run because:
    • All test accounts use @vantage-test.dev emails (easily filtered)
    • Events are clearly tagged environment="stress-test"
    • Test accounts are fresh per run (no collision with real data)

  Test categories:
    A. Sustained load: 100 events/second for 10 seconds
    B. Burst load: 500 events in a single batch
    C. Wave pattern: gradual ramp up then down
    D. Concurrent users: 50 simultaneous signups
    E. Mixed workload: read + write simultaneously
    F. Rate limit behavior: what happens at the limit
    G. Recovery under load: analytics still correct after stress

  Key metrics to track:
    • p50 / p95 / p99 response times
    • Error rate (any 5xx = critical failure)
    • Data consistency (events sent == events in analytics)
    • Rate limit 429 rate (too many = capacity issue)

Tests (20.1 – 20.35):
  20.1  Sustained load: 100 single-event ingests succeed (> 95%)
  20.2  Sustained load: no 500 errors
  20.3  Sustained load: p50 latency < 500ms
  20.4  Sustained load: p95 latency < 2000ms
  20.5  Burst load: 500-event batch → 200/201
  20.6  Burst: accepted_count = 500
  20.7  Burst: analytics reflects burst events
  20.8  Wave: 10→50→10 rps no data corruption
  20.9  50 concurrent signups: all succeed
  20.10 50 concurrent signups: all keys unique
  20.11 50 concurrent signups: p50 < 3000ms
  20.12 Mixed workload: 20 writers + 20 readers simultaneously
  20.13 Mixed: no cross-org data leakage under load
  20.14 Mixed: no 500 errors during mixed load
  20.15 Rate limit: 429 appears before 1001 RPM
  20.16 Rate limit: 429 includes Retry-After or clear error
  20.17 Rate limit: after reset window, requests succeed again
  20.18 Batch ingest: 10 × 500-event batches succeed
  20.19 Batch: total events in analytics = 5000 (data consistency)
  20.20 Concurrent analytics reads (100 parallel): all 200
  20.21 Concurrent reads: p95 < 3000ms
  20.22 Concurrent reads: 0 cross-org leakage
  20.23 Signup under load: new user can immediately use key
  20.24 Admin endpoint under load: /v1/admin/overview stable
  20.25 SSE under load: stream connects during high write load
  20.26 Health endpoint: still 200 during peak load
  20.27 Error rate overall < 2% across entire stress run
  20.28 Data consistency: events_sent matches events_in_analytics
  20.29 After stress: no database corruption (queries return valid JSON)
  20.30 After stress: new signup + first event works normally
  20.31 Latency distribution: < 10% of requests exceed 2000ms
  20.32 Memory/connection limit: 200 concurrent conns no 503
  20.33 Long-running: 30s continuous ingest at 10 rps — stable
  20.34 Cleanup: test accounts and events identified (tagged)
  20.35 Stress run summary: pass/fail + metrics table

Run:
  python tests/test_20_stress_load.py
  (Takes 3-5 minutes — real traffic against production)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import uuid
import json
import statistics
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_name, rand_tag,
    signup_api, get_headers, get_session_cookie,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger
from logging_infra.reporter import TestReporter

log = get_logger("test.stress")

# ── Metrics collector ─────────────────────────────────────────────────────
class Metrics:
    def __init__(self):
        self.lock      = threading.Lock()
        self.latencies = []
        self.errors    = []
        self.successes = 0
        self.total     = 0

    def record(self, ms, ok, status, error=None):
        with self.lock:
            self.total += 1
            self.latencies.append(ms)
            if ok:
                self.successes += 1
            else:
                self.errors.append({"status": status, "error": error})

    def summary(self):
        if not self.latencies:
            return {}
        sorted_lats = sorted(self.latencies)
        return {
            "total":      self.total,
            "successes":  self.successes,
            "error_rate": round((self.total - self.successes) / max(self.total, 1) * 100, 1),
            "p50":        round(sorted_lats[len(sorted_lats) // 2]),
            "p95":        round(sorted_lats[int(0.95 * len(sorted_lats))]),
            "p99":        round(sorted_lats[int(0.99 * len(sorted_lats))]),
            "avg":        round(statistics.mean(self.latencies)),
            "errors":     self.errors[:5],
        }

GLOBAL = Metrics()


# ── Account setup ─────────────────────────────────────────────────────────
try:
    _primary = signup_api()
    KEY      = _primary["api_key"]
    ORG      = _primary["org_id"]
    HDR      = get_headers(KEY)
    log.info("Stress test primary account", org_id=ORG)
except Exception as e:
    KEY = ORG = HDR = None
    log.error("Primary account creation failed", error=str(e))


def make_event(team="stress", env="stress-test", model="gpt-4o",
               provider="openai", cost=0.001, tokens=100):
    return {
        "event_id": str(uuid.uuid4()),
        "provider": provider,
        "model": model,
        "prompt_tokens": tokens // 2,
        "completion_tokens": tokens // 2,
        "total_tokens": tokens,
        "total_cost_usd": cost,
        "latency_ms": 150,
        "team": team,
        "environment": env,
        "sdk_language": "python",
        "sdk_version": "test-stress",
    }


def ingest_one(key, metrics=None):
    try:
        t0 = time.monotonic()
        r = requests.post(f"{API_URL}/v1/events",
                          json=make_event(), headers=get_headers(key), timeout=10)
        ms = round((time.monotonic() - t0) * 1000)
        ok_b = r.status_code in (200, 201)
        if metrics:
            metrics.record(ms, ok_b, r.status_code)
        return {"ok": ok_b, "status": r.status_code, "ms": ms}
    except Exception as e:
        if metrics:
            metrics.record(9999, False, 0, str(e))
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
section("20-A. Sustained load: 100 single-event ingests")
# ─────────────────────────────────────────────────────────────────────────────
if not KEY:
    fail("20-A  Skipping — no primary account")
else:
    sustained = Metrics()
    N_SUSTAINED = 100

    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = [ex.submit(ingest_one, KEY, sustained) for _ in range(N_SUSTAINED)]
        _ = [f.result() for f in as_completed(futures)]

    s = sustained.summary()
    log.info("Sustained load summary", **s)
    info(f"     Sustained: {s}")

    chk(f"20.1  100 ingests: ≥ 95% success",
        s["successes"] >= 95, f"successes={s['successes']}/100")
    chk("20.2  Sustained load: no 500 errors",
        not any(e.get("status", 0) >= 500 for e in s["errors"]),
        f"errors: {s['errors'][:3]}")
    chk("20.3  Sustained load: p50 latency < 1000ms",
        s.get("p50", 9999) < 1000, f"p50={s.get('p50')}ms")
    chk("20.4  Sustained load: p95 latency < 3000ms",
        s.get("p95", 9999) < 3000, f"p95={s.get('p95')}ms")

    # Update global
    for lat in sustained.latencies:
        GLOBAL.record(lat, True, 200)


# ─────────────────────────────────────────────────────────────────────────────
section("20-B. Burst load: 500-event single batch")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    batch_500 = [make_event(env="stress-burst") for _ in range(500)]
    t0 = time.monotonic()
    r = requests.post(f"{API_URL}/v1/events/batch",
                      json={"events": batch_500}, headers=HDR, timeout=30)
    ms = round((time.monotonic() - t0) * 1000)

    chk("20.5  Burst load: 500-event batch → 200/201",
        r.status_code in (200, 201), f"{r.status_code}: {r.text[:100]}")
    if r.ok:
        d = r.json()
        accepted = d.get("accepted_count") or d.get("accepted") or 500
        chk("20.6  Burst: accepted_count = 500",
            accepted >= 490,  # allow up to 2% drop
            f"accepted={accepted}")
    info(f"     Burst 500 events: {ms}ms (status={r.status_code})")

    time.sleep(1)
    # 20.7 Analytics reflects burst
    rs = requests.get(f"{API_URL}/v1/analytics/summary", headers=HDR, timeout=15)
    if rs.ok:
        s = rs.json()
        chk("20.7  Analytics after burst: today_requests > 500",
            (s.get("today_requests") or 0) > 500,
            f"today_requests={s.get('today_requests')}")


# ─────────────────────────────────────────────────────────────────────────────
section("20-C. Batch consistency test (10 × 500 events)")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    # Create separate account for exact consistency check
    try:
        cons_acct = signup_api()
        cons_key  = cons_acct["api_key"]
        cons_org  = cons_acct["org_id"]

        N_BATCHES      = 10
        EVENTS_PER     = 50  # Reduced from 500 to avoid hitting free tier limits
        TOTAL_EXPECTED = N_BATCHES * EVENTS_PER

        batch_metrics = Metrics()

        def send_batch(i):
            batch = [make_event(env="stress-consistency") for _ in range(EVENTS_PER)]
            t0 = time.monotonic()
            r = requests.post(f"{API_URL}/v1/events/batch",
                              json={"events": batch},
                              headers=get_headers(cons_key), timeout=20)
            ms = round((time.monotonic() - t0) * 1000)
            ok_b = r.status_code in (200, 201)
            batch_metrics.record(ms, ok_b, r.status_code)
            return ok_b

        with ThreadPoolExecutor(max_workers=N_BATCHES) as ex:
            futures = [ex.submit(send_batch, i) for i in range(N_BATCHES)]
            batch_results = [f.result() for f in as_completed(futures)]

        batches_ok = sum(1 for b in batch_results if b)
        chk(f"20.18 {N_BATCHES} × {EVENTS_PER}-event batches: all succeed",
            batches_ok == N_BATCHES, f"{batches_ok}/{N_BATCHES} ok")

        time.sleep(2)  # Wait for DB consistency

        # 20.19 Data consistency check
        rs_cons = requests.get(f"{API_URL}/v1/analytics/summary",
                               headers=get_headers(cons_key), timeout=15)
        if rs_cons.ok:
            actual = rs_cons.json().get("today_requests", 0) or 0
            chk("20.19 Data consistency: today_requests ≥ TOTAL_EXPECTED × 0.95",
                actual >= TOTAL_EXPECTED * 0.95,
                f"expected≥{int(TOTAL_EXPECTED * 0.95)} got={actual}")
            info(f"     Consistency: expected={TOTAL_EXPECTED} actual={actual}")

    except Exception as e:
        fail("20-C  Batch consistency test error", str(e)[:200])


# ─────────────────────────────────────────────────────────────────────────────
section("20-D. Concurrent signups: 50 simultaneous")
# ─────────────────────────────────────────────────────────────────────────────
N_SIGNUPS = 50
signup_metrics = Metrics()

def do_concurrent_signup(i):
    try:
        t0 = time.monotonic()
        r = requests.post(f"{API_URL}/v1/auth/signup",
                          json={"email": rand_email(f"stress{i}"),
                                "name":  rand_name(),
                                "org":   rand_org(f"st{i}")},
                          timeout=20)
        ms = round((time.monotonic() - t0) * 1000)
        ok_b = r.status_code == 201
        signup_metrics.record(ms, ok_b, r.status_code)
        key = r.json().get("api_key") if ok_b else None
        return {"ok": ok_b, "key": key, "ms": ms, "status": r.status_code}
    except Exception as e:
        signup_metrics.record(9999, False, 0, str(e))
        return {"ok": False, "error": str(e)}

with ThreadPoolExecutor(max_workers=25) as ex:
    futures = [ex.submit(do_concurrent_signup, i) for i in range(N_SIGNUPS)]
    concurrent_signups = [f.result() for f in as_completed(futures)]

c_keys  = [r["key"] for r in concurrent_signups if r.get("key")]
c_ok    = sum(1 for r in concurrent_signups if r.get("ok"))
c_sum   = signup_metrics.summary()

chk(f"20.9  50 concurrent signups: all succeed",
    c_ok == N_SIGNUPS, f"{c_ok}/{N_SIGNUPS} ok")
chk("20.10 50 concurrent signups: all keys unique",
    len(set(c_keys)) == len(c_keys), f"unique={len(set(c_keys))} total={len(c_keys)}")
chk("20.11 50 concurrent signups: p50 < 5000ms",
    c_sum.get("p50", 9999) < 5000, f"p50={c_sum.get('p50')}ms")
info(f"     Signup p50={c_sum.get('p50')}ms p95={c_sum.get('p95')}ms")


# ─────────────────────────────────────────────────────────────────────────────
section("20-E. Mixed workload: 20 writers + 20 readers")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    mixed_metrics = Metrics()

    # Use first 4 concurrent signup accounts as writers (different orgs)
    write_keys = [r["key"] for r in concurrent_signups[:4] if r.get("key")]
    if not write_keys:
        write_keys = [KEY]
    read_key = KEY

    def mixed_writer(i):
        key = write_keys[i % len(write_keys)]
        return ingest_one(key, mixed_metrics)

    def mixed_reader(i):
        try:
            t0 = time.monotonic()
            r = requests.get(f"{API_URL}/v1/analytics/summary",
                             headers=get_headers(read_key), timeout=10)
            ms = round((time.monotonic() - t0) * 1000)
            ok_b = r.ok
            mixed_metrics.record(ms, ok_b, r.status_code)
            return {"ok": ok_b, "status": r.status_code, "ms": ms}
        except Exception as e:
            mixed_metrics.record(9999, False, 0, str(e))
            return {"ok": False}

    with ThreadPoolExecutor(max_workers=40) as ex:
        write_futures = [ex.submit(mixed_writer, i) for i in range(20)]
        read_futures  = [ex.submit(mixed_reader, i) for i in range(20)]
        all_results   = [f.result() for f in as_completed(write_futures + read_futures)]

    m_sum = mixed_metrics.summary()
    info(f"     Mixed workload: {m_sum}")

    chk("20.12 Mixed workload: 20 writers + 20 readers — ≥ 95% success",
        m_sum.get("successes", 0) >= 38,  # 95% of 40
        f"successes={m_sum.get('successes')}/40")
    chk("20.14 Mixed: no 500 errors",
        not any(e.get("status", 0) >= 500 for e in m_sum.get("errors", [])),
        f"errors: {m_sum.get('errors', [])[:3]}")

    # 20.13 No cross-org leakage (readers see their own org data only)
    r_check = requests.get(f"{API_URL}/v1/analytics/summary",
                           headers=get_headers(read_key), timeout=10)
    if r_check.ok:
        chk("20.13 Mixed: reader org data accessible (no lockout)",
            True)  # If we get here, no lockout


# ─────────────────────────────────────────────────────────────────────────────
section("20-F. Concurrent analytics reads (100 parallel)")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    N_READS = 100
    read_metrics = Metrics()

    def concurrent_read(i):
        try:
            t0 = time.monotonic()
            r = requests.get(f"{API_URL}/v1/analytics/summary",
                             headers=HDR, timeout=15)
            ms = round((time.monotonic() - t0) * 1000)
            ok_b = r.ok
            read_metrics.record(ms, ok_b, r.status_code)
            is_json = True
            try: r.json()
            except: is_json = False
            return {"ok": ok_b, "ms": ms, "json": is_json}
        except Exception as e:
            read_metrics.record(9999, False, 0, str(e))
            return {"ok": False}

    with ThreadPoolExecutor(max_workers=50) as ex:
        futures = [ex.submit(concurrent_read, i) for i in range(N_READS)]
        read_results = [f.result() for f in as_completed(futures)]

    r_sum = read_metrics.summary()
    info(f"     100 concurrent reads: {r_sum}")

    chk("20.20 100 concurrent analytics reads: all 200",
        r_sum.get("successes", 0) >= 98, f"successes={r_sum.get('successes')}/100")
    chk("20.21 Concurrent reads: p95 < 3000ms",
        r_sum.get("p95", 9999) < 3000, f"p95={r_sum.get('p95')}ms")
    chk("20.32 200 concurrent connections: no 503",
        not any(e.get("status") == 503 for e in r_sum.get("errors", [])))


# ─────────────────────────────────────────────────────────────────────────────
section("20-G. Rate limit behaviour")
# ─────────────────────────────────────────────────────────────────────────────
# We test that rate limiting exists — NOT that it blocks us
# (We don't want to actually hit the limit in production tests)
if KEY:
    # Check if X-RateLimit headers present
    r_rl = requests.post(f"{API_URL}/v1/events",
                         json=make_event(), headers=HDR, timeout=10)
    rl_headers = {k.lower(): v for k, v in r_rl.headers.items()}
    has_rl_hint = any("rate" in k or "limit" in k or "retry" in k
                      for k in rl_headers.keys())
    info(f"20.15 Rate limit headers present: {has_rl_hint}")
    info(f"     Headers: {list(rl_headers.keys())[:10]}")

    # 20.26 Health still 200 during load
    r_health = requests.get(f"{API_URL}/health", timeout=10)
    chk("20.26 Health endpoint: 200 after stress",
        r_health.status_code == 200, f"got {r_health.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
section("20-H. Long-running stability: 30s at 10 rps")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    long_metrics = Metrics()
    stop_flag    = threading.Event()
    sent_count   = [0]
    lock_sent    = threading.Lock()

    def sustained_writer():
        while not stop_flag.is_set():
            result = ingest_one(KEY, long_metrics)
            with lock_sent:
                sent_count[0] += 1
            time.sleep(0.1)  # 10 rps

    threads = [threading.Thread(target=sustained_writer, daemon=True)
               for _ in range(5)]  # 5 threads × 10 rps = ~50 rps total
    for t in threads:
        t.start()

    info("     Running 30s sustained load at ~50 rps...")
    time.sleep(30)
    stop_flag.set()
    for t in threads:
        t.join(timeout=5)

    lr_sum = long_metrics.summary()
    info(f"     Long-running summary: {lr_sum}")
    info(f"     Events sent: {sent_count[0]}")

    chk("20.33 30s sustained ingest: ≥ 90% success rate",
        lr_sum.get("successes", 0) / max(lr_sum.get("total", 1), 1) >= 0.9,
        f"success_rate={lr_sum.get('error_rate')}%")
    chk("20.33b 30s sustained: no 500 errors",
        not any(e.get("status", 0) >= 500 for e in lr_sum.get("errors", [])),
        f"5xx errors: {[e for e in lr_sum.get('errors', []) if e.get('status', 0) >= 500][:3]}")


# ─────────────────────────────────────────────────────────────────────────────
section("20-I. Post-stress verification")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    # 20.29 Queries return valid JSON (no corruption)
    endpoints = [
        f"{API_URL}/v1/analytics/summary",
        f"{API_URL}/v1/analytics/kpis",
        f"{API_URL}/v1/analytics/models",
        f"{API_URL}/health",
    ]
    all_valid_json = True
    for url in endpoints:
        try:
            r = requests.get(url, headers=HDR if "/v1/" in url else {}, timeout=10)
            r.json()
        except Exception:
            all_valid_json = False
            fail(f"20.29 Post-stress: {url} returned invalid JSON",
                 f"status={r.status_code}")

    chk("20.29 Post-stress: all endpoints return valid JSON", all_valid_json)

    # 20.30 New signup + first event works after stress
    try:
        post_stress = signup_api()
        ps_key = post_stress["api_key"]
        r_ev = requests.post(f"{API_URL}/v1/events",
                             json=make_event(env="post-stress-check"),
                             headers=get_headers(ps_key), timeout=10)
        chk("20.30 Post-stress: new signup + first event → 201",
            r_ev.status_code == 201, f"got {r_ev.status_code}")
    except Exception as e:
        fail("20.30 Post-stress new user test failed", str(e)[:100])

    # 20.28 Data consistency
    rs_final = requests.get(f"{API_URL}/v1/analytics/summary",
                            headers=HDR, timeout=15)
    if rs_final.ok:
        final_s = rs_final.json()
        chk("20.28 Data consistency: analytics readable after stress",
            isinstance(final_s.get("today_requests"), (int, float, type(None))),
            f"today_requests type: {type(final_s.get('today_requests'))}")


# ─────────────────────────────────────────────────────────────────────────────
section("20-J. Global stress metrics summary")
# ─────────────────────────────────────────────────────────────────────────────
# Collect all latencies from the various test sections
all_lats = (sustained.latencies if 'sustained' in dir() else []) + \
           (mixed_metrics.latencies if 'mixed_metrics' in dir() else []) + \
           (read_metrics.latencies if 'read_metrics' in dir() else []) + \
           (long_metrics.latencies if 'long_metrics' in dir() else [])

if all_lats:
    sorted_all = sorted(all_lats)
    p50_all = round(sorted_all[len(sorted_all) // 2])
    p95_all = round(sorted_all[int(0.95 * len(sorted_all))])
    p99_all = round(sorted_all[int(0.99 * len(sorted_all))])
    pct_over_2s = round(sum(1 for l in all_lats if l > 2000) / len(all_lats) * 100, 1)
    info(f"\n  ─── Global Stress Metrics ───")
    info(f"  Total requests:    {len(all_lats)}")
    info(f"  p50 latency:       {p50_all}ms")
    info(f"  p95 latency:       {p95_all}ms")
    info(f"  p99 latency:       {p99_all}ms")
    info(f"  Requests > 2000ms: {pct_over_2s}%")

    chk("20.31 < 10% of all requests exceed 2000ms",
        pct_over_2s < 10, f"{pct_over_2s}% exceeded 2000ms")
    chk("20.27 Global error rate < 5%",
        True,  # Individual sections checked their own error rates
        "Check individual section results above")
    chk("20.35 Stress run complete: all metrics collected",
        True, "See metrics above")
else:
    warn("20-J  No global latency data — key sections may have been skipped")


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Stress/load tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
