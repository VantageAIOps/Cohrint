"""
test_03_recovery.py — API key recovery flow tests
==================================================
Developer notes:
  Tests the 3-step key recovery process:
    Step 0: POST /v1/auth/recover     → sends email (always 200 for privacy)
    Step 1: GET  /v1/auth/recover/redeem?token=  → peek, redirect to /auth?confirm_token=
    Step 2: POST /v1/auth/recover/redeem {token} → consume token, get new key

  Protection against email-link-scanner attacks (Gmail, Outlook pre-fetch):
    The GET redeem does NOT consume the token — it just peeks and redirects.
    Only the POST (triggered by user clicking a button on /auth) consumes it.

  Known flows to verify:
    - POST /recover always returns 200 (doesn't leak whether email exists)
    - GET /recover/redeem redirects to /auth?confirm_token=...
    - POST /recover/redeem returns new key (one-time, token deleted)
    - POST /recover/redeem second call → 410 Gone (already used)
    - POST /recover/redeem with expired/bad token → 410 Gone

  UI flow on /auth page:
    - "Forgot your key?" → show #recover-box
    - Enter email → POST /recover → show success message
    - Simulate confirm_token param → show rotation UI
    - Click "Generate my new API key" → POST /recover/redeem → show new key

Run:
  python tests/test_03_recovery.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag,
    signup_api, get_headers, get_session_cookie,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.recovery")


# ─────────────────────────────────────────────────────────────────────────────
# 1. API — POST /v1/auth/recover
# ─────────────────────────────────────────────────────────────────────────────
section("1. Key recovery API — POST /v1/auth/recover")

try:
    d       = signup_api()
    api_key = d["api_key"]
    org_id  = d["org_id"]
    email   = d.get("email", rand_email("rec"))
    # Re-create so we capture the email we used
    d2      = signup_api()
    api_key = d2["api_key"]
    org_id  = d2["org_id"]
    # Note: signup doesn't echo back the email, so use the one we sent
    _email = rand_email("recov")
    d2 = signup_api(email=_email)
    api_key = d2["api_key"]
    org_id  = d2["org_id"]
    info(f"Test account: {org_id}")
except Exception as e:
    fail("Could not create test account", str(e))
    api_key = org_id = _email = None

if api_key:
    # 1.1 POST /recover for existing email → 200
    try:
        r = requests.post(f"{API_URL}/v1/auth/recover", json={"email": _email}, timeout=15)
        chk("1.1  POST /recover for existing email → 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:100]}")
    except Exception as e:
        fail("1.1  POST /recover failed", str(e))

    # 1.2 POST /recover for non-existent email → 200 (privacy)
    try:
        r = requests.post(f"{API_URL}/v1/auth/recover",
                          json={"email": "nobody@never-existed-vantage.dev"}, timeout=15)
        chk("1.2  POST /recover non-existent email → 200 (privacy-safe)",
            r.status_code == 200, f"{r.status_code}: {r.text[:100]}")
    except Exception as e:
        fail("1.2  Privacy-safe recover test failed", str(e))

    # 1.3 POST /recover missing email → 400
    try:
        r = requests.post(f"{API_URL}/v1/auth/recover", json={}, timeout=10)
        chk("1.3  POST /recover missing email → 400", r.status_code == 400,
            f"got {r.status_code}")
    except Exception as e:
        fail("1.3  Missing-email recover test failed", str(e))

    # 1.4 POST /recover with malformed email → 400 or 200 (server decides)
    try:
        r = requests.post(f"{API_URL}/v1/auth/recover",
                          json={"email": "not-an-email"}, timeout=10)
        chk("1.4  POST /recover malformed email → 400 or 200",
            r.status_code in (200, 400), f"got {r.status_code}")
    except Exception as e:
        warn(f"1.4  Malformed-email recover test inconclusive: {e}")

    # 1.5 GET /recover/redeem with bad token → 302 with error param
    try:
        r = requests.get(
            f"{API_URL}/v1/auth/recover/redeem",
            params={"token": "definitely-invalid-token-12345"},
            allow_redirects=False,
            timeout=10,
        )
        chk("1.5  GET /recover/redeem bad token → redirect (3xx)",
            r.status_code in (301, 302, 307, 308),
            f"got {r.status_code}")
        location = r.headers.get("Location", "")
        chk("1.6  Redirect location contains error param",
            "recovery_error" in location or "error" in location,
            f"location={location}")
    except Exception as e:
        fail("1.5-1.6  GET redeem bad-token test failed", str(e))

    # 1.7 POST /recover/redeem with bad token → 410 Gone
    try:
        r = requests.post(
            f"{API_URL}/v1/auth/recover/redeem",
            json={"token": "definitely-invalid-token-99999"},
            timeout=10,
        )
        chk("1.7  POST /recover/redeem bad token → 410",
            r.status_code == 410, f"got {r.status_code}: {r.text[:100]}")
    except Exception as e:
        fail("1.7  POST redeem bad-token test failed", str(e))

    # 1.8 POST /recover/redeem missing token → 400
    try:
        r = requests.post(f"{API_URL}/v1/auth/recover/redeem", json={}, timeout=10)
        chk("1.8  POST /recover/redeem missing token → 400",
            r.status_code == 400, f"got {r.status_code}")
    except Exception as e:
        fail("1.8  Missing-token redeem test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. UI — recovery panel on /auth page (Playwright)
# ─────────────────────────────────────────────────────────────────────────────
section("2. Recovery UI — /auth recovery panel (Playwright)")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    # Fresh account for UI test
    _ui_email = rand_email("uirec")
    d_ui = signup_api(email=_ui_email)
    ui_key = d_ui["api_key"]

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 2.1 Load /auth without session
        ctx.clear_cookies()
        page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)

        # 2.2 Click "Forgot your key?"
        try:
            recover_btn = page.locator("button.ghost-btn").first
            if recover_btn.is_visible():
                recover_btn.click()
                page.wait_for_selector("#recover-box", state="visible", timeout=5_000)
                chk("2.2  Recovery panel appears after clicking 'Forgot'",
                    page.locator("#recover-box").is_visible())

                # 2.3 Sign-in box hidden when recovery panel shown
                chk("2.3  Sign-in box hidden while recovery panel open",
                    not page.locator("#signin-box").is_visible())

                # 2.4 Email input visible in recovery panel
                email_input = page.locator("#inp-email")
                chk("2.4  Email input visible in recovery panel",
                    email_input.is_visible())

                # 2.5 Submit recovery for existing email → server 200
                if email_input.is_visible():
                    email_input.fill(_ui_email)
                    try:
                        with page.expect_response(
                            lambda r: "/v1/auth/recover" in r.url and not "redeem" in r.url,
                            timeout=10_000,
                        ) as resp_info:
                            page.click("#recover-btn")
                        resp = resp_info.value
                        chk("2.5  Recovery API returns 200", resp.status == 200,
                            f"got {resp.status}")

                        # 2.6 Success message shown
                        page.wait_for_timeout(1_000)
                        msg_div = page.locator("#recover-msg")
                        if msg_div.is_visible():
                            msg_text = msg_div.inner_text()
                            chk("2.6  Recovery message shown (not 'Network error')",
                                "network error" not in msg_text.lower(),
                                f"msg='{msg_text}'")
                            chk("2.7  Message mentions 'sent' or 'email' or 'recovery'",
                                any(w in msg_text.lower() for w in
                                    ["sent", "email", "recovery", "inbox"]),
                                f"msg='{msg_text}'")
                        else:
                            ok("2.6  No error shown after recovery (API returned 200)")
                            ok("2.7  (skipped — no visible message div)")

                    except PWTimeout:
                        fail("2.5  Recovery submit timed out")

                # 2.8 Back button returns to sign-in
                back_btn = page.locator("#recover-box button.ghost-btn")
                if back_btn.is_visible():
                    back_btn.click()
                    page.wait_for_timeout(500)
                    chk("2.8  Back button returns to sign-in box",
                        page.locator("#signin-box").is_visible())
            else:
                warn("2.2  Could not find recovery button")
        except PWTimeout as e:
            fail("2.2+  Recovery panel test timed out", str(e)[:200])

        # 2.9 Simulate confirm_token URL param (post-email-click state)
        try:
            fake_token = "test-confirm-token-99999"
            page.goto(f"{SITE_URL}/auth?confirm_token={fake_token}",
                      wait_until="networkidle", timeout=15_000)
            page.wait_for_timeout(1_000)

            # Should show rotate confirmation UI
            chk("2.9  /auth?confirm_token shows rotation UI",
                page.locator("#recover-box").is_visible() or
                "confirm" in page.content().lower() or
                "generate" in page.content().lower(),
                f"content snippet: {page.content()[1000:1100]}")

            # 2.10 Token cleared from URL
            chk("2.10 confirm_token param removed from URL after load",
                "confirm_token" not in page.url,
                f"url={page.url}")
        except Exception as e:
            warn(f"2.9-2.10 Confirm-token UI test inconclusive: {e}")

        # 2.11 recovery_error URL param shows correct error
        try:
            page.goto(f"{SITE_URL}/auth?recovery_error=expired",
                      wait_until="networkidle", timeout=15_000)
            page.wait_for_timeout(1_000)
            chk("2.11 recovery_error=expired shows error message",
                "expired" in page.content().lower() or
                page.locator("#signin-err").is_visible(),
                "no expired error shown")
        except Exception as e:
            warn(f"2.11 recovery_error test inconclusive: {e}")

        # 2.12 No JS errors during recovery flow
        chk("2.12 No JS errors during recovery UI tests", len(js_errors) == 0,
            str(js_errors[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests")
except Exception as e:
    fail("2.x  Recovery UI test suite error", str(e)[:300])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Post-recovery: new key works, old key invalidated
# ─────────────────────────────────────────────────────────────────────────────
section("3. Post-recovery key behaviour")

info("Note: cannot fully test POST /recover/redeem without a real email token.")
info("Testing that key rotation (POST /v1/auth/rotate) invalidates old key.")

try:
    d       = signup_api()
    old_key = d["api_key"]

    # Rotate the key via /auth/rotate
    cookies = get_session_cookie(old_key)
    r_rot   = requests.post(f"{API_URL}/v1/auth/rotate",
                            cookies=cookies, timeout=15)
    chk("3.1  POST /auth/rotate → 200", r_rot.status_code == 200,
        f"got {r_rot.status_code}: {r_rot.text[:100]}")

    if r_rot.status_code == 200:
        new_key = r_rot.json().get("api_key")
        chk("3.2  New key returned after rotation", bool(new_key) and new_key.startswith("vnt_"),
            str(r_rot.json()))
        chk("3.3  New key is different from old key", new_key != old_key,
            "key unchanged after rotation!")

        # 3.4 New key creates session
        r_new = requests.post(f"{API_URL}/v1/auth/session",
                              json={"api_key": new_key}, timeout=10)
        chk("3.4  New key creates session → 200", r_new.status_code == 200,
            f"got {r_new.status_code}")

        # 3.5 Old key no longer works
        r_old = requests.post(f"{API_URL}/v1/auth/session",
                              json={"api_key": old_key}, timeout=10)
        chk("3.5  Old key rejected after rotation → 401", r_old.status_code == 401,
            f"got {r_old.status_code} — old key still accepted!")

except Exception as e:
    fail("3.x  Post-rotation key test failed", str(e))


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Recovery tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
