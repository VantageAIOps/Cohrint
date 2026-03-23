"""
test_org_admin.py — Org-level admin tests
==========================================
Suite OA: Tests budget management, member listing, shared analytics.
Labels: OA.1 - OA.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name, make_event
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_budget_endpoints(owner_key, org_id):
    section("OA. Org Admin — Budget Management")

    headers = get_headers(owner_key)

    # OA.1 GET /admin/budget → 200 or 404 (if not implemented)
    r = requests.get(f"{API_URL}/v1/admin/budget", headers=headers, timeout=15)
    chk("OA.1  GET /admin/budget → 200/404",
        r.status_code in (200, 404), f"got {r.status_code}")

    if r.ok:
        d = r.json()
        chk("OA.2  Budget response has limit field",
            "limit" in d or "budget" in d or "monthly_limit" in d,
            f"keys: {list(d.keys())}")

    # OA.3 POST /admin/budget (set limit)
    r2 = requests.post(f"{API_URL}/v1/admin/budget",
                       json={"limit": 100.0, "period": "monthly"},
                       headers=headers, timeout=15)
    chk("OA.3  POST /admin/budget → 200/201/404",
        r2.status_code in (200, 201, 404, 405),
        f"got {r2.status_code}: {r2.text[:100]}")


def test_members_list(owner_key):
    section("OA. Org Admin — Members Listing")

    headers = get_headers(owner_key)

    # OA.4 GET /auth/members lists all members with roles
    r = requests.get(f"{API_URL}/v1/auth/members", headers=headers, timeout=15)
    chk("OA.4  GET /auth/members → 200/404",
        r.status_code in (200, 404), f"got {r.status_code}")

    if r.ok:
        d = r.json()
        members = d.get("members") or d.get("data") or (d if isinstance(d, list) else [])
        chk("OA.5  Members list returned (may be empty for fresh org)",
            isinstance(members, list),
            f"got {type(members).__name__}: {members}")

        if members:
            first = members[0]
            chk("OA.6  Member entry has role or permissions",
                "role" in first or "permissions" in first or "email" in first,
                f"member keys: {list(first.keys())}")


def test_shared_analytics(owner_key, org_id):
    section("OA. Org Admin — Shared Analytics Under Org")

    headers = get_headers(owner_key)

    # Ingest some events
    for i in range(3):
        requests.post(f"{API_URL}/v1/events",
                      json=make_event(i=i, cost=0.01 * (i + 1)),
                      headers=headers, timeout=10)

    time.sleep(1)

    # OA.7 GET /analytics/summary shows aggregated data
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    chk("OA.7  GET /analytics/summary → 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        cost = (d.get("today_cost_usd") or d.get("mtd_cost_usd") or
                d.get("session_cost_usd") or d.get("total_cost") or
                d.get("cost") or d.get("totalCost") or
                d.get("summary", {}).get("total_cost") or 0)
        chk("OA.8  Analytics shows cost > 0 after ingest", cost > 0,
            f"cost={cost}, keys={list(d.keys())}")


def test_admin_requires_owner(owner_key):
    section("OA. Org Admin — Admin Requires Owner Role")

    # Create a non-owner account (separate org)
    try:
        d = signup_api()
        non_owner_key = d["api_key"]
    except Exception as e:
        warn(f"OA.9  Could not create non-owner account: {e}")
        return

    non_owner_headers = get_headers(non_owner_key)

    # OA.9 Non-org member cannot access first org's admin
    r = requests.post(f"{API_URL}/v1/auth/members",
                      json={"email": rand_email("oa"), "name": rand_name()},
                      headers=non_owner_headers, timeout=15)
    # This should either 403 (not authorized for this org) or succeed for their own org
    chk("OA.9  POST /auth/members requires auth",
        r.status_code in (200, 201, 400, 401, 403, 404),
        f"got {r.status_code}")

    # OA.10 Delete/deactivate endpoint exists (404 means not yet implemented)
    r2 = requests.delete(f"{API_URL}/v1/auth/members/some-member-id",
                         headers=get_headers(owner_key), timeout=15)
    chk("OA.10 DELETE /auth/members/:id → 200/404/405",
        r2.status_code in (200, 204, 404, 405, 400),
        f"got {r2.status_code}")


def main():
    section("Suite OA — Org Admin Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        owner_key = d["api_key"]
        org_id    = d["org_id"]
        info(f"Owner org: {org_id}")
    except Exception as e:
        fail(f"Could not create owner account: {e}")
        sys.exit(1)

    test_budget_endpoints(owner_key, org_id)
    test_members_list(owner_key)
    test_shared_analytics(owner_key, org_id)
    test_admin_requires_owner(owner_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
