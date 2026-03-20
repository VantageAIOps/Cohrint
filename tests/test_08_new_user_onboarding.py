"""
test_08_new_user_onboarding.py — New user onboarding flow
==========================================================
Developer notes:
  Simulates a brand-new user going through the complete onboarding journey:

    Phase 1: Discovery (landing page)
      → Homepage loads, nav links visible, hero CTA works

    Phase 2: Sign-up (/signup)
      → Fill form → get API key → auto-sign-in → dashboard

    Phase 3: First dashboard experience
      → Data is empty (no events yet) — dashboard should show empty state,
        not an error or crash
      → Seed data panel may appear for empty orgs

    Phase 4: First event ingestion (SDK simulation)
      → POST /v1/events with new key
      → Data appears in /analytics/summary

    Phase 5: Dashboard data visible
      → MTD cost > 0 after event ingest
      → KPI cards populate

    Phase 6: First key recovery (simulate forgot key)
      → POST /v1/auth/recover → 200

  All phases tested end-to-end as a single user journey (same account throughout).

Run:
  python tests/test_08_new_user_onboarding.py
  HEADLESS=0 python tests/test_08_new_user_onboarding.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_tag, rand_name,
    signup_api, get_headers, get_session_cookie, signin_ui,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.onboarding")

NEW_EMAIL = rand_email("new")
NEW_KEY   = None
NEW_ORG   = None


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 1 — Discovery: homepage CTA and navigation")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors = collect_console_errors(page)

        # P1.1 Homepage loads
        try:
            page.goto(f"{SITE_URL}/", wait_until="networkidle", timeout=20_000)
            chk("P1.1 Homepage loads", page.title() != "")
        except Exception as e:
            fail("P1.1 Homepage failed to load", str(e)[:200])

        # P1.2 Sign-up CTA is visible and clickable
        cta = page.locator("#nav-cta, a[href*='/signup'].nav-cta")
        chk("P1.2 Sign-up CTA visible in nav", cta.count() > 0 and cta.first.is_visible())

        # P1.3 CTA points to /signup
        if cta.count() > 0:
            href = cta.first.get_attribute("href") or ""
            chk("P1.3 Sign-up CTA href points to /signup", "signup" in href, f"href={href}")

        # P1.4 Docs link accessible
        docs_link = page.locator("a[href*='docs']")
        chk("P1.4 Docs link exists on homepage", docs_link.count() > 0)

        # P1.5 Calculator link accessible
        calc_link = page.locator("a[href*='calculator']")
        chk("P1.5 Calculator link exists on homepage", calc_link.count() > 0)

        # P1.6 No JS errors on homepage
        page.wait_for_timeout(1_500)
        chk("P1.6 No JS errors on homepage", len(js_errors) == 0,
            str(js_errors[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping Phase 1 UI tests")
except Exception as e:
    fail("Phase 1 error", str(e)[:300])


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 2 — Sign-up via UI and API")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors_p2 = collect_console_errors(page)

        page.goto(f"{SITE_URL}/signup", wait_until="networkidle", timeout=20_000)

        page.fill("#inp-name",  rand_name())
        page.fill("#inp-email", NEW_EMAIL)
        page.fill("#inp-org",   rand_org("newusr"))

        captured_key = None
        try:
            with page.expect_response(
                lambda r: "/v1/auth/signup" in r.url, timeout=15_000
            ) as resp_info:
                page.click("#submit-btn")
            resp = resp_info.value
            chk("P2.1 Signup form submit → 201", resp.status == 201,
                f"status={resp.status}")

            if resp.status == 201:
                page.wait_for_selector("#success-state", state="visible", timeout=8_000)
                chk("P2.2 Success state appears", page.locator("#success-state").is_visible())

                key_el = page.locator("#key-display")
                captured_key = key_el.inner_text().strip()
                NEW_KEY = captured_key
                chk("P2.3 API key displayed in success state",
                    bool(captured_key) and captured_key.startswith("vnt_"),
                    f"key={captured_key[:20] if captured_key else 'empty'}")

                chk("P2.4 'Shown once' warning present",
                    any(w in page.content() for w in ["once", "never", "save"]))

                # P2.5 Dashboard link present
                dash = page.locator("#dashboard-link")
                chk("P2.5 'Open dashboard' button exists", dash.count() > 0)

                if captured_key:
                    info(f"New user key: {captured_key[:28]}…")

        except PWTimeout as e:
            fail("P2.1 Signup form timed out", str(e)[:200])

        chk("P2.6 No JS errors during signup", len(js_errors_p2) == 0,
            str(js_errors_p2[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — using API signup for Phase 2")
    try:
        d2 = signup_api(email=NEW_EMAIL)
        NEW_KEY = d2["api_key"]
        NEW_ORG = d2["org_id"]
        chk("P2.x  API signup (fallback)", True)
    except Exception as e:
        fail("P2.x  API signup fallback failed", str(e))
except Exception as e:
    fail("Phase 2 error", str(e)[:300])
    # Fallback to API signup
    try:
        d2 = signup_api(email=NEW_EMAIL)
        NEW_KEY = d2.get("api_key")
        NEW_ORG = d2.get("org_id")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 3 — First dashboard: empty state")
# ─────────────────────────────────────────────────────────────────────────────
if not NEW_KEY:
    fail("P3   No key — cannot test dashboard. Running API fallback.")
    try:
        d3 = signup_api()
        NEW_KEY = d3["api_key"]
        NEW_ORG = d3["org_id"]
    except Exception as e:
        fail("P3   API fallback failed", str(e))
        sys.exit(1)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        browser, ctx, page = make_browser_ctx(pw)
        js_errors_p3 = collect_console_errors(page)

        signed = signin_ui(page, NEW_KEY)
        chk("P3.1 New user signs in → dashboard", signed, page.url)

        if signed:
            page.wait_for_timeout(2_000)

            # P3.2 Dashboard stays on /app (no bounce for new user)
            chk("P3.2 Dashboard stable for new user (no redirect loop)",
                "/app" in page.url, f"url={page.url}")

            # P3.3 KPI grid exists (may show $0.00 for empty account)
            chk("P3.3 KPI grid rendered even for new (empty) account",
                page.locator(".kpi-grid, .kpi").count() > 0)

            # P3.4 No crash JS errors for empty data
            page.wait_for_timeout(2_000)
            critical_errors = [e for e in js_errors_p3
                               if "uncaught" in e.lower() or "typeerror" in e.lower()]
            chk("P3.4 No critical JS errors for empty-data new user",
                len(critical_errors) == 0, str(critical_errors[:3]))

        ctx.close()
        browser.close()

except ImportError:
    warn("Playwright not installed — skipping Phase 3 UI tests")
except Exception as e:
    fail("Phase 3 error", str(e)[:300])


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 4 — First event ingestion")
# ─────────────────────────────────────────────────────────────────────────────
try:
    hdr = get_headers(NEW_KEY)

    # P4.1 Single event
    evt = {
        "event_id":          f"onboard-{rand_tag()}",
        "provider":          "openai",
        "model":             "gpt-4o",
        "prompt_tokens":     300,
        "completion_tokens": 100,
        "total_tokens":      400,
        "total_cost_usd":    0.003,
        "latency_ms":        250,
        "team":              "onboarding",
        "environment":       "test",
    }
    r = requests.post(f"{API_URL}/v1/events", json=evt, headers=hdr, timeout=15)
    chk("P4.1 New user ingests first event → 200/201",
        r.status_code in (200, 201), f"{r.status_code}: {r.text[:100]}")

    # P4.2 Batch of events (simulating SDK flush)
    batch = {
        "events": [
            {**evt, "event_id": f"onboard-batch-{i}-{rand_tag()}",
             "total_cost_usd": 0.002 + i * 0.001}
            for i in range(5)
        ]
    }
    r = requests.post(f"{API_URL}/v1/events/batch", json=batch, headers=hdr, timeout=15)
    chk("P4.2 New user batch ingest (5 events) → 200/201",
        r.status_code in (200, 201), f"{r.status_code}: {r.text[:100]}")
    if r.ok:
        chk("P4.3 Batch accepted=5", r.json().get("accepted") == 5, str(r.json()))

    log.info("Events ingested for new user", key_prefix=NEW_KEY[:20])

except Exception as e:
    fail("Phase 4 event ingestion failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 5 — Data visible in dashboard after ingest")
# ─────────────────────────────────────────────────────────────────────────────
time.sleep(2)  # allow D1 writes to propagate

try:
    hdr = get_headers(NEW_KEY)

    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=hdr, timeout=10)
    chk("P5.1 Analytics summary → 200 after event ingest", r.status_code == 200,
        f"{r.status_code}")
    if r.ok:
        d = r.json()
        chk("P5.2 MTD cost > $0 after events", d.get("mtd_cost_usd", 0) > 0,
            f"mtd_cost_usd={d.get('mtd_cost_usd')}")

    r = requests.get(f"{API_URL}/v1/analytics/kpis?period=30", headers=hdr, timeout=10)
    chk("P5.3 KPIs → 200 after event ingest", r.status_code == 200)
    if r.ok:
        d = r.json()
        chk("P5.4 Total requests ≥6 (1 single + 5 batch)",
            d.get("total_requests", 0) >= 6,
            f"total_requests={d.get('total_requests')}")

except Exception as e:
    fail("Phase 5 data verification failed", str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("Phase 6 — Key recovery initiation")
# ─────────────────────────────────────────────────────────────────────────────
try:
    r = requests.post(f"{API_URL}/v1/auth/recover",
                      json={"email": NEW_EMAIL}, timeout=15)
    chk("P6.1 POST /recover for new user email → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")
except Exception as e:
    fail("P6.1 Key recovery initiation failed", str(e))


# ── Summary ───────────────────────────────────────────────────────────────────
r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Onboarding tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
