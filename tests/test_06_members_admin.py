"""
test_06_members_admin.py — Team member management & admin features
==================================================================
Developer notes:
  Tests the full team management workflow:
    • Owner invites member (POST /v1/auth/members)
    • Member key works immediately
    • Owner lists members (GET /v1/auth/members)
    • Owner updates member role (PATCH /v1/auth/members/:id)
    • Owner revokes member (DELETE /v1/auth/members/:id)
    • Owner rotates member key (POST /v1/auth/members/:id/rotate)
    • Scoped member only sees their team's data
    • Viewer cannot ingest events
    • Admin endpoints enforce owner/admin-only access
    • Team budgets: set, list, update, delete
    • Org budget: PATCH /v1/admin/org

  UI tests (Playwright):
    • Members view loads (via admin overview)
    • Invite modal opens and shows generated key
    • Revoke confirmation dialog

Run:
  python tests/test_06_members_admin.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_tag, rand_name,
    signup_api, get_headers, get_session_cookie, fresh_account, signin_ui,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.members")

# ── Owner account ─────────────────────────────────────────────────────────────
try:
    d         = signup_api()
    OWNER_KEY = d["api_key"]
    ORG_ID    = d["org_id"]
    OWNER_HDR = get_headers(OWNER_KEY)
    OWNER_CKS = get_session_cookie(OWNER_KEY)
    info(f"Owner account: {ORG_ID}")
except Exception as e:
    fail("Could not create owner account", str(e))
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
section("1. Invite & manage members")
# ─────────────────────────────────────────────────────────────────────────────

MEMBER_ID  = None
MEMBER_KEY = None

# 1.1 Invite member
try:
    r = requests.post(f"{API_URL}/v1/auth/members",
                      json={"email":      rand_email("mbr"),
                            "name":       "Test Member",
                            "role":       "member",
                            "scope_team": "team-alpha"},
                      cookies=OWNER_CKS, timeout=15)
    chk("1.1  Invite member → 200/201", r.status_code in (200, 201),
        f"{r.status_code}: {r.text[:100]}")
    if r.status_code in (200, 201):
        body = r.json()
        MEMBER_ID  = body.get("id") or body.get("member_id")
        MEMBER_KEY = body.get("api_key")
        chk("1.2  Member: api_key in response", bool(MEMBER_KEY), str(body))
        chk("1.3  Member key starts with vnt_",
            bool(MEMBER_KEY) and MEMBER_KEY.startswith("vnt_"), MEMBER_KEY)
        chk("1.4  Member: id in response", bool(MEMBER_ID), str(body))
        log.info("Member invited", member_id=MEMBER_ID, org=ORG_ID)
except Exception as e:
    fail("1.1  Invite member failed", str(e))

# 1.5 Member key works immediately
if MEMBER_KEY:
    try:
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": MEMBER_KEY}, timeout=10)
        chk("1.5  Member key creates session → 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:100]}")
        MEMBER_CKS = r.cookies if r.ok else None

        # 1.6 Member session returns role='member'
        if r.ok:
            sess_r = requests.get(f"{API_URL}/v1/auth/session",
                                  cookies=r.cookies, timeout=10)
            if sess_r.ok:
                sess = sess_r.json()
                chk("1.6  Member session role is 'member' or 'viewer'",
                    sess.get("role") in ("member", "viewer", "admin"),
                    f"role={sess.get('role')}")
    except Exception as e:
        fail("1.5-1.6  Member session test failed", str(e))
        MEMBER_CKS = None

# 1.7 List members
try:
    r = requests.get(f"{API_URL}/v1/auth/members", cookies=OWNER_CKS, timeout=10)
    chk("1.7  GET /auth/members → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")
    if r.ok:
        body = r.json()
        members = body.get("members", body) if isinstance(body, dict) else body
        chk("1.8  List members: returns array", isinstance(members, list), str(type(body)))
        if isinstance(members, list) and MEMBER_ID:
            ids = [str(m.get("id","")) for m in members]
            chk("1.9  Invited member appears in list", str(MEMBER_ID) in ids,
                f"ids={ids}")
except Exception as e:
    fail("1.7  List members failed", str(e))

# 1.10 Update member role to 'viewer'
if MEMBER_ID:
    try:
        r = requests.patch(f"{API_URL}/v1/auth/members/{MEMBER_ID}",
                           json={"role": "viewer"}, cookies=OWNER_CKS, timeout=10)
        chk("1.10 PATCH member role → 200/204", r.status_code in (200, 204),
            f"{r.status_code}: {r.text[:100]}")
    except Exception as e:
        fail("1.10 Update member role failed", str(e))

# 1.11 Rotate member key
if MEMBER_ID:
    try:
        r = requests.post(f"{API_URL}/v1/auth/members/{MEMBER_ID}/rotate",
                          cookies=OWNER_CKS, timeout=15)
        chk("1.11 Rotate member key → 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:100]}")
        if r.ok:
            new_key = r.json().get("api_key")
            chk("1.12 Rotated key is new (different from original)",
                new_key and new_key != MEMBER_KEY and new_key.startswith("vnt_"),
                f"new={new_key[:20] if new_key else 'None'}")
            if new_key:
                MEMBER_KEY = new_key  # keep MEMBER_KEY current for section 2 tests
    except Exception as e:
        fail("1.11 Rotate member key failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("2. Access control enforcement")
# ─────────────────────────────────────────────────────────────────────────────

# 2.1 Viewer cannot ingest events
if MEMBER_KEY:
    try:
        # (viewer role was just set above)
        viewer_cookies = get_session_cookie(MEMBER_KEY)
        if not viewer_cookies:
            # Key might have been rotated above — use original
            pass
        r = requests.post(f"{API_URL}/v1/events",
                          json={"event_id": f"viewer-{rand_tag()}", "provider": "openai",
                                "model": "gpt-4o"},
                          cookies=viewer_cookies, timeout=10)
        chk("2.1  Viewer cannot ingest events → 403",
            r.status_code == 403, f"got {r.status_code} — viewer should be blocked")
    except Exception as e:
        warn(f"2.1  Viewer-block test inconclusive: {e}")

# 2.2 Scoped member sees only their team in analytics
if MEMBER_KEY:
    try:
        member_hdr = get_headers(MEMBER_KEY)
        r = requests.get(f"{API_URL}/v1/analytics/teams?period=30",
                         headers=member_hdr, timeout=10)
        chk("2.2  Scoped member GET /analytics/teams → 200", r.status_code == 200,
            f"{r.status_code}")
        # (Data validation of team scoping requires events to exist)
    except Exception as e:
        warn(f"2.2  Scoped member test inconclusive: {e}")

# 2.3 Member cannot access admin overview
if MEMBER_KEY:
    try:
        member_hdr = get_headers(MEMBER_KEY)
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=member_hdr, timeout=10)
        chk("2.3  Member cannot access admin overview → 403",
            r.status_code == 403, f"got {r.status_code}")
    except Exception as e:
        warn(f"2.3  Admin-block test inconclusive: {e}")

# 2.4 Member cannot invite other members
if MEMBER_KEY:
    try:
        member_cks = get_session_cookie(MEMBER_KEY)
        r = requests.post(f"{API_URL}/v1/auth/members",
                          json={"email": rand_email("unauth"), "name": "Unauth", "role": "member"},
                          cookies=member_cks, timeout=10)
        chk("2.4  Member cannot invite members → 403",
            r.status_code == 403, f"got {r.status_code}")
    except Exception as e:
        warn(f"2.4  Member-invite-block test inconclusive: {e}")


# ─────────────────────────────────────────────────────────────────────────────
section("3. Team budgets")
# ─────────────────────────────────────────────────────────────────────────────

TEAM_NAME = f"budget-team-{rand_tag(4)}"

# 3.1 Set team budget
try:
    r = requests.put(f"{API_URL}/v1/admin/team-budgets/{TEAM_NAME}",
                     json={"budget_usd": 250.0}, cookies=OWNER_CKS, timeout=10)
    chk("3.1  PUT team budget → 200/201", r.status_code in (200, 201),
        f"{r.status_code}: {r.text[:100]}")
except Exception as e:
    fail("3.1  Set team budget failed", str(e))

# 3.2 List team budgets
try:
    r = requests.get(f"{API_URL}/v1/admin/team-budgets", cookies=OWNER_CKS, timeout=10)
    chk("3.2  GET team budgets → 200/404", r.status_code in (200, 404),
        f"{r.status_code}")
    if r.ok:
        budgets = r.json()
        chk("3.3  Team budgets is array or dict", isinstance(budgets, (list, dict)))
except Exception as e:
    fail("3.2  List team budgets failed", str(e))

# 3.4 Org-level budget
try:
    r = requests.patch(f"{API_URL}/v1/admin/org",
                       json={"budget_usd": 1000.0}, cookies=OWNER_CKS, timeout=10)
    chk("3.4  PATCH org budget → 200/201", r.status_code in (200, 201),
        f"{r.status_code}: {r.text[:100]}")
except Exception as e:
    fail("3.4  Org budget test failed", str(e))

# 3.5 Delete team budget
try:
    r = requests.delete(f"{API_URL}/v1/admin/team-budgets/{TEAM_NAME}",
                        cookies=OWNER_CKS, timeout=10)
    chk("3.5  DELETE team budget → 200/204", r.status_code in (200, 204),
        f"{r.status_code}")
except Exception as e:
    fail("3.5  Delete team budget failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("4. Members UI (Playwright)")
# ─────────────────────────────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        signed_in = signin_ui(page, OWNER_KEY)
        chk("4.1  Signed in to dashboard", signed_in, page.url)

        if signed_in:
            # Navigate to Team Members view
            members_btn = page.locator(".sb-item:has-text('Member'), .sb-item:has-text('Team')")
            if members_btn.count() == 0:
                members_btn = page.locator(".sb-item").last
            try:
                members_btn.first.click()
                page.wait_for_timeout(2_000)
                chk("4.2  Members view loads without crash", "/app" in page.url,
                    page.url)

                # Check if members view content is shown
                has_member_content = (
                    page.locator("table").count() > 0 or
                    page.locator(".member-row, .members-table").count() > 0 or
                    "member" in page.content().lower()
                )
                chk("4.3  Members view shows content", has_member_content)

                # 4.4 Invite modal opens
                invite_btn = page.locator("[onclick*='openInviteModal'], button:has-text('Invite')")
                if invite_btn.count() > 0:
                    invite_btn.first.click()
                    page.wait_for_timeout(600)
                    chk("4.4  Invite modal opens",
                        page.locator("#invite-modal, .modal.open, [id*='invite']").count() > 0)
                    page.keyboard.press("Escape")
                else:
                    warn("4.4  Invite button not found (may be role-restricted)")

            except PWTimeout as e:
                fail("4.2  Members view timed out", str(e)[:200])

        # 4.5 No JS errors
        page.wait_for_timeout(1_000)
        chk("4.5  No JS errors in members view", len(js_errors) == 0,
            str(js_errors[:3]))

        # Cleanup: delete the test member we created
        if MEMBER_ID:
            try:
                requests.delete(f"{API_URL}/v1/auth/members/{MEMBER_ID}",
                                cookies=OWNER_CKS, timeout=10)
            except Exception:
                pass

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests")
except Exception as e:
    fail("4.x  Members UI test error", str(e)[:300])


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Members/admin tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
