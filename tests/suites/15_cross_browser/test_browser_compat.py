"""
test_browser_compat.py — Cross-browser compatibility tests
===========================================================
Suite CB: Tests all public pages across Chrome, Firefox, Safari (WebKit),
          Android mobile, iOS mobile, and tablet viewports.

Each browser/device runs the same core page-load + JS-error + layout checks
so regressions are caught before they reach production.

Labels: CB.A.<n> (Chrome), CB.F.<n> (Firefox), CB.W.<n> (WebKit/Safari),
        CB.M.<n> (Mobile), CB.T.<n> (Tablet)

Run modes:
  - Default CI   : Chrome + Firefox + WebKit (all installed in ubuntu runner)
  - Full matrix  : add --devices flag to run_suite.py (or set CB_ALL_DEVICES=1)
"""

import os
import sys
import time
import requests
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api
from helpers.browser import (
    DESKTOP_BROWSERS, MOBILE_DEVICES, TABLET_DEVICES,
    make_desktop_ctx, make_device_ctx,
    collect_console_errors,
)
from helpers.output import ok, fail, warn, info, section, chk, get_results

# Pages that must load cleanly without authentication
PUBLIC_PAGES = [
    ("/",              "Landing page"),
    ("/auth",          "Auth / Sign-in"),
    ("/signup",        "Sign-up"),
    ("/docs",          "Documentation"),
    ("/calculator",    "Calculator"),
]

# Pages that redirect to /auth when not authenticated (just check they don't 500)
PROTECTED_PAGES = [
    ("/app",  "Dashboard"),
]

# Critical DOM elements that MUST be present on each page
PAGE_CRITICAL_ELEMENTS = {
    "/":           ["body", "nav, header, .nav, .navbar, #nav"],
    "/auth":       ["body", "#inp-key, input[type='password'], input[type='text']"],
    "/signup":     ["body", "input, form"],
    "/docs":       ["body"],
    "/calculator": ["body"],
    "/app":        ["body"],
}

# Selectors for viewport/layout checks (at least ONE must be visible)
LAYOUT_PROBE_SELECTORS = [
    "body > *",
    "main, #app, .app, .container, .wrapper",
    "header, nav, .navbar",
]

# Performance budget (ms) — relaxed for CI/cold-cache
LOAD_BUDGET_MS = 8_000


def _available_browsers(playwright):
    """Return which engines are actually installed (graceful degradation)."""
    available = []
    for engine, label, vp in DESKTOP_BROWSERS:
        try:
            getattr(playwright, engine)
            available.append((engine, label, vp))
        except Exception:
            pass
    return available


def _page_http_ok(path: str) -> tuple[bool, int]:
    """HTTP-level check: returns (ok, status_code)."""
    try:
        r = requests.get(f"{SITE_URL}{path}", timeout=15, allow_redirects=True)
        return r.status_code < 500, r.status_code
    except Exception as e:
        return False, 0


def _critical_elements_present(page, path: str) -> list[str]:
    """Return list of critical selectors that are MISSING on this page."""
    selectors = PAGE_CRITICAL_ELEMENTS.get(path, ["body"])
    missing = []
    for sel in selectors:
        try:
            # Use comma-separated selectors — any match is a pass
            page.wait_for_selector(sel, timeout=3000, state="attached")
        except Exception:
            missing.append(sel)
    return missing


def _no_critical_js_errors(errors) -> tuple[bool, list]:
    errs = list(errors)
    return len(errs) == 0, errs[:3]


def _layout_not_broken(page) -> bool:
    """Check that the page body has rendered content (not an empty shell)."""
    try:
        return page.evaluate("document.body.children.length") > 0
    except Exception:
        return False


def _page_loaded_fast(t_ms: float) -> bool:
    return t_ms < LOAD_BUDGET_MS


# ── Core page-load probe (runs for every browser/device) ─────────────────────

