"""
test_semantic_cache.py — Semantic Caching / Cache Analytics Tests
=================================================================
Suite SC: Phase 1 (cache analytics KPIs) + Phase 2 (exact-match dedup detection).

Phase 1 checks:
  SC.1  POST event with cache_tokens → D1 stores it
  SC.2  GET /v1/analytics/kpis → cache_tokens_total > 0
  SC.3  GET /v1/analytics/kpis → cache_savings_usd > 0
  SC.4  GET /v1/analytics/kpis → cache_hit_rate_pct > 0

Phase 2 checks:
  SC.5  POST track_llm_call with prompt_hash → first call returns no cache_warning
  SC.6  POST same prompt_hash again → response contains cache_warning (duplicate detected)
  SC.7  GET /v1/analytics/kpis → duplicate_calls >= 1
  SC.8  GET /v1/analytics/kpis → wasted_cost_usd > 0
"""

import sys
import time
import uuid
import hashlib
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.output import section, chk, get_results


def make_event(event_id=None, **kwargs):
    base = {
        "event_id":          event_id or f"sc-{uuid.uuid4()}",
        "provider":          "anthropic",
        "model":             "claude-sonnet-4-6",
        "prompt_tokens":     1000,
        "completion_tokens": 500,
        "total_cost_usd":    0.0045,
        "latency_ms":        320,
    }
    base.update(kwargs)
    return base


def poll_kpis(headers, predicate, attempts=6, delay=3):
    """Poll GET /v1/analytics/kpis until predicate(data) is True or attempts exhausted."""
    for _ in range(attempts):
        r = requests.get(f"{API_URL}/v1/analytics/kpis", headers=headers, timeout=15)
        if r.ok:
            data = r.json()
            if predicate(data):
                return data
        time.sleep(delay)
    return r.json() if r.ok else {}


def test_cache_analytics(headers):
    section("SC Phase 1 — Cache Analytics KPIs")

    # Post event with 500 cache tokens for claude-sonnet-4-6
    ev = make_event(cache_tokens=500)
    r = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=15)
    chk("SC.1  POST event with cache_tokens=500 → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")

    # Wait for D1 write to propagate, then check KPIs
    data = poll_kpis(headers, lambda d: d.get("cache_tokens_total", 0) > 0)

    chk("SC.2  GET /kpis → cache_tokens_total > 0",
        data.get("cache_tokens_total", 0) > 0,
        f"got cache_tokens_total={data.get('cache_tokens_total')}")

    chk("SC.3  GET /kpis → cache_savings_usd > 0",
        data.get("cache_savings_usd", 0) > 0,
        f"got cache_savings_usd={data.get('cache_savings_usd')}")

    chk("SC.4  GET /kpis → cache_hit_rate_pct > 0",
        data.get("cache_hit_rate_pct", 0) > 0,
        f"got cache_hit_rate_pct={data.get('cache_hit_rate_pct')}")


def test_dedup_detection(headers):
    section("SC Phase 2 — Exact-Match Dedup Detection")

    prompt = "explain caching in distributed systems"
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:32]

    # First call — should NOT trigger duplicate warning
    ev1 = make_event(
        event_id=f"sc-dedup-{uuid.uuid4()}",
        prompt_hash=prompt_hash,
        total_cost_usd=0.0045,
    )
    r1 = requests.post(f"{API_URL}/v1/events", json=ev1, headers=headers, timeout=15)
    chk("SC.5  First POST with prompt_hash → 201, no cache_warning",
        r1.status_code == 201 and "cache_warning" not in r1.json(),
        f"got {r1.status_code}: {r1.text[:200]}")

    # Wait for KV write to propagate (async after response)
    time.sleep(5)

    # Second call with same hash — should detect duplicate
    ev2 = make_event(
        event_id=f"sc-dedup-{uuid.uuid4()}",
        prompt_hash=prompt_hash,
        total_cost_usd=0.0045,
    )
    r2 = requests.post(f"{API_URL}/v1/events", json=ev2, headers=headers, timeout=15)
    body2 = r2.json()
    chk("SC.6  Second POST with same prompt_hash → cache_warning present",
        r2.status_code == 201 and "cache_warning" in body2,
        f"got {r2.status_code}: {body2}")

    # KPIs should now show duplicate_calls >= 1 and wasted_cost_usd > 0
    data = poll_kpis(headers, lambda d: d.get("duplicate_calls", 0) >= 1)

    chk("SC.7  GET /kpis → duplicate_calls >= 1",
        data.get("duplicate_calls", 0) >= 1,
        f"got duplicate_calls={data.get('duplicate_calls')}")

    chk("SC.8  GET /kpis → wasted_cost_usd > 0",
        data.get("wasted_cost_usd", 0) > 0,
        f"got wasted_cost_usd={data.get('wasted_cost_usd')}")


def run():
    api_key, _org_id, _cookies = fresh_account(prefix="sc")
    headers = get_headers(api_key)

    test_cache_analytics(headers)
    test_dedup_detection(headers)

    results = get_results()
    passed = results["passed"]
    total  = results["passed"] + results["failed"]
    print(f"\nSuite: SC  {passed}/{total} passed")
    return results["failed"] == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
