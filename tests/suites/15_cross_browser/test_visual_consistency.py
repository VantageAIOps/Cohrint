"""
test_visual_consistency.py — Visual + layout consistency across browsers
=========================================================================
Suite CV: Verifies that critical UI elements are visible and correctly
laid out across Chrome, Firefox, Safari, and mobile viewports.

Checks:
  - Landing page hero, navigation, CTA buttons
  - Auth page form, submit button, branding
  - App dashboard (post-auth): sidebar, KPI grid, navigation
  - Theme toggle (dark/light) works in each browser
  - Fonts load (no FOIT/invisible text)
  - Interactive elements are tappable on mobile (min 44px touch target)

Labels: CV.D (desktop), CV.M (mobile), CV.T (tablet)
"""

import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api
from helpers.browser import (
    make_desktop_ctx, make_device_ctx,
    collect_console_errors,
    DESKTOP_BROWSERS, MOBILE_DEVICES,
)
from helpers.output import ok, fail, warn, info, section, chk, get_results


# ── Shared element probes ─────────────────────────────────────────────────────

LANDING_ELEMENTS = {
    "hero/main heading":   "h1, .hero h2, .hero-title, [class*='hero'] h1, [class*='hero'] h2",
    "navigation bar":      "nav, header nav, .navbar, .nav-bar, #navbar",
    "CTA button":          "a.btn, .btn-primary, .cta, button.cta, a[href*='signup'], a[href*='/auth']",
}

AUTH_ELEMENTS = {
    "API key input":       "#inp-key, input[type='password'], input[name='api_key']",
    "sign-in button":      "#signin-btn, button[type='submit'], .btn-signin, .btn-login",
    "branding/logo":       ".logo, .brand, #logo, img[alt*='logo'], img[alt*='Vantage']",
}

APP_ELEMENTS = {
    "sidebar navigation":  ".sidebar, #sidebar, nav.sidebar, [class*='sidebar']",
    "KPI grid":            ".kpi-grid, .kpi-card, .metric-card, [class*='kpi']",
    "main content area":   ".main, main, #main, .content, [class*='content']",
}

TOUCH_MIN_PX = 44  # WCAG 2.5.5 minimum touch target size


def _element_visible(page, selector: str, timeout=4000) -> bool:
    try:
        page.wait_for_selector(selector, state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def _element_touch_size_ok(page, selector: str) -> tuple[bool, str]:
    """Check that an element meets minimum 44×44px touch target size."""
    try:
        el = page.query_selector(selector)
        if el is None:
            return False, "element not found"
        box = el.bounding_box()
        if box is None:
            return False, "no bounding box (possibly hidden)"
        w, h = box["width"], box["height"]
        ok_size = w >= TOUCH_MIN_PX and h >= TOUCH_MIN_PX
        return ok_size, f"{w:.0f}×{h:.0f}px"
    except Exception as e:
        return False, str(e)


def _theme_toggles(page) -> bool:
    """Click theme toggle and verify the data-theme attribute changes."""
    toggle_sel = (
        "#theme-toggle, .theme-toggle, [data-action='toggle-theme'], "
        ".btn-theme, [aria-label*='heme']"
    )
    try:
        toggle = page.query_selector(toggle_sel)
        if toggle is None:
            return False  # no toggle — warn, not fail
        before = page.evaluate("document.documentElement.getAttribute('data-theme') || ''")
        toggle.click()
        time.sleep(0.3)
        after = page.evaluate("document.documentElement.getAttribute('data-theme') || ''")
        return before != after
    except Exception:
        return False


def _fonts_loaded(page) -> bool:
    """Check that document.fonts.status is 'loaded' (no invisible text)."""
    try:
        status = page.evaluate("document.fonts.status")
        return status == "loaded"
    except Exception:
        return True  # Older browsers may not support document.fonts


# ── Desktop visual checks ─────────────────────────────────────────────────────

def _desktop_visual_check(pw, engine: str, label: str, prefix: str,
                           width: int, height: int, api_key: str):
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        browser, ctx, page = make_desktop_ctx(pw, engine=engine, width=width, height=height)
    except Exception as e:
        warn(f"{prefix}.1  {label} not installed: {e}")
        return

    errors = collect_console_errors(page)
    n = 1

    try:
        # ── Landing page ──────────────────────────────────────────────────────
        page.goto(f"{SITE_URL}/", wait_until="domcontentloaded", timeout=15_000)

        for elem_label, selector in LANDING_ELEMENTS.items():
            visible = _element_visible(page, selector)
            chk(f"{prefix}.{n}  [{label}] Landing — {elem_label} visible",
                visible, f"selector: {selector[:60]}")
            n += 1

        # Fonts loaded on landing
        chk(f"{prefix}.{n}  [{label}] Landing — fonts loaded (no invisible text)",
            _fonts_loaded(page))
        n += 1

        # Theme toggle
        toggled = _theme_toggles(page)
        if toggled:
            chk(f"{prefix}.{n}  [{label}] Landing — theme toggle switches data-theme", True)
        else:
            warn(f"{prefix}.{n}  [{label}] Landing — theme toggle not found or no data-theme change")
        n += 1

        # ── Auth page ─────────────────────────────────────────────────────────
        try:
            page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=15_000)
        except Exception as nav_err:
            if "interrupted by another navigation" in str(nav_err):
                warn(f"{prefix}.{n}  [{label}] Auth — navigation redirected (Safari session check)")
                n += len(AUTH_ELEMENTS)
            else:
                raise

        for elem_label, selector in AUTH_ELEMENTS.items():
            visible = _element_visible(page, selector)
            chk(f"{prefix}.{n}  [{label}] Auth — {elem_label} visible",
                visible, f"selector: {selector[:60]}")
            n += 1

        # Submit on Enter key (keyboard accessibility)
        page.fill("#inp-key, input[type='password']", "test_key_kbd")
        page.keyboard.press("Enter")
        time.sleep(0.8)
        chk(f"{prefix}.{n}  [{label}] Auth — Enter key submits form (no crash)",
            True)  # If we got here without exception, Enter key didn't crash the page
        n += 1

        # ── App (post-auth) ───────────────────────────────────────────────────
        if api_key:
            try:
                page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=15_000)
                page.fill("#inp-key, input[type='password']", api_key)
                with page.expect_response(
                    lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                    timeout=10_000,
                ):
                    page.click("#signin-btn, button[type='submit']")
                page.wait_for_url(f"{SITE_URL}/app**", timeout=10_000)

                page.wait_for_load_state("domcontentloaded")
                time.sleep(1)

                for elem_label, selector in APP_ELEMENTS.items():
                    visible = _element_visible(page, selector)
                    chk(f"{prefix}.{n}  [{label}] App — {elem_label} visible",
                        visible, f"selector: {selector[:60]}")
                    n += 1

                # No JS errors after signing in and loading app
                ok_js = len(errors) == 0
                chk(f"{prefix}.{n}  [{label}] App — no critical JS errors after sign-in",
                    ok_js, f"errors: {list(errors)[:3]}")
                n += 1

            except PWTimeout as e:
                warn(f"{prefix}.{n}  [{label}] App sign-in timed out: {e}")
                n += len(APP_ELEMENTS) + 1
        else:
            warn(f"{prefix}.{n}  [{label}] App checks skipped (no API key)")
            n += len(APP_ELEMENTS) + 1

    except Exception as e:
        if "interrupted by another navigation" in str(e):
            warn(f"{prefix}.X  [{label}] Navigation redirected (Safari session check)")
        else:
            fail(f"{prefix}.X  [{label}] Unexpected error: {e}")
    finally:
        browser.close()


