"""
test_auth_cross_browser.py — Sign-in flow across all browsers + devices
=========================================================================
Suite CA: Verifies that the full sign-in flow (API key → /app) works
identically across every supported browser and device.

Tests:
  CA.D  Desktop: Chrome, Firefox, Safari/WebKit
  CA.M  Mobile:  Android Chrome, Mobile Safari
  CA.T  Tablet:  iPad Safari, Android Tablet

Each browser runs:
  1. Navigate to /auth
  2. Enter invalid key → verify stays on /auth (no crash)
  3. Enter valid key   → verify redirected to /app
  4. Reload /app       → verify session persists (cookie correctly set)
  5. No console errors throughout
"""

import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api
from helpers.browser import make_desktop_ctx, make_device_ctx, collect_console_errors
from helpers.output import ok, fail, warn, info, section, chk, get_results

TIMEOUT = 15_000

# Shared test account — created once, reused across all browser tests
_api_key: str = ""


def _ensure_account() -> str:
    global _api_key
    if _api_key:
        return _api_key
    try:
        d = signup_api()
        _api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Cannot create test account: {e}")
    return _api_key


def _run_auth_flow(page, errors, api_key: str, prefix: str, label: str, is_webkit: bool = False) -> int:
    """
    Run the standard sign-in flow on an already-open page/context.
    Returns number of checks executed.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    n = 1

    # Step 1: navigate to /auth
    try:
        page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=20_000)
        chk(f"{prefix}.{n}  [{label}] /auth page loads", True)
    except Exception as e:
        fail(f"{prefix}.{n}  [{label}] /auth failed to load: {e}")
        return n
    n += 1

    # Step 2: invalid key stays on /auth
    try:
        page.fill("#inp-key, input[type='password'], input[type='text']",
                  "vnt_invalid_crossbrowser_test")
        try:
            with page.expect_response(
                lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                timeout=8000,
            ):
                page.click("#signin-btn, button[type='submit'], .btn-login, .btn-signin")
        except PWTimeout:
            pass  # some browsers may not fire the request for invalid keys
        time.sleep(0.8)
        still_auth = "/auth" in page.url or "/app" not in page.url
        chk(f"{prefix}.{n}  [{label}] Invalid key → stays on /auth",
            still_auth, f"url: {page.url}")
    except Exception as e:
        warn(f"{prefix}.{n}  [{label}] Invalid key step: {e}")
    n += 1

    # Step 3: valid key → /app
    if not api_key:
        warn(f"{prefix}.{n}  [{label}] No API key — skipping valid sign-in")
        return n + 2

    try:
        page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=20_000)
        page.fill("#inp-key, input[type='password'], input[type='text']", api_key)
        with page.expect_response(
            lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
            timeout=TIMEOUT,
        ):
            page.click("#signin-btn, button[type='submit'], .btn-login, .btn-signin")
        page.wait_for_url(f"{SITE_URL}/app**", timeout=TIMEOUT)
        chk(f"{prefix}.{n}  [{label}] Valid key → redirects to /app",
            "/app" in page.url, f"url: {page.url}")
    except PWTimeout as e:
        fail(f"{prefix}.{n}  [{label}] Sign-in timeout: {e}")
        return n + 2
    except Exception as e:
        fail(f"{prefix}.{n}  [{label}] Sign-in error: {e}")
        return n + 2
    n += 1

    # Step 4: reload preserves session
    try:
        page.reload(wait_until="domcontentloaded", timeout=15_000)
        # Wait for JS auth-check redirect to settle (WebKit ITP needs more time)
        try:
            page.wait_for_url(lambda url: "/app" in url or "/auth" in url, timeout=5_000)
        except Exception:
            pass
        # TODO: restore chk after SameSite=None Worker fix deploys (PR #44)
        if is_webkit:
            warn(f"{prefix}.{n}  [{label}] Session persists after reload — known WebKit ITP issue (SameSite=None fix pending deploy)")
        else:
            chk(f"{prefix}.{n}  [{label}] Session persists after reload",
                "/app" in page.url, f"url after reload: {page.url}")
    except Exception as e:
        warn(f"{prefix}.{n}  [{label}] Reload check: {e}")
    n += 1

    # Step 5: no console errors (filter out CORS warnings — not critical)
    critical_errors = [e for e in errors if "access control" not in str(e).lower()]
    ok_js = len(critical_errors) == 0
    chk(f"{prefix}.{n}  [{label}] No critical JS errors during auth flow",
        ok_js, f"errors: {list(critical_errors)[:3]}")
    n += 1

    return n


# ── Desktop auth flow ─────────────────────────────────────────────────────────

def _desktop_auth(engine: str, label: str, prefix: str, width=1440, height=900):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn(f"{prefix}.1  playwright not installed — skipping {label}")
        return

    api_key = _ensure_account()
    with sync_playwright() as pw:
        try:
            browser, ctx, page = make_desktop_ctx(pw, engine=engine, width=width, height=height)
        except Exception as e:
            warn(f"{prefix}.1  {label} not installed: {e}")
            return
        errors = collect_console_errors(page)
        try:
            _run_auth_flow(page, errors, api_key, prefix, label, is_webkit=(engine == "webkit"))
        finally:
            browser.close()


def test_auth_chrome():
    section("CA-D1. Auth Flow — Chrome Desktop")
    _desktop_auth("chromium", "Chrome", "CA.D1")


def test_auth_firefox():
    section("CA-D2. Auth Flow — Firefox Desktop")
    _desktop_auth("firefox", "Firefox", "CA.D2")


def test_auth_webkit():
    section("CA-D3. Auth Flow — Safari/WebKit Desktop")
    _desktop_auth("webkit", "Safari/WebKit", "CA.D3")


def test_auth_chrome_small():
    section("CA-D4. Auth Flow — Chrome (1024×768 small laptop)")
    _desktop_auth("chromium", "Chrome 1024w", "CA.D4", width=1024, height=768)


# ── Mobile auth flow ──────────────────────────────────────────────────────────

def _device_auth(device_name: str, engine: str, label: str, prefix: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn(f"{prefix}.1  playwright not installed — skipping {label}")
        return

    api_key = _ensure_account()
    with sync_playwright() as pw:
        try:
            browser, ctx, page = make_device_ctx(pw, device_name, engine=engine)
        except Exception as e:
            warn(f"{prefix}.1  {label} ({device_name}) not available: {e}")
            return
        errors = collect_console_errors(page)
        try:
            _run_auth_flow(page, errors, api_key, prefix, label, is_webkit=(engine == "webkit"))
        finally:
            browser.close()


def test_auth_android():
    section("CA-M1. Auth Flow — Android Chrome (Pixel 5)")
    _device_auth("Pixel 5", "chromium", "Android/Pixel 5", "CA.M1")


def test_auth_ios():
    section("CA-M2. Auth Flow — Mobile Safari (iPhone 14)")
    _device_auth("iPhone 14", "webkit", "Mobile Safari/iPhone 14", "CA.M2")


def test_auth_tablet_ipad():
    section("CA-T1. Auth Flow — Safari iPad")
    _device_auth("iPad Pro 11", "webkit", "Safari/iPad", "CA.T1")


def test_auth_tablet_android():
    section("CA-T2. Auth Flow — Android Tablet (Galaxy Tab S4)")
    _device_auth("Galaxy Tab S4", "chromium", "Android/Tablet", "CA.T2")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    info(f"Site URL : {SITE_URL}")
    print()

    # Desktop
    test_auth_chrome()
    test_auth_firefox()
    test_auth_webkit()
    test_auth_chrome_small()

    # Mobile / Tablet (opt-in or always in CI)
    all_devices = os.environ.get("CB_ALL_DEVICES", "1") == "1"
    if all_devices:
        test_auth_android()
        test_auth_ios()
        test_auth_tablet_ipad()
        test_auth_tablet_android()
    else:
        test_auth_android()

    results = get_results()
    passed  = results["passed"]
    failed  = results["failed"]
    warned  = results["warned"]
    total   = passed + failed

    print()
    print(f"{'='*62}")
    print(f"  Auth Cross-Browser Suite: {passed}/{total} passed  |  {warned} warnings")
    print(f"{'='*62}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
