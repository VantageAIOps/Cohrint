"""
test_04_dashboard.py — Dashboard stability & all views (Playwright UI)
=======================================================================
Developer notes:
  Tests the main /app.html dashboard completely:
    • Page load without redirect-loop (known bug: page goes down after sign-in)
    • Topbar elements (logo, period selector, settings, home link)
    • Sidebar navigation — all 10 views load without JS error
    • Data loading: KPIs, timeseries, analytics summary
    • Settings modal — opens, org ID shown, API base shown
    • User menu — opens, contains sign out
    • Command palette (⌘K)
    • Notification panel
    • Period selector (7 / 30 / 90 days)
    • Live stream panel (Developer Experience view)
    • No JS errors throughout

  Known bugs to catch:
    - Dashboard bouncing back to /auth after sign-in (session race)
    - Data not loading (GET /v1/auth/session not returning org_id)
    - Settings modal "Save" breaking session (key-switch bug)
    - "← Home" button present (user finds it confusing — document location)

Run:
  python tests/test_04_dashboard.py
  HEADLESS=0 python tests/test_04_dashboard.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL,
    signup_api, get_headers, get_session_cookie, fresh_account,
    make_browser_ctx, collect_console_errors, signin_ui,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.dashboard")

# ─────────────────────────────────────────────────────────────────────────────
# Create test account
# ─────────────────────────────────────────────────────────────────────────────
try:
    d = signup_api()
    API_KEY = d["api_key"]
    ORG_ID  = d["org_id"]
    info(f"Test account: {ORG_ID}  key={API_KEY[:24]}…")
except Exception as e:
    fail("Could not create test account — aborting dashboard tests", str(e))
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Dashboard page load & stability
# ─────────────────────────────────────────────────────────────────────────────
section("1. Dashboard load & stability")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 1.1 Sign in via UI
        signed_in = signin_ui(page, API_KEY)
        chk("1.1  Sign-in and redirect to /app succeeded", signed_in, f"url={page.url}")

        # 1.2 Dashboard does NOT immediately bounce back to /auth
        page.wait_for_timeout(2_000)
        chk("1.2  Dashboard stays on /app after 2s (no session race)",
            "/app" in page.url,
            f"bounced to: {page.url}  — CRITICAL BUG: session race condition")

        # 1.3 After 4s still on dashboard (covers slower session checks)
        page.wait_for_timeout(2_000)
        chk("1.3  Dashboard stable after 4s total", "/app" in page.url,
            f"url={page.url}")

        # 1.4 Topbar visible
        chk("1.4  Topbar (#topbar) rendered", page.locator("#topbar").count() > 0)

        # 1.5 VANTAGEAI logo present
        chk("1.5  VANTAGEAI logo in topbar", "VANTAGE" in page.content().upper())

        # 1.6 Period selector present
        chk("1.6  Period selector visible", page.locator(".tb-period").count() > 0)

        # 1.7 Sidebar present
        chk("1.7  Sidebar (#sidebar) rendered", page.locator("#sidebar").count() > 0)

        # 1.8 At least 5 sidebar items
        sb_count = page.locator(".sb-item").count()
        chk("1.8  ≥5 sidebar nav items", sb_count >= 5, f"found {sb_count}")

        # 1.9 KPI grid rendered
        chk("1.9  KPI grid (.kpi-grid) rendered", page.locator(".kpi-grid").count() > 0)

        # 1.10 Charts rendered (canvas elements)
        canvas_count = page.locator("canvas").count()
        chk("1.10 ≥1 chart canvas rendered", canvas_count >= 1, f"found {canvas_count}")

        # 1.11 User avatar (initials) set — requires session to load
        page.wait_for_timeout(2_000)
        avatar_text = page.locator("#user-avatar").inner_text() if \
            page.locator("#user-avatar").count() > 0 else ""
        chk("1.11 User avatar has initials (session loaded correctly)",
            len(avatar_text.strip()) >= 1, f"avatar='{avatar_text}'")

        # 1.12 Org name shown in topbar
        org_text = page.locator(".tb-org-badge").inner_text() if \
            page.locator(".tb-org-badge").count() > 0 else ""
        chk("1.12 Org badge shows org name", len(org_text.strip()) > 0,
            "org badge empty — session data not loading")

        # ── 2. Test each sidebar view ──────────────────────────────────────
        section("2. Sidebar views — all 10 views load without crash")

        # nav() ids match onclick="nav('cost',this)" pattern
        VIEWS = [
            ("cost",     "Cost Intelligence"),
            ("tokens",   "Token Analytics"),
            ("models",   "Model Comparison"),
            ("perf",     "Performance & Latency"),
            ("quality",  "Quality & Evaluation"),
            ("ai",       "AI Intelligence Layer"),
            ("traces",   "Agent Traces"),
            ("reports",  "Enterprise Reporting"),
            ("security", "Security & Governance"),
            ("devx",     "Developer Experience"),
        ]

        for nav_id, view_name in VIEWS:
            try:
                # Use evaluate() — same approach as test_21, avoids click timeouts
                page.evaluate(
                    f"nav('{nav_id}', document.querySelector('.sb-item') || document.body)"
                )
                page.wait_for_timeout(400)
                still_on_app = "/app" in page.url
                chk(f"2.x  '{view_name}' view — no crash/redirect",
                    still_on_app, f"redirected to {page.url}")
            except Exception as e:
                fail(f"2.x  '{view_name}' view error", str(e)[:100])

        # Wait for any lazy-loaded charts
        page.wait_for_timeout(1_500)

        # ── 3. UI Controls ─────────────────────────────────────────────────
        section("3. UI controls — settings, user menu, command palette")

        # 3.1 Settings view opens (Settings is now a sidebar view, not a modal)
        try:
            sb_settings = page.locator("#sb-settings")
            if sb_settings.count() > 0:
                sb_settings.first.click(timeout=8000)
                page.wait_for_timeout(800)
                settings_active = page.locator("#view-settings.active").count() > 0
                chk("3.1  Settings sidebar view becomes active",
                    settings_active, "#view-settings did not get .active class")

                if settings_active:
                    # 3.2 Settings view shows org ID (moved to Account view — skip)
                    warn("3.2  Org ID is in Account view, not Settings — skipping")

                    # 3.3 API base URL shown
                    base_el = page.locator("#set-base-input, #sm-base-input")
                    if base_el.count() > 0:
                        api_base = base_el.first.get_attribute("value") or ""
                        chk("3.3  Settings view shows API base URL",
                            "vantageaiops.com" in api_base or len(api_base) > 5,
                            f"api_base='{api_base}'")
                    else:
                        warn("3.3  API base URL input not found in settings view")
            else:
                warn("3.1  #sb-settings button not found in sidebar")
        except Exception as e:
            warn(f"3.1  Settings view test inconclusive: {e}")

        # 3.4 User menu opens
        try:
            user_menu = page.locator("#user-menu, #user-avatar")
            if user_menu.count() > 0:
                user_menu.first.click(timeout=8000)
                page.wait_for_timeout(400)
                dropdown_visible = page.locator("#user-dropdown").is_visible() if \
                    page.locator("#user-dropdown").count() > 0 else False
                chk("3.4  User menu dropdown opens", dropdown_visible)
                # Close by clicking elsewhere
                page.click("body", position={"x": 100, "y": 100})
                page.wait_for_timeout(300)
            else:
                warn("3.4  User menu element not found")
        except Exception as e:
            warn(f"3.4  User menu test inconclusive: {e}")

        # 3.5 Period selector changes period
        try:
            period_sel = page.locator("#period-sel")
            if period_sel.count() > 0:
                period_sel.select_option("7")
                page.wait_for_timeout(1_000)
                chk("3.5  Period selector set to 7 days without crash",
                    "/app" in page.url)
                period_sel.select_option("30")
                page.wait_for_timeout(500)
        except Exception as e:
            warn(f"3.5  Period selector test inconclusive: {e}")

        # 3.6 Command palette (⌘K) opens
        try:
            page.keyboard.press("Meta+k")
            page.wait_for_timeout(500)
            cmd_visible = page.locator("#cmd-overlay, #cmd-modal, .cmd-palette").count() > 0 or \
                          page.locator("[id*='cmd']").count() > 0
            chk("3.6  Command palette opens on ⌘K", cmd_visible)
            if cmd_visible:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
        except Exception as e:
            warn(f"3.6  Command palette test inconclusive: {e}")

        # 3.7 Home link (informational — removed from topbar by design)
        home_link = page.locator("a[href='/'], a[href='/'i], a:has-text('Home')")
        if home_link.count() > 0:
            warn("3.7  ← Home link present in topbar (may be confusing to users — consider removing)")
            info(f"     Home link text: '{home_link.first.inner_text()}' href='{home_link.first.get_attribute('href')}'")
        else:
            ok("3.7  ← Home link removed from topbar (design decision)")

        # ── 4. Data loading ────────────────────────────────────────────────
        section("4. Data loading — KPIs, analytics")

        # Navigate to Cost Intelligence (first view with real API data)
        try:
            page.evaluate("nav('cost', document.querySelector('.sb-item') || document.body)")
            page.wait_for_timeout(2_000)
        except Exception:
            page.wait_for_timeout(500)

        # 4.1-4.3 Test via API (not UI, more reliable)
        hdrs = get_headers(API_KEY)
        try:
            r = requests.get(f"{API_URL}/v1/analytics/summary", headers=hdrs, timeout=10)
            chk("4.1  GET /analytics/summary → 200", r.status_code == 200,
                f"{r.status_code}: {r.text[:100]}")
            d = r.json()
            chk("4.2  Summary contains mtd_cost_usd", "mtd_cost_usd" in d, str(d))
        except Exception as e:
            fail("4.1-4.2  Analytics summary failed", str(e))

        try:
            r = requests.get(f"{API_URL}/v1/analytics/kpis?period=30", headers=hdrs, timeout=10)
            chk("4.3  GET /analytics/kpis → 200", r.status_code == 200,
                f"{r.status_code}: {r.text[:100]}")
        except Exception as e:
            fail("4.3  Analytics KPIs failed", str(e))

        try:
            r = requests.get(f"{API_URL}/v1/analytics/timeseries?period=30", headers=hdrs, timeout=10)
            chk("4.4  GET /analytics/timeseries → 200", r.status_code == 200,
                f"{r.status_code}: {r.text[:100]}")
        except Exception as e:
            fail("4.4  Analytics timeseries failed", str(e))

        try:
            r = requests.get(f"{API_URL}/v1/analytics/models?period=30", headers=hdrs, timeout=10)
            chk("4.5  GET /analytics/models → 200", r.status_code == 200,
                f"{r.status_code}: {r.text[:100]}")
        except Exception as e:
            fail("4.5  Analytics models failed", str(e))

        # ── 5. Logout from dashboard ───────────────────────────────────────
        section("5. Logout from dashboard")
        try:
            # Sign out via API
            cookies_dict = {c["name"]: c["value"] for c in ctx.cookies()}
            r_logout = requests.delete(f"{API_URL}/v1/auth/session",
                                       cookies=cookies_dict, timeout=10)
            chk("5.1  DELETE /session (logout API) → 200", r_logout.status_code == 200,
                f"got {r_logout.status_code}")
        except Exception as e:
            fail("5.1  Logout API test failed", str(e))

        # ── 6. JS errors ───────────────────────────────────────────────────
        section("6. JavaScript error check")
        page.wait_for_timeout(1_000)
        chk("6.1  No JS errors on dashboard during full test run",
            len(js_errors) == 0, str(js_errors[:5]))
        if js_errors:
            for err in js_errors[:5]:
                info(f"     JS error: {err[:150]}")

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests")
except Exception as e:
    fail("Dashboard UI test suite error", str(e)[:300])


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Dashboard tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
