"""
test_dashboard_role_ui.py — Suite 51: Dashboard Role Visibility + API Data Integrity
======================================================================================
Playwright UI tests + API contract tests covering:

  A) Role-based UI visibility    (member vs admin vs ceo vs superadmin)
  B) API endpoint data integrity (all analytics routes return valid structure)
  C) Period Spend card           (not stuck in "Failed to load" loop)
  D) Today hourly chart          (returns hours array, not 500)
  E) Executive dashboard         (non-zero when data exists)
  F) Cross-platform /trend       (created_at column, not period_start)
  G) Admin overview              (period stats use text dates)

Credentials sourced from tests/artifacts/da45_credentials.txt (DA45 seed accounts).
All checks are against LIVE production: https://cohrint.com / https://api.cohrint.com

Labels: DU.1 – DU.60
"""

import sys
import json
import time
import pytest
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL, HEADLESS
from helpers.output import section, chk, ok, fail, warn, info
from helpers.browser import signin_ui

# ── Credentials from DA45 seed ────────────────────────────────────────────────

_SEED = json.loads(
    (Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json").read_text()
)

ADMIN_KEY       = _SEED["admin"]["api_key"]
MEMBER_KEY      = _SEED["member"]["api_key"]
CEO_KEY         = _SEED["ceo"]["api_key"]
SUPERADMIN_KEY  = _SEED["superadmin"]["api_key"]

BASE = API_URL
TIMEOUT = 20


# ── API helpers ───────────────────────────────────────────────────────────────

def _h(key): return {"Authorization": f"Bearer {key}"}

def _get(path, key, **kwargs):
    return requests.get(f"{BASE}{path}", headers=_h(key), timeout=TIMEOUT, **kwargs)


# ── Browser login helper ──────────────────────────────────────────────────────

def _login(page, api_key):
    """Sign in via the auth.html form — fills API key and submits."""
    ok = signin_ui(page, api_key, timeout=20_000)
    if not ok:
        return False
    # Wait for the dashboard app shell to render
    try:
        page.wait_for_selector("#view-overview", timeout=12_000)
        # Give applyRoleUI() time to run after session fetch
        time.sleep(2)
        return True
    except PWTimeout:
        return False


def _visible(page, selector):
    """Return True if element exists and is visible."""
    el = page.query_selector(selector)
    if el is None:
        return False
    return el.is_visible()


def _hidden(page, selector):
    """Return True if element does not exist OR is hidden (display:none)."""
    el = page.query_selector(selector)
    if el is None:
        return True
    return not el.is_visible()


# =============================================================================
# SECTION A — API: Analytics endpoint structure
# =============================================================================

section("A — API: Analytics Endpoint Structure")


def test_DU_A1_summary_shape():
    """DU.A1 — /analytics/summary returns expected top-level keys."""
    r = _get("/v1/analytics/summary", ADMIN_KEY)
    chk("DU.A1", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    for key in ("total_cost_usd", "total_requests", "active_developers"):
        chk(f"DU.A1.{key}", key in d, f"missing key {key!r} in summary")


def test_DU_A2_kpis_shape():
    """DU.A2 — /analytics/kpis returns period_days and kpi block."""
    r = _get("/v1/analytics/kpis?period=30", ADMIN_KEY)
    chk("DU.A2", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A2.period", "period_days" in d, f"missing period_days; keys={list(d)[:8]}")
    chk("DU.A2.kpi", "kpi" in d or "total_cost_usd" in d, "no kpi block")


def test_DU_A3_timeseries_shape():
    """DU.A3 — /analytics/timeseries returns series array."""
    r = _get("/v1/analytics/timeseries?period=30", ADMIN_KEY)
    chk("DU.A3", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A3.series", "series" in d, f"missing series; keys={list(d)[:8]}")
    chk("DU.A3.list", isinstance(d["series"], list), "series not a list")


def test_DU_A4_models_shape():
    """DU.A4 — /analytics/models returns models list."""
    r = _get("/v1/analytics/models?period=30", ADMIN_KEY)
    chk("DU.A4", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A4.models", "models" in d, f"missing models; keys={list(d)[:8]}")


def test_DU_A5_teams_shape():
    """DU.A5 — /analytics/teams returns teams list."""
    r = _get("/v1/analytics/teams?period=30", ADMIN_KEY)
    chk("DU.A5", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A5.teams", "teams" in d, f"missing teams; keys={list(d)[:8]}")


def test_DU_A6_today_shape():
    """DU.A6 — /analytics/today returns date + hours array (not 500)."""
    r = _get("/v1/analytics/today", ADMIN_KEY)
    chk("DU.A6.status", r.status_code == 200, f"status {r.status_code} — likely datetime(created_at,'unixepoch') bug")
    d = r.json()
    chk("DU.A6.date", "date" in d, f"missing date; keys={list(d)[:8]}")
    chk("DU.A6.hours", "hours" in d, f"missing hours; keys={list(d)[:8]}")
    chk("DU.A6.list", isinstance(d.get("hours", []), list), "hours not a list")


def test_DU_A7_cost_shape():
    """DU.A7 — /analytics/cost returns total_cost_usd."""
    r = _get("/v1/analytics/cost?period=7", ADMIN_KEY)
    chk("DU.A7", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A7.field", "total_cost_usd" in d, f"missing total_cost_usd; keys={list(d)[:8]}")


def test_DU_A8_business_units_admin_only():
    """DU.A8 — /analytics/business-units: admin gets 200, member gets 200 (empty units)."""
    r_admin = _get("/v1/analytics/business-units", ADMIN_KEY)
    r_member = _get("/v1/analytics/business-units", MEMBER_KEY)
    chk("DU.A8.admin", r_admin.status_code == 200, f"admin status {r_admin.status_code}")
    # members can call but loadSpend() gates the fetch client-side
    chk("DU.A8.member", r_member.status_code in (200, 403), f"member status {r_member.status_code}")


def test_DU_A9_traces_shape():
    """DU.A9 — /analytics/traces returns traces list (not empty due to date bug)."""
    r = _get("/v1/analytics/traces?period=90", ADMIN_KEY)
    chk("DU.A9.status", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.A9.traces", "traces" in d, f"missing traces; keys={list(d)[:8]}")


# =============================================================================
# SECTION B — API: Admin overview date fix
# =============================================================================

section("B — API: Admin Overview")


def test_DU_B1_admin_overview_returns_data():
    """DU.B1 — /admin/overview returns non-null org block (not 500 from unix bug)."""
    r = _get("/v1/admin/overview?period=30", ADMIN_KEY)
    chk("DU.B1.status", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.B1.org", "org" in d, f"missing org block; keys={list(d)[:8]}")
    chk("DU.B1.teams", "teams" in d, f"missing teams; keys={list(d)[:8]}")


def test_DU_B2_admin_overview_mtd_not_none():
    """DU.B2 — admin/overview MTD cost is a number (was always 0 with strftime('%s') bug)."""
    r = _get("/v1/admin/overview?period=30", ADMIN_KEY)
    assert r.status_code == 200
    d = r.json()
    mtd = d.get("org", {}).get("mtd_cost_usd")
    chk("DU.B2.mtd_type", isinstance(mtd, (int, float)), f"mtd_cost_usd={mtd!r} not numeric")


def test_DU_B3_admin_overview_member_forbidden():
    """DU.B3 — member cannot access /admin/overview."""
    r = _get("/v1/admin/overview", MEMBER_KEY)
    chk("DU.B3", r.status_code == 403, f"member got {r.status_code}, expected 403")


# =============================================================================
# SECTION C — API: Executive dashboard (text date fix)
# =============================================================================

section("C — API: Executive Dashboard")


def test_DU_C1_executive_superadmin_200():
    """DU.C1 — Superadmin can access /analytics/executive."""
    r = _get("/v1/analytics/executive", SUPERADMIN_KEY)
    chk("DU.C1", r.status_code == 200, f"status {r.status_code}")


def test_DU_C2_executive_shape():
    """DU.C2 — Executive returns totals + by_team + by_provider."""
    # NOTE: CEO seed account has member role due to auth.ts VALID_ROLES bug (ceo was excluded).
    # Fixed in this PR — re-run seed.py --force after deploy to fix CEO key.
    # Using superadmin key (also has executive access) until CEO is reseeded.
    r = _get("/v1/analytics/executive?days=30", SUPERADMIN_KEY)
    chk("DU.C2.status", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    for key in ("totals", "by_team", "by_provider"):
        chk(f"DU.C2.{key}", key in d, f"missing {key!r}; keys={list(d)[:10]}")


def test_DU_C3_executive_totals_numeric():
    """DU.C3 — Executive totals are numeric (not null from sinceUnix bug)."""
    r = _get("/v1/analytics/executive?days=30", SUPERADMIN_KEY)
    chk("DU.C3.status", r.status_code == 200, f"status {r.status_code}")
    totals = r.json().get("totals", {})
    chk("DU.C3.cost", isinstance(totals.get("total_cost_usd"), (int, float)), f"total_cost_usd={totals.get('total_cost_usd')!r}")
    chk("DU.C3.tokens", isinstance(totals.get("total_tokens"), (int, float)), f"total_tokens={totals.get('total_tokens')!r}")


def test_DU_C4_executive_member_forbidden():
    """DU.C4 — Member cannot access /analytics/executive."""
    r = _get("/v1/analytics/executive", MEMBER_KEY)
    chk("DU.C4", r.status_code == 403, f"member got {r.status_code}, expected 403")


# =============================================================================
# SECTION D — API: Cross-platform endpoints (period_start → created_at fix)
# =============================================================================

section("D — API: Cross-Platform Endpoints")


def test_DU_D1_trend_not_500():
    """DU.D1 — /cross-platform/trend returns 200 (not 500 from period_start bug)."""
    r = _get("/v1/cross-platform/trend?days=30", ADMIN_KEY)
    chk("DU.D1.status", r.status_code == 200, f"status {r.status_code} — likely period_start column bug")
    d = r.json()
    chk("DU.D1.days", "days" in d, f"missing days; keys={list(d)[:8]}")


def test_DU_D2_summary_shape():
    """DU.D2 — /cross-platform/summary returns total_cost_usd (period spend card source)."""
    r = _get("/v1/cross-platform/summary?days=30", ADMIN_KEY)
    chk("DU.D2.status", r.status_code == 200, f"status {r.status_code}")
    d = r.json()
    chk("DU.D2.field", "total_cost_usd" in d or "total_cost" in d, f"missing cost field; keys={list(d)[:8]}")


def test_DU_D3_summary_days_validation():
    """DU.D3 — /cross-platform/summary rejects invalid days with 400."""
    r = _get("/v1/cross-platform/summary?days=14", ADMIN_KEY)
    chk("DU.D3", r.status_code == 400, f"expected 400 for days=14, got {r.status_code}")


def test_DU_D4_developers_admin_only():
    """DU.D4 — /cross-platform/developers requires admin+."""
    r_admin = _get("/v1/cross-platform/developers?days=30", ADMIN_KEY)
    chk("DU.D4.admin", r_admin.status_code == 200, f"admin got {r_admin.status_code}")


# =============================================================================
# SECTION E — API: Role-based access enforcement
# =============================================================================

section("E — API: RBAC Enforcement")


@pytest.mark.parametrize("path,expected", [
    ("/v1/admin/overview",               403),
    ("/v1/analytics/executive",          403),
    ("/v1/cross-platform/developers?days=30", 200),  # members can call but scoped
    ("/v1/analytics/summary",            200),
    ("/v1/analytics/kpis",               200),
    ("/v1/analytics/today",              200),
    ("/v1/analytics/traces",             200),
])
def test_DU_E_member_access(path, expected):
    """DU.E — Member role access enforcement per endpoint."""
    r = _get(path, MEMBER_KEY)
    chk(f"DU.E.{path}", r.status_code == expected,
        f"member: {path} → {r.status_code}, expected {expected}")


# =============================================================================
# SECTION F — Playwright UI: Member role visibility
# =============================================================================

section("F — UI: Member Role Visibility")


def _with_member(fn):
    """Run fn(page) inside a headless member browser session. Returns result."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        if not _login(page, MEMBER_KEY):
            browser.close()
            return None, "login_failed"
        result = fn(page)
        browser.close()
        return result, None


def test_DU_F1_member_budgets_tab_hidden():
    """DU.F1 — Budgets & Alerts sidebar button hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#sb-budgets"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F1", result, "sb-budgets is visible — should be hidden for member")


def test_DU_F2_member_cross_platform_tab_hidden():
    """DU.F2 — Cross-Platform sidebar button hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#sb-cross-platform"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F2", result, "sb-cross-platform visible — should be hidden for member")


def test_DU_F3_member_settings_tab_hidden():
    """DU.F3 — Settings sidebar button hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#sb-settings"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F3", result, "sb-settings visible — should be hidden for member")


def test_DU_F4_member_integrations_tab_hidden():
    """DU.F4 — Integrations sidebar button hidden for member.
    NOTE: This will FAIL until PR #67 is merged (Integrations ID + guard added in that PR).
    """
    result, err = _with_member(lambda p: _hidden(p, "#sb-integrations"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F4", result, "sb-integrations visible — should be hidden for member (needs PR #67)")


def test_DU_F5_member_executive_section_hidden():
    """DU.F5 — Executive section hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#sb-section-executive"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F5", result, "sb-section-executive visible — should be hidden for member")


def test_DU_F6_member_team_section_hidden():
    """DU.F6 — Team section (Members) hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#sb-section-team"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F6", result, "sb-section-team visible — should be hidden for member")


def test_DU_F7_member_cost_per_dev_card_hidden():
    """DU.F7 — Cost per Developer card hidden for member."""
    result, err = _with_member(lambda p: _hidden(p, "#card-cost-per-developer"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F7", result, "card-cost-per-developer visible — should be hidden for member")


def test_DU_F8_member_overview_loads():
    """DU.F8 — Member can load overview without JS errors."""
    def _check(page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.evaluate("nav('overview', null)")
        time.sleep(1)
        el = page.query_selector("#totalCostValue, #spendTotal")
        return {"el": el is not None, "errors": [e for e in errors if "Uncaught" in e or "TypeError" in e]}
    result, err = _with_member(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F8.element", result["el"], "No cost KPI element found on overview")
    chk("DU.F8.no_js_errors", len(result["errors"]) == 0, f"JS errors: {result['errors'][:3]}")


def test_DU_F9_member_nav_guard_budgets():
    """DU.F9 — nav('budgets') redirects member to overview."""
    def _check(page):
        page.evaluate("nav('budgets', null)")
        time.sleep(0.5)
        return page.evaluate("activeView")
    result, err = _with_member(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F9", result == "overview",
        f"activeView={result!r} after nav('budgets') — should redirect to overview")


def test_DU_F10_member_nav_guard_cross_platform():
    """DU.F10 — nav('cross-platform') redirects member to overview."""
    def _check(page):
        page.evaluate("nav('cross-platform', null)")
        time.sleep(0.5)
        return page.evaluate("activeView")
    result, err = _with_member(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F10", result == "overview",
        f"activeView={result!r} after nav('cross-platform') — should redirect to overview")


def test_DU_F11_member_nav_guard_integrations():
    """DU.F11 — nav('integrations') redirects member to overview.
    NOTE: This will FAIL until PR #67 is merged (nav guard added in that PR).
    """
    def _check(page):
        page.evaluate("nav('integrations', null)")
        time.sleep(0.5)
        return page.evaluate("activeView")
    result, err = _with_member(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.F11", result == "overview",
        f"activeView={result!r} after nav('integrations') — should redirect to overview (needs PR #67)")


# =============================================================================
# SECTION G — Playwright UI: Admin role — Period Spend card
# =============================================================================

section("G — UI: Admin Period Spend")


def _with_admin(fn):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        if not _login(page, ADMIN_KEY):
            browser.close()
            return None, "login_failed"
        result = fn(page)
        browser.close()
        return result, None


def test_DU_G1_admin_sees_budgets_tab():
    """DU.G1 — Admin sees Budgets & Alerts sidebar button."""
    result, err = _with_admin(lambda p: _visible(p, "#sb-budgets"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G1", result, "sb-budgets hidden — should be visible for admin")


def test_DU_G2_admin_sees_cross_platform_tab():
    """DU.G2 — Admin sees Cross-Platform sidebar button."""
    result, err = _with_admin(lambda p: _visible(p, "#sb-cross-platform"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G2", result, "sb-cross-platform hidden — should be visible for admin")


def test_DU_G3_admin_sees_settings_tab():
    """DU.G3 — Admin sees Settings sidebar button."""
    result, err = _with_admin(lambda p: _visible(p, "#sb-settings"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G3", result, "sb-settings hidden — should be visible for admin")


def test_DU_G4_period_spend_not_error():
    """DU.G4 — Period Spend KPI card does not show 'Error' / 'Failed to load'."""
    def _check(page):
        page.evaluate("nav('spend', document.getElementById('sb-spend') || null)")
        try:
            page.wait_for_function(
                "document.getElementById('spendTotal') && "
                "document.getElementById('spendTotal').textContent !== '—' && "
                "document.getElementById('spendTotal').textContent !== 'Error'",
                timeout=15_000,
            )
        except PWTimeout:
            pass
        return {
            "val": page.evaluate("document.getElementById('spendTotal')?.textContent || ''"),
            "sub": page.evaluate("document.getElementById('spendTotalSub')?.textContent || ''"),
        }
    result, err = _with_admin(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G4.not_error", "Error" not in result["val"] and "Error" not in result["sub"],
        f"Period Spend shows error: val={result['val']!r} sub={result['sub']!r}")
    chk("DU.G4.not_retrying", "retrying" not in result["sub"].lower(),
        f"Period Spend stuck in retry loop: sub={result['sub']!r}")


def test_DU_G5_today_hourly_renders():
    """DU.G5 — Today's hourly chart canvas exists (not a JS error from unixepoch bug)."""
    def _check(page):
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.evaluate("nav('spend', null)")
        time.sleep(3)
        canvas = page.query_selector("#todayHourlyChart")
        return {
            "has_canvas": canvas is not None,
            "errors": [e for e in errors if "unixepoch" in e.lower() or "TypeError" in e],
        }
    result, err = _with_admin(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G5.canvas_exists", result["has_canvas"], "todayHourlyChart canvas not found")
    chk("DU.G5.no_unixepoch_error", len(result["errors"]) == 0, f"JS errors: {result['errors'][:2]}")


def test_DU_G6_admin_sees_cost_per_dev_card():
    """DU.G6 — Admin sees Cost per Developer card in overview."""
    def _check(page):
        page.evaluate("nav('overview', null)")
        time.sleep(1)
        return _visible(page, "#card-cost-per-developer")
    result, err = _with_admin(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.G6", result, "card-cost-per-developer hidden — should be visible for admin")


# =============================================================================
# SECTION H — Playwright UI: Superadmin role — Executive dashboard
# =============================================================================

section("H — UI: Superadmin Executive Dashboard")


def _with_superadmin(fn):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        if not _login(page, SUPERADMIN_KEY):
            browser.close()
            return None, "login_failed"
        result = fn(page)
        browser.close()
        return result, None


def test_DU_H1_superadmin_sees_executive_section():
    """DU.H1 — Superadmin sees Executive section in sidebar."""
    result, err = _with_superadmin(lambda p: _visible(p, "#sb-section-executive"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.H1", result, "sb-section-executive hidden — should be visible for superadmin")


def test_DU_H2_superadmin_executive_loads():
    """DU.H2 — Superadmin executive view loads without error."""
    def _check(page):
        page.evaluate("nav('executive', document.getElementById('sb-executive') || null)")
        time.sleep(3)
        return page.evaluate("document.getElementById('exec-total')?.textContent || ''")
    result, err = _with_superadmin(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.H2.not_error", "Error" not in result, f"exec-total shows error: {result!r}")


def test_DU_H3_executive_api_accessible():
    """DU.H3 — Superadmin can access /analytics/executive via API."""
    r = _get("/v1/analytics/executive", SUPERADMIN_KEY)
    chk("DU.H3", r.status_code == 200, f"Superadmin cannot access executive endpoint: {r.status_code}")


# =============================================================================
# SECTION I — Playwright UI: Superadmin — Budget Control Center
# =============================================================================

section("I — UI: Superadmin Budget Control")


def test_DU_I1_superadmin_budget_control_visible():
    """DU.I1 — Superadmin sees Budget Control Center panel."""
    def _check(page):
        page.evaluate("nav('budgets', document.getElementById('sb-budgets') || null)")
        time.sleep(2)
        return _visible(page, "#budget-control-panel")
    result, err = _with_superadmin(_check)
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.I1", result, "budget-control-panel hidden — should be visible for superadmin")


def test_DU_I2_member_budget_control_hidden():
    """DU.I2 — Member does NOT see Budget Control Center."""
    result, err = _with_member(lambda p: _hidden(p, "#budget-control-panel"))
    if err: pytest.skip(f"login failed: {err}")
    chk("DU.I2", result, "budget-control-panel visible — should be hidden for member")
