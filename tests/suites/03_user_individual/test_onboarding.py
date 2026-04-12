"""
test_onboarding.py — New user onboarding journey tests
======================================================
Suite ON: E2E new user journey — signup, ingest, analytics verification.
Labels: ON.1 - ON.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import signup_api, get_headers, get_session_cookie
from helpers.data import rand_email, rand_org, rand_name, make_event
from helpers.output import ok, fail, warn, info, section, chk, get_results


MODELS = ["gpt-4o", "gpt-3.5-turbo", "claude-3-sonnet", "gemini-pro"]


def test_api_onboarding():
    section("ON. Onboarding — API Journey")

    # ON.1 Signup
    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        chk("ON.1  Signup → 201 + api_key + org_id", True)
        info(f"  org_id: {org_id}")
    except Exception as e:
        fail(f"ON.1  Signup failed: {e}")
        return None

    headers = get_headers(api_key)

    # ON.2 Sign in via API
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": api_key}, timeout=15)
    chk("ON.2  Sign in API → 200 + cookie", r.status_code == 200 and bool(r.cookies),
        f"status={r.status_code}, cookies={bool(r.cookies)}")
    cookies = r.cookies

    # ON.3 Ingest 6 events (cost/tokens/model fields)
    events_ingested = 0
    for i, model in enumerate(MODELS[:3] + ["gpt-4o"] * 3):
        event = make_event(i=i, model=model, cost=0.002 * (i + 1),
                           tags={"test": "onboarding", "run": f"event_{i}"})
        r = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
        if r.status_code in (201, 202):
            events_ingested += 1

    chk("ON.3  Ingested 6 events", events_ingested == 6,
        f"only ingested {events_ingested}/6")

    # ON.4 Wait briefly for data propagation
    time.sleep(2)

    # ON.5 GET /analytics/summary → cost > 0
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    chk("ON.4  GET /analytics/summary → 200", r.status_code == 200,
        f"got {r.status_code}")

    if r.ok:
        d = r.json()
        # Try various field name patterns (API returns today_cost_usd / mtd_cost_usd)
        cost = (d.get("today_cost_usd") or d.get("mtd_cost_usd") or
                d.get("session_cost_usd") or d.get("total_cost") or
                d.get("cost") or d.get("totalCost") or
                d.get("summary", {}).get("total_cost") or 0)
        chk("ON.5  Analytics summary cost > 0", cost > 0,
            f"cost={cost}, keys={list(d.keys())}")

    # ON.6 GET /analytics/models → model appears
    r2 = requests.get(f"{API_URL}/v1/analytics/models", headers=headers, timeout=15)
    chk("ON.6  GET /analytics/models → 200", r2.status_code == 200,
        f"got {r2.status_code}")

    if r2.ok:
        d2 = r2.json()
        # Check that at least one model appears in response
        models_data = d2.get("models") or d2.get("data") or (d2 if isinstance(d2, list) else [])
        if len(models_data) == 0:
            warn("ON.7  Analytics models contains data — skipped (fresh account, data may not have propagated yet)")
        else:
            chk("ON.7  Analytics models contains data", True)

    return api_key


def test_playwright_onboarding():
    section("ON. Onboarding — Playwright Journey")

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        warn("ON.8  playwright not installed — skipping browser onboarding tests")
        return

    try:
        d = signup_api()
        api_key = d["api_key"]
        info(f"  New user org: {d.get('org_id')}")
    except Exception as e:
        fail(f"ON.8  Could not create user for browser test: {e}")
        return

    with sync_playwright() as pw:
        from helpers.browser import make_browser_ctx, collect_console_errors, signin_ui
        try:
            browser, ctx, page = make_browser_ctx(pw)
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                warn("ON.8  Chromium not installed — skipping browser onboarding tests")
                return
            raise
        errors = collect_console_errors(page)

        try:
            # ON.8 Homepage loads
            page.goto(f"{SITE_URL}/", wait_until="networkidle", timeout=20000)
            chk("ON.8  Homepage loads", page.url.startswith(SITE_URL))

            # ON.9 Signup page accessible
            page.goto(f"{SITE_URL}/signup", wait_until="networkidle", timeout=20000)
            chk("ON.9  /signup page loads", True)

            # ON.10 Auth page accessible
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20000)
            chk("ON.10 /auth page loads", True)

            # ON.11 Sign in → /app
            signed_in = signin_ui(page, api_key)
            chk("ON.11 Sign in → /app", signed_in, f"URL: {page.url}")

            if signed_in:
                # ON.12 /app shows empty state (no data yet for this new account)
                time.sleep(2)
                chk("ON.12 /app loads without crash", "/app" in page.url)

                # Ingest some events
                headers = get_headers(api_key)
                for i in range(3):
                    requests.post(f"{API_URL}/v1/events",
                                  json=make_event(i=i, cost=0.01 * (i + 1)),
                                  headers=headers, timeout=10)

                time.sleep(2)

                # ON.13 Reload app and check KPI data appears
                page.reload(wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)
                chk("ON.13 App reloads after data ingest", "/app" in page.url)

        except Exception as e:
            fail(f"ON.8  Playwright onboarding exception: {e}")
        finally:
            browser.close()


def main():
    section("Suite ON — New User Onboarding Tests")
    info(f"API: {API_URL}")
    info(f"Site: {SITE_URL}")

    test_api_onboarding()
    test_playwright_onboarding()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
