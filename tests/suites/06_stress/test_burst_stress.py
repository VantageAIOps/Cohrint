"""
test_burst_stress.py — Burst and stress tests
=============================================
Suite BS: 200-event bursts, oversized payloads, rapid key rotations.
Labels: BS.1 - BS.N
"""

import sys
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers
from helpers.data import rand_tag
from helpers.output import ok, fail, warn, info, section, chk, get_results


def send_event(headers, i):
    """Send a single event, return (status_code, ok)."""
    try:
        r = requests.post(f"{API_URL}/v1/events",
                          json={"model": "gpt-4o",
                                "cost": 0.001,
                                "tokens": {"prompt": 50, "completion": 25},
                                "timestamp": int(time.time() * 1000) + i,
                                "tags": {"burst": str(i)}},
                          headers=headers, timeout=15)
        return r.status_code, r.ok
    except Exception as e:
        return 0, False


def test_burst_200_events(api_key):
    section("BS. Stress — 200-Event Burst in 2s")

    headers = get_headers(api_key)
    start = time.monotonic()

    statuses = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(send_event, headers, i) for i in range(200)]
        for f in as_completed(futures):
            status, ok_resp = f.result()
            statuses.append(status)

    elapsed = time.monotonic() - start
    accepted = sum(1 for s in statuses if s in (201, 202))
    errors_5xx = sum(1 for s in statuses if s >= 500)

    chk("BS.1  200-event burst: all 200 sent", len(statuses) == 200,
        f"sent {len(statuses)}")
    chk("BS.2  Burst: >= 180 events accepted (201/202)",
        accepted >= 180,
        f"accepted={accepted}/200, statuses={set(statuses)}")
    chk("BS.3  Burst: no 5xx errors", errors_5xx == 0,
        f"{errors_5xx} 5xx errors")
    chk("BS.4  Burst completes in < 30s", elapsed < 30,
        f"took {elapsed:.1f}s")
    info(f"  Burst: {accepted}/200 accepted in {elapsed:.1f}s")


def test_500_sustained_batch(api_key):
    section("BS. Stress — 500-Event Sustained Batch")

    headers = get_headers(api_key)
    batch = [
        {"model": "gpt-4o", "cost": 0.0005,
         "tokens": {"prompt": 30, "completion": 15},
         "timestamp": int(time.time() * 1000) + i}
        for i in range(500)
    ]

    r = requests.post(f"{API_URL}/v1/events/batch",
                      json={"events": batch},
                      headers=headers, timeout=60)
    chk("BS.5  500-event batch accepted (201/202)",
        r.status_code in (201, 202),
        f"got {r.status_code}: {r.text[:100]}")


def test_bad_keys_server_stable():
    section("BS. Stress — 50 Bad Key Requests")

    statuses = []
    for i in range(50):
        r = requests.post(f"{API_URL}/v1/events",
                          json={"model": "gpt-4o", "cost": 0.001,
                                "tokens": {"prompt": 50, "completion": 25},
                                "timestamp": int(time.time() * 1000)},
                          headers={"Authorization": f"Bearer vnt_badkey_{rand_tag()}"},
                          timeout=10)
        statuses.append(r.status_code)

    all_401 = all(s == 401 for s in statuses)
    no_5xx  = all(s < 500 for s in statuses)
    chk("BS.6  50 bad-key requests → all 401", all_401,
        f"statuses: {set(statuses)}")
    chk("BS.7  Server stable under bad-key flood (no 5xx)", no_5xx,
        f"5xx statuses: {[s for s in statuses if s >= 500]}")


def test_max_batch_size(api_key):
    section("BS. Stress — Max Batch Size (500 events)")

    headers = get_headers(api_key)
    batch = [
        {"model": "gpt-4o", "cost": 0.001,
         "tokens": {"prompt": 50, "completion": 25},
         "timestamp": int(time.time() * 1000) + i}
        for i in range(500)
    ]

    r = requests.post(f"{API_URL}/v1/events/batch",
                      json={"events": batch},
                      headers=headers, timeout=60)
    chk("BS.8  Max 500-event batch → 201/202",
        r.status_code in (201, 202),
        f"got {r.status_code}: {r.text[:100]}")


def test_oversized_payload(api_key):
    section("BS. Stress — Oversized Single Event")

    headers = get_headers(api_key)
    # Create a large payload (tags with lots of data)
    large_tags = {f"key_{i}": "x" * 100 for i in range(100)}
    large_event = {
        "model": "gpt-4o",
        "cost": 0.001,
        "tokens": {"prompt": 50, "completion": 25},
        "timestamp": int(time.time() * 1000),
        "tags": large_tags,
        "metadata": {"large_field": "y" * 10000},
    }

    r = requests.post(f"{API_URL}/v1/events", json=large_event,
                      headers=headers, timeout=15)
    # Should either accept (201/202) or reject cleanly (400/413), NOT 500
    chk("BS.9  Oversized event → 201/202/400/413 (not 500)",
        r.status_code in (201, 202, 400, 413),
        f"got {r.status_code}: {r.text[:100]}")


def test_rapid_rotations(api_key):
    section("BS. Stress — 3 Rapid Key Rotations")

    current_key = api_key
    for i in range(3):
        r = requests.post(f"{API_URL}/v1/auth/rotate",
                          headers=get_headers(current_key), timeout=15)
        chk(f"BS.10.{i+1} Rotation {i+1} → 200", r.status_code == 200,
            f"got {r.status_code}: {r.text[:100]}")
        if r.ok:
            d = r.json()
            new_key = d.get("api_key") or d.get("new_key") or d.get("key")
            if new_key:
                current_key = new_key
            else:
                break

    # After 3 rotations, current key should still work
    r_final = requests.post(f"{API_URL}/v1/auth/session",
                            json={"api_key": current_key}, timeout=15)
    chk("BS.11 Key after 3 rotations still works", r_final.status_code == 200,
        f"got {r_final.status_code}")


def main():
    section("Suite BS — Burst Stress Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_burst_200_events(api_key)
    test_500_sustained_batch(api_key)
    test_bad_keys_server_stable()
    test_max_batch_size(api_key)
    test_oversized_payload(api_key)
    test_rapid_rotations(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
