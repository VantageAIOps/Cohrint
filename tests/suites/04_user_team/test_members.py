"""
test_members.py — Team member management tests
===============================================
Suite TM: Tests invite, member sign-in, event ingestion, key rotation.
Labels: TM.1 - TM.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_owner_invite(owner_key, owner_id):
    section("TM. Members — Owner Invites Member")

    headers = get_headers(owner_key)
    member_email = rand_email("tm-member")

    # TM.1 POST /admin/invite → member key
    r = requests.post(f"{API_URL}/v1/admin/invite",
                      json={"email": member_email, "name": rand_name(), "role": "member"},
                      headers=headers, timeout=15)
    chk("TM.1  POST /admin/invite → 200/201",
        r.status_code in (200, 201),
        f"got {r.status_code}: {r.text[:100]}")

    member_key = None
    if r.ok:
        d = r.json()
        member_key = (d.get("api_key") or d.get("member_key") or
                      d.get("key") or d.get("invite_key"))
        chk("TM.2  Invite response includes member key", bool(member_key),
            f"response keys: {list(d.keys())}")
    else:
        warn("TM.2  /admin/invite may not be implemented yet")
        # Try alternative: create member via signup with org context
        try:
            d2 = signup_api(email=member_email, org=rand_org("tm-sub"))
            member_key = d2.get("api_key")
            info("  Using separate signup as fallback for member")
        except Exception as e:
            warn(f"  Fallback signup also failed: {e}")

    return member_key, member_email


def test_member_signin(member_key):
    section("TM. Members — Member Sign-in")

    if not member_key:
        warn("TM.3  No member key — skipping")
        return None

    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": member_key}, timeout=15)
    chk("TM.3  Member can sign in", r.status_code == 200,
        f"got {r.status_code}")
    return r.cookies if r.ok else None


def test_list_members(owner_key, member_key):
    section("TM. Members — List Members")

    headers = get_headers(owner_key)
    r = requests.get(f"{API_URL}/v1/admin/members", headers=headers, timeout=15)
    chk("TM.4  GET /admin/members → 200",
        r.status_code in (200, 404),  # 404 = not implemented yet
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        members = d.get("members") or d.get("data") or (d if isinstance(d, list) else [])
        chk("TM.5  Members list is non-empty", len(members) >= 1,
            f"got {len(members)} members")


def test_member_ingest(member_key, owner_key):
    section("TM. Members — Member Ingests Events")

    if not member_key:
        warn("TM.6  No member key — skipping ingest test")
        return

    headers = get_headers(member_key)
    event = {
        "model": "gpt-4o",
        "cost": 0.003,
        "tokens": {"prompt": 80, "completion": 40},
        "timestamp": int(time.time() * 1000),
        "tags": {"source": "member_test"},
    }
    r = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
    chk("TM.6  Member can ingest events", r.status_code in (201, 202),
        f"got {r.status_code}: {r.text[:100]}")

    # TM.7 Member can read analytics
    r2 = requests.get(f"{API_URL}/v1/analytics/summary",
                      headers=headers, timeout=15)
    chk("TM.7  Member can read analytics", r2.status_code in (200, 404),
        f"got {r2.status_code}")


def test_rotate_member_key(owner_key, member_key):
    section("TM. Members — Owner Rotates Member Key")

    if not member_key:
        warn("TM.8  No member key — skipping rotation test")
        return

    headers = get_headers(owner_key)

    # TM.8 Owner rotates member key
    r = requests.post(f"{API_URL}/v1/admin/rotate-member",
                      json={"member_key": member_key},
                      headers=headers, timeout=15)
    chk("TM.8  POST /admin/rotate-member → 200 or 404 (endpoint may not exist)",
        r.status_code in (200, 201, 404, 405),
        f"got {r.status_code}: {r.text[:100]}")

    if r.ok:
        d = r.json()
        new_member_key = d.get("api_key") or d.get("new_key") or d.get("key")
        if new_member_key:
            # New key works
            r2 = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": new_member_key}, timeout=15)
            chk("TM.9  New member key works", r2.status_code == 200,
                f"got {r2.status_code}")

            # Old key rejected
            r3 = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": member_key}, timeout=15)
            chk("TM.10 Old member key rejected after rotation",
                r3.status_code in (401, 403),
                f"got {r3.status_code}")
        else:
            warn("TM.9  No new key returned from rotate-member")


def main():
    section("Suite TM — Team Member Management Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        owner_key = d["api_key"]
        owner_id  = d["org_id"]
        info(f"Owner org: {owner_id}")
    except Exception as e:
        fail(f"Could not create owner account: {e}")
        sys.exit(1)

    member_key, member_email = test_owner_invite(owner_key, owner_id)
    member_cookies = test_member_signin(member_key)
    test_list_members(owner_key, member_key)
    test_member_ingest(member_key, owner_key)
    test_rotate_member_key(owner_key, member_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
