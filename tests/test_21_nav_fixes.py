"""
test_21_nav_fixes.py — Navigation & Recent Bug-Fix Verification
===============================================================
Developer notes:
  Targets the specific bugs fixed in March 2026:

  BUG-1  "All sidebar nav buttons not responsive"
    Root cause: raw unquoted HTML inside a JS template literal in
    loadMembersView() caused a SyntaxError in the entire first <script>
    block, so nav(), init_cost() and every other function in that block
    were never defined.  Fix: quoted the HTML fallback string.

  BUG-2  "Account and Settings views show dashes / empty fields"
    Root cause: nav() never called loadAccountView() / loadSettingsView()
    (because nav() wasn't defined — same SyntaxError as above).
    Secondary: session response was missing api_key_hint + created_at.

  BUG-3  CSP blocking Cloudflare Insights beacon
    Cloudflare Pages auto-injects beacon.min.js but the old CSP did not
    whitelist static.cloudflareinsights.com.  Caused spurious console
    errors in every test that checked for "no JS errors".
    Fix: added cloudflareinsights.com to default-src + connect-src.

  BUG-4  Duplicate ⚙ Settings button in topbar
    Fix: removed the redundant topbar Settings button; Settings is now
    only in the sidebar and the user-avatar dropdown.

Tests (21.1 – 21.30):
  API sanity (21.1 – 21.10):
    21.1   GET /v1/auth/session → 200, authenticated=true
    21.2   Session contains org_id
    21.3   Session contains org.name
    21.4   Session contains org.email
    21.5   Session contains org.plan
    21.6   Session contains sse_token
    21.7   Session org.api_key_hint present (null OK if worker not redeployed)
    21.8   Session org.created_at present (null OK if worker not redeployed)
    21.9   POST /v1/events → 202 (ingest works after fix)
    21.10  GET /v1/analytics/kpis → 200

  nav() function defined — no SyntaxError (21.11 – 21.15):
    21.11  app.html loads with no page-level JS errors
    21.12  nav() is defined (evaluates in browser without ReferenceError)
    21.13  loadAccountView() is defined
    21.14  loadSettingsView() is defined
    21.15  loadMembersView() is defined

  All sidebar buttons navigate correctly (21.16 – 21.23):
    21.16  Cost Intelligence button → view-cost becomes active
    21.17  Token Analytics button → view-tokens becomes active
    21.18  Model Comparison button → view-models becomes active
    21.19  Performance & Latency button → view-perf becomes active
    21.20  Settings sidebar button → view-settings becomes active
    21.21  Account sidebar button → view-account becomes active
    21.22  Developer Experience button → view-devx becomes active
    21.23  Agent Traces button → view-traces becomes active

  Account view data (21.24 – 21.26):
    21.24  Account view shows org name (not just dashes)
    21.25  Account view shows API key hint element
    21.26  Account view has Save profile button

  Settings view data (21.27 – 21.28):
    21.27  Settings view has API Base URL input
    21.28  API Base URL input value is not empty

  CSP / no regressions (21.29 – 21.30):
    21.29  No critical JS errors on dashboard (Cloudflare beacon is allowed)
    21.30  Team Members view renders without crash (tests the fixed template)

Run:
  python tests/test_21_nav_fixes.py
  HEADLESS=0 python tests/test_21_nav_fixes.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, signup_api, get_session_cookie,
    make_browser_ctx, collect_critical_errors, HEADLESS,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.nav_fixes")

# ── Create a fresh test account ───────────────────────────────────────────────
try:
    _acct   = signup_api()
    TEST_KEY = _acct["api_key"]
    TEST_ORG = _acct["org_id"]
    log.info("Test account ready", org_id=TEST_ORG)
except Exception as e:
    TEST_KEY = TEST_ORG = None
    log.error("Could not create test account", error=str(e))


def _set_session_cookie(ctx):
    """Inject the session cookie into a Playwright browser context."""
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

    # ── Section A: API sanity ─────────────────────────────────────────────────
    section("21-A. Session API sanity after fix")

    if not TEST_KEY:
        fail("21.1  Could not create test account — skipping API tests")
    else:
        cookies = get_session_cookie(TEST_KEY)
        r = requests.get(f"{API_URL}/v1/auth/session",
                         cookies=cookies, timeout=15)
        sess = r.json() if r.ok else {}

        chk("21.1   GET /v1/auth/session → 200", r.status_code == 200)
        chk("21.2   Session authenticated=true", sess.get("authenticated") is True)
        chk("21.3   Session contains org_id",  bool(sess.get("org_id")))
        chk("21.4   Session contains org.name", bool(sess.get("org", {}).get("name")))
        chk("21.5   Session contains org.email", bool(sess.get("org", {}).get("email")))
        chk("21.6   Session contains org.plan",  bool(sess.get("org", {}).get("plan")))
        chk("21.7   Session contains sse_token", bool(sess.get("sse_token")))

        # api_key_hint / created_at: may be null if worker not redeployed yet
        hint = sess.get("org", {}).get("api_key_hint")
        cat  = sess.get("org", {}).get("created_at")
        if hint is not None:
            chk("21.8   org.api_key_hint present in session", True)
            info(f"  api_key_hint = {hint}")
        else:
            warn("21.8   org.api_key_hint not in session (worker not redeployed yet — expected)")
        if cat is not None:
            chk("21.9a  org.created_at present in session", True)
        else:
            warn("21.9a  org.created_at not in session (worker not redeployed yet — expected)")

        # Ingest + analytics
        ev_r = requests.post(
            f"{API_URL}/v1/events",
            json={"model": "gpt-4o", "provider": "openai",
                  "prompt_tokens": 100, "completion_tokens": 50,
                  "cost_usd": 0.003, "latency_ms": 800},
            headers={"Authorization": f"Bearer {TEST_KEY}"},
            timeout=15,
        )
        chk("21.9   POST /v1/events → 202", ev_r.status_code == 202,
            f"got {ev_r.status_code}: {ev_r.text[:100]}")

        kpi_r = requests.get(
            f"{API_URL}/v1/analytics/kpis",
            cookies=cookies, timeout=15,
        )
        chk("21.10  GET /v1/analytics/kpis → 200",
            kpi_r.status_code == 200, f"got {kpi_r.status_code}")

    # ── Section B: nav() defined — no SyntaxError ─────────────────────────────
    section("21-B. nav() and view functions defined (no SyntaxError in first <script>)")

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        all_errs, critical = collect_critical_errors(page)

        ok_session = _set_session_cookie(ctx)
        if not ok_session:
            warn("Could not set session cookie — some tests will be limited")

        try:
            page.goto(f"{SITE_URL}/app.html", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_000)
            chk("21.11  app.html loads without page-level JS error",
                len([e for e in all_errs if e.startswith("JS:")]) == 0,
                str(all_errs[:3]))
        except Exception as e:
            fail("21.11  app.html failed to load", str(e)[:200])

        # Check that nav() and siblings are defined in the browser
        for fn_name, test_id in [
            ("nav",               "21.12"),
            ("loadAccountView",   "21.13"),
            ("loadSettingsView",  "21.14"),
            ("loadMembersView",   "21.15"),
        ]:
            try:
                result = page.evaluate(f"typeof {fn_name}")
                chk(f"{test_id}  {fn_name}() is defined (not SyntaxError)",
                    result == "function",
                    f"typeof {fn_name} = '{result}' (expected 'function')")
            except Exception as e:
                fail(f"{test_id}  {fn_name}() threw during evaluation", str(e)[:150])

        # ── Section C: All sidebar buttons navigate correctly ─────────────────
        section("21-C. Sidebar navigation buttons (was broken by JS SyntaxError)")

        NAV_TESTS = [
            ("nav('cost',document.querySelector('.sb-item'))",    "view-cost",     "21.16  Cost Intelligence"),
            ("nav('tokens',document.querySelector('.sb-item'))",  "view-tokens",   "21.17  Token Analytics"),
            ("nav('models',document.querySelector('.sb-item'))",  "view-models",   "21.18  Model Comparison"),
            ("nav('perf',document.querySelector('.sb-item'))",    "view-perf",     "21.19  Performance & Latency"),
            ("nav('settings',document.getElementById('sb-settings'))", "view-settings", "21.20  Settings"),
            ("nav('account',document.getElementById('sb-account'))",   "view-account",  "21.21  Account"),
            ("nav('devx',document.querySelector('.sb-item'))",    "view-devx",     "21.22  Developer Experience"),
            ("nav('traces',document.querySelector('.sb-item'))",  "view-traces",   "21.23  Agent Traces"),
        ]

        for js_call, expected_view_id, label in NAV_TESTS:
            try:
                page.evaluate(js_call)
                page.wait_for_timeout(300)
                has_active = page.evaluate(
                    f"document.getElementById('{expected_view_id}')?.classList.contains('active') ?? false"
                )
                chk(f"{label} → {expected_view_id} active",
                    has_active,
                    f"view '{expected_view_id}' did not become active")
            except Exception as e:
                fail(f"{label} threw exception", str(e)[:200])

        # ── Section D: Account & Settings views show real data ────────────────
        section("21-D. Account view data (BUG-2: was showing only dashes)")

        # Navigate to account view
        try:
            page.evaluate("nav('account', document.getElementById('sb-account'))")
            page.wait_for_timeout(1_500)

            # Name must not be just dashes
            name_text = page.evaluate(
                "document.getElementById('acct-name-display')?.textContent?.trim() || ''"
            )
            chk("21.24  Account view shows org name (not just '—')",
                name_text not in ("", "—", "Loading..."),
                f"acct-name-display = '{name_text}'")

            # Key hint element present
            hint_text = page.evaluate(
                "document.getElementById('acct-key-hint')?.textContent?.trim() || ''"
            )
            chk("21.25  Account view has API key hint element",
                len(hint_text) > 0 and "vnt_" in hint_text,
                f"acct-key-hint = '{hint_text}'")

            # Save profile button visible
            save_btn = page.locator("button[onclick='saveProfile()']")
            chk("21.26  Account view has Save profile button",
                save_btn.count() > 0)
        except Exception as e:
            fail("21.24-26  Account view evaluation failed", str(e)[:200])

        section("21-E. Settings view data (BUG-2: was showing empty fields)")
        try:
            page.evaluate("nav('settings', document.getElementById('sb-settings'))")
            page.wait_for_timeout(1_000)

            base_val = page.evaluate(
                "document.getElementById('set-base-input')?.value || ''"
            )
            chk("21.27  Settings view has API Base URL input",
                bool(base_val),
                "set-base-input was empty")
            chk("21.28  API Base URL contains api.vantageaiops.com",
                "vantageaiops.com" in base_val,
                f"set-base-input = '{base_val}'")
        except Exception as e:
            fail("21.27-28  Settings view evaluation failed", str(e)[:200])

        # ── Section E: CSP + no regressions ──────────────────────────────────
        section("21-F. CSP & regression checks")

        chk("21.29  No CRITICAL JS errors on dashboard (beacon noise filtered)",
            len(critical) == 0,
            str(critical[:3]))

        # Team Members view — the exact template that had the SyntaxError
        section("21-G. Team Members view (fixed template literal)")
        try:
            page.evaluate("nav('members', document.getElementById('sb-members'))")
            page.wait_for_timeout(1_500)

            members_view_active = page.evaluate(
                "document.getElementById('view-members')?.classList.contains('active') ?? false"
            )
            chk("21.30  Team Members view → view-members activates without crash",
                members_view_active)

            # Ensure no NEW JS errors appeared during members render
            new_critical = [e for e in all_errs
                            if e.startswith("JS:") and
                            not any(n in e for n in ("cloudflare", "beacon"))]
            chk("21.30b No JS errors after navigating to Team Members",
                len(new_critical) == 0,
                str(new_critical[:3]))
        except Exception as e:
            fail("21.30  Team Members navigation threw exception", str(e)[:200])

        browser.close()

except Exception as e:
    fail(f"Unexpected top-level error in test_21", str(e)[:300])

# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
print(f"\n  Nav-fixes tests: {r['passed']} passed  {r['failed']} failed  "
      f"{r['warned']} warned  ({r['passed']+r['failed']+r['warned']} total)")

if r["failed"] > 0:
    sys.exit(1)
