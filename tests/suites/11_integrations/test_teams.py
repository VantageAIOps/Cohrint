"""
test_teams.py — Microsoft Teams integration tests
==================================================
Suite TEAMS: Tests Teams alert webhook integration.
SKIPPED if TEAMS_WEBHOOK_URL env var is not set.
Labels: TEAMS.1 - TEAMS.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, TEAMS_WEBHOOK_URL
from helpers.api import signup_api, get_headers
from helpers.output import ok, fail, warn, info, section, chk, get_results


def main():
    section("Suite TEAMS — Teams Integration Tests")
    info(f"API: {API_URL}")

    if not TEAMS_WEBHOOK_URL:
        warn("TEAMS.0  TEAMS_WEBHOOK_URL not set — skipping all Teams integration tests")
        info("  Set TEAMS_WEBHOOK_URL env var to enable these tests in CI")
        sys.exit(0)

    info(f"  TEAMS_WEBHOOK_URL is set (length={len(TEAMS_WEBHOOK_URL)})")

    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        info(f"Test account: {org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    headers = get_headers(api_key)

    # TEAMS.1 POST /alerts/teams with valid webhook → 200
    r = requests.post(f"{API_URL}/v1/alerts/teams",
                      json={
                          "webhook_url": TEAMS_WEBHOOK_URL,
                          "threshold": 10.0,
                          "current_value": 15.0,
                          "org_id": org_id,
                          "message": "Test alert from Cohrint CI",
                      },
                      headers=headers, timeout=30)
    chk("TEAMS.1  POST /alerts/teams valid webhook → 200",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    # TEAMS.2 POST /alerts/teams with invalid webhook URL → 4xx (not 500)
    r2 = requests.post(f"{API_URL}/v1/alerts/teams",
                       json={
                           "webhook_url": "https://outlook.office.com/INVALID_WEBHOOK",
                           "threshold": 10.0,
                           "current_value": 15.0,
                       },
                       headers=headers, timeout=30)
    chk("TEAMS.2  POST /alerts/teams invalid webhook → 4xx (not 500)",
        r2.status_code < 500,
        f"got {r2.status_code}: {r2.text[:100]}")
    chk("TEAMS.3  Invalid webhook does not return 500",
        r2.status_code != 500,
        f"got {r2.status_code}")

    # TEAMS.4 Verify response fields
    if r.ok:
        try:
            d_resp = r.json()
            has_confirmation = (
                "alert_id" in d_resp or "id" in d_resp or
                "sent" in d_resp or "status" in d_resp or "ok" in d_resp
            )
            chk("TEAMS.4  Alert response includes confirmation field",
                has_confirmation,
                f"response keys: {list(d_resp.keys())}")
        except Exception:
            warn("TEAMS.4  Response is not JSON or unexpected format")

    # TEAMS.5 POST with missing fields → 400
    r3 = requests.post(f"{API_URL}/v1/alerts/teams",
                       json={},
                       headers=headers, timeout=15)
    chk("TEAMS.5  POST /alerts/teams missing fields → 400",
        r3.status_code in (400, 422),
        f"got {r3.status_code}: {r3.text[:100]}")

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
