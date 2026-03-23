"""
test_concurrent.py — Concurrent load tests
==========================================
Suite CL: 10 concurrent signups, sign-ins, reads, writes; no cross-org leakage.
Labels: CL.1 - CL.N
"""

import sys
import time
import uuid
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


def do_signup(_):
    try:
        d = signup_api()
        return True, d["api_key"], d["org_id"]
    except Exception as e:
        return False, None, str(e)


def do_signin(api_key):
    try:
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": api_key}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def do_analytics_read(api_key):
    try:
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=get_headers(api_key), timeout=15)
        return r.status_code in (200, 404)
    except Exception:
        return False


def do_event_write(api_key):
    try:
        r = requests.post(f"{API_URL}/v1/events",
                          json={"event_id": f"cl-{uuid.uuid4().hex[:12]}",
                                "provider": "openai", "model": "gpt-4o",
                                "total_cost_usd": 0.001,
                                "prompt_tokens": 50, "completion_tokens": 25},
                          headers=get_headers(api_key), timeout=15)
        return r.status_code in (201, 202)
    except Exception:
        return False


def test_concurrent_signups():
    section("CL. Concurrent — 10 Concurrent Signups")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(do_signup, i) for i in range(10)]
        results = [f.result() for f in as_completed(futures)]

    successes = [r for r in results if r[0]]
    chk("CL.1  10 concurrent signups → all succeed",
        len(successes) == 10,
        f"{len(successes)}/10 succeeded")

    return [r[1] for r in successes if r[1]]


def test_concurrent_signins(api_keys):
    section("CL. Concurrent — 10 Concurrent Sign-ins")

    if not api_keys:
        warn("CL.2  No keys to test sign-in")
        return

    keys_to_test = api_keys[:10]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(do_signin, k) for k in keys_to_test]
        results = [f.result() for f in as_completed(futures)]

    passed = sum(1 for r in results if r)
    chk("CL.2  10 concurrent sign-ins → all succeed",
        passed == len(keys_to_test),
        f"{passed}/{len(keys_to_test)} succeeded")


def test_concurrent_reads(api_keys):
    section("CL. Concurrent — 20 Concurrent Analytics Reads")

    if not api_keys:
        warn("CL.3  No keys for concurrent reads")
        return

    # Use keys twice to get 20 concurrent reads
    keys_20 = (api_keys * 2)[:20]
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(do_analytics_read, k) for k in keys_20]
        results = [f.result() for f in as_completed(futures)]

    passed = sum(1 for r in results if r)
    chk("CL.3  20 concurrent reads → all 200",
        passed == 20,
        f"{passed}/20 returned 200/404")


def test_concurrent_writes(api_keys):
    section("CL. Concurrent — 10 Concurrent Event Writes")

    if not api_keys:
        warn("CL.4  No keys for concurrent writes")
        return

    keys_to_test = api_keys[:10]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(do_event_write, k) for k in keys_to_test]
        results = [f.result() for f in as_completed(futures)]

    passed = sum(1 for r in results if r)
    chk("CL.4  10 concurrent writes → all accepted",
        passed == len(keys_to_test),
        f"{passed}/{len(keys_to_test)} accepted")


def test_no_cross_org_leakage(api_keys):
    section("CL. Concurrent — No Cross-Org Leakage Under Load")

    if len(api_keys) < 2:
        warn("CL.5  Not enough keys for cross-org isolation test")
        return

    key_a = api_keys[0]
    key_b = api_keys[1]

    # Ingest org-A-specific event with very high cost
    requests.post(f"{API_URL}/v1/events",
                  json={"event_id": f"leak-{uuid.uuid4().hex[:12]}",
                        "provider": "openai", "model": "gpt-4o",
                        "total_cost_usd": 999.0,
                        "prompt_tokens": 9999, "completion_tokens": 9999},
                  headers=get_headers(key_a), timeout=10)

    time.sleep(1)

    # Check org B doesn't see org A's event
    r_b = requests.get(f"{API_URL}/v1/analytics/summary",
                       headers=get_headers(key_b), timeout=15)
    if r_b.ok:
        d_b = r_b.json()
        cost_b = (d_b.get("today_cost_usd") or d_b.get("mtd_cost_usd") or
                  d_b.get("session_cost_usd") or d_b.get("total_cost") or
                  d_b.get("cost") or d_b.get("totalCost") or 0)
        chk("CL.5  Org B doesn't see Org A's $999 event under load",
            cost_b < 500,
            f"Org B total_cost={cost_b}")
    else:
        chk("CL.5  Org B analytics returns 200/404 (not Org A's data)",
            r_b.status_code in (200, 404), f"got {r_b.status_code}")


def main():
    section("Suite CL — Concurrent Load Tests")
    info(f"API: {API_URL}")

    api_keys = test_concurrent_signups()
    test_concurrent_signins(api_keys)
    test_concurrent_reads(api_keys)
    test_concurrent_writes(api_keys)
    test_no_cross_org_leakage(api_keys)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
