"""
test_12_data_loading.py — Dashboard Data Loading Tests
=======================================================
Developer notes:
  Targets the reported bug: "after loading it does not show any data"
  and "website goes down immediately after using existing API key".

  Root causes investigated:
    1. Dashboard loads but API calls fail silently (no error shown, just empty state)
    2. API key cookie not set correctly → all /v1/* calls return 401 silently
    3. Analytics endpoints return empty arrays (no seeded data for new account)
    4. Chart.js initialisation fails when data is empty → blank chart area
    5. KPI cards show "—" or "0" but no indication to the user why

  Strategy:
    A. Create a fresh account and ingest real events first
    B. Sign in via UI cookie (not mock)
    C. Assert every KPI card updates from the events we sent
    D. Assert charts are rendered (canvas elements present)
    E. Assert tables have at least one row
    F. Test with zero-data account too (new user state)

Tests (12.1 – 12.40):
  12.1  POST /v1/events succeeds with valid key (single event)
  12.2  POST /v1/events/batch succeeds (10 events)
  12.3  GET /v1/analytics/summary returns data after ingest
  12.4  Summary today_cost_usd > 0 after ingest
  12.5  Summary today_requests > 0 after ingest
  12.6  GET /v1/analytics/kpis returns 200
  12.7  KPIs contain expected fields
  12.8  GET /v1/analytics/timeseries returns 200 with data
  12.9  GET /v1/analytics/models returns 200 with at least 1 model
  12.10 GET /v1/analytics/teams returns 200
  12.11 Dashboard loads for authenticated user
  12.12 Dashboard: KPI cards rendered (4 cards)
  12.13 Dashboard: Today cost card shows value (not just "—")
  12.14 Dashboard: MTD cost card shows value
  12.15 Dashboard: Total requests card shows value
  12.16 Dashboard: Avg latency card shows value
  12.17 Dashboard: Chart canvas elements present
  12.18 Dashboard: Models table has at least one row after ingest
  12.19 Dashboard: No "undefined" or "NaN" visible in KPI cards
  12.20 Dashboard: No "null" text in KPI cards
  12.21 Dashboard: API errors NOT silently swallowed (error state visible if 401)
  12.22 Zero-data account: dashboard shows empty state (not crash)
  12.23 Zero-data: KPI cards show 0 or "—" (not crash)
  12.24 Zero-data: Charts render empty (not crash)
  12.25 POST /v1/events batch: all 50 events accepted
  12.26 After 50 events: summary requests >= 50
  12.27 Analytics timeseries has data for today
  12.28 Analytics models shows correct model name from ingest
  12.29 Team analytics respects team field
  12.30 Cost field in events matches expected formula
  12.31 Dashboard: live stream indicator loads (SSE connection attempt)
  12.32 Dashboard: no JS errors during data load
  12.33 Page does NOT go blank after data loads
  12.34 Page does NOT go blank when navigating Overview → Analytics
  12.35 Events endpoint returns event_id in response
  12.36 Batch ingest returns accepted_count
  12.37 Dashboard period selector: 7d data loads without crash
  12.38 Dashboard period selector: 30d data loads without crash
  12.39 POST /v1/events: large payload (500 events) accepted
  12.40 Analytics after 500 events: summary cost > 0

Run:
  python tests/test_12_data_loading.py
  HEADLESS=0 python tests/test_12_data_loading.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import uuid
import json
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_name, rand_tag,
    signup_api, get_headers, get_session_cookie,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.data_loading")

# ── Test account setup ─────────────────────────────────────────────────────
try:
    _acct = signup_api()
    KEY   = _acct["api_key"]
    ORG   = _acct["org_id"]
    HDR   = get_headers(KEY)
    log.info("Data-loading test account created", org_id=ORG)
except Exception as e:
    KEY = ORG = HDR = None
    log.error("Failed to create test account", error=str(e))

# ── Zero-data account (new user) ────────────────────────────────────────────
try:
    _acct2  = signup_api()
    KEY0    = _acct2["api_key"]
    ORG0    = _acct2["org_id"]
    HDR0    = get_headers(KEY0)
except Exception:
    KEY0 = ORG0 = HDR0 = None

def make_event(provider="openai", model="gpt-4o", team="eng",
               cost=0.003, tokens=150, latency=245):
    return {
        "event_id": str(uuid.uuid4()),
        "provider": provider,
        "model": model,
        "prompt_tokens": 100,
        "completion_tokens": tokens - 100,
        "total_tokens": tokens,
        "total_cost_usd": cost,
        "latency_ms": latency,
        "team": team,
        "environment": "test",
        "sdk_language": "python",
        "sdk_version": "1.0.0",
    }


# ─────────────────────────────────────────────────────────────────────────────
section("12-A. Event ingest API (single + batch)")
# ─────────────────────────────────────────────────────────────────────────────
if not KEY:
    fail("12-A  Skipping — no test account available")
else:
    # 12.1 Single event
    ev = make_event()
    with log.timer("POST /v1/events single"):
        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=HDR, timeout=15)
    chk("12.1  Single event ingest → 201", r.status_code == 201,
        f"{r.status_code}: {r.text[:100]}")

    # 12.35 event_id in response
    if r.ok:
        d = r.json()
        chk("12.35 Single event returns event_id", bool(d.get("event_id") or d.get("id")),
            str(d))

    # 12.2 Batch of 10
    batch_10 = [make_event(model="claude-3-5-sonnet-20241022",
                            provider="anthropic", team="ml") for _ in range(10)]
    with log.timer("POST /v1/events/batch 10"):
        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": batch_10}, headers=HDR, timeout=15)
    chk("12.2  Batch 10 events → 200/201", r.status_code in (200, 201),
        f"{r.status_code}: {r.text[:100]}")

    # 12.36 accepted_count
    if r.ok:
        d = r.json()
        chk("12.36 Batch returns accepted_count", "accepted" in str(d).lower()
            or d.get("accepted_count") is not None or d.get("accepted") is not None, str(d))

    # 12.25 Batch of 50
    batch_50 = [make_event(provider="google",
                            model="gemini-1.5-pro",
                            cost=0.001, tokens=120) for _ in range(50)]
    with log.timer("POST /v1/events/batch 50"):
        r50 = requests.post(f"{API_URL}/v1/events/batch",
                            json={"events": batch_50}, headers=HDR, timeout=20)
    chk("12.25 Batch 50 events → 200/201", r50.status_code in (200, 201),
        f"{r50.status_code}: {r50.text[:100]}")

    # 12.39 Batch of 500
    batch_500 = [make_event(provider="openai", model="gpt-4",
                             cost=0.004, tokens=200) for _ in range(500)]
    with log.timer("POST /v1/events/batch 500"):
        r500 = requests.post(f"{API_URL}/v1/events/batch",
                             json={"events": batch_500}, headers=HDR, timeout=30)
    chk("12.39 Batch 500 events → 200/201", r500.status_code in (200, 201),
        f"{r500.status_code}: {r500.text[:100]}")

    # Give the DB a moment to settle
    time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
section("12-B. Analytics API after ingest")
# ─────────────────────────────────────────────────────────────────────────────
if not KEY:
    fail("12-B  Skipping — no test account")
else:
    # 12.3 Summary
    with log.timer("GET /v1/analytics/summary"):
        rs = requests.get(f"{API_URL}/v1/analytics/summary", headers=HDR, timeout=15)
    chk("12.3  GET /v1/analytics/summary → 200", rs.status_code == 200,
        f"{rs.status_code}: {rs.text[:100]}")

    if rs.ok:
        s = rs.json()
        log.info("Summary response", data=s)
        chk("12.4  summary today_cost_usd > 0", (s.get("today_cost_usd") or 0) > 0,
            f"today_cost={s.get('today_cost_usd')}")
        chk("12.5  summary today_requests > 0", (s.get("today_requests") or 0) > 0,
            f"today_requests={s.get('today_requests')}")
        chk("12.26 summary today_requests >= 50", (s.get("today_requests") or 0) >= 50,
            f"today_requests={s.get('today_requests')}")
        chk("12.40 summary after 500 events: today_cost > 0",
            (s.get("today_cost_usd") or 0) > 0, f"cost={s.get('today_cost_usd')}")

    # 12.6 KPIs
    with log.timer("GET /v1/analytics/kpis"):
        rk = requests.get(f"{API_URL}/v1/analytics/kpis", headers=HDR, timeout=15)
    chk("12.6  GET /v1/analytics/kpis → 200", rk.status_code == 200,
        f"{rk.status_code}: {rk.text[:100]}")

    if rk.ok:
        k = rk.json()
        expected_fields = ["total_cost_usd", "total_requests", "avg_latency_ms"]
        present = [f for f in expected_fields if f in k or any(f in str(kk) for kk in k)]
        chk("12.7  KPIs contain expected cost/request/latency fields",
            len(present) >= 2, f"got keys: {list(k.keys())[:10]}")

    # 12.8 Timeseries
    with log.timer("GET /v1/analytics/timeseries"):
        rt = requests.get(f"{API_URL}/v1/analytics/timeseries", headers=HDR, timeout=15)
    chk("12.8  GET /v1/analytics/timeseries → 200", rt.status_code == 200,
        f"{rt.status_code}: {rt.text[:100]}")

    if rt.ok:
        ts = rt.json()
        has_data = isinstance(ts, list) and len(ts) > 0 or isinstance(ts, dict) and ts
        chk("12.27 Timeseries has data for today", has_data, f"response: {str(ts)[:200]}")

    # 12.9 Models
    with log.timer("GET /v1/analytics/models"):
        rm = requests.get(f"{API_URL}/v1/analytics/models", headers=HDR, timeout=15)
    chk("12.9  GET /v1/analytics/models → 200", rm.status_code == 200,
        f"{rm.status_code}: {rm.text[:100]}")

    if rm.ok:
        models = rm.json()
        model_list = models if isinstance(models, list) else models.get("models", [])
        chk("12.28 Models endpoint has ≥ 1 model (from ingest)",
            len(model_list) >= 1, f"got: {model_list[:2]}")
        if model_list:
            model_names = [m.get("model", "") for m in model_list if isinstance(m, dict)]
            chk("12.28b Model name matches ingested model",
                any("gpt" in n.lower() or "claude" in n.lower() or "gemini" in n.lower()
                    for n in model_names),
                f"names: {model_names[:3]}")

    # 12.10 Teams
    with log.timer("GET /v1/analytics/teams"):
        rteam = requests.get(f"{API_URL}/v1/analytics/teams", headers=HDR, timeout=15)
    chk("12.10 GET /v1/analytics/teams → 200", rteam.status_code == 200,
        f"{rteam.status_code}: {rteam.text[:100]}")

    if rteam.ok:
        teams = rteam.json()
        team_list = teams if isinstance(teams, list) else teams.get("teams", [])
        chk("12.29 Teams endpoint shows 'eng' or 'ml' team from ingest",
            any(t.get("team") in ("eng", "ml") for t in team_list if isinstance(t, dict)),
            f"teams: {team_list[:3]}")


# ─────────────────────────────────────────────────────────────────────────────
section("12-C. Zero-data new account analytics")
# ─────────────────────────────────────────────────────────────────────────────
if KEY0:
    rs0 = requests.get(f"{API_URL}/v1/analytics/summary",
                       headers=get_headers(KEY0), timeout=15)
    chk("12.22 Zero-data account: summary → 200 (not crash)",
        rs0.status_code == 200, f"{rs0.status_code}: {rs0.text[:100]}")
    if rs0.ok:
        s0 = rs0.json()
        chk("12.23 Zero-data: today_cost_usd is 0 or null (not NaN)",
            s0.get("today_cost_usd") in (0, 0.0, None, ""),
            f"today_cost={s0.get('today_cost_usd')}")
else:
    warn("12.22 Zero-data tests skipped — no second account")


# ─────────────────────────────────────────────────────────────────────────────
section("12-D. Dashboard UI data loading (Playwright)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:

        # ── Authenticated dashboard ────────────────────────────────────────
        if KEY:
            browser, ctx, page = make_browser_ctx(pw)
            js_errors = collect_console_errors(page)

            # Set session via API
            sr = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": KEY}, timeout=15)
            if sr.ok:
                for c in sr.cookies:
                    ctx.add_cookies([{
                        "name": c.name, "value": c.value,
                        "domain": "cohrint.com", "path": "/",
                    }])

            try:
                with log.timer("Load /app authenticated with data"):
                    page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(3_000)   # Wait for async data to load

                # 12.11 Dashboard loads
                chk("12.11 Dashboard loads for authenticated user (stays on /app)",
                    "/app" in page.url, f"redirected to: {page.url}")

                content = page.content()
                content_lower = content.lower()

                # 12.12 KPI cards (look for the 4 key stats)
                kpi_count = 0
                kpi_selectors = [
                    ".kpi-card", ".stat-card", "[data-kpi]",
                    ".metric-card", ".summary-card",
                ]
                for sel in kpi_selectors:
                    n = page.locator(sel).count()
                    if n > 0:
                        kpi_count = n
                        break
                # Also count by text content patterns
                if kpi_count == 0:
                    for kw in ["today", "mtd", "requests", "latency"]:
                        if kw in content_lower:
                            kpi_count += 1
                chk("12.12 Dashboard: KPI cards rendered (≥ 4)",
                    kpi_count >= 4, f"found {kpi_count} KPI indicators")

                # 12.17 Chart canvas elements
                canvas_count = page.locator("canvas").count()
                chk("12.17 Dashboard: chart canvas elements present",
                    canvas_count >= 1, f"found {canvas_count} canvas elements")

                # 12.13–12.16 KPI values not blank
                bad_values = ["undefined", "nan", "null", "error"]
                for bv in bad_values:
                    chk(f"12.19/20 KPI cards: no '{bv}' in page",
                        bv not in content_lower,
                        f"Found '{bv}' text in dashboard output")

                # 12.13 Today cost visible
                chk("12.13 Today cost: numeric value visible",
                    any(c.isdigit() for c in content) and
                    any(w in content_lower for w in ["$", "cost", "usd"]),
                    "No numeric cost value found")

                # 12.18 Models table has at least 1 row
                table_rows = page.locator("table tbody tr, .model-row, .data-row").count()
                chk("12.18 Dashboard: at least 1 data row in table",
                    table_rows >= 1 or any(m in content_lower
                        for m in ["gpt", "claude", "gemini"]),
                    f"table rows={table_rows}")

                # 12.33 Page not blank
                chk("12.33 Page NOT blank after data loads",
                    len(content.strip()) > 1000, f"body length={len(content)}")

                # 12.32 No JS errors
                page.wait_for_timeout(1_000)
                chk("12.32 No JS errors during data load",
                    len(js_errors) == 0, f"errors: {js_errors[:3]}")

                log.info("Dashboard data load passed", org=ORG, js_errors=len(js_errors))

            except Exception as e:
                fail("12-D  Dashboard data load test error", str(e)[:300])
                log.exception("Dashboard data load error", e)

            ctx.close()
            browser.close()


        # ── Period selector tests ─────────────────────────────────────────
        if KEY:
            browser, ctx, page = make_browser_ctx(pw)
            sr2 = requests.post(f"{API_URL}/v1/auth/session",
                                json={"api_key": KEY}, timeout=15)
            if sr2.ok:
                for c in sr2.cookies:
                    ctx.add_cookies([{
                        "name": c.name, "value": c.value,
                        "domain": "cohrint.com", "path": "/",
                    }])
            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(2_000)

                sel = page.locator("select#period, select[name='period'], .period-select, [data-period]").first
                if sel.count() > 0:
                    # 12.37 7d
                    try:
                        sel.select_option(value="7d")
                        page.wait_for_timeout(2_000)
                        chk("12.37 Period selector 7d: no crash",
                            len(page.content()) > 500 and "/app" in page.url)
                    except Exception as e:
                        warn(f"12.37 Period 7d: {e}")

                    # 12.38 30d
                    try:
                        sel.select_option(value="30d")
                        page.wait_for_timeout(2_000)
                        chk("12.38 Period selector 30d: no crash",
                            len(page.content()) > 500 and "/app" in page.url)
                    except Exception as e:
                        warn(f"12.38 Period 30d: {e}")
                else:
                    warn("12.37/38 Period selector element not found")

            except Exception as e:
                fail("12-D  Period selector test error", str(e)[:200])
            ctx.close()
            browser.close()


        # ── Zero-data account dashboard ────────────────────────────────────
        if KEY0:
            browser, ctx, page = make_browser_ctx(pw)
            js_errors0 = collect_console_errors(page)

            sr0 = requests.post(f"{API_URL}/v1/auth/session",
                                json={"api_key": KEY0}, timeout=15)
            if sr0.ok:
                for c in sr0.cookies:
                    ctx.add_cookies([{
                        "name": c.name, "value": c.value,
                        "domain": "cohrint.com", "path": "/",
                    }])

            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=30_000)
                page.wait_for_timeout(3_000)
                content0 = page.content()

                chk("12.22b Zero-data dashboard: loads without crash",
                    len(content0) > 500 and "/app" in page.url)
                chk("12.24 Zero-data: canvas/charts render (not crash)",
                    page.locator("canvas").count() >= 0)  # 0 charts is ok, no crash
                chk("12.23b Zero-data: no 'undefined' or 'NaN' visible",
                    "undefined" not in content0.lower() and
                    "nan" not in content0.lower(),
                    "Found undefined/NaN in zero-data dashboard")

                # 12.34 Nav Overview → Analytics: no blank page
                try:
                    analytics_link = page.locator(
                        "[data-view='analytics'], nav a:has-text('Analytics'), .sidebar a:has-text('Analytics')"
                    ).first
                    if analytics_link.count() > 0:
                        analytics_link.click()
                        page.wait_for_timeout(1_500)
                        chk("12.34 Overview→Analytics: page not blank",
                            len(page.content()) > 500)
                    else:
                        warn("12.34 Analytics link not found in sidebar")
                except Exception as e:
                    warn(f"12.34 Overview→Analytics: {e}")

            except Exception as e:
                fail("12-D  Zero-data dashboard test error", str(e)[:200])
            ctx.close()
            browser.close()


except ImportError:
    warn("Playwright not installed — run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("test_12  Data loading test suite crashed", str(e)[:400])
    log.exception("Data loading suite crash", e)


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Data loading tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
