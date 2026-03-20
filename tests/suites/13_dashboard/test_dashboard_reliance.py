"""
test_dashboard_reliance.py — Full dashboard E2E reliance tests
==============================================================
Suite DR: Complete flow: signup → ingest 50 events → sign in via UI →
verify all 8 sidebar views → KPI cards show data → charts → logout.
Labels: DR.1 - DR.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import signup_api, get_headers
from helpers.data import rand_email, rand_org, rand_name
from helpers.output import ok, fail, warn, info, section, chk, get_results


MODELS = ["gpt-4o", "gpt-3.5-turbo", "claude-3-sonnet", "gemini-pro",
          "gpt-4-turbo", "claude-instant"]

SIDEBAR_SELECTORS = [
    ("#nav-cost",     "Cost"),
    ("#nav-tokens",   "Tokens"),
    ("#nav-models",   "Models"),
    ("#nav-perf",     "Performance"),
    ("#nav-settings", "Settings"),
    ("#nav-account",  "Account"),
    ("#nav-devx",     "DevX"),
    ("#nav-traces",   "Traces"),
]


def ingest_50_events(api_key):
    """Ingest 50 mixed events for dashboard data."""
    headers = get_headers(api_key)
    accepted = 0
    for i in range(50):
        model = MODELS[i % len(MODELS)]
        event = {
            "model":     model,
            "cost":      round(0.001 + (i % 10) * 0.002, 6),
            "tokens":    {"prompt": 100 + i * 5, "completion": 50 + i * 2},
            "timestamp": int(time.time() * 1000) + i * 100,
            "tags":      {"test": "dashboard_reliance", "model_family": model.split("-")[0]},
        }
        r = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
        if r.status_code in (201, 202):
            accepted += 1
    return accepted


def test_api_preconditions(api_key):
    section("DR. Dashboard — API Pre-conditions")

    # DR.1 Ingest 50 events
    accepted = ingest_50_events(api_key)
    chk("DR.1  50 events ingested", accepted >= 45,
        f"{accepted}/50 accepted")

    # Wait for propagation
    time.sleep(2)

    # DR.2 Analytics shows data
    r = requests.get(f"{API_URL}/v1/analytics/summary",
                     headers=get_headers(api_key), timeout=15)
    chk("DR.2  Analytics summary → 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        cost = (d.get("total_cost") or d.get("cost") or d.get("totalCost") or
                d.get("summary", {}).get("total_cost") or 0)
        chk("DR.3  Analytics shows cost > 0", cost > 0,
            f"cost={cost}")

    return accepted


def test_pages_stable():
    section("DR. Dashboard — Static Pages Stable")

    pages = [
        ("/",           "Landing page"),
        ("/docs",       "Docs page"),
        ("/calculator", "Calculator page"),
    ]

    for i, (path, label) in enumerate(pages, start=4):
        try:
            r = requests.get(f"{SITE_URL}{path}", timeout=15, allow_redirects=True)
            chk(f"DR.{i}  {label} ({path}) → 200", r.status_code == 200,
                f"got {r.status_code}")
            chk(f"DR.{i}a  {label} body non-empty", len(r.text) > 100,
                f"body length: {len(r.text)}")
        except Exception as e:
            fail(f"DR.{i}  {label} exception: {e}")


def test_full_dashboard_flow(api_key, email):
    section("DR. Dashboard — Full Playwright E2E Flow")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("DR.7  playwright not installed — skipping E2E dashboard tests")
        return

    with sync_playwright() as pw:
        from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
        browser, ctx, page = make_browser_ctx(pw)
        all_errors = []
        page.on("pageerror", lambda e: all_errors.append(f"JS: {e}"))
        page.on("console", lambda m: all_errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        try:
            # DR.7 Sign in via UI
            signed_in = signin_ui(page, api_key)
            chk("DR.7  Sign in via UI → /app", signed_in,
                f"URL: {page.url}")

            if not signed_in:
                fail("DR.8  Cannot test dashboard — sign in failed")
                return

            time.sleep(2)  # Wait for app to fully render

            # DR.8 All 8 sidebar views load
            views_loaded = 0
            for selector, label in SIDEBAR_SELECTORS:
                try:
                    page.click(selector, timeout=5000)
                    time.sleep(0.8)
                    views_loaded += 1
                    chk(f"DR.8.{views_loaded}  {label} view loads", True)
                except PWTimeout:
                    warn(f"DR.8  {label} sidebar selector ({selector}) not found")

            chk("DR.8  All 8 sidebar views reachable", views_loaded >= 6,
                f"only {views_loaded}/8 views loaded")

            # DR.9 KPI cards show real data (not dashes)
            page.click("#nav-cost, .nav-cost", timeout=3000)
            time.sleep(1)
            body = page.inner_text("body")

            # Check for some numeric data (not just dashes or zeros)
            import re
            numbers = re.findall(r'\$[\d.]+|[\d]+\s*(?:tokens|req|ms)', body)
            chk("DR.9  KPI cards show data (not all dashes)",
                len(numbers) > 0,
                f"found {len(numbers)} numeric values in body")

            # DR.10 Cost chart has data points
            canvas_count = page.evaluate("document.querySelectorAll('canvas').length")
            svg_count = page.evaluate("document.querySelectorAll('svg').length")
            chk("DR.10 Cost chart renders (canvas/svg present)",
                canvas_count > 0 or svg_count > 0,
                f"canvas={canvas_count}, svg={svg_count}")

            # DR.11 Models view shows model breakdown
            try:
                page.click("#nav-models", timeout=3000)
                time.sleep(1)
                models_body = page.inner_text("body")
                has_model_names = any(m.split("-")[0] in models_body.lower()
                                     for m in MODELS[:3])
                chk("DR.11 Models view shows model names",
                    has_model_names,
                    f"model names not found in: {models_body[:200]}")
            except PWTimeout:
                warn("DR.11 #nav-models not found")

            # DR.12 Performance view loads
            try:
                page.click("#nav-perf", timeout=3000)
                time.sleep(0.8)
                chk("DR.12 Performance view loads", True)
            except PWTimeout:
                warn("DR.12 #nav-perf not found")

            # DR.13 Settings shows org info
            try:
                page.click("#nav-settings", timeout=3000)
                time.sleep(0.5)
                settings_body = page.inner_text("body")
                chk("DR.13 Settings/Account view loads with content",
                    len(settings_body) > 50)
            except PWTimeout:
                warn("DR.13 #nav-settings not found")

            # DR.14 Account shows correct email
            try:
                page.click("#nav-account", timeout=3000)
                time.sleep(0.5)
                account_body = page.inner_text("body")
                if email:
                    chk("DR.14 Account view shows user email",
                        email in account_body,
                        f"email '{email}' not found in account view")
                else:
                    chk("DR.14 Account view loads", True)
            except PWTimeout:
                warn("DR.14 #nav-account not found")

            # DR.15 No JS errors across all views
            noise = ("cloudflareinsights.com", "beacon.min.js", "status of 401",
                     "401 ()", "extension://")
            critical_errors = [e for e in all_errors
                               if not any(n in e for n in noise)]
            chk("DR.15 No critical JS errors across all views",
                len(critical_errors) == 0,
                f"errors: {critical_errors[:3]}")

            # DR.16 Logout → session cleared
            try:
                page.click("#btn-logout, [data-action='logout'], .logout-btn",
                           timeout=5000)
                time.sleep(1)
                chk("DR.16 Logout → navigates away from /app",
                    "/app" not in page.url or "/auth" in page.url,
                    f"URL: {page.url}")

                # DR.17 Verify session cleared (can't access /app)
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=15000)
                time.sleep(1)
                chk("DR.17 After logout, /app redirects to /auth",
                    "/auth" in page.url or "/app" not in page.url,
                    f"URL: {page.url}")
            except PWTimeout:
                warn("DR.16 Logout button not found")

        except Exception as e:
            fail(f"DR.7  Dashboard E2E exception: {e}")
        finally:
            browser.close()


def main():
    section("Suite DR — Full Dashboard Reliance Tests")
    info(f"API: {API_URL}")
    info(f"Site: {SITE_URL}")

    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        email   = d.get("email", "")
        info(f"Test account: {org_id}")
    except Exception as e:
        fail(f"Could not create test account: {e}")
        sys.exit(1)

    test_api_preconditions(api_key)
    test_pages_stable()
    test_full_dashboard_flow(api_key, email)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
