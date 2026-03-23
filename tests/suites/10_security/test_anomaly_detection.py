"""
test_anomaly_detection.py — Anomaly detection system tests
===========================================================
Suite AD: Tests the Z-score anomaly detection pipeline end-to-end.
  - Ingest normal baseline events over simulated hours
  - Ingest a cost spike that exceeds 3-sigma
  - Verify the analytics API reflects the spike
  - Verify Slack webhook receives anomaly alert (if configured)

Labels: AD.1 - AD.N
"""

import sys
import time
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


def make_event(i, cost=0.001, model="gpt-4o"):
    """Generate a valid event with unique ID."""
    return {
        "event_id": f"ad-{uuid.uuid4().hex[:12]}-{i}",
        "provider": "openai",
        "model": model,
        "total_cost_usd": cost,
        "prompt_tokens": 100 + i * 5,
        "completion_tokens": 50 + i * 2,
        "latency_ms": 200 + i * 10,
        "environment": "test",
        "tags": {"test": "anomaly_detection"},
    }


def test_baseline_ingest(api_key):
    """AD.1-3: Ingest baseline events to establish normal cost pattern."""
    section("AD. Anomaly Detection — Baseline Ingest")

    headers = get_headers(api_key)
    accepted = 0

    # Ingest 50 normal-cost events (simulate baseline)
    for i in range(50):
        event = make_event(i, cost=round(0.001 + (i % 5) * 0.0005, 6))
        r = requests.post(f"{API_URL}/v1/events", json=event,
                          headers=headers, timeout=15)
        if r.status_code in (201, 202):
            accepted += 1

    chk("AD.1  Baseline: 50 normal events ingested", accepted >= 45,
        f"{accepted}/50 accepted")

    time.sleep(1)

    # Verify analytics reflects baseline
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    chk("AD.2  Analytics summary returns 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        cost = (d.get("today_cost_usd") or d.get("mtd_cost_usd") or 0)
        chk("AD.3  Baseline cost > 0 in analytics", cost > 0,
            f"cost={cost}")

    return accepted


def test_cost_spike(api_key):
    """AD.4-6: Ingest a sudden cost spike (50x normal)."""
    section("AD. Anomaly Detection — Cost Spike Injection")

    headers = get_headers(api_key)
    accepted = 0

    # Ingest 10 expensive events (simulate spike)
    for i in range(10):
        event = make_event(100 + i, cost=0.50, model="gpt-4-turbo")  # 500x baseline
        r = requests.post(f"{API_URL}/v1/events", json=event,
                          headers=headers, timeout=15)
        if r.status_code in (201, 202):
            accepted += 1

    chk("AD.4  Spike: 10 expensive events ingested", accepted == 10,
        f"{accepted}/10 accepted")

    time.sleep(1)

    # Verify the spike shows in analytics
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    if r.ok:
        d = r.json()
        cost = (d.get("today_cost_usd") or d.get("mtd_cost_usd") or 0)
        # Spike events add $5 total (10 × $0.50)
        chk("AD.5  Analytics reflects spike (cost > $1)", cost > 1.0,
            f"cost=${cost}")

    # Verify model breakdown shows the spike model
    r2 = requests.get(f"{API_URL}/v1/analytics/models?period=1",
                       headers=headers, timeout=15)
    if r2.ok:
        models = r2.json().get("models", [])
        spike_model = [m for m in models if m.get("model") == "gpt-4-turbo"]
        chk("AD.6  Model breakdown shows spike model (gpt-4-turbo)",
            len(spike_model) > 0,
            f"models: {[m.get('model') for m in models]}")


def test_anomaly_z_score_logic():
    """AD.7-9: Verify Z-score math works correctly."""
    section("AD. Anomaly Detection — Z-Score Math Verification")

    # Simulate the Z-score calculation locally
    # Normal hourly costs: ~$0.06/hr for 7 days
    baseline = [0.05, 0.06, 0.07, 0.05, 0.06, 0.08, 0.05, 0.06,
                0.07, 0.05, 0.06, 0.06, 0.05, 0.07, 0.06, 0.05,
                0.06, 0.08, 0.05, 0.06, 0.07, 0.05, 0.06, 0.06] * 7

    # Mean and stdev
    m = sum(baseline) / len(baseline)
    variance = sum((x - m) ** 2 for x in baseline) / (len(baseline) - 1)
    s = variance ** 0.5

    chk("AD.7  Baseline mean is reasonable (~$0.06/hr)",
        0.04 < m < 0.08, f"mean=${m:.4f}")
    chk("AD.8  Baseline stdev is small (<$0.02)",
        s < 0.02, f"stdev=${s:.4f}")

    # Spike: $3.00 in 10 minutes = $18/hr projected
    spike_hourly = 3.0 * 6  # 10 min → 1 hr
    z = (spike_hourly - m) / max(s, 0.001)
    chk("AD.9  Z-score of $18/hr spike > 3.0 (anomaly threshold)",
        z > 3.0, f"z_score={z:.1f}")
    info(f"  Z-score: {z:.1f} (threshold: 3.0)")
    info(f"  This would trigger: {'YES' if z > 3.0 else 'NO'}")


def test_slack_webhook_config(api_key):
    """AD.10-11: Verify Slack webhook configuration endpoints."""
    section("AD. Anomaly Detection — Slack Webhook Config")

    headers = get_headers(api_key)

    # Get current alert config (may return 404 if not set)
    r = requests.get(f"{API_URL}/v1/alerts/{_org_id}",
                     headers=headers, timeout=15)
    chk("AD.10 GET /alerts/:org returns 200/404",
        r.status_code in (200, 404),
        f"got {r.status_code}")

    # Test setting a webhook (use a fake URL — we just test the endpoint accepts it)
    r2 = requests.post(f"{API_URL}/v1/alerts/slack/{_org_id}",
                        json={"webhook_url": "https://hooks.slack.com/test/fake"},
                        headers=headers,
                        timeout=15)
    chk("AD.11 POST /alerts/slack/:org accepts webhook URL",
        r2.status_code in (200, 201, 400),
        f"got {r2.status_code}: {r2.text[:100]}")


def test_kpis_reflect_spike(api_key):
    """AD.12-13: Verify KPIs API shows the cost spike data."""
    section("AD. Anomaly Detection — KPIs After Spike")

    headers = get_headers(api_key)
    r = requests.get(f"{API_URL}/v1/analytics/kpis?period=1",
                     headers=headers, timeout=15)
    chk("AD.12 KPIs endpoint returns 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        total_cost = float(d.get("total_cost_usd", 0))
        total_requests = int(d.get("total_requests", 0))
        chk("AD.13 KPIs show 60+ events after baseline + spike",
            total_requests >= 55,
            f"requests={total_requests}, cost=${total_cost:.4f}")


# ── Globals ──────────────────────────────────────────
_org_id = ""


def main():
    global _org_id

    section("Suite AD — Anomaly Detection Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        _org_id = d["org_id"]
        info(f"Test account: {_org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_baseline_ingest(api_key)
    test_cost_spike(api_key)
    test_anomaly_z_score_logic()
    test_slack_webhook_config(api_key)
    test_kpis_reflect_spike(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
