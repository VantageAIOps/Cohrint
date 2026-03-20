"""
test_sustained.py — Sustained load tests
=========================================
Suite SL: 100-event sequential ingest, login/logout cycles, throughput.
Labels: SL.1 - SL.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_sustained_ingest(api_key):
    section("SL. Sustained — 100-Event Sequential Ingest over ~10s")

    headers = get_headers(api_key)
    start = time.monotonic()
    accepted = 0
    latencies = []

    for i in range(100):
        t0 = time.monotonic()
        try:
            r = requests.post(f"{API_URL}/v1/events",
                              json={"model": "gpt-4o",
                                    "cost": 0.001,
                                    "tokens": {"prompt": 50, "completion": 25},
                                    "timestamp": int(time.time() * 1000) + i},
                              headers=headers, timeout=15)
            ms = (time.monotonic() - t0) * 1000
            latencies.append(ms)
            if r.status_code in (201, 202):
                accepted += 1
        except Exception as e:
            warn(f"  Event {i} failed: {e}")

    elapsed = time.monotonic() - start
    throughput = 100 / elapsed if elapsed > 0 else 0

    chk("SL.1  100 events ingested sequentially", accepted >= 90,
        f"{accepted}/100 accepted")
    chk("SL.2  Throughput > 5 events/sec", throughput > 5,
        f"throughput={throughput:.1f} ev/s")
    chk("SL.3  Sustained ingest completes in < 60s", elapsed < 60,
        f"took {elapsed:.1f}s")
    info(f"  Throughput: {throughput:.1f} ev/s over {elapsed:.1f}s")

    return accepted


def test_analytics_consistent_after_ingest(api_key, events_count):
    section("SL. Sustained — Analytics Consistent After Ingest")

    time.sleep(2)  # Brief wait for data propagation

    headers = get_headers(api_key)
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    chk("SL.4  Analytics reachable after sustained write", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        cost = (d.get("total_cost") or d.get("cost") or d.get("totalCost") or
                d.get("summary", {}).get("total_cost") or 0)
        chk("SL.5  Analytics shows non-zero cost after 100-event ingest",
            cost > 0, f"cost={cost}")


def test_login_logout_cycles(api_key):
    section("SL. Sustained — 10 Login/Logout Cycles")

    successes = 0
    for i in range(10):
        # Login
        r_in = requests.post(f"{API_URL}/v1/auth/session",
                             json={"api_key": api_key}, timeout=15)
        if r_in.status_code != 200:
            warn(f"  Cycle {i+1} login failed: {r_in.status_code}")
            continue

        cookies = r_in.cookies

        # Logout
        r_out = requests.post(f"{API_URL}/v1/auth/logout",
                              cookies=cookies, timeout=15)
        if r_out.status_code == 200:
            successes += 1

    chk("SL.6  10 login/logout cycles succeed",
        successes >= 9,
        f"{successes}/10 cycles completed")


def test_no_latency_degradation(api_key):
    section("SL. Sustained — No Latency Degradation")

    headers = get_headers(api_key)
    early_latencies = []
    late_latencies = []

    # First 10 requests
    for i in range(10):
        t0 = time.monotonic()
        requests.post(f"{API_URL}/v1/events",
                      json={"model": "gpt-4o", "cost": 0.001,
                            "tokens": {"prompt": 50, "completion": 25},
                            "timestamp": int(time.time() * 1000) + i},
                      headers=headers, timeout=15)
        early_latencies.append((time.monotonic() - t0) * 1000)

    # 50 more requests
    for i in range(50):
        requests.post(f"{API_URL}/v1/events",
                      json={"model": "gpt-4o", "cost": 0.001,
                            "tokens": {"prompt": 50, "completion": 25},
                            "timestamp": int(time.time() * 1000) + 10 + i},
                      headers=headers, timeout=15)

    # Last 10 requests
    for i in range(10):
        t0 = time.monotonic()
        requests.post(f"{API_URL}/v1/events",
                      json={"model": "gpt-4o", "cost": 0.001,
                            "tokens": {"prompt": 50, "completion": 25},
                            "timestamp": int(time.time() * 1000) + 60 + i},
                      headers=headers, timeout=15)
        late_latencies.append((time.monotonic() - t0) * 1000)

    avg_early = sum(early_latencies) / len(early_latencies)
    avg_late  = sum(late_latencies)  / len(late_latencies)

    # Late latency should not be > 3x early latency
    ratio = avg_late / avg_early if avg_early > 0 else 1.0
    chk("SL.7  Latency not degraded > 3x over sustained run",
        ratio < 3.0,
        f"avg_early={avg_early:.0f}ms, avg_late={avg_late:.0f}ms, ratio={ratio:.1f}x")
    info(f"  Early avg: {avg_early:.0f}ms, Late avg: {avg_late:.0f}ms, ratio: {ratio:.1f}x")


def main():
    section("Suite SL — Sustained Load Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    events_count = test_sustained_ingest(api_key)
    test_analytics_consistent_after_ingest(api_key, events_count)
    test_login_logout_cycles(api_key)
    test_no_latency_degradation(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
