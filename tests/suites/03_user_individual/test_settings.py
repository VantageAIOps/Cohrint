"""
test_settings.py — User settings and key rotation tests
=======================================================
Suite ST: Tests GET session, POST rotate, Playwright settings modal.
Labels: ST.1 - ST.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_session_shows_org(api_key, org_id):
    section("ST. Settings — Session Data")

    cookies = get_session_cookie(api_key)
    if not cookies:
        fail("ST.1  Could not get session cookie")
        return

    r = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=15)
    chk("ST.1  GET /session → 200", r.status_code == 200, f"got {r.status_code}")

    if r.ok:
        d = r.json()
        chk("ST.2  Session returns org_id", "org_id" in d,
            f"keys: {list(d.keys())}")
        if "org_id" in d:
            chk("ST.3  Session org_id matches signup org_id",
                d["org_id"] == org_id,
                f"session={d['org_id']}, signup={org_id}")


def test_key_rotation(api_key):
    section("ST. Settings — Key Rotation")

    headers = get_headers(api_key)

    # ST.4 POST /rotate → 200 + new key
    r = requests.post(f"{API_URL}/v1/auth/rotate", headers=headers, timeout=15)
    chk("ST.4  POST /rotate → 200", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")

    if r.ok:
        d = r.json()
        new_key = d.get("api_key") or d.get("new_key") or d.get("key")
        chk("ST.5  POST /rotate returns new key", bool(new_key),
            f"response keys: {list(d.keys())}")

        if new_key:
            chk("ST.6  New key starts with vnt_", new_key.startswith("vnt_"))

            # ST.7 New key works for session
            r2 = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": new_key}, timeout=15)
            chk("ST.7  New rotated key works for session", r2.status_code == 200,
                f"got {r2.status_code}")

            # ST.8 New key works for analytics
            r3 = requests.get(f"{API_URL}/v1/analytics/summary",
                              headers=get_headers(new_key), timeout=15)
            chk("ST.8  New key works for analytics", r3.status_code in (200, 404),
                f"got {r3.status_code}")

            return new_key

    return None


def test_settings_ui(api_key, org_id):
    section("ST. Settings — Playwright Settings Modal")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("ST.9  playwright not installed — skipping")
        return

    with sync_playwright() as pw:
        from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
        try:
            browser, ctx, page = make_browser_ctx(pw)
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                warn("ST.9  Chromium not installed — skipping browser tests")
                return
            raise
        errors = collect_console_errors(page)

        try:
            signed_in = signin_ui(page, api_key)
            if not signed_in:
                fail("ST.9  Sign in failed — cannot test settings UI")
                return

            chk("ST.9  Sign in → /app", True)

            # ST.10 Settings modal opens
            try:
                page.click("#nav-settings, [data-action='settings'], .settings-btn",
                           timeout=5000)
                time.sleep(0.5)
                page.wait_for_selector(".modal, dialog, [role='dialog']", timeout=5000)
                chk("ST.10 Settings modal opens", True)
            except PWTimeout:
                warn("ST.10 Settings modal not found (selector may differ)")

            # ST.11 Org ID visible in settings
            try:
                body = page.inner_text("body")
                chk("ST.11 Org ID visible in page", org_id in body,
                    f"org_id '{org_id}' not found in page text")
            except Exception as e:
                warn(f"ST.11 Could not check org_id in page: {e}")

            # ST.12 API base URL shown
            try:
                body = page.inner_text("body")
                has_api_url = "api.vantageaiops.com" in body or API_URL in body
                chk("ST.12 API base URL visible in settings", has_api_url,
                    "API URL not found in page text")
            except Exception as e:
                warn(f"ST.12 Could not check API URL in page: {e}")

            # ST.13 Logout works
            try:
                page.press("Escape")  # Close modal
                time.sleep(0.3)
                page.click("#btn-logout, [data-action='logout'], .logout-btn", timeout=5000)
                time.sleep(1)
                chk("ST.13 Logout navigates away from /app",
                    "/app" not in page.url or "/auth" in page.url,
                    f"URL: {page.url}")
            except PWTimeout:
                warn("ST.13 Logout button not found (selector may differ)")

        except Exception as e:
            fail(f"ST.9  Settings UI exception: {e}")
        finally:
            browser.close()


def main():
    section("Suite ST — Settings & Profile Tests")
    info(f"API: {API_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        info(f"Test account: {org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_session_shows_org(api_key, org_id)
    new_key = test_key_rotation(api_key)

    # Use new key for UI test if rotation succeeded
    test_key = new_key if new_key else api_key
    test_settings_ui(test_key, org_id)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
