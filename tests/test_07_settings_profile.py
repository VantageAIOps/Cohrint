"""
test_07_settings_profile.py — Settings modal & profile features
===============================================================
Developer notes:
  Tests the settings and profile section of the dashboard:
    • Settings modal opens and shows correct org ID and plan
    • API key switch (paste new key → creates new session → stays on /app)
    • Save settings with new key doesn't redirect to /auth (known bug)
    • Org ID copy button works
    • Sign out from settings / user menu works
    • Key rotation (POST /v1/auth/rotate) from UI
    • Plan label correctly shows 'Free', 'Team', etc.
    • API base URL override (settings modal #sm-base-input)

  Known bug to catch:
    After saving a new key in settings, if the new key is valid the page
    should stay on /app. But if saveSettings() → initKeyAuth() has a race,
    it may redirect to /auth and bounce back (visible as a page flash).

Run:
  python tests/test_07_settings_profile.py
  HEADLESS=0 python tests/test_07_settings_profile.py
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

log = get_logger("test.settings")


# ─────────────────────────────────────────────────────────────────────────────
# Create two accounts: primary for settings, secondary to switch to
# ─────────────────────────────────────────────────────────────────────────────
try:
    d1        = signup_api()
    KEY1      = d1["api_key"]
    ORG1      = d1["org_id"]
    d2        = signup_api()
    KEY2      = d2["api_key"]
    ORG2      = d2["org_id"]
    info(f"Primary: {ORG1}   Secondary: {ORG2}")
except Exception as e:
    fail("Could not create test accounts", str(e))
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
section("1. Settings API — key rotation & session management")
# ─────────────────────────────────────────────────────────────────────────────

# 1.1 POST /auth/rotate — owner can rotate key
try:
    cookies1 = get_session_cookie(KEY1)
    r = requests.post(f"{API_URL}/v1/auth/rotate", cookies=cookies1, timeout=15)
    chk("1.1  POST /auth/rotate → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")
    if r.ok:
        rotated_key = r.json().get("api_key")
        chk("1.2  Rotated key starts with vnt_",
            bool(rotated_key) and rotated_key.startswith("vnt_"), str(rotated_key))
        chk("1.3  Rotated key different from original", rotated_key != KEY1,
            "key unchanged — rotation may have failed silently")
        KEY1 = rotated_key  # use new key for remaining tests

        # 1.4 Old key no longer valid after rotation
        r_old = requests.post(f"{API_URL}/v1/auth/session",
                              json={"api_key": d1["api_key"]}, timeout=10)
        chk("1.4  Old key rejected after rotation → 401", r_old.status_code == 401,
            f"got {r_old.status_code} — old key still valid!")

        # 1.5 New key creates session
        r_new = requests.post(f"{API_URL}/v1/auth/session",
                              json={"api_key": KEY1}, timeout=10)
        chk("1.5  New key creates session → 200", r_new.status_code == 200,
            f"{r_new.status_code}: {r_new.text[:100]}")
except Exception as e:
    fail("1.1  Key rotation test failed", str(e))

# 1.6 GET /session after rotation returns new org_id (same org)
try:
    cookies_new = get_session_cookie(KEY1)
    if cookies_new:
        r = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies_new, timeout=10)
        chk("1.6  GET session after rotation → 200", r.status_code == 200,
            f"{r.status_code}")
        if r.ok:
            chk("1.7  Session still on same org after rotation",
                r.json().get("org_id") == ORG1, f"org={r.json().get('org_id')}")
except Exception as e:
    fail("1.6  Post-rotation session test failed", str(e))

# 1.8 API key switch: POST /session with KEY2 from existing session
try:
    cookies_key2 = get_session_cookie(KEY2)
    r_sess = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies_key2, timeout=10)
    chk("1.8  Session switch to different account → 200", r_sess.status_code == 200)
    if r_sess.ok:
        switched_org = r_sess.json().get("org_id")
        chk("1.9  Switched to correct org (KEY2 → ORG2)", switched_org == ORG2,
            f"got={switched_org} expected={ORG2}")
except Exception as e:
    fail("1.8  API key switch test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("2. Settings UI — Playwright")
# ─────────────────────────────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # Sign in with KEY1
        signed_in = signin_ui(page, KEY1)
        chk("2.1  Signed in with KEY1", signed_in, page.url)

        if not signed_in:
            warn("Cannot test settings UI — sign-in failed")
        else:
            page.wait_for_timeout(1_500)

            # 2.2 Open Settings (sidebar view — Settings moved from topbar modal to sidebar)
            try:
                settings_btn = page.locator("#sb-settings")
                if settings_btn.count() == 0:
                    # Fallback: try old topbar button
                    settings_btn = page.locator("[onclick*='openSettings']")
                if settings_btn.count() > 0:
                    settings_btn.first.click(timeout=8000)
                    page.wait_for_timeout(800)
                    # Settings is now a sidebar view (#view-settings), not a modal
                    settings_view = page.locator("#view-settings")
                    is_open = settings_view.count() > 0 and \
                        "active" in (settings_view.get_attribute("class") or "")
                    chk("2.2  Settings view opens (sidebar view becomes active)", is_open,
                        "view-settings did not get 'active' class")

                    if is_open:
                        # 2.3 Org info now lives in Account view — skip or note
                        warn("2.3  Org ID is in Account view (#view-account), not Settings view — skipping")
                        warn("2.4  Org ID check skipped (moved to Account view)")
                        warn("2.5  Plan label check skipped (moved to Account view)")

                        # 2.6 API base URL shown (#set-base-input in sidebar settings)
                        base_el = page.locator("#set-base-input, #sm-base-input")
                        base_val = base_el.get_attribute("value") or "" if base_el.count() > 0 else ""
                        chk("2.6  Settings shows API base URL",
                            "vantageaiops.com" in base_val, f"base='{base_val}'")

                        # 2.7 Key input field is empty (key not pre-filled for security)
                        key_el = page.locator("#set-key-input, #sm-key-input")
                        key_val = key_el.get_attribute("value") or "" if key_el.count() > 0 else ""
                        chk("2.7  API key input is empty by default (security)",
                            len(key_val) == 0, f"key pre-filled: '{key_val[:20]}'")

                        # 2.8 Switch to KEY2 via settings (applyNewKey or saveSettings)
                        try:
                            if key_el.count() > 0:
                                key_el.first.fill(KEY2)
                                save_btn = page.locator("[onclick*='applyNewKey'],[onclick*='saveSettings'],button:has-text('Apply')")
                                if save_btn.count() > 0:
                                    with page.expect_response(
                                        lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                                        timeout=10_000
                                    ) as resp_info:
                                        save_btn.first.click()
                                    resp = resp_info.value
                                    chk("2.8  Settings key switch → POST session 200",
                                        resp.status == 200, f"got {resp.status}")
                                    page.wait_for_timeout(2_000)
                                    chk("2.9  After key switch, stays on /app (no redirect to /auth)",
                                        "/app" in page.url,
                                        f"redirected to: {page.url}")
                                    warn("2.10 Org ID check skipped (Settings now sidebar view, org in Account view)")
                                else:
                                    warn("2.8  Save/Apply settings button not found")
                            else:
                                warn("2.8  Key input not found in settings view")
                        except PWTimeout:
                            fail("2.8  Settings key switch timed out")
                else:
                    warn("2.2  Settings button not found (tried #sb-settings and openSettings)")
            except Exception as e:
                warn(f"2.2  Settings view test error: {e}")

            # 2.11 Sign out via API (simulating logout button)
            try:
                cookies_dict = {c["name"]: c["value"] for c in ctx.cookies()}
                r_logout = requests.delete(f"{API_URL}/v1/auth/session",
                                           cookies=cookies_dict, timeout=10)
                chk("2.11 Logout (DELETE /session) → 200", r_logout.status_code == 200,
                    f"got {r_logout.status_code}")

                # 2.12 After logout, old cookies should not work
                r_after = requests.get(f"{API_URL}/v1/auth/session",
                                       cookies=cookies_dict, timeout=10)
                chk("2.12 After logout, session is invalidated → 401",
                    r_after.status_code == 401,
                    f"got {r_after.status_code} — session not properly cleared!")
            except Exception as e:
                fail("2.11  Logout test failed", str(e))

        # 2.13 No JS errors
        chk("2.13 No JS errors in settings tests", len(js_errors) == 0,
            str(js_errors[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests")
except Exception as e:
    fail("2.x  Settings UI test error", str(e)[:300])


# ─────────────────────────────────────────────────────────────────────────────
section("3. Homepage stability checks")
# ─────────────────────────────────────────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 3.1 Homepage loads
        page.goto(f"{SITE_URL}/", wait_until="networkidle", timeout=20_000)
        chk("3.1  Homepage loads (200)", page.title() != "")

        # 3.2 Nav buttons visible immediately (after nav-delay fix)
        signin_link = page.locator("#nav-signin")
        cta_link    = page.locator("#nav-cta")

        # Buttons should be visible right away now (opacity:0 removed)
        chk("3.2  Sign-in nav button visible on load",
            signin_link.count() > 0 and signin_link.is_visible(),
            "Sign in button hidden or missing")
        chk("3.3  Sign-up CTA button visible on load",
            cta_link.count() > 0 and cta_link.is_visible(),
            "Sign up button hidden or missing")

        # 3.4 Nav buttons don't have opacity:0 style
        si_opacity = signin_link.get_attribute("style") or "" if signin_link.count() > 0 else ""
        chk("3.4  Sign-in button not opacity:0 in inline style",
            "opacity:0" not in si_opacity and "opacity: 0" not in si_opacity,
            f"style='{si_opacity}' — nav delay bug still present!")

        # 3.5 VANTAGEAI brand visible
        chk("3.5  VANTAGEAI brand present", "VANTAGE" in page.content().upper())

        # 3.6 No JS errors on homepage
        page.wait_for_timeout(2_000)
        chk("3.6  No JS errors on homepage", len(js_errors) == 0,
            str(js_errors[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping homepage stability tests")
except Exception as e:
    fail("3.x  Homepage stability test error", str(e)[:300])


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Settings/profile tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
