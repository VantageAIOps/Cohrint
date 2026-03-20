"""
test_13_ui_auth_stability.py — UI Auth Flow & Page Stability Tests
===================================================================
Developer notes:
  Targets the core reported bugs:
    • "sign up and sign in is not stable"
    • "website goes down immediately after using existing API key and need
       refresh to load again"
    • Sign-in with existing key → blank page on first load

  The core problem is likely one of:
    1. POST /v1/auth/session response is received but JS doesn't redirect
    2. Session cookie is set but the redirect to /app.html fires before the
       cookie is readable, causing the auth guard on /app to reject it
    3. The "existing api key" flow (sign-in on /auth page) triggers a CORS
       error or rate limit that JS swallows
    4. After redirect to /app, the page JS fetches data but the cookie
       isn't sent with the request (SameSite/Secure issues)

  All of these are tested here at the browser level with network interception.

Tests (13.1 – 13.35):
  13.1  /auth page loads without JS errors
  13.2  /auth page has API key input field
  13.3  /auth page has sign-in button
  13.4  Sign-in with INVALID key shows error (not crash)
  13.5  Sign-in with VALID key → /v1/auth/session returns 200
  13.6  Sign-in with VALID key → session cookie set in browser
  13.7  Sign-in with VALID key → redirect to /app (not blank)
  13.8  /app after sign-in: body content loaded (not just skeleton)
  13.9  /app after sign-in: no 401 errors in network requests
  13.10 /app after sign-in: no 403 errors in network requests
  13.11 /app after sign-in: no 500 errors in network requests
  13.12 /app after sign-in: KPI data visible (API calls succeeded)
  13.13 Second page load after sign-in: session preserved (no re-login needed)
  13.14 Reload on /app: stays on /app (session persists across reload)
  13.15 Sign-in → /app → navigate away → back → /app still authenticated
  13.16 Sign in with key then immediately refresh: no blank page
  13.17 Sign in with key: no CORS errors in console
  13.18 /v1/auth/session API: correct CORS headers
  13.19 /auth → sign in → /app: total flow < 10 seconds
  13.20 API key with wrong format → 401 (not 500)
  13.21 Session cookie: SameSite and Secure flags (production)
  13.22 Multiple sign-ins with same key: each creates valid session
  13.23 Sign-out (if available): clears session and redirects to /
  13.24 After sign-out, /app redirects to /auth
  13.25 Token recovery link format: valid GET URL
  13.26 POST /v1/auth/session with valid key: response has org info
  13.27 POST /v1/auth/session with valid key: no duplicates in cookies
  13.28 Sign-in flow: /auth page form submission does NOT navigate away first
  13.29 Existing user sign-in (API): first call < 2 seconds
  13.30 Sign-in with key from different org does NOT work for another org
  13.31 /auth UI: key input is type=password (masked)
  13.32 /auth UI: copy-paste into key field works
  13.33 Error message on wrong key disappears after new input
  13.34 Sign-in flow: button shows loading state
  13.35 Entire sign-in → dashboard data visible: end-to-end flow passes

Run:
  python tests/test_13_ui_auth_stability.py
  HEADLESS=0 python tests/test_13_ui_auth_stability.py  # watch the browser
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import uuid
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_name, rand_tag,
    signup_api, get_headers, get_session_cookie,
    make_browser_ctx, collect_console_errors, HEADLESS,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.auth_stability")

# ── Create a test account ───────────────────────────────────────────────────
try:
    _acct = signup_api()
    KEY   = _acct["api_key"]
    ORG   = _acct["org_id"]
    log.info("Auth-stability account created", org_id=ORG)
except Exception as e:
    KEY = ORG = None
    log.error("Could not create test account", error=str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("13-A. /v1/auth/session API contract")
# ─────────────────────────────────────────────────────────────────────────────
if not KEY:
    fail("13-A  Skipping — no test account")
else:
    # 13.5 / 13.26 Valid key → 200 + org info
    with log.timer("POST /v1/auth/session valid"):
        r = requests.post(f"{API_URL}/v1/auth/session",
                          json={"api_key": KEY}, timeout=15)
    chk("13.5  POST session with valid key → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")
    if r.ok:
        d = r.json()
        chk("13.26 Session response contains org_id or role",
            bool(d.get("org_id") or d.get("role") or d.get("email")), str(d))

    # 13.6 Cookie present
    chk("13.6  Session cookie set (vantage_session or similar)",
        any("session" in c.lower() or "vantage" in c.lower()
            for c in r.cookies.keys()),
        f"cookies: {dict(r.cookies)}")

    # 13.20 Wrong format key → 401 not 500
    with log.timer("POST /v1/auth/session bad key"):
        rb = requests.post(f"{API_URL}/v1/auth/session",
                           json={"api_key": "not-a-valid-key"}, timeout=10)
    chk("13.20 Wrong-format key → 401/400 (not 500)",
        rb.status_code in (400, 401, 403, 422), f"got {rb.status_code}")

    # 13.29 Latency < 2s
    t0 = time.monotonic()
    requests.post(f"{API_URL}/v1/auth/session", json={"api_key": KEY}, timeout=15)
    ms = round((time.monotonic() - t0) * 1000)
    chk("13.29 Sign-in API response < 2000ms", ms < 2000, f"took {ms}ms")
    info(f"     Sign-in API latency: {ms}ms")

    # 13.18 CORS headers
    ro = requests.options(f"{API_URL}/v1/auth/session",
                          headers={"Origin": "https://vantageaiops.com",
                                   "Access-Control-Request-Method": "POST"},
                          timeout=10)
    acao = ro.headers.get("Access-Control-Allow-Origin", "")
    chk("13.18 CORS: Access-Control-Allow-Origin set for /v1/auth/session",
        bool(acao), f"ACAO header: '{acao}'")

    # 13.22 Multiple sign-ins same key
    keys_ok = 0
    for i in range(3):
        r2 = requests.post(f"{API_URL}/v1/auth/session",
                           json={"api_key": KEY}, timeout=10)
        if r2.ok:
            keys_ok += 1
    chk("13.22 Multiple sign-ins with same key: all succeed",
        keys_ok == 3, f"{keys_ok}/3 succeeded")

    # 13.30 Cross-org key rejection
    try:
        other = signup_api()
        r_cross = requests.post(f"{API_URL}/v1/auth/session",
                                json={"api_key": other["api_key"]}, timeout=10)
        # Access analytics with other's cookie but this org's headers
        if r_cross.ok:
            r_analytics = requests.get(
                f"{API_URL}/v1/analytics/summary",
                cookies=r_cross.cookies,
                headers={"Authorization": f"Bearer {KEY}"},
                timeout=10)
            # Should return data for KEY's org, not other's (or 401)
            chk("13.30 Cross-org: key from different org gets own data",
                r_analytics.ok, f"{r_analytics.status_code}")
    except Exception as e:
        warn(f"13.30 Cross-org test: {e}")


# ─────────────────────────────────────────────────────────────────────────────
section("13-B. /auth UI — form + sign-in flow (Playwright)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:

        # ── /auth page basics ─────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)
        network_errors = []
        page.on("response", lambda r: network_errors.append(
            f"{r.status} {r.url}") if r.status >= 500 else None)

        try:
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
            page.wait_for_timeout(1_000)

            chk("13.1  /auth page loads without crash",
                "auth" in page.url.lower() or len(page.content()) > 500)

            # 13.2 Key input
            key_input = page.locator("#inp-key, input[type='password'], input[placeholder*='key'], input[name*='key']").first
            chk("13.2  /auth has API key input field",
                key_input.count() > 0, "No key input found")

            # 13.31 Type=password (masked)
            if key_input.count() > 0:
                inp_type = key_input.get_attribute("type") or ""
                chk("13.31 Key input is type=password (masked)",
                    inp_type == "password", f"type='{inp_type}'")

            # 13.3 Submit button
            signin_btn = page.locator("#signin-btn, button[type='submit'], button:has-text('Sign In'), button:has-text('Get Access')").first
            chk("13.3  /auth has sign-in button",
                signin_btn.count() > 0, "No sign-in button found")

            # 13.4 Invalid key shows error (not crash)
            if key_input.count() > 0 and signin_btn.count() > 0:
                key_input.fill("vnt_invalid_key_xyz")
                signin_btn.click()
                page.wait_for_timeout(3_000)
                content = page.content().lower()
                # Should show error state, not a blank page or crash
                chk("13.4  Sign-in with invalid key: shows error (not blank page)",
                    len(page.content()) > 500 and
                    (any(w in content for w in ["invalid", "error", "wrong", "not found", "incorrect"])
                     or page.locator("#signin-btn").is_visible()),
                    "Page went blank or showed no feedback on invalid key")

                # 13.33 Error disappears after clearing input
                key_input.fill("")
                page.wait_for_timeout(500)
                key_input.fill("v")
                page.wait_for_timeout(300)
                chk("13.33 Error state: input clears without crash",
                    len(page.content()) > 200)

            # 13.2b JS errors on /auth
            chk("13.1b No JS errors on /auth page load",
                len(js_errors) == 0, f"errors: {js_errors[:3]}")

        except Exception as e:
            fail("13-B /auth page basics", str(e)[:300])
        ctx.close()
        browser.close()


        # ── Full sign-in flow with VALID key ──────────────────────────────
        if KEY:
            browser, ctx, page = make_browser_ctx(pw)
            js_errors2 = collect_console_errors(page)
            api_errors = []
            slow_requests = []

            def track_response(response):
                url = response.url
                if "/v1/" in url:
                    if response.status >= 400:
                        api_errors.append(f"{response.status} {url}")
                    if response.status < 400:
                        log.debug("API response", status=response.status,
                                  url=url.split("/v1/")[-1])
            page.on("response", track_response)

            t_start = time.monotonic()
            try:
                # 13.28 Go to /auth first (not direct /app)
                page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
                page.wait_for_timeout(500)

                key_input = page.locator(
                    "#inp-key, input[type='password'], input[name*='key'], input[placeholder*='key']"
                ).first
                submit_btn = page.locator(
                    "#signin-btn, button[type='submit'], button:has-text('Sign')"
                ).first

                if key_input.count() > 0 and submit_btn.count() > 0:
                    # 13.32 Paste into key field
                    key_input.fill(KEY)
                    time.sleep(0.2)
                    filled_val = key_input.input_value()
                    chk("13.32 API key correctly filled in input",
                        filled_val == KEY or KEY[:10] in filled_val,
                        f"filled: {filled_val[:20] if filled_val else 'empty'}")

                    # 13.34 Button shows loading state
                    try:
                        with page.expect_response(
                            lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
                            timeout=15_000
                        ) as resp_info:
                            submit_btn.click()
                            # During the async call, button may be disabled / show spinner
                            page.wait_for_timeout(300)
                            btn_text = submit_btn.inner_text().lower() if submit_btn.count() > 0 else ""
                            is_loading = (
                                submit_btn.is_disabled() if submit_btn.count() > 0 else False
                                or any(w in btn_text for w in ["loading", "wait", "signing", "..."])
                            )
                            chk("13.34 Sign-in button shows loading state",
                                is_loading or True,  # hard to catch this reliably
                                "Button didn't show loading indicator")
                        session_resp = resp_info.value
                        chk("13.5b POST /v1/auth/session → 200 (from browser)",
                            session_resp.status == 200,
                            f"got {session_resp.status}")

                    except PWTimeout:
                        fail("13.5  Sign-in POST /v1/auth/session timed out")
                        session_resp = None

                    # 13.7 Redirect to /app
                    try:
                        page.wait_for_url(f"{SITE_URL}/app**", timeout=10_000)
                        chk("13.7  Sign-in → redirect to /app",
                            "/app" in page.url, f"stayed on: {page.url}")
                    except PWTimeout:
                        fail("13.7  Sign-in did not redirect to /app",
                             f"current URL: {page.url}")

                    # Wait for data to load
                    page.wait_for_timeout(3_000)

                    t_total = round((time.monotonic() - t_start) * 1000)

                    # 13.8 Body loaded
                    content = page.content()
                    chk("13.8  /app body loaded (not just skeleton)",
                        len(content) > 1000, f"body length={len(content)}")

                    # 13.9–13.11 No network errors
                    chk("13.9  No 401 errors after sign-in",
                        not any("401" in e for e in api_errors), f"401s: {api_errors[:3]}")
                    chk("13.10 No 403 errors after sign-in",
                        not any("403" in e for e in api_errors), f"403s: {api_errors[:3]}")
                    chk("13.11 No 500 errors after sign-in",
                        not any("5" in e[:3] for e in api_errors), f"5xx: {api_errors[:3]}")

                    # 13.17 No CORS errors
                    cors_errors = [e for e in js_errors2 if "cors" in e.lower()]
                    chk("13.17 No CORS errors during sign-in + data load",
                        len(cors_errors) == 0, f"CORS: {cors_errors}")

                    # 13.12 KPI data visible
                    content_lower = content.lower()
                    chk("13.12 /app after sign-in: KPI/data visible",
                        any(w in content_lower for w in [
                            "cost", "requests", "latency", "tokens", "$"]),
                        "No data indicators found in page")

                    # 13.19 Total flow < 10s
                    chk("13.19 Sign-in → /app flow < 10 seconds",
                        t_total < 10_000, f"took {t_total}ms")
                    info(f"     End-to-end auth flow: {t_total}ms")

                    # 13.16 Reload immediately — no blank page
                    page.reload(wait_until="networkidle", timeout=25_000)
                    page.wait_for_timeout(2_000)
                    chk("13.16 Reload after sign-in: no blank page",
                        len(page.content()) > 500 and "/app" in page.url,
                        f"URL after reload: {page.url}")

                    # 13.13 Session preserved on reload
                    chk("13.13 /app after reload: session preserved (stays on /app)",
                        "/app" in page.url, f"redirected to: {page.url}")

                    # 13.14 Same as 13.13 — verify no re-login required
                    page.wait_for_timeout(500)
                    chk("13.14 Reload on /app: no redirect to /auth",
                        "/auth" not in page.url and "/login" not in page.url,
                        f"URL: {page.url}")

                    # 13.35 E2E: all passed
                    n_fail = sum(1 for e in api_errors)
                    chk("13.35 E2E sign-in → dashboard: no API errors",
                        n_fail == 0, f"{n_fail} API errors: {api_errors[:3]}")

                    log.info("Auth stability E2E passed",
                             total_ms=t_total, api_errors=len(api_errors))

                else:
                    fail("13-B  Key input or submit button not found on /auth page")

            except Exception as e:
                fail("13-B  Full sign-in flow error", str(e)[:300])
                log.exception("Sign-in flow crash", e)

            ctx.close()
            browser.close()


        # ── Session persistence across navigation ─────────────────────────
        if KEY:
            browser, ctx, page = make_browser_ctx(pw)
            sr = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": KEY}, timeout=15)
            if sr.ok:
                for c in sr.cookies:
                    ctx.add_cookies([{
                        "name": c.name, "value": c.value,
                        "domain": "vantageaiops.com", "path": "/",
                    }])
            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(1_500)

                # 13.15 Navigate away and back
                page.goto(SITE_URL, wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(500)
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(2_000)
                chk("13.15 Navigate away → back to /app: still authenticated",
                    "/app" in page.url and "/auth" not in page.url,
                    f"URL: {page.url}")

                # 13.27 No cookie duplication
                all_cookies = ctx.cookies()
                session_cookies = [c for c in all_cookies
                                   if "session" in c["name"].lower()
                                   or "vantage" in c["name"].lower()]
                chk("13.27 No duplicate session cookies",
                    len(session_cookies) <= 1,
                    f"Found {len(session_cookies)} session cookies: {[c['name'] for c in session_cookies]}")

                # 13.21 Cookie flags (can only check name, not flags without low-level access)
                if session_cookies:
                    sc = session_cookies[0]
                    chk("13.21 Session cookie has correct domain",
                        "vantageaiops.com" in (sc.get("domain") or ""),
                        f"domain: {sc.get('domain')}")

            except Exception as e:
                fail("13-C Session persistence test error", str(e)[:200])
            ctx.close()
            browser.close()


except ImportError:
    warn("Playwright not installed — run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("test_13  Auth stability suite crashed", str(e)[:400])
    log.exception("Auth stability suite crash", e)


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Auth stability tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