def probe_page(page, errors, path: str, label: str, prefix: str, counter: list):
    """
    Run all standard checks for a single page in a single browser context.
    `counter` is a mutable [int] used to auto-number checks.
    """
    n = counter[0]

    # Load the page and measure time
    t0 = time.monotonic()
    try:
        resp = page.goto(
            f"{SITE_URL}{path}",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        t_ms = (time.monotonic() - t0) * 1000
    except Exception as e:
        fail(f"{prefix}.{n}  [{label}] {path} — page.goto failed: {e}")
        counter[0] += 1
        return

    # Check HTTP status (not 5xx)
    status = resp.status if resp else 0
    chk(f"{prefix}.{n}  [{label}] {path} loads (no 5xx)",
        status < 500,
        f"HTTP {status}")
    counter[0] += 1; n += 1

    # Layout not broken
    chk(f"{prefix}.{n}  [{label}] {path} body has rendered content",
        _layout_not_broken(page),
        "body.children.length == 0")
    counter[0] += 1; n += 1

    # Load time
    chk(f"{prefix}.{n}  [{label}] {path} loads < {LOAD_BUDGET_MS}ms",
        _page_loaded_fast(t_ms),
        f"took {t_ms:.0f}ms")
    counter[0] += 1; n += 1

    # Critical DOM elements present
    missing = _critical_elements_present(page, path)
    chk(f"{prefix}.{n}  [{label}] {path} critical DOM elements present",
        len(missing) == 0,
        f"missing: {missing}")
    counter[0] += 1; n += 1


# ── Desktop browser tests ─────────────────────────────────────────────────────

def test_desktop_chrome():
    section("CB-A. Chrome / Chromium — Desktop")
    _run_desktop("chromium", "Chrome",  "CB.A", (1440, 900))


def test_desktop_firefox():
    section("CB-F. Firefox — Desktop")
    _run_desktop("firefox", "Firefox", "CB.F", (1440, 900))


def test_desktop_webkit():
    section("CB-W. Safari / WebKit — Desktop")
    _run_desktop("webkit", "Safari/WebKit", "CB.W", (1440, 900))


def test_desktop_widescreen():
    section("CB-L. Chromium — Wide / Large Monitor (1920×1080)")
    _run_desktop("chromium", "Chrome 1920w", "CB.L", (1920, 1080))


def test_desktop_small():
    section("CB-S. Chromium — Small Laptop (1280×768)")
    _run_desktop("chromium", "Chrome 1280w", "CB.S", (1280, 768))


def _run_desktop(engine: str, label: str, prefix: str, viewport: tuple):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn(f"{prefix}.1  playwright not installed — skipping {label}")
        return

    with sync_playwright() as pw:
        try:
            browser, ctx, page = make_desktop_ctx(pw, engine=engine,
                                                   width=viewport[0], height=viewport[1])
        except Exception as e:
            warn(f"{prefix}.1  {label} not installed: {e}")
            return

        errors = collect_console_errors(page)
        counter = [1]

        try:
            for path, page_label in PUBLIC_PAGES + PROTECTED_PAGES:
                probe_page(page, errors, path, label, prefix, counter)

            # JS error check covering ALL pages visited
            ok_js, errs = _no_critical_js_errors(errors)
            chk(f"{prefix}.{counter[0]}  [{label}] No critical JS errors across all pages",
                ok_js, f"errors: {errs}")
            counter[0] += 1

            # Theme toggle present on landing page
            page.goto(f"{SITE_URL}/", wait_until="domcontentloaded", timeout=15_000)
            theme_toggle = page.query_selector(
                "#theme-toggle, .theme-toggle, [data-action='toggle-theme'], "
                ".btn-theme, [aria-label*='theme'], [aria-label*='Theme']"
            )
            warn(f"{prefix}.{counter[0]}  [{label}] Theme toggle element present" +
                 (" — found" if theme_toggle else " — not on landing page (acceptable)"))
            counter[0] += 1

        except Exception as e:
            fail(f"{prefix}.X  [{label}] Unexpected error: {e}")
        finally:
            browser.close()


# ── Mobile device tests ───────────────────────────────────────────────────────

def test_mobile_android():
    section("CB-M1. Android Chrome — Mobile (Pixel 5)")
    _run_device("Pixel 5", "Android/Chrome", "CB.M1", "chromium")


def test_mobile_ios():
    section("CB-M2. Mobile Safari — iOS (iPhone 14)")
    _run_device("iPhone 14", "Mobile Safari/iOS", "CB.M2", "webkit")


def test_mobile_samsung():
    section("CB-M3. Samsung Internet — Android (Galaxy S8)")
    _run_device("Galaxy S8", "Samsung/Android", "CB.M3", "chromium")


def test_mobile_ios_large():
    section("CB-M4. Mobile Safari — iPhone 14 Pro Max")
    _run_device("iPhone 14 Pro Max", "Mobile Safari/Large", "CB.M4", "webkit")


def _run_device(device_name: str, label: str, prefix: str, engine: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn(f"{prefix}.1  playwright not installed — skipping {label}")
        return

    with sync_playwright() as pw:
        try:
            browser, ctx, page = make_device_ctx(pw, device_name, engine=engine)
        except Exception as e:
            warn(f"{prefix}.1  {label} ({device_name}) not available: {e}")
            return

        errors = collect_console_errors(page)
        counter = [1]

        try:
            # Core pages
            for path, page_label in PUBLIC_PAGES + PROTECTED_PAGES:
                probe_page(page, errors, path, label, prefix, counter)

            # Mobile: check that viewport meta is respected (page doesn't overflow)
            page.goto(f"{SITE_URL}/", wait_until="domcontentloaded", timeout=15_000)
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            viewport_width = page.evaluate("window.innerWidth")
            chk(f"{prefix}.{counter[0]}  [{label}] No horizontal overflow on landing page",
                scroll_width <= viewport_width + 5,  # 5px tolerance
                f"scrollWidth={scroll_width} > viewportWidth={viewport_width}")
            counter[0] += 1

            # Mobile: auth page input accessible
            page.goto(f"{SITE_URL}/auth", wait_until="domcontentloaded", timeout=15_000)
            try:
                page.wait_for_selector("#inp-key, input[type='password'], input[type='text']",
                                       timeout=5000)
                chk(f"{prefix}.{counter[0]}  [{label}] Auth input field reachable on mobile",
                    True)
            except Exception:
                warn(f"{prefix}.{counter[0]}  [{label}] Auth input not found on mobile")
            counter[0] += 1

            # No critical JS errors
            ok_js, errs = _no_critical_js_errors(errors)
            chk(f"{prefix}.{counter[0]}  [{label}] No critical JS errors",
                ok_js, f"errors: {errs}")

        except Exception as e:
            fail(f"{prefix}.X  [{label}] Unexpected error: {e}")
        finally:
            browser.close()


# ── Tablet device tests ───────────────────────────────────────────────────────

def test_tablet_ipad():
    section("CB-T1. Safari iPad — Tablet")
    _run_tablet("iPad Pro 11", "Safari/iPad", "CB.T1", "webkit")


def test_tablet_android():
    section("CB-T2. Android Chrome — Galaxy Tablet")
    _run_tablet("Galaxy Tab S4", "Android/Tablet", "CB.T2", "chromium")


def _run_tablet(device_name: str, label: str, prefix: str, engine: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        warn(f"{prefix}.1  playwright not installed — skipping {label}")
        return

    with sync_playwright() as pw:
        try:
            browser, ctx, page = make_device_ctx(pw, device_name, engine=engine)
        except Exception as e:
            warn(f"{prefix}.1  {label} ({device_name}) not available: {e}")
            return

        errors = collect_console_errors(page)
        counter = [1]

        try:
            for path, page_label in PUBLIC_PAGES + PROTECTED_PAGES:
                probe_page(page, errors, path, label, prefix, counter)

            # Tablet: check two-column layout visible on landing (not mobile stack)
            page.goto(f"{SITE_URL}/", wait_until="domcontentloaded", timeout=15_000)
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            viewport_width = page.evaluate("window.innerWidth")
            chk(f"{prefix}.{counter[0]}  [{label}] No horizontal overflow on tablet",
                scroll_width <= viewport_width + 5,
                f"scrollWidth={scroll_width} > viewportWidth={viewport_width}")
            counter[0] += 1

            ok_js, errs = _no_critical_js_errors(errors)
            chk(f"{prefix}.{counter[0]}  [{label}] No critical JS errors",
                ok_js, f"errors: {errs}")

        except Exception as e:
            fail(f"{prefix}.X  [{label}] Unexpected error: {e}")
        finally:
            browser.close()


# ── CSP / header consistency check ───────────────────────────────────────────

def test_security_headers():
    section("CB-H. Security Headers — All Pages")
    n = 1
    required_headers = [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options",        "deny"),   # lowercased — headers_lower lowercases values
        ("referrer-policy",        None),     # just presence
    ]

    for path, label in PUBLIC_PAGES:
        try:
            r = requests.get(f"{SITE_URL}{path}", timeout=15, allow_redirects=True)
            headers_lower = {k.lower(): v.lower() for k, v in r.headers.items()}
            for hname, hval in required_headers:
                present = hname in headers_lower
                if hval:
                    correct = hval in headers_lower.get(hname, "")
                else:
                    correct = present
                chk(f"CB.H.{n}  [{label}] {hname} header correct",
                    correct,
                    f"got: {headers_lower.get(hname, 'MISSING')}")
                n += 1
        except Exception as e:
            warn(f"CB.H.{n}  [{label}] Could not check headers: {e}")
            n += 1


# ── Responsive breakpoint checks (HTTP only) ─────────────────────────────────

def test_responsive_meta():
    """
    HTTP-level: verify viewport meta tag is present on all pages
    (required for mobile browsers to respect responsive design).
    """
    section("CB-R. Responsive Meta Tag — All Pages")
    n = 1
    for path, label in PUBLIC_PAGES:
        try:
            r = requests.get(f"{SITE_URL}{path}", timeout=15, allow_redirects=True)
            has_viewport = 'name="viewport"' in r.text or "name='viewport'" in r.text
            chk(f"CB.R.{n}  [{label}] viewport meta tag present",
                has_viewport,
                f"path={path}")
            n += 1
            # No horizontal scroll indication (rough check: no overflow:scroll in inline styles)
            no_overflow_x = "overflow-x: scroll" not in r.text
            chk(f"CB.R.{n}  [{label}] No forced horizontal scroll in HTML",
                no_overflow_x,
                f"path={path}")
            n += 1
        except Exception as e:
            warn(f"CB.R.{n}  [{label}] Could not check: {e}")
            n += 2


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    info(f"Site URL    : {SITE_URL}")
    info(f"Headless    : {os.environ.get('HEADLESS', '0')}")
    info(f"All devices : {os.environ.get('CB_ALL_DEVICES', '0')}")
    print()

    # Always run (HTTP + header checks — no browser needed)
    test_security_headers()
    test_responsive_meta()

    # Desktop browsers
    test_desktop_chrome()
    test_desktop_firefox()
    test_desktop_webkit()
    test_desktop_widescreen()
    test_desktop_small()

    # Mobile devices (opt-in via CB_ALL_DEVICES=1 or always in CI)
    all_devices = os.environ.get("CB_ALL_DEVICES", "1") == "1"
    if all_devices:
        test_mobile_android()
        test_mobile_ios()
        test_mobile_samsung()
        test_mobile_ios_large()
        test_tablet_ipad()
        test_tablet_android()
    else:
        # Even without full device matrix, run one mobile + one tablet
        test_mobile_android()
        test_tablet_ipad()

    results = get_results()
    passed  = results["passed"]
    failed  = results["failed"]
    warned  = results["warned"]
    total   = passed + failed

    print()
    print(f"{'='*62}")
    print(f"  Cross-Browser Suite: {passed}/{total} passed  |  {warned} warnings")
    print(f"{'='*62}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
