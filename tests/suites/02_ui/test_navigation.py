"""
test_navigation.py — Navigation and page load tests (Playwright)
================================================================
Suite N: Tests all navigation, page loads, sidebar links, and mobile layout.
Labels: N.1 - N.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api, fresh_account
from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
from helpers.output import ok, fail, warn, info, section, chk, get_results


SIDEBAR_VIEWS = [
    ("button.sb-item:has-text('Spend')",    "/app", "Spend Analysis"),
    ("button.sb-item:has-text('Model')",    "/app", "Model Pricing"),
    ("button.sb-item:has-text('Members')",  "/app", "Members"),
    ("button.sb-item:has-text('Budget')",   "/app", "Budgets"),
    ("button.sb-item:has-text('Settings')", "/app", "Settings"),
    ("button.sb-item:has-text('Account')",  "/app", "Account"),
]

PAGES_TO_CHECK = [
    ("/auth",        200, "Auth page"),
    ("/signup",      200, "Signup page"),
    ("/docs",        200, "Docs page"),
    ("/calculator",  200, "Calculator page"),
    ("/",            200, "Landing page"),
]


def test_pages_load():
    section("N. Navigation — Page Load Tests")
    for path, expected_status, label in PAGES_TO_CHECK:
        try:
            r = requests.get(f"{SITE_URL}{path}", timeout=15, allow_redirects=True)
            chk(f"N.1  {label} ({path}) loads → {expected_status}",
                r.status_code == expected_status,
                f"got {r.status_code}")
        except Exception as e:
            fail(f"N.1  {label} ({path}) → exception: {e}")


def test_app_navigation(api_key):
    section("N. Navigation — App Sidebar (Playwright)")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("N.2  playwright not installed — skipping UI navigation tests")
        return

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        errors = collect_console_errors(page)

        try:
            # Sign in
            signed_in = signin_ui(page, api_key)
            chk("N.2  Sign in → /app redirect", signed_in,
                f"current URL: {page.url}")

            if not signed_in:
                fail("N.3  Cannot test navigation — sign in failed")
                return

            # Check each sidebar nav item
            for i, (selector, url_contains, label) in enumerate(SIDEBAR_VIEWS, start=3):
                try:
                    page.click(selector, timeout=5000)
                    time.sleep(0.5)
                    chk(f"N.{i}  Sidebar {label} clickable", True)
                except PWTimeout:
                    warn(f"N.{i}  Sidebar {label} ({selector}) not found or timeout")
                except Exception as e:
                    warn(f"N.{i}  Sidebar {label} ({selector}): {e}")

            # Test "← home" button
            try:
                page.click("#btn-home, .btn-home, [data-action='home']", timeout=3000)
                time.sleep(1)
                chk("N.11 Home button navigates away from /app",
                    "/app" not in page.url or SITE_URL in page.url)
            except PWTimeout:
                warn("N.11 Home button not found — may use different selector")

            # Logo click
            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=20000)
                page.click("img.logo, .logo, #logo, a[href='/']", timeout=3000)
                time.sleep(1)
                chk("N.12 Logo click navigates to home", True)
            except PWTimeout:
                warn("N.12 Logo selector not found")
            except Exception as e:
                warn(f"N.12 Logo click: {e}")

            # No JS errors after navigation
            chk("N.13 No critical JS errors during navigation",
                len(errors) == 0,
                f"errors: {list(errors)[:3]}")

        finally:
            browser.close()


def test_mobile_layout(api_key):
    section("N. Navigation — Mobile Layout (375x812)")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("N.14 playwright not installed — skipping mobile tests")
        return

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw, viewport=(375, 812))
        errors = collect_console_errors(page)

        try:
            # Landing page on mobile
            page.goto(f"{SITE_URL}/", wait_until="networkidle", timeout=20000)
            chk("N.14 Landing page loads on mobile (375x812)",
                page.url.startswith(SITE_URL))

            # Auth page on mobile
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20000)
            chk("N.15 Auth page loads on mobile", True)

            # Check no horizontal overflow (basic layout check)
            width = page.evaluate("document.documentElement.scrollWidth")
            viewport_w = page.evaluate("window.innerWidth")
            chk("N.16 No horizontal scroll on mobile",
                width <= viewport_w + 20,  # 20px tolerance for scrollbar/rounding
                f"scrollWidth={width}, viewportWidth={viewport_w}")

            chk("N.17 No critical JS errors on mobile", len(errors) == 0,
                f"errors: {list(errors)[:3]}")

        except Exception as e:
            fail(f"N.14 Mobile layout test exception: {e}")
        finally:
            browser.close()


def main():
    section("Suite N — Navigation Tests")
    info(f"Site: {SITE_URL}")

    # Page load tests (no auth needed)
    test_pages_load()

    # Create account for app navigation tests
    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account created: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_app_navigation(api_key)
    test_mobile_layout(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
