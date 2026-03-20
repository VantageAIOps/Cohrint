"""
test_mail_alerts.py — Mail alert integration tests
===================================================
Suite MAIL: Tests email alert sending.
SKIPPED if VANTAGE_ALERT_EMAIL env var is not set.
Labels: MAIL.1 - MAIL.N
"""

import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, ALERT_EMAIL
from helpers.api import signup_api, get_headers
from helpers.data import rand_email
from helpers.output import ok, fail, warn, info, section, chk, get_results


def main():
    section("Suite MAIL — Mail Alert Tests")
    info(f"API: {API_URL}")

    if not ALERT_EMAIL:
        warn("MAIL.0  VANTAGE_ALERT_EMAIL not set — skipping all mail alert tests")
        info("  Set VANTAGE_ALERT_EMAIL env var to enable these tests in CI")
        sys.exit(0)

    info(f"  ALERT_EMAIL: {ALERT_EMAIL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        info(f"Test account: {org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    headers = get_headers(api_key)

    # MAIL.1 POST /alerts/email with valid email → 200 (queued)
    r = requests.post(f"{API_URL}/v1/alerts/email",
                      json={
                          "email": ALERT_EMAIL,
                          "threshold": 10.0,
                          "current_value": 15.5,
                          "org_id": org_id,
                          "subject": "VantageAI CI Test Alert",
                      },
                      headers=headers, timeout=30)
    chk("MAIL.1  POST /alerts/email valid email → 200",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    # MAIL.2 Verify response includes alert_id
    if r.ok:
        try:
            d_resp = r.json()
            has_alert_id = "alert_id" in d_resp or "id" in d_resp or "queued" in d_resp
            chk("MAIL.2  Alert response includes alert_id or queued confirmation",
                has_alert_id,
                f"response keys: {list(d_resp.keys())}")
        except Exception:
            warn("MAIL.2  Response is not JSON or unexpected format")

    # MAIL.3 POST /alerts/email with malformed email → 400
    r2 = requests.post(f"{API_URL}/v1/alerts/email",
                       json={
                           "email": "not-a-valid-email",
                           "threshold": 10.0,
                           "current_value": 15.0,
                       },
                       headers=headers, timeout=15)
    chk("MAIL.3  POST /alerts/email malformed email → 400",
        r2.status_code in (400, 422),
        f"got {r2.status_code}: {r2.text[:100]}")

    # MAIL.4 POST with missing fields → 400
    r3 = requests.post(f"{API_URL}/v1/alerts/email",
                       json={},
                       headers=headers, timeout=15)
    chk("MAIL.4  POST /alerts/email missing fields → 400",
        r3.status_code in (400, 422),
        f"got {r3.status_code}: {r3.text[:100]}")

    # MAIL.5 POST without auth → 401
    r4 = requests.post(f"{API_URL}/v1/alerts/email",
                       json={"email": ALERT_EMAIL, "threshold": 10.0, "current_value": 15.0},
                       timeout=15)
    chk("MAIL.5  POST /alerts/email no auth → 401",
        r4.status_code == 401,
        f"got {r4.status_code}")

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
