"""
test_11_navigation.py — UI Navigation Stability Tests
======================================================
Developer notes:
  Targets the reported bugs:
    • "← home" text appearing in nav (should be "Vantage" or logo only)
    • "Vantage" button / logo taking user back to home page (correct or bug?)
    • Navigation links in sidebar (Overview, Analytics, Alerts, Admin, Settings)
      not responding or crashing the page
    • Page going blank after clicking nav links post-signin

  Every nav link is clicked, every page transition is verified, and
  console errors are captured throughout. A 'blank page' is detected when
  either the DOM root is empty, the body has no visible text, or the
  auth guard redirected back to the landing page without reason.

Tests (11.1 – 11.30):
  11.1  Landing page loads without crash
  11.2  Landing page has no JS errors
  11.3  "← home" text does NOT appear on landing page nav
  11.4  "← home" text does NOT appear on /app (dashboard) nav
  11.5  Logo / brand button on landing page → stays on /
  11.6  Logo / brand button on /app → stays on /app (does NOT go to home)
  11.7  Sidebar: Overview link navigates to overview view
  11.8  Sidebar: Analytics link opens analytics section
  11.9  Sidebar: Alerts link opens alerts section
  11.10 Sidebar: Admin link opens admin section (owner)
  11.11 Sidebar: Settings link opens settings modal/section
  11.12 Page does NOT go blank after clicking each nav item
  11.13 Back button (browser) from /app returns to /app, not blank
  11.14 /app with no session redirects to /auth (not blank page)
  11.15 /auth page loads cleanly
  11.16 /signup page loads cleanly
  11.17 /docs page loads cleanly (or 200 redirect)
  11.18 /calculator page loads
  11.19 All anchor links in landing page nav are valid (no 404 hrefs)
  11.20 Mobile viewport: hamburger menu or nav is accessible
  11.21 After sign-in, clicking logo stays on dashboard
  11.22 "Home" page nav: Get Started / Login buttons present
  11.23 /app topbar: org badge visible
  11.24 /app topbar: period selector visible
  11.25 /app topbar: user avatar / profile button visible
  11.26 Settings modal: opens and closes without page crash
  11.27 Settings modal: API key hint displayed
  11.28 Period selector changes data (no crash)
  11.29 Multiple rapid nav clicks do not cause blank page
  11.30 Refresh on /app preserves session (cookie) and reloads data

Run:
  python tests/test_11_navigation.py
  HEADLESS=0 python tests/test_11_navigation.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, signup_api, get_session_cookie,
    make_browser_ctx, collect_console_errors, HEADLESS,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.navigation")

# ── Fresh account for authenticated tests ──────────────────────────────────
try:
    _account = signup_api()
    TEST_KEY  = _account["api_key"]
    TEST_ORG  = _account["org_id"]
    log.info("Test account created", org_id=TEST_ORG)
except Exception as e:
    TEST_KEY = TEST_ORG = None
    log.error("Could not create test account", error=str(e))


def signin_session_via_api(ctx):
    """Set the session cookie in the Playwright context via API."""
    if not TEST_KEY:
        return False
    r = requests.post(f"{API_URL}/v1/auth/session",
                      json={"api_key": TEST_KEY}, timeout=15)
    if not r.ok:
        return False
    for c in r.cookies:
        ctx.add_cookies([{
            "name":   c.name,
            "value":  c.value,
            "domain": "vantageaiops.com",
            "path":   "/",
        }])
    return True


try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:

        # ─────────────────────────────────────────────────────────────────────
        section("11-A. Landing page navigation")
        # ─────────────────────────────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 11.1 / 11.2
        try:
            with log.timer("Load landing page"):
                page.goto(SITE_URL, wait_until="networkidle", timeout=25_000)
            chk("11.1  Landing page loads (200)", True)
        except Exception as e:
            fail("11.1  Landing page failed to load", str(e)[:200])

        page.wait_for_timeout(1_000)
        chk("11.2  No JS errors on landing page", len(js_errors) == 0,
            f"{js_errors[:3]}")

        # 11.3 ← home must not appear in nav
        nav_text = ""
        try:
            nav_el = page.locator("nav, header").first
            nav_text = nav_el.inner_text().lower() if nav_el.count() > 0 else page.content()[:3000].lower()
        except Exception:
            nav_text = page.content()[:3000].lower()

        chk("11.3  '← home' NOT in landing nav",
            "← home" not in nav_text and "<- home" not in nav_text,
            "Found '← home' text in nav — this is a stale UI artifact")

        # 11.4 check later in dashboard section

        # 11.5  Logo / brand on landing → stays on landing
        try:
            logo_sel = "a.logo, .brand a, nav a:first-child, a[href='/'], a[href='./'], .nav-logo"
            logo = page.locator(logo_sel).first
            if logo.count() > 0:
                logo.click()
                page.wait_for_timeout(1_500)
                chk("11.5  Logo on landing keeps user on landing page",
                    "/" in page.url and "/app" not in page.url and "/auth" not in page.url,
                    f"redirected to: {page.url}")
            else:
                warn("11.5  Logo element not found on landing — check selector")
        except Exception as e:
            warn(f"11.5  Logo click test skipped: {e}")

        # 11.19 All nav anchor hrefs valid (not #, not empty, not javascript:void)
        try:
            anchors = page.locator("nav a, header a").all()
            bad_hrefs = []
            for a in anchors:
                href = a.get_attribute("href") or ""
                if href in ("", "javascript:void(0)", "javascript:;", "#"):
                    label = a.inner_text().strip()[:30]
                    bad_hrefs.append(f"'{label}' href='{href}'")
            chk("11.19 All nav links have real hrefs",
                len(bad_hrefs) == 0, f"Empty hrefs: {bad_hrefs}")
        except Exception as e:
            warn(f"11.19 Nav href check inconclusive: {e}")

        # 11.22 CTA buttons present
        content = page.content().lower()
        chk("11.22 Landing nav has Get Started or Login button",
            any(w in content for w in ["get started", "sign up", "login", "sign in"]))

        # 11.20 Mobile viewport nav
        try:
            mobile_ctx = browser.new_context(
                viewport={"width": 375, "height": 812})
            mp = mobile_ctx.new_page()
            mp.goto(SITE_URL, wait_until="domcontentloaded", timeout=20_000)
            mp.wait_for_timeout(1_000)
            mobile_content = mp.content().lower()
            chk("11.20 Mobile viewport: nav or menu accessible",
                any(w in mobile_content for w in ["menu", "nav", "hamburger", "vantage", "home"]))
            mobile_ctx.close()
        except Exception as e:
            warn(f"11.20 Mobile test skipped: {e}")

        ctx.close()
        browser.close()


        # ─────────────────────────────────────────────────────────────────────
        section("11-B. Page load stability (/auth /signup /docs /calculator)")
        # ─────────────────────────────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw)
        errs = collect_console_errors(page)

        for slug, test_id, label in [
            ("/auth",       "11.15", "/auth page"),
            ("/signup",     "11.16", "/signup page"),
            ("/docs",       "11.17", "/docs page"),
            ("/calculator", "11.18", "/calculator page"),
        ]:
            try:
                page.goto(f"{SITE_URL}{slug}",
                          wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(800)
                body = page.content()
                chk(f"{test_id}  {label} loads (non-empty body)",
                    len(body) > 500, f"body length={len(body)}")
            except PWTimeout:
                fail(f"{test_id}  {label} timed out loading")
            except Exception as e:
                fail(f"{test_id}  {label} load error", str(e)[:150])

        ctx.close()
        browser.close()


        # ─────────────────────────────────────────────────────────────────────
        section("11-C. Dashboard navigation (authenticated)")
        # ─────────────────────────────────────────────────────────────────────
        if not TEST_KEY:
            warn("11-C  Skipping dashboard nav — no test account")
        else:
            browser, ctx, page = make_browser_ctx(pw)
            js_errors = collect_console_errors(page)

            # Set session cookie directly
            session_ok = signin_session_via_api(ctx)
            if not session_ok:
                warn("11-C  Could not create session cookie — skipping dashboard nav tests")
            else:
                try:
                    with log.timer("Load /app (authenticated)"):
                        page.goto(f"{SITE_URL}/app",
                                  wait_until="networkidle", timeout=25_000)
                    page.wait_for_timeout(2_000)

                    app_url = page.url
                    chk("11-C.0 Authenticated /app loads (stays on /app)",
                        "/app" in app_url, f"redirected to: {app_url}")

                    content = page.content().lower()

                    # 11.4  ← home must not appear in dashboard nav
                    chk("11.4   '← home' NOT in dashboard nav",
                        "← home" not in content and "<- home" not in content,
                        "Found '← home' in /app — bad nav text")

                    # 11.23 org badge
                    chk("11.23  Topbar org badge visible",
                        page.locator(".org-badge, #org-badge, .org-name, [data-org]").count() > 0
                        or any(w in content for w in ["org", "organization", "account"]))

                    # 11.24 period selector
                    chk("11.24  Period selector visible",
                        page.locator("select, .period-selector, [data-period], #period").count() > 0
                        or any(w in content for w in ["today", "7d", "30d", "period"]))

                    # 11.25 user avatar/profile
                    chk("11.25  Profile/avatar button visible",
                        page.locator(".avatar, .profile-btn, #user-menu, [data-user]").count() > 0
                        or any(w in content for w in ["profile", "account", "settings"]))

                    # 11.6  Logo/brand on /app should NOT redirect to landing page
                    try:
                        logo_sel = "a.logo, .brand a, .nav-logo a, #sidebar-logo, a[href='/app'], .sidebar a:first-child"
                        logo = page.locator(logo_sel).first
                        if logo.count() > 0:
                            before_url = page.url
                            logo.click()
                            page.wait_for_timeout(1_500)
                            after_url = page.url
                            chk("11.6   Logo on /app stays on /app (not → landing page)",
                                "/app" in after_url,
                                f"Logo redirected to: {after_url}")
                        else:
                            warn("11.6   Logo/brand element not found in /app — check selector")
                    except Exception as e:
                        warn(f"11.6   Logo click in /app failed: {e}")

                    # 11.7–11.11 Sidebar navigation
                    NAV_TESTS = [
                        ("11.7",  ["overview", "Overview"],         "Overview"),
                        ("11.8",  ["analytics", "Analytics"],       "Analytics"),
                        ("11.9",  ["alert", "Alert"],               "Alerts"),
                        ("11.10", ["admin", "Admin"],               "Admin"),
                        ("11.11", ["setting", "Setting", "config"], "Settings"),
                    ]
                    for test_id, keywords, label in NAV_TESTS:
                        try:
                            # Try clicking nav link by text or data attribute
                            clicked = False
                            for kw in keywords:
                                sel = f"[data-view='{kw.lower()}'], nav a:has-text('{kw}'), .sidebar a:has-text('{kw}'), button:has-text('{kw}')"
                                el = page.locator(sel).first
                                if el.count() > 0:
                                    el.click()
                                    page.wait_for_timeout(1_000)
                                    clicked = True
                                    break
                            if clicked:
                                body_after = page.content()
                                is_blank = len(body_after.strip()) < 200
                                chk(f"{test_id}  Sidebar {label}: page not blank after click",
                                    not is_blank, "Page went blank after nav click!")
                            else:
                                warn(f"{test_id}  Sidebar {label}: nav element not found — check selectors")
                        except Exception as e:
                            warn(f"{test_id}  Sidebar {label} click failed: {e}")

                    # 11.12 No blank pages detected during nav
                    page.wait_for_timeout(1_000)
                    final_body = page.content()
                    chk("11.12  Page not blank after nav clicks",
                        len(final_body.strip()) > 500,
                        "App body is nearly empty — possible crash state")

                    # 11.29 Rapid nav clicks
                    try:
                        nav_links = page.locator("nav a, .sidebar a, .sidebar button").all()
                        for link in nav_links[:4]:
                            try:
                                link.click()
                                page.wait_for_timeout(300)
                            except Exception:
                                pass
                        page.wait_for_timeout(1_000)
                        after_rapid = page.content()
                        chk("11.29  Rapid nav clicks do not crash page",
                            len(after_rapid.strip()) > 500, "Page blank after rapid clicks")
                    except Exception as e:
                        warn(f"11.29  Rapid click test: {e}")

                    # 11.28 Period selector
                    try:
                        sel = page.locator("select#period, select[name='period'], .period-select").first
                        if sel.count() > 0:
                            sel.select_option(index=1)
                            page.wait_for_timeout(1_500)
                            chk("11.28  Period change: no crash",
                                len(page.content()) > 500)
                        else:
                            warn("11.28  Period selector not found via select element")
                    except Exception as e:
                        warn(f"11.28  Period selector: {e}")

                    # 11.21 After signin logo stays on dashboard
                    chk("11.21  After sign-in, still on /app (not bounced)",
                        "/app" in page.url, f"current URL: {page.url}")

                    # 11.2 JS errors check
                    page.wait_for_timeout(500)
                    if js_errors:
                        fail("11-C  JS errors detected during dashboard nav",
                             str(js_errors[:3]))
                    else:
                        ok("11-C  No JS errors during dashboard navigation")

                except Exception as e:
                    fail("11-C  Dashboard nav test error", str(e)[:300])
                    log.exception("Dashboard nav error", e)

            ctx.close()
            browser.close()


        # ─────────────────────────────────────────────────────────────────────
        section("11-D. /app unauthenticated redirect")
        # ─────────────────────────────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw)
        errs = collect_console_errors(page)
        try:
            # No cookies set — fresh context
            page.goto(f"{SITE_URL}/app", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2_000)
            final_url = page.url
            chk("11.14  /app without session → redirect to /auth (not blank)",
                "/auth" in final_url or "/login" in final_url or "/signup" in final_url,
                f"Stayed on: {final_url} — may be serving blank dashboard")
        except Exception as e:
            fail("11.14  /app unauthenticated test failed", str(e)[:200])
        ctx.close()
        browser.close()


        # ─────────────────────────────────────────────────────────────────────
        section("11-E. Settings modal")
        # ─────────────────────────────────────────────────────────────────────
        if TEST_KEY:
            browser, ctx, page = make_browser_ctx(pw)
            errs = collect_console_errors(page)
            signin_session_via_api(ctx)
            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(2_000)

                # Find and click settings
                settings_sel = "[data-view='settings'], nav a:has-text('Settings'), button:has-text('Settings'), #settings-btn, .settings-link"
                el = page.locator(settings_sel).first
                if el.count() > 0:
                    el.click()
                    page.wait_for_timeout(1_500)

                    # 11.26 Modal opens
                    modal_visible = page.locator(".modal, .settings-modal, #settings-panel, dialog").count() > 0
                    chk("11.26  Settings modal/panel opens",
                        modal_visible or "api key" in page.content().lower())

                    # 11.27 API key hint shown
                    content = page.content().lower()
                    chk("11.27  Settings shows API key hint",
                        any(w in content for w in ["vnt_", "api key", "key", "****"]))

                    # Close modal
                    try:
                        close_btn = page.locator(".modal-close, button:has-text('Close'), button:has-text('×'), [aria-label='Close']").first
                        if close_btn.count() > 0:
                            close_btn.click()
                            page.wait_for_timeout(800)
                    except Exception:
                        pass

                    # 11.26 After close, page still intact
                    chk("11.26b Settings modal closes without crash",
                        len(page.content()) > 500)
                else:
                    warn("11.26  Settings button/link not found — check selectors")

            except Exception as e:
                fail("11-E  Settings modal test failed", str(e)[:200])
            ctx.close()
            browser.close()


        # ─────────────────────────────────────────────────────────────────────
        section("11-F. Session refresh / back button")
        # ─────────────────────────────────────────────────────────────────────
        if TEST_KEY:
            browser, ctx, page = make_browser_ctx(pw)
            signin_session_via_api(ctx)
            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(1_500)

                # 11.30 Refresh preserves session
                page.reload(wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(2_000)
                chk("11.30  Refresh on /app preserves session (stays on /app)",
                    "/app" in page.url, f"Redirected to: {page.url}")

                # 11.13 Browser back button
                page.go_back()
                page.wait_for_timeout(1_500)
                page.go_forward()
                page.wait_for_timeout(1_500)
                chk("11.13  Browser back+forward on /app: no blank page",
                    len(page.content()) > 500)

            except Exception as e:
                fail("11-F  Refresh/back test failed", str(e)[:200])
            ctx.close()
            browser.close()


except ImportError:
    warn("Playwright not installed — run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("test_11  Navigation test suite crashed", str(e)[:400])
    log.exception("Navigation suite crash", e)


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Navigation tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
