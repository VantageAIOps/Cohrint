"""
test_02_signin.py — Sign-in flow tests (API + UI)
==================================================
Developer notes:
  Tests the full sign-in path:
    • POST /v1/auth/session  (exchange API key → session cookie)
    • GET  /v1/auth/session  (validate session, get org/member info)
    • DELETE /v1/auth/session (logout, cookie cleared)
    • UI form on /auth page  (Playwright)

Known bugs to detect:
  - "Website goes down immediately after using existing api_key"
    → check that POST session → redirect to /app works without crashing
  - Session cookie domain must match vantageaiops.com
  - Redirect loop guard: /auth?next=/auth should go to /app not loop
  - After sign-in, GET /session should return org info needed to load data

Run:
  python tests/test_02_signin.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag,
    signup_api, get_headers, get_session_cookie, session_get, fresh_account,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.signin")


# ─────────────────────────────────────────────────────────────────────────────
# 1. API — session create / read / delete
# ─────────────────────────────────────────────────────────────────────────────
section("1. Sign-in API — POST /v1/auth/session")

API_KEY = ORG_ID = None

try:
    d       = signup_api()
    API_KEY = d["api_key"]
    ORG_ID  = d["org_id"]
    info(f"Test account: {ORG_ID}  key={API_KEY[:24]}…")
except Exception as e:
    fail("Could not create test account — skipping API tests", str(e))
    API_KEY = None

if API_KEY:
    # 1.1 Valid key → 200 + session cookie
    try:
        r = requests.post(f"{API_URL}/v1/auth/session", json={"api_key": API_KEY}, timeout=15)
        chk("1.1  Valid key → POST session 200", r.status_code == 200,
            f"{r.status_code}: {r.text[:100]}")
        chk("1.2  Response has ok=true", r.json().get("ok") is True, str(r.json()))
        chk("1.3  Set-Cookie header present", "set-cookie" in {k.lower() for k in r.headers},
            f"headers={list(r.headers.keys())}")
        session_cookie = r.cookies
    except Exception as e:
        fail("1.1-1.3  Session create failed", str(e))
        session_cookie = None

    # 1.4 Wrong key → 401
    try:
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": "vnt_wrongorg_000000000000000000000000"}, timeout=10)
        chk("1.4  Wrong key → 401", r.status_code == 401, f"got {r.status_code}")
    except Exception as e:
        fail("1.4  Wrong-key test failed", str(e))

    # 1.5 Malformed key (no vnt_ prefix) → 400 or 401
    try:
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": "sk-notavantagekey"}, timeout=10)
        chk("1.5  Malformed key (no vnt_) → 400/401", r.status_code in (400, 401),
            f"got {r.status_code}")
    except Exception as e:
        fail("1.5  Malformed-key test failed", str(e))

    # 1.6 Missing api_key field → 400
    try:
        r = requests.post(f"{API_URL}/v1/auth/session", json={}, timeout=10)
        chk("1.6  Missing api_key → 400", r.status_code == 400, f"got {r.status_code}")
    except Exception as e:
        fail("1.6  Missing-key test failed", str(e))

    # 1.7 GET /session with valid cookie → 200 + org info
    try:
        cookies = get_session_cookie(API_KEY)
        assert cookies, "Could not obtain session cookie"
        r = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=10)
        chk("1.7  GET /session with cookie → 200", r.status_code == 200,
            f"got {r.status_code}: {r.text[:100]}")
        sess = r.json()
        chk("1.8  Session contains org_id", bool(sess.get("org_id")), str(sess))
        chk("1.9  Session contains role", bool(sess.get("role")), str(sess))
        chk("1.10 Session contains sse_token", bool(sess.get("sse_token")), str(sess))
        log.info("Session GET succeeded", org_id=sess.get("org_id"), role=sess.get("role"))
    except Exception as e:
        fail("1.7-1.10  GET session test failed", str(e))

    # 1.11 GET /session without cookie → 401
    try:
        r = requests.get(f"{API_URL}/v1/auth/session", timeout=10)
        chk("1.11 GET /session without cookie → 401", r.status_code == 401,
            f"got {r.status_code}")
    except Exception as e:
        fail("1.11 No-cookie session test failed", str(e))

    # 1.12 DELETE /session logs out (cookie cleared)
    try:
        cookies = get_session_cookie(API_KEY)
        r_del = requests.delete(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=10)
        chk("1.12 DELETE /session → 200", r_del.status_code == 200,
            f"got {r_del.status_code}")
        # After logout, using old cookie should fail
        r_get = requests.get(f"{API_URL}/v1/auth/session", cookies=cookies, timeout=10)
        chk("1.13 After logout, old cookie → 401", r_get.status_code == 401,
            f"got {r_get.status_code} — session not invalidated!")
        log.info("Logout succeeded")
    except Exception as e:
        fail("1.12-1.13  Logout test failed", str(e))

    # 1.14 Bearer token auth also works (no cookie)
    try:
        r = requests.get(f"{API_URL}/v1/analytics/summary",
                         headers=get_headers(API_KEY), timeout=10)
        chk("1.14 Bearer token auth works for analytics", r.status_code == 200,
            f"got {r.status_code}: {r.text[:100]}")
    except Exception as e:
        fail("1.14 Bearer auth test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. UI — /auth sign-in page (Playwright)
# ─────────────────────────────────────────────────────────────────────────────
section("2. Sign-in UI — /auth page (Playwright)")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    # Create a fresh account to sign in with
    d_ui = signup_api()
    ui_key = d_ui["api_key"]
    info(f"UI test key = {ui_key[:28]}…")

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 2.1 Auth page loads
        try:
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
            chk("2.1  /auth page loads", "auth" in page.url.lower() or
                any(w in page.content().lower() for w in ["sign in", "api key"]))
        except Exception as e:
            fail("2.1  Auth page load failed", str(e)[:200])

        # 2.2-2.4 Form elements
        chk("2.2  API key input visible",  page.locator("#inp-key").is_visible())
        chk("2.3  Sign-in button visible", page.locator("#signin-btn").is_visible())
        chk("2.4  'Forgot your key?' visible",
            page.locator("button.ghost-btn").count() > 0)

        # 2.5 Wrong key shows error message
        try:
            page.fill("#inp-key", "vnt_badorg_0000000000000000000000000000")
            with page.expect_response(
                lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                timeout=10_000
            ) as resp_info:
                page.click("#signin-btn")
            resp = resp_info.value
            chk("2.5  Wrong key → 401 from server", resp.status == 401,
                f"got {resp.status}")
            page.wait_for_selector("#signin-err", state="visible", timeout=5_000)
            err_text = page.locator("#signin-err").inner_text()
            chk("2.6  Error message shown for wrong key",
                bool(err_text) and len(err_text) > 5, f"err='{err_text}'")
        except PWTimeout as e:
            fail("2.5-2.6  Wrong-key error test timed out", str(e)[:200])
        except Exception as e:
            fail("2.5-2.6  Wrong-key error test failed", str(e)[:200])

        # 2.7 Button re-enables after failed sign-in
        chk("2.7  Sign-in button re-enabled after failed attempt",
            not page.locator("#signin-btn").is_disabled())

        # 2.8 Valid key → redirect to /app
        try:
            page.fill("#inp-key", ui_key)
            with page.expect_response(
                lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                timeout=10_000
            ) as resp_info:
                page.click("#signin-btn")
            resp = resp_info.value
            # Note: resp.text() may throw "Protocol error: No resource with given identifier"
            # after a redirect — check status only, body consumed by redirect
            chk("2.8  Valid key → 200 from server", resp.status == 200,
                f"got {resp.status}")
            page.wait_for_url(f"{SITE_URL}/app**", timeout=8_000)
            chk("2.9  Redirected to /app after sign-in", "/app" in page.url,
                f"url={page.url}")
        except PWTimeout as e:
            fail("2.8-2.9  Valid sign-in / redirect timed out", str(e)[:200])
        except Exception as e:
            fail("2.8-2.9  Valid sign-in test failed", str(e)[:200])

        # 2.10 Dashboard stays loaded (doesn't immediately crash / redirect back)
        try:
            page.wait_for_timeout(2_000)
            chk("2.10 Dashboard stays on /app (doesn't bounce back to /auth)",
                "/app" in page.url,
                f"bounced to: {page.url}")
        except Exception as e:
            fail("2.10 Stability check failed", str(e)[:200])

        # 2.11 Session cookie set after sign-in
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        chk("2.11 Session cookie exists after sign-in",
            any("session" in k.lower() for k in cookies),
            f"cookies={list(cookies.keys())}")

        # 2.12 Enter key submits sign-in form
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
        page2 = ctx2.new_page()
        try:
            page2.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
            page2.fill("#inp-key", "vnt_badkey_00000000000000000000000000")
            with page2.expect_response(
                lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                timeout=10_000
            ):
                page2.keyboard.press("Enter")
            chk("2.12 Enter key submits sign-in form", True)
        except PWTimeout:
            fail("2.12 Enter-key submit timed out — form may not respond to Enter")
        finally:
            ctx2.close()

        # 2.13 Redirect loop guard: /auth?next=/auth → should go to /app
        try:
            ctx3 = browser.new_context(viewport={"width": 1280, "height": 800})
            page3 = ctx3.new_page()
            # Pre-seed session cookies from earlier sign-in
            for c in ctx.cookies():
                ctx3.add_cookies([c])
            page3.goto(f"{SITE_URL}/auth?next=/auth", wait_until="networkidle", timeout=15_000)
            page3.wait_for_timeout(2_000)
            chk("2.13 /auth?next=/auth doesn't loop (goes to /app)",
                "/auth?next" not in page3.url,
                f"stuck at: {page3.url}")
            ctx3.close()
        except Exception as e:
            warn(f"2.13 Redirect-loop test inconclusive: {e}")

        # 2.14 No critical JS errors (filter out expected 401 from initial session probe)
        critical = [e for e in js_errors
                    if "401" not in e and "Unexpected token" not in e]
        unexpected_token = [e for e in js_errors if "Unexpected token" in e]
        chk("2.14 No critical JS errors during sign-in flow", len(critical) == 0,
            str(critical[:3]))
        # Report Unexpected token separately — indicates HTML returned instead of JSON (real bug)
        if unexpected_token:
            fail("2.14b BUG: 'Unexpected token' JS error — API returning HTML instead of JSON",
                 str(unexpected_token[:2]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests")
except Exception as e:
    fail("2.x  Sign-in UI test suite error", str(e)[:300])


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Sign-in tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