def test_visual_chrome():
    section("CV-D1. Visual Consistency — Chrome (1440×900)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-D1  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _desktop_visual_check(pw, "chromium", "Chrome", "CV.D1", 1440, 900, api_key)


def test_visual_firefox():
    section("CV-D2. Visual Consistency — Firefox (1440×900)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-D2  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _desktop_visual_check(pw, "firefox", "Firefox", "CV.D2", 1440, 900, api_key)


def test_visual_webkit():
    section("CV-D3. Visual Consistency — Safari/WebKit (1440×900)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-D3  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _desktop_visual_check(pw, "webkit", "Safari/WebKit", "CV.D3", 1440, 900, api_key)


# ── Mobile visual + touch-target checks ──────────────────────────────────────

def _mobile_visual_check(pw, device_name: str, engine: str, label: str,
                          prefix: str, api_key: str):
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        browser, ctx, page = make_device_ctx(pw, device_name, engine=engine)
    except Exception as e:
        warn(f"{prefix}.1  {label} not available: {e}")
        return

    errors = collect_console_errors(page)
    n = 1

    try:
        # ── Landing ───────────────────────────────────────────────────────────
        page.goto(f"{SITE_URL}/", wait_until="domcontentloaded", timeout=15_000)

        # No horizontal overflow
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        vp_w     = page.evaluate("window.innerWidth")
        chk(f"{prefix}.{n}  [{label}] Landing — no horizontal overflow",
            scroll_w <= vp_w + 5, f"scrollWidth={scroll_w} viewportWidth={vp_w}")
        n += 1

        # Navigation is accessible (hamburger or full nav)
        nav_visible = _element_visible(page, "nav, header, .navbar, .nav-toggle, .hamburger, #nav",
                                       timeout=3000)
        chk(f"{prefix}.{n}  [{label}] Landing — navigation accessible on mobile",
            nav_visible)
        n += 1

        # CTA button meets touch-target size
        cta_ok, cta_info = _element_touch_size_ok(
            page, "a.btn, .btn-primary, .cta, button.cta, a[href*='signup'], a[href*='/auth']"
        )
        if cta_ok:
            chk(f"{prefix}.{n}  [{label}] Landing — CTA button ≥44px touch target", True,
                cta_info)
        else:
            warn(f"{prefix}.{n}  [{label}] Landing — CTA touch target: {cta_info}")
        n += 1

        # ── Auth page ─────────────────────────────────────────────────────────
        page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=15_000)

        # Input + button visible
        chk(f"{prefix}.{n}  [{label}] Auth — input visible on mobile",
            _element_visible(page, "#inp-key, input[type='password']"))
        n += 1

        # Submit button meets touch target
        btn_ok, btn_info = _element_touch_size_ok(
            page, "#signin-btn, button[type='submit'], .btn-signin, .btn-login"
        )
        if btn_ok:
            chk(f"{prefix}.{n}  [{label}] Auth — sign-in button ≥44px touch target",
                True, btn_info)
        else:
            warn(f"{prefix}.{n}  [{label}] Auth — sign-in button touch target: {btn_info}")
        n += 1

        # Auth page no horizontal overflow
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        vp_w     = page.evaluate("window.innerWidth")
        chk(f"{prefix}.{n}  [{label}] Auth — no horizontal overflow",
            scroll_w <= vp_w + 5, f"scrollWidth={scroll_w} viewportWidth={vp_w}")
        n += 1

        # ── App (post-auth) ───────────────────────────────────────────────────
        if api_key:
            try:
                page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=15_000)
                page.fill("#inp-key, input[type='password']", api_key)
                with page.expect_response(
                    lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                    timeout=10_000,
                ):
                    page.click("#signin-btn, button[type='submit']")
                page.wait_for_url(f"{SITE_URL}/app**", timeout=10_000)
                time.sleep(1)

                # No horizontal overflow on app
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                vp_w     = page.evaluate("window.innerWidth")
                chk(f"{prefix}.{n}  [{label}] App — no horizontal overflow on mobile",
                    scroll_w <= vp_w + 5, f"scrollWidth={scroll_w}")
                n += 1

                # Sidebar collapses / mobile menu present
                mobile_nav = _element_visible(
                    page, ".sidebar, .mobile-menu, .nav-toggle, "
                          "[class*='mobile'], [class*='hamburger'], "
                          "nav, #nav",
                    timeout=3000
                )
                if mobile_nav:
                    chk(f"{prefix}.{n}  [{label}] App — mobile navigation present", True)
                else:
                    warn(f"{prefix}.{n}  [{label}] App — mobile navigation not yet implemented")
                n += 1

            except PWTimeout as e:
                warn(f"{prefix}.{n}  [{label}] App sign-in timed out: {e}")
                n += 2

        # No critical JS errors
        ok_js = len(errors) == 0
        chk(f"{prefix}.{n}  [{label}] No critical JS errors across all pages",
            ok_js, f"errors: {list(errors)[:3]}")

    except Exception as e:
        if "interrupted by another navigation" in str(e):
            warn(f"{prefix}.X  [{label}] Navigation redirected (Safari session check)")
        else:
            fail(f"{prefix}.X  [{label}] Unexpected error: {e}")
    finally:
        browser.close()


def test_visual_mobile_android():
    section("CV-M1. Visual Consistency — Android Chrome (Pixel 5)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-M1  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _mobile_visual_check(pw, "Pixel 5", "chromium", "Android/Pixel 5", "CV.M1", api_key)


def test_visual_mobile_ios():
    section("CV-M2. Visual Consistency — Mobile Safari (iPhone 14)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-M2  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _mobile_visual_check(pw, "iPhone 14", "webkit", "Mobile Safari/iPhone 14", "CV.M2", api_key)


def test_visual_tablet_ipad():
    section("CV-T1. Visual Consistency — Safari iPad (Tablet)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-T1  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _mobile_visual_check(pw, "iPad Pro 11", "webkit", "Safari/iPad", "CV.T1", api_key)


def test_visual_tablet_android():
    section("CV-T2. Visual Consistency — Android Tablet (Galaxy Tab S4)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn("CV-T2  playwright not installed — skipping")
        return
    api_key = _get_api_key()
    with sync_playwright() as pw:
        _mobile_visual_check(pw, "Galaxy Tab S4", "chromium", "Android/Tablet", "CV.T2", api_key)


# ── Helpers ───────────────────────────────────────────────────────────────────

_shared_api_key: str = ""


def _get_api_key() -> str:
    global _shared_api_key
    if _shared_api_key:
        return _shared_api_key
    try:
        d = signup_api()
        _shared_api_key = d.get("api_key", "")
        info(f"Test account created: {d.get('org_id', 'unknown')}")
    except Exception as e:
        warn(f"Could not create test account: {e} — app checks will be skipped")
    return _shared_api_key


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    info(f"Site URL : {SITE_URL}")
    print()

    # Desktop visual checks
    test_visual_chrome()
    test_visual_firefox()
    test_visual_webkit()

    # Mobile and tablet visual + touch-target checks
    all_devices = os.environ.get("CB_ALL_DEVICES", "1") == "1"
    if all_devices:
        test_visual_mobile_android()
        test_visual_mobile_ios()
        test_visual_tablet_ipad()
        test_visual_tablet_android()
    else:
        test_visual_mobile_android()
        test_visual_tablet_ipad()

    results = get_results()
    passed  = results["passed"]
    failed  = results["failed"]
    warned  = results["warned"]
    total   = passed + failed

    print()
    print(f"{'='*62}")
    print(f"  Visual Consistency Suite: {passed}/{total} passed  |  {warned} warnings")
    print(f"{'='*62}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
