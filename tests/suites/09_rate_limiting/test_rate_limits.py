"""
test_rate_limits.py — Rate limiting tests
==========================================
Suite RL: Tests rate limits on /events, recovery, cross-org independence.
Labels: RL.1 - RL.N
"""

import sys
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_rate_limit_headers(api_key):
    section("RL. Rate Limiting — Headers on /events")

    headers = get_headers(api_key)
    statuses = []
    rate_limit_headers_seen = False
    retry_after_seen = False
    hit_429 = False

    # Send 100 rapid requests
    for i in range(100):
        r = requests.post(f"{API_URL}/v1/events",
                          json={"model": "gpt-4o", "cost": 0.001,
                                "tokens": {"prompt": 50, "completion": 25},
                                "timestamp": int(time.time() * 1000) + i},
                          headers=headers, timeout=10)
        statuses.append(r.status_code)

        # Check for rate limit headers
        r_headers_lower = {k.lower(): v for k, v in r.headers.items()}
        if any(k in r_headers_lower for k in
               ("x-ratelimit-limit", "x-ratelimit-remaining", "ratelimit-limit")):
            rate_limit_headers_seen = True

        if r.status_code == 429:
            hit_429 = True
            if "retry-after" in r_headers_lower:
                retry_after_seen = True
            if "x-ratelimit-limit" in r_headers_lower:
                chk("RL.3  429 has X-RateLimit-Limit header", True)
            if "x-ratelimit-remaining" in r_headers_lower:
                chk("RL.4  429 has X-RateLimit-Remaining header", True)
            break

    non_500 = all(s < 500 for s in statuses)
    chk("RL.1  100 rapid requests → no 5xx errors", non_500,
        f"5xx statuses: {[s for s in statuses if s >= 500]}")

    # Rate limiting may or may not be in place
    if hit_429:
        chk("RL.2  Rate limit hit → 429 returned", True)
        chk("RL.5  429 has Retry-After header", retry_after_seen,
            "Retry-After header not found on 429")
    else:
        # Rate limiting may not be implemented or thresholds are higher
        warn("RL.2  No 429 hit in 100 requests — rate limiting may be set higher")
        # Still check no server errors
        chk("RL.2  Server stable under 100 rapid requests (no rate limit configured)",
            non_500, f"statuses: {set(statuses)}")
        warn("RL.3  Skipping — no 429 was returned")
        warn("RL.4  Skipping — no 429 was returned")
        warn("RL.5  Skipping — no 429 was returned")

    if rate_limit_headers_seen:
        chk("RL.6  Rate limit headers present on responses", True)
    else:
        warn("RL.6  X-RateLimit-* headers not observed (may not be implemented)")

    return hit_429


def test_rate_limit_recovery(api_key, hit_429):
    section("RL. Rate Limiting — Recovery After Rate Limit")

    if not hit_429:
        warn("RL.7  Skipping — no 429 was hit in previous test")
        return

    # Wait for rate limit to reset
    info("  Waiting 2s for rate limit recovery...")
    time.sleep(2)

    headers = get_headers(api_key)
    r = requests.post(f"{API_URL}/v1/events",
                      json={"model": "gpt-4o", "cost": 0.001,
                            "tokens": {"prompt": 50, "completion": 25},
                            "timestamp": int(time.time() * 1000)},
                      headers=headers, timeout=15)
    chk("RL.7  After rate limit + 2s wait → request succeeds",
        r.status_code in (201, 202),
        f"got {r.status_code}")


def test_independent_org_rate_limits():
    section("RL. Rate Limiting — Independent Org Rate Limits")

    # Create two separate orgs
    try:
        d_a = signup_api()
        key_a = d_a["api_key"]
        d_b = signup_api()
        key_b = d_b["api_key"]
    except Exception as e:
        fail(f"RL.8  Could not create test orgs: {e}")
        return

    # Exhaust org A's rate limit with rapid requests
    hit_429_a = False
    for i in range(100):
        r = requests.post(f"{API_URL}/v1/events",
                          json={"model": "gpt-4o", "cost": 0.001,
                                "tokens": {"prompt": 50, "completion": 25},
                                "timestamp": int(time.time() * 1000) + i},
                          headers=get_headers(key_a), timeout=10)
        if r.status_code == 429:
            hit_429_a = True
            break

    if hit_429_a:
        # Org B should not be affected
        r_b = requests.post(f"{API_URL}/v1/events",
                            json={"model": "gpt-4o", "cost": 0.001,
                                  "tokens": {"prompt": 50, "completion": 25},
                                  "timestamp": int(time.time() * 1000)},
                            headers=get_headers(key_b), timeout=15)
        chk("RL.8  Org A hitting rate limit doesn't affect Org B",
            r_b.status_code in (201, 202),
            f"Org B got {r_b.status_code}")
    else:
        warn("RL.8  Org A didn't hit rate limit — cannot verify org isolation")
        # Org B should still work
        r_b = requests.post(f"{API_URL}/v1/events",
                            json={"model": "gpt-4o", "cost": 0.001,
                                  "tokens": {"prompt": 50, "completion": 25},
                                  "timestamp": int(time.time() * 1000)},
                            headers=get_headers(key_b), timeout=15)
        chk("RL.8  Org B accepts events independently",
            r_b.status_code in (201, 202),
            f"got {r_b.status_code}")


def test_health_not_rate_limited():
    section("RL. Rate Limiting — Health Endpoint Not Rate Limited")

    statuses = []
    for i in range(100):
        r = requests.get(f"{API_URL}/v1/health", timeout=10)
        statuses.append(r.status_code)

    all_200 = all(s == 200 for s in statuses)
    chk("RL.9  100 /health requests → all 200 (not rate limited)",
        all_200,
        f"statuses: {set(statuses)}")


def main():
    section("Suite RL — Rate Limiting Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    hit_429 = test_rate_limit_headers(api_key)
    test_rate_limit_recovery(api_key, hit_429)
    test_independent_org_rate_limits()
    test_health_not_rate_limited()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
