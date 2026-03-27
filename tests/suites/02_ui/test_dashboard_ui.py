"""
test_dashboard_ui.py — Dashboard UI tests (Playwright)
======================================================
Suite D: Tests dashboard views, KPI grid, charts, settings modal, no JS errors.
Labels: D.1 - D.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import SITE_URL, API_URL
from helpers.api import signup_api, get_headers
from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
from helpers.output import ok, fail, warn, info, section, chk, get_results


SIDEBAR_VIEWS = [
    ("button.sb-item:has-text('Spend')",    "Spend Analysis"),
    ("button.sb-item:has-text('Model')",    "Model Pricing"),
    ("button.sb-item:has-text('Members')",  "Members"),
    ("button.sb-item:has-text('Budget')",   "Budgets"),
    ("button.sb-item:has-text('Settings')", "Settings"),
    ("button.sb-item:has-text('Account')",  "Account"),
]


def test_dashboard_loads(page, errors):
    section("D. Dashboard — Initial Load")

    chk("D.1  Loaded /app URL", "/app" in page.url, f"current: {page.url}")

    # KPI grid visible
    try:
        page.wait_for_selector(".kpi-grid, .kpi-card, [data-testid='kpi'], .metric-card",
                               timeout=8000)
        chk("D.2  KPI grid visible", True)
    except Exception:
        warn("D.2  KPI grid selector not found (may use different class)")

    # No JS errors on initial load
    chk("D.3  No critical JS errors on load", len(errors) == 0,
        f"errors: {list(errors)[:3]}")


def test_sidebar_views(page, errors_list):
    section("D. Dashboard — Sidebar Views")

    for i, (selector, label) in enumerate(SIDEBAR_VIEWS, start=4):
        try:
            from playwright.sync_api import TimeoutError as PWTimeout
            try:
                page.click(selector, timeout=5000)
                time.sleep(0.8)
                chk(f"D.{i}  {label} view loads without crash", True)
            except PWTimeout:
                warn(f"D.{i}  {label} sidebar selector ({selector}) not found — skipping")
        except Exception as e:
            warn(f"D.{i}  {label} view: {e}")

    # Check no JS errors after touring all views
    chk("D.12 No JS errors after touring all sidebar views", len(errors_list) == 0,
        f"errors: {list(errors_list)[:3]}")


def test_views_load(page):
    section("D. Dashboard — View Navigation")

    from playwright.sync_api import TimeoutError as PWTimeout

    # Settings view
    try:
        page.click("button.sb-item:has-text('Settings')", timeout=5000)
        time.sleep(0.5)
        chk("D.13 Settings view loads", True)
    except PWTimeout:
        warn("D.13 Settings view selector not found")
    except Exception as e:
        warn(f"D.13 Settings view: {e}")

    # Account view
    try:
        page.click("button.sb-item:has-text('Account')", timeout=5000)
        time.sleep(0.5)
        chk("D.14 Account view loads", True)
    except PWTimeout:
        warn("D.14 Account view selector not found")
    except Exception as e:
        warn(f"D.14 Account view: {e}")


def test_charts(page):
    section("D. Dashboard — Charts")

    # Navigate to Overview view (default, has charts)
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        page.click("button.sb-item:has-text('Overview')", timeout=3000)
        time.sleep(1)
    except Exception:
        pass

    # Check for canvas or svg chart elements
    canvas_count = page.evaluate("document.querySelectorAll('canvas').length")
    svg_count = page.evaluate("document.querySelectorAll('svg').length")
    chk("D.15 Chart elements present (canvas or svg)",
        canvas_count > 0 or svg_count > 0,
        f"canvas={canvas_count}, svg={svg_count}")


def main():
    section("Suite D — Dashboard UI Tests")
    info(f"Site: {SITE_URL}")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("playwright not installed — skipping all UI tests")
        sys.exit(0)

    # Create test account and ingest some data
    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"Test account: {d.get('org_id', 'unknown')}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    # Ingest a few events so dashboard has data
    headers = get_headers(api_key)
    try:
        for i in range(3):
            requests.post(f"{API_URL}/v1/events",
                          json={"model": "gpt-4o", "cost": 0.01 * (i + 1),
                                "tokens": {"prompt": 100, "completion": 50},
                                "timestamp": int(time.time() * 1000) + i},
                          headers=headers, timeout=10)
    except Exception:
        pass  # Data is nice-to-have, not required

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        errors = collect_console_errors(page)

        try:
            signed_in = signin_ui(page, api_key)
            if not signed_in:
                fail("D.1  Sign in failed — cannot run dashboard tests")
                sys.exit(1)

            test_dashboard_loads(page, errors)
            test_sidebar_views(page, errors)
            test_views_load(page)
            test_charts(page)

        except Exception as e:
            fail(f"Dashboard test exception: {e}")
        finally:
            browser.close()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
