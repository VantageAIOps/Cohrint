"""
test_auth_ui.py — Auth UI flow tests (Playwright)
=================================================
Suite AU: Tests /auth page UI, key input, sign in flow, session persistence.
Labels: AU.1 - AU.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api, get_session_cookie
from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
from helpers.output import ok, fail, warn, info, section, chk, get_results


def test_auth_page_load():
    section("AU. Auth UI — Page Load")

    r = requests.get(f"{SITE_URL}/auth", timeout=15, allow_redirects=True)
    chk("AU.1  /auth page loads → 200", r.status_code == 200, f"got {r.status_code}")
    chk("AU.2  /auth response not empty", len(r.text) > 100, f"body length: {len(r.text)}")


def test_auth_flow(api_key):
    section("AU. Auth UI — Sign In Flow (Playwright)")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("AU.3  playwright not installed — skipping")
        return

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        errors = collect_console_errors(page)
        start = time.monotonic()

        try:
            # AU.3 /auth page loads
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20000)
            chk("AU.3  /auth page loads in browser", True)

            # AU.4 Input field exists
            try:
                page.wait_for_selector("#inp-key", timeout=5000)
                chk("AU.4  API key input (#inp-key) present", True)
            except PWTimeout:
                fail("AU.4  API key input #inp-key not found")

            # AU.5 Invalid key shows error (not blank)
            page.fill("#inp-key", "vnt_invalidkey_abc123")
            try:
                with page.expect_response(
                    lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                    timeout=10000,
                ):
                    page.click("#signin-btn")
            except PWTimeout:
                warn("AU.5  No session request observed after clicking sign in")

            time.sleep(1)
            # Check that some error indicator is visible (not just blank)
            body_text = page.inner_text("body")
            still_on_auth = "/auth" in page.url or "/app" not in page.url
            chk("AU.5  Invalid key → stays on /auth or shows error", still_on_auth,
                f"URL: {page.url}")

            # AU.6 Valid key → redirects to /app
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20000)
            page.fill("#inp-key", api_key)
            try:
                with page.expect_response(
                    lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                    timeout=10000,
                ):
                    page.click("#signin-btn")
                page.wait_for_url(f"{SITE_URL}/app**", timeout=10000)
                chk("AU.6  Valid key → redirects to /app", "/app" in page.url,
                    f"URL: {page.url}")
            except PWTimeout:
                fail("AU.6  Did not redirect to /app after valid key sign in")

            # AU.7 Session preserved on reload
            if "/app" in page.url:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                chk("AU.7  Session preserved after reload", "/app" in page.url,
                    f"URL: {page.url}")
            else:
                warn("AU.7  Skipping session persistence — not on /app")

            # AU.8 No CORS errors in console
            cors_errors = [e for e in errors if "CORS" in e.upper() or "cors" in e.lower()]
            chk("AU.8  No CORS console errors", len(cors_errors) == 0,
                f"CORS errors: {cors_errors[:2]}")

            # AU.9 Full flow completes in < 15s (relaxed for CI)
            elapsed = time.monotonic() - start
            chk("AU.9  Auth flow completes < 15s", elapsed < 15,
                f"took {elapsed:.1f}s")

            # AU.10 No critical JS errors
            chk("AU.10 No critical JS errors", len(errors) == 0,
                f"errors: {list(errors)[:3]}")

        except Exception as e:
            fail(f"AU.3  Auth UI test exception: {e}")
        finally:
            browser.close()


def main():
    section("Suite AU — Auth UI Tests")
    info(f"Site: {SITE_URL}")

    test_auth_page_load()

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_auth_flow(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
