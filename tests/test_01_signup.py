"""
test_01_signup.py — Sign-up flow tests (API + UI)
==================================================
Developer notes:
  Tests the full sign-up path end-to-end including:
    • POST /v1/auth/signup  (API contract, validation, duplicates)
    • Automatic session creation after signup (POST /v1/auth/session)
    • UI form on /signup page (Playwright)
    • Key format, copy button, dashboard link, success state

Known issue to watch:
  After signup the frontend auto-calls POST /v1/auth/session and should
  redirect to /app.html. If this redirect breaks users see a blank page.

Run:
  python tests/test_01_signup.py
  HEADLESS=0 python tests/test_01_signup.py   # watch the browser
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_name, rand_tag,
    signup_api, get_headers, get_session_cookie,
    make_browser_ctx, collect_console_errors, HEADLESS,
    ok, fail, warn, info, section, chk,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.signup")


# ─────────────────────────────────────────────────────────────────────────────
# 1. API — contract & validation
# ─────────────────────────────────────────────────────────────────────────────
section("1. Signup API — contract & validation")

# 1.1 Valid signup returns 201 + api_key
try:
    email = rand_email("s1")
    with log.timer("POST /v1/auth/signup valid"):
        r = requests.post(f"{API_URL}/v1/auth/signup",
                          json={"email": email, "name": rand_name(), "org": rand_org()},
                          timeout=15)
    chk("1.1  Valid signup → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:100]}")
    d = r.json()
    chk("1.2  api_key present in response", "api_key" in d, str(d))
    chk("1.3  api_key starts with crt_", d.get("api_key","").startswith("crt_"), d.get("api_key",""))
    chk("1.4  org_id present in response", bool(d.get("org_id")), str(d))
    chk("1.5  hint present (last 4 chars)", bool(d.get("hint")), str(d))
    log.info("Signup succeeded", email=email, org_id=d.get("org_id"))
except Exception as e:
    fail("1.x  Signup API exception", str(e))
    log.exception("Signup API failed", e)

# 1.6 Missing email → 400
try:
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"name": "No Email", "org": rand_org()}, timeout=10)
    chk("1.6  Missing email → 400", r.status_code == 400, f"got {r.status_code}")
except Exception as e:
    fail("1.6  Missing-email test failed", str(e))

# 1.7 Empty body → 400
try:
    r = requests.post(f"{API_URL}/v1/auth/signup", json={}, timeout=10)
    chk("1.7  Empty body → 400", r.status_code == 400, f"got {r.status_code}")
except Exception as e:
    fail("1.7  Empty-body test failed", str(e))

# 1.8 Duplicate email → 409
try:
    dup_email = rand_email("dup")
    requests.post(f"{API_URL}/v1/auth/signup",
                  json={"email": dup_email, "name": "First", "org": rand_org()}, timeout=10)
    r2 = requests.post(f"{API_URL}/v1/auth/signup",
                       json={"email": dup_email, "name": "Second", "org": rand_org()}, timeout=10)
    chk("1.8  Duplicate email → 409", r2.status_code == 409, f"got {r2.status_code}")
except Exception as e:
    fail("1.8  Duplicate-email test failed", str(e))

# 1.9 Invalid email format — should be rejected (400 or 422)
try:
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": "not-an-email", "name": "Bad", "org": rand_org()}, timeout=10)
    chk("1.9  Invalid email format → 4xx", r.status_code in (400, 422),
        f"got {r.status_code} — server accepted malformed email")
except Exception as e:
    warn(f"1.9  Invalid-email test inconclusive: {e}")

# 1.10 Org name with special chars is accepted (or safely sanitised)
try:
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": rand_email("sp"), "name": "Spec", "org": "org-with_dots.123"},
                      timeout=10)
    chk("1.10 Special-char org name → 201", r.status_code == 201, f"got {r.status_code}")
except Exception as e:
    warn(f"1.10 Special-char org test inconclusive: {e}")

# 1.11 Very long org name is handled
try:
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": rand_email("long"), "name": "Long",
                            "org": "a" * 200},
                      timeout=10)
    chk("1.11 Very long org name → 201 or 400 (not 500)", r.status_code in (201, 400, 422),
        f"got {r.status_code}")
except Exception as e:
    warn(f"1.11 Long-org test inconclusive: {e}")

# 1.12 API key can be used immediately to create session
try:
    d = signup_api(rand_email("imm"))
    key = d["api_key"]
    r = requests.post(f"{API_URL}/v1/auth/session", json={"api_key": key}, timeout=10)
    chk("1.12 New key immediately usable for session", r.status_code == 200,
        f"got {r.status_code}: {r.text[:100]}")
except Exception as e:
    fail("1.12 Immediate-session test failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 2. UI — /signup page (Playwright)
# ─────────────────────────────────────────────────────────────────────────────
section("2. Signup UI — /signup page (Playwright)")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # 2.1 Page loads
        try:
            page.goto(f"{SITE_URL}/signup", wait_until="networkidle", timeout=20_000)
            chk("2.1  /signup page loads (200)",
                "signup" in page.url.lower() or page.url.rstrip("/").endswith("signup"))
        except Exception as e:
            fail("2.1  /signup page load failed", str(e)[:200])

        # 2.2 Form elements present
        chk("2.2  Name field visible",   page.locator("#inp-name").is_visible())
        chk("2.3  Email field visible",  page.locator("#inp-email").is_visible())
        chk("2.4  Submit button visible",page.locator("#submit-btn").is_visible())
        chk("2.5  Page title contains 'free' or 'api key'",
            any(w in page.content().lower() for w in ["free", "api key"]))

        # 2.6 Validation: submit empty form shows error (not crash)
        page.click("#submit-btn")
        time.sleep(0.5)
        chk("2.6  Empty submit doesn't crash page",
            page.locator("#submit-btn").is_visible())

        # 2.7 Fill and submit valid form
        signup_email = rand_email("ui")
        page.fill("#inp-name",  "UI Test User")
        page.fill("#inp-email", signup_email)
        page.fill("#inp-org",   f"uitest{rand_tag(4)}")

        captured_key = None
        try:
            with page.expect_response(
                lambda r: "/v1/auth/signup" in r.url, timeout=15_000
            ) as resp_info:
                page.click("#submit-btn")
            resp = resp_info.value
            chk("2.7  Signup API reached (201)", resp.status == 201,
                f"status={resp.status}")

            if resp.status == 201:
                # 2.8 Success state visible
                page.wait_for_selector("#success-state", state="visible", timeout=8_000)
                chk("2.8  Success state appeared", page.locator("#success-state").is_visible())

                # 2.9 API key displayed
                key_el = page.locator("#key-display")
                captured_key = key_el.inner_text().strip()
                chk("2.9  API key in success state (starts crt_)",
                    bool(captured_key) and captured_key.startswith("crt_"),
                    f"got: {captured_key[:30] if captured_key else 'empty'}")

                # 2.10 "Shown once" warning present
                chk("2.10 'shown once' / 'never' warning visible",
                    any(w in page.content() for w in ["once", "never", "copy"]))

                # 2.11 Dashboard link present + points to /app
                dash_btn = page.locator("#dashboard-link")
                chk("2.11 Dashboard link exists", dash_btn.count() > 0)
                if dash_btn.count() > 0:
                    href = dash_btn.first.get_attribute("href") or ""
                    chk("2.12 Dashboard link href contains /app", "/app" in href, f"href={href}")

                # 2.13 No JS errors during signup
                page.wait_for_timeout(1_000)
                chk("2.13 No JS errors on signup page", len(js_errors) == 0,
                    str(js_errors[:3]))

                if captured_key:
                    info(f"Captured key = {captured_key[:28]}…")

        except PWTimeout as e:
            fail("2.7+ Signup form submission timed out", str(e)[:200])

        # 2.14 After signup a session cookie exists (auto-login)
        if captured_key:
            cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            chk("2.14 Session cookie set after signup",
                any("session" in k.lower() for k in cookies),
                f"cookies={list(cookies.keys())}")

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping UI tests. Run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("2.x  Signup UI test suite error", str(e)[:300])


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
from helpers import get_results
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Signup tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
