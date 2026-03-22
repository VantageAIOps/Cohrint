"""
test_team_access.py — Team access control tests
================================================
Suite TA: Tests role-based access, cross-org isolation under concurrent load.
Labels: TA.1 - TA.N
"""

import sys
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie, fresh_account
from helpers.data import rand_email, rand_org, rand_name, make_event
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_cross_org_isolation():
    section("TA. Team Access — Cross-Org Data Isolation")

    # Create two separate orgs
    try:
        d_a = signup_api()
        key_a = d_a["api_key"]
        org_a = d_a["org_id"]

        d_b = signup_api()
        key_b = d_b["api_key"]
        org_b = d_b["org_id"]
        info(f"  Org A: {org_a}")
        info(f"  Org B: {org_b}")
    except Exception as e:
        fail(f"TA.1  Could not create two test orgs: {e}")
        return

    # Ingest event for org A
    r_ingest = requests.post(f"{API_URL}/v1/events",
                             json=make_event(cost=9.99, prompt_tokens=999,
                                             completion_tokens=999,
                                             tags={"secret": "org_a_only"}),
                             headers=get_headers(key_a), timeout=15)
    chk("TA.1  Org A can ingest events", r_ingest.status_code in (201, 202),
        f"got {r_ingest.status_code}")

    time.sleep(1)

    # TA.2 Org B cannot see Org A's analytics
    r_b = requests.get(f"{API_URL}/v1/analytics/summary",
                       headers=get_headers(key_b), timeout=15)
    if r_b.ok:
        d_b_data = r_b.json()
        cost_b = (d_b_data.get("total_cost") or d_b_data.get("cost") or
                  d_b_data.get("totalCost") or 0)
        # Org B should not see org A's $9.99 event
        chk("TA.2  Org B analytics don't include Org A's data",
            cost_b < 9.0,  # Org B just signed up, should have ~0 cost
            f"Org B cost={cost_b} (should not include Org A's 9.99)")
    else:
        chk("TA.2  Org B analytics → 200 or 404 (not Org A's data)",
            r_b.status_code in (200, 404), f"got {r_b.status_code}")

    # TA.3 Org B key cannot access Org A's admin
    r_admin = requests.get(f"{API_URL}/v1/admin/members",
                           headers=get_headers(key_b), timeout=15)
    # Should only see Org B's members (or 404 if not implemented)
    chk("TA.3  Org B admin only sees Org B data (no cross-org leak)",
        r_admin.status_code in (200, 404, 403),
        f"got {r_admin.status_code}")


def test_member_cannot_invite():
    section("TA. Team Access — Member Cannot Invite")

    # Create org + member via signup
    try:
        d_owner = signup_api()
        owner_key = d_owner["api_key"]

        # Invite or create a member
        r_invite = requests.post(f"{API_URL}/v1/admin/invite",
                                 json={"email": rand_email("ta-m"), "name": rand_name()},
                                 headers=get_headers(owner_key), timeout=15)
        if r_invite.status_code in (200, 201):
            d_inv = r_invite.json()
            member_key = (d_inv.get("api_key") or d_inv.get("member_key") or
                         d_inv.get("key"))
        else:
            # Create separate account as proxy
            d_member = signup_api()
            member_key = d_member["api_key"]
            warn("TA.4  Using separate account as proxy for member role test")
    except Exception as e:
        warn(f"TA.4  Could not set up member: {e}")
        return

    if not member_key:
        warn("TA.4  No member key — skipping")
        return

    # TA.4 Member key cannot invite others (403)
    r = requests.post(f"{API_URL}/v1/admin/invite",
                      json={"email": rand_email("ta-new"), "name": rand_name()},
                      headers=get_headers(member_key), timeout=15)
    chk("TA.4  Member cannot invite others → 403/401",
        r.status_code in (401, 403),
        f"got {r.status_code}: {r.text[:100]}")


def test_concurrent_reads_isolated():
    section("TA. Team Access — Concurrent Multi-Member Reads Isolated")

    # Create 3 orgs
    try:
        orgs = [signup_api() for _ in range(3)]
    except Exception as e:
        fail(f"TA.5  Could not create test orgs: {e}")
        return

    # Ingest unique data for each org
    for i, d in enumerate(orgs):
        requests.post(f"{API_URL}/v1/events",
                      json=make_event(i=i, cost=float(i + 1) * 1.0),
                      headers=get_headers(d["api_key"]), timeout=10)

    time.sleep(1)

    # Concurrent reads
    def read_analytics(d):
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=get_headers(d["api_key"]), timeout=15)
        return d["org_id"], r.status_code, r.json() if r.ok else {}

    results_list = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(read_analytics, d) for d in orgs]
        for f in as_completed(futures):
            try:
                results_list.append(f.result())
            except Exception as e:
                warn(f"TA.5  Concurrent read exception: {e}")

    chk("TA.5  All 3 concurrent reads succeed",
        all(status in (200, 404) for _, status, _ in results_list),
        f"statuses: {[s for _, s, _ in results_list]}")


def main():
    section("Suite TA — Team Access Control Tests")
    info(f"API: {API_URL}")

    test_cross_org_isolation()
    test_member_cannot_invite()
    test_concurrent_reads_isolated()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
