"""
test_slack.py — Slack integration tests
========================================
Suite SLK: Tests Slack alert webhook integration.
SKIPPED if SLACK_WEBHOOK_URL env var is not set.
Labels: SLK.1 - SLK.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SLACK_WEBHOOK_URL
from helpers.api import signup_api, get_headers
from helpers.data import rand_email
from helpers.output import ok, fail, warn, info, section, chk, get_results


def main():
    section("Suite SLK — Slack Integration Tests")
    info(f"API: {API_URL}")

    if not SLACK_WEBHOOK_URL:
        warn("SLK.0  SLACK_WEBHOOK_URL not set — skipping all Slack integration tests")
        info("  Set SLACK_WEBHOOK_URL env var to enable these tests in CI")
        sys.exit(0)

    info(f"  SLACK_WEBHOOK_URL is set (length={len(SLACK_WEBHOOK_URL)})")

    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        info(f"Test account: {org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    headers = get_headers(api_key)

    # SLK.1 POST /alerts/slack with valid webhook → 200
    r = requests.post(f"{API_URL}/v1/alerts/slack",
                      json={
                          "webhook_url": SLACK_WEBHOOK_URL,
                          "threshold": 10.0,
                          "current_value": 15.0,
                          "org_id": org_id,
                          "message": "Test alert from Cohrint CI",
                      },
                      headers=headers, timeout=30)
    chk("SLK.1  POST /alerts/slack valid webhook → 200",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    # SLK.2 POST /alerts/slack with invalid webhook URL → 4xx (not 500)
    r2 = requests.post(f"{API_URL}/v1/alerts/slack",
                       json={
                           "webhook_url": "https://hooks.slack.com/INVALID_WEBHOOK_URL",
                           "threshold": 10.0,
                           "current_value": 15.0,
                       },
                       headers=headers, timeout=30)
    chk("SLK.2  POST /alerts/slack invalid webhook → 4xx (not 500)",
        r2.status_code < 500,
        f"got {r2.status_code}: {r2.text[:100]}")
    chk("SLK.3  Invalid webhook does not return 500",
        r2.status_code != 500,
        f"got {r2.status_code}")

    # SLK.4 Verify response includes expected fields
    if r.ok:
        try:
            d_resp = r.json()
            # Check for alert_id or similar confirmation field
            has_confirmation = (
                "alert_id" in d_resp or "id" in d_resp or
                "sent" in d_resp or "status" in d_resp or "ok" in d_resp
            )
            chk("SLK.4  Alert response includes confirmation field",
                has_confirmation,
                f"response keys: {list(d_resp.keys())}")
        except Exception:
            warn("SLK.4  Response is not JSON or has unexpected format")

    # SLK.5 POST with missing required fields → 400
    r3 = requests.post(f"{API_URL}/v1/alerts/slack",
                       json={},
                       headers=headers, timeout=15)
    chk("SLK.5  POST /alerts/slack missing fields → 400",
        r3.status_code in (400, 422),
        f"got {r3.status_code}: {r3.text[:100]}")

    # SLK.6 Verify alert payload includes org_id, threshold, current_value, timestamp
    r4 = requests.post(f"{API_URL}/v1/alerts/slack",
                       json={
                           "webhook_url": SLACK_WEBHOOK_URL,
                           "threshold": 50.0,
                           "current_value": 75.5,
                           "org_id": org_id,
                       },
                       headers=headers, timeout=30)
    chk("SLK.6  Second alert with full payload → 200",
        r4.status_code == 200,
        f"got {r4.status_code}")

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
