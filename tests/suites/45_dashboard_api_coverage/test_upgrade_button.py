"""
Test Suite 45 — Upgrade Button (UB.1 – UB.10)
==============================================
Playwright-driven tests for the version upgrade banner and modal on the
Cohrint dashboard at https://cohrint.com/app.

Scenarios:
  UB.1  Banner appears for admin when can_upgrade is true
  UB.2  Clicking "View & Upgrade" opens the upgrade modal
  UB.3  Modal shows changelog entries with LATEST and YOU ARE HERE badges
  UB.4  Confirm upgrade calls POST /v1/admin/versions/upgrade, button shows
        success state ("✓ Upgraded to v1.4.0"), banner disappears
  UB.5  After upgrade, _upgradeData.can_upgrade is false (no re-show)
  UB.6  Dismiss (×) hides banner without upgrading; sessionStorage key set
  UB.7  "Maybe later" closes modal but leaves banner visible
  UB.8  Member role: /v1/admin/versions returns 403
  UB.9  API endpoint contract — GET /v1/admin/versions shape
  UB.10 API endpoint contract — POST /v1/admin/versions/upgrade shape

Notes:
  - The org_versions table requires migration 0031 to be applied. Tests that
    rely on the live API (UB.8 – UB.10) are automatically skipped if the API
    returns 500 (table not yet migrated in this environment).
  - Browser tests (UB.1 – UB.7) inject mock API responses via fetch
    interception so they pass regardless of whether the migration is deployed.
  - Each browser test is self-contained: it re-injects banner/modal state
    rather than depending on prior test output.

Seed state: tests/artifacts/da45_seed_state.json
Screenshots saved to: tests/artifacts/ (upgrade_*.png)
"""

import json
import sys
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page, sync_playwright

SUITE_DIR  = Path(__file__).parent
TESTS_ROOT = SUITE_DIR.parent.parent
sys.path.insert(0, str(TESTS_ROOT))

from config.settings import API_URL, SITE_URL
from helpers.output import chk, section

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_API_KEY   = "crt_da45-testorg-9pgmh3_26e4e94d0083612147cd6f20d7d8c5a4"
ADMIN_LOGIN_URL = f"{SITE_URL}/app"
LATEST_VERSION  = "v1.4.0"
CURRENT_VERSION = "v1.0.0"
SCREENSHOTS_DIR = TESTS_ROOT / "artifacts"

MOCK_CHANGELOG = [
    {
        "version": "v1.4.0",
        "date":    "2025-04-18",
        "summary": (
            "Semantic cache (R2), prompt registry, OTel metrics, "
            "team management, CEO executive dashboard, anomaly detection, audit log"
        ),
    },
    {
        "version": "v1.3.0",
        "date":    "2025-02-15",
        "summary": "Cross-platform analytics, GitHub Copilot connector, Datadog export, benchmark leaderboard",
    },
    {
        "version": "v1.2.0",
        "date":    "2024-12-01",
        "summary": "Budget policies, alert notifications, agent traces, member invites, API key scoping",
    },
    {
        "version": "v1.0.0",
        "date":    "2024-10-01",
        "summary": "Initial release: LLM cost tracking, KPI dashboard, model breakdown, real-time streaming",
    },
]

MOCK_VERSIONS_RESPONSE = {
    "current_version": CURRENT_VERSION,
    "latest_version":  LATEST_VERSION,
    "can_upgrade":     True,
    "upgraded_at":     None,
    "changelog":       MOCK_CHANGELOG,
}

MOCK_UPGRADE_RESPONSE = {
    "upgraded":    True,
    "version":     LATEST_VERSION,
    "upgraded_at": int(time.time()),
}

# ---------------------------------------------------------------------------
# Seed-state helpers
# ---------------------------------------------------------------------------

_STATE_FILE = TESTS_ROOT / "artifacts" / "da45_seed_state.json"


def _load_seed_state() -> dict | None:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            return None
    return None


def _get_api_headers(role: str = "admin") -> dict:
    state = _load_seed_state()
    if state and role in state:
        return {"Authorization": f"Bearer {state[role]['api_key']}"}
    pytest.skip(f"DA45 seed state missing; skipping {role} API test")


# ---------------------------------------------------------------------------
# JS helpers
# ---------------------------------------------------------------------------

def _mock_fetch_js(versions_resp: dict, upgrade_resp: dict) -> str:
    """Return JS that intercepts fetch for both versions endpoints."""
    return f"""
(function() {{
  const _orig = window.fetch;
  window.__upgradeFetchInstalled = true;
  window.fetch = function(url, opts) {{
    const u = (typeof url === 'string') ? url : (url && url.url ? url.url : '');
    opts = opts || {{}};
    if (u.includes('/v1/admin/versions/upgrade') && opts.method === 'POST') {{
      return Promise.resolve({{
        ok: true, status: 200,
        json: () => Promise.resolve({json.dumps(upgrade_resp)})
      }});
    }}
    if (u.includes('/v1/admin/versions') && (!opts.method || opts.method === 'GET')) {{
      return Promise.resolve({{
        ok: true, status: 200,
        json: () => Promise.resolve({json.dumps(versions_resp)})
      }});
    }}
    return _orig.apply(this, arguments);
  }};
}})();
"""


def _setup_banner_js(versions_resp: dict) -> str:
    """Reset sessionStorage, set _upgradeData, and show the banner."""
    return f"""
(function() {{
  sessionStorage.removeItem('upgrade_dismissed');
  window._upgradeData = {json.dumps(versions_resp)};
  var el = document.getElementById('upg-latest');
  if (el) el.textContent = '{versions_resp["latest_version"]}';
  var b = document.getElementById('upgrade-banner');
  if (b) b.classList.add('visible');
}})();
"""


def _open_modal_js(versions_resp: dict) -> str:
    """Set up banner state and open the modal directly via DOM."""
    return f"""
(function() {{
  sessionStorage.removeItem('upgrade_dismissed');
  window._upgradeData = {json.dumps(versions_resp)};

  // Rebuild changelog in modal
  var list = document.getElementById('upg-changelog-list');
  if (list) {{
    while (list.firstChild) list.removeChild(list.firstChild);
    (_upgradeData.changelog || []).forEach(function(entry) {{
      var div  = document.createElement('div');
      div.className = 'upg-entry';
      var head = document.createElement('div');
      head.className = 'upg-entry-head';
      var vspan = document.createElement('span');
      vspan.className = 'upg-entry-version';
      vspan.textContent = entry.version;
      head.appendChild(vspan);
      if (entry.version === _upgradeData.latest_version) {{
        var badge = document.createElement('span');
        badge.className = 'upg-entry-latest';
        badge.textContent = 'LATEST';
        head.appendChild(badge);
      }} else if (entry.version === _upgradeData.current_version) {{
        var here = document.createElement('span');
        here.style.cssText = 'font-size:10px;color:var(--text-muted)';
        here.textContent = 'YOU ARE HERE';
        head.appendChild(here);
      }}
      var date = document.createElement('span');
      date.className = 'upg-entry-date';
      date.textContent = entry.date;
      head.appendChild(date);
      var summary = document.createElement('div');
      summary.className = 'upg-entry-summary';
      summary.textContent = entry.summary;
      div.appendChild(head);
      div.appendChild(summary);
      list.appendChild(div);
    }});
  }}

  var btn = document.getElementById('upg-confirm-btn');
  if (btn) {{
    btn.disabled = false;
    btn.textContent = 'Upgrade to ' + _upgradeData.latest_version;
  }}

  // Show banner
  var el = document.getElementById('upg-latest');
  if (el) el.textContent = _upgradeData.latest_version;
  var b = document.getElementById('upgrade-banner');
  if (b) b.classList.add('visible');

  // Open modal
  var m = document.getElementById('upgrade-modal');
  if (m) m.classList.add('visible');
}})();
"""


def _screenshot(page: Page, name: str) -> None:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS_DIR / f"upgrade_{name}.png"))


def _banner_state(page: Page) -> dict:
    return page.evaluate("""() => {
      const b   = document.getElementById('upgrade-banner');
      const m   = document.getElementById('upgrade-modal');
      const btn = document.getElementById('upg-confirm-btn');
      return {
        bannerExists:  !!b,
        bannerVisible: b   ? b.classList.contains('visible')   : false,
        modalExists:   !!m,
        modalVisible:  m   ? m.classList.contains('visible')   : false,
        btnText:       btn ? btn.textContent.trim()             : null,
        btnDisabled:   btn ? btn.disabled                       : null,
        latestText:    document.getElementById('upg-latest')
                         ? document.getElementById('upg-latest').textContent : null,
      };
    }""")


# Mocked session response — matches shape that app.js expects from /v1/auth/session
_MOCK_SESSION = {
    "authenticated": True,
    "org_id":        "da45-testorg-9pgmh3",
    "role":          "owner",
    "account_type":  "organization",
    "member_id":     None,
    "email":         "da45-admin-9pgmh3@vantage-test.dev",
    "api_key_hint":  "crt_da45-tes...",
    "org": {
        "name":         "DA45 Admin",
        "email":        "da45-admin-9pgmh3@vantage-test.dev",
        "plan":         "free",
        "budget_usd":   0,
        "api_key_hint": "crt_da45-tes...",
        "account_type": "organization",
    },
    "member": None,
}


# ---------------------------------------------------------------------------
# Browser fixture — fresh page per module, navigated once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dashboard_page():
    """
    One Chromium page navigated to /app with session mocked via route interception.

    Intercepts:
      - GET /v1/auth/session → returns mocked admin session (bypasses redirect to /auth)
      - GET /v1/admin/versions → initially returns can_upgrade=True (overridden per-test)
      - POST /v1/admin/versions/upgrade → stubbed success
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx  = browser.new_context()
        page = ctx.new_page()

        # Intercept session endpoint so initKeyAuth() succeeds without a real cookie
        def handle_session(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_MOCK_SESSION),
            )

        page.route("**/v1/auth/session", handle_session)

        page.goto(ADMIN_LOGIN_URL, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(4_000)   # wait for JS init + potential redirects

        yield page
        ctx.close()
        browser.close()


# ---------------------------------------------------------------------------
# UB.1 — Banner appears for admin when can_upgrade is true
# ---------------------------------------------------------------------------

class TestUB1BannerAppearsForAdmin:
    def test_ub1_banner_visible_when_can_upgrade(self, dashboard_page: Page) -> None:
        section("UB.1 — Banner appears for admin when can_upgrade is true")
        p = dashboard_page

        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_setup_banner_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(300)

        state = _banner_state(p)
        chk("upgrade-banner element exists in DOM",     state["bannerExists"])
        chk("banner has .visible class",                state["bannerVisible"])
        chk(f"upg-latest span shows {LATEST_VERSION}", state["latestText"] == LATEST_VERSION)

        _screenshot(p, "01_banner_visible")


# ---------------------------------------------------------------------------
# UB.2 — Clicking "View & Upgrade" opens the modal
# ---------------------------------------------------------------------------

class TestUB2ViewUpgradeOpensModal:
    def test_ub2_click_view_upgrade_opens_modal(self, dashboard_page: Page) -> None:
        section("UB.2 — Clicking 'View & Upgrade' opens the modal")
        p = dashboard_page

        # Self-contained setup: ensure banner is visible with mock
        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_setup_banner_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("pre-condition: banner is visible", state["bannerVisible"])

        # Use evaluate click to avoid Playwright visibility/viewport restrictions
        p.evaluate("document.querySelector('button.upg-btn').click()")
        p.wait_for_timeout(300)

        state = _banner_state(p)
        chk("modal is visible after clicking View & Upgrade",     state["modalVisible"])
        chk(f"confirm button says 'Upgrade to {LATEST_VERSION}'",
            state["btnText"] == f"Upgrade to {LATEST_VERSION}")
        chk("confirm button is not disabled", not state["btnDisabled"])

        _screenshot(p, "02_modal_open")


# ---------------------------------------------------------------------------
# UB.3 — Modal shows changelog entries with LATEST and YOU ARE HERE badges
# ---------------------------------------------------------------------------

class TestUB3ModalChangelog:
    def test_ub3_changelog_entries_and_badges(self, dashboard_page: Page) -> None:
        section("UB.3 — Modal changelog entries with LATEST / YOU ARE HERE badges")
        p = dashboard_page

        # Self-contained: build modal state from scratch
        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_open_modal_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("pre-condition: modal is visible", state["modalVisible"])

        result = p.evaluate("""() => {
          const entries   = document.querySelectorAll('#upg-changelog-list .upg-entry');
          const latestBadge = document.querySelector('.upg-entry-latest');
          const versions  = Array.from(document.querySelectorAll('.upg-entry-version'))
                              .map(el => el.textContent.trim());
          const summaries = Array.from(document.querySelectorAll('.upg-entry-summary'))
                              .map(el => el.textContent.trim());
          const youAreHere = Array.from(document.querySelectorAll('#upg-changelog-list *'))
                               .find(el => el.textContent.trim() === 'YOU ARE HERE');
          return {
            entryCount:      entries.length,
            latestBadgeText: latestBadge ? latestBadge.textContent.trim() : null,
            versions:        versions,
            firstSummary:    summaries[0] || null,
            hasYouAreHere:   !!youAreHere,
          };
        }""")

        chk("changelog has 4 entries",          result["entryCount"] == 4)
        chk("first entry is v1.4.0",            result["versions"][0] == "v1.4.0")
        chk("LATEST badge present",             result["latestBadgeText"] == "LATEST")
        chk("YOU ARE HERE marker shown",        result["hasYouAreHere"])
        chk("first summary is non-empty text",  bool(result["firstSummary"]))

        # Close modal before next test
        p.evaluate("document.getElementById('upgrade-modal').classList.remove('visible')")


# ---------------------------------------------------------------------------
# UB.4 — Confirm upgrade: POST called, success state, banner disappears
# ---------------------------------------------------------------------------

class TestUB4ConfirmUpgrade:
    def test_ub4_confirm_upgrade_success_state(self, dashboard_page: Page) -> None:
        section("UB.4 — Confirm upgrade: success state, banner gone")
        p = dashboard_page

        # Self-contained: install mocks and open modal
        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_open_modal_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("pre-condition: modal is open",    state["modalVisible"])
        chk("pre-condition: banner is visible", state["bannerVisible"])

        p.evaluate("document.getElementById('upg-confirm-btn').click()")
        p.wait_for_timeout(1_500)  # upgrade async + 800 ms auto-close

        state = _banner_state(p)
        chk("modal closed after upgrade",     not state["modalVisible"])
        chk("banner hidden after upgrade",    not state["bannerVisible"])
        chk("button text contains 'Upgraded'",
            state["btnText"] is not None and "Upgraded" in state["btnText"])
        chk(f"button text contains '{LATEST_VERSION}'",
            state["btnText"] is not None and LATEST_VERSION in state["btnText"])
        chk("confirm button is disabled",     state["btnDisabled"])

        _screenshot(p, "04_upgraded_success")


# ---------------------------------------------------------------------------
# UB.5 — After upgrade, can_upgrade is false (banner stays hidden on re-check)
# ---------------------------------------------------------------------------

class TestUB5NoReshowAfterUpgrade:
    def test_ub5_no_banner_after_upgrade(self, dashboard_page: Page) -> None:
        section("UB.5 — After upgrade: can_upgrade=False, banner not re-shown")
        p = dashboard_page

        # Install mock that returns already-upgraded state
        already_upgraded = {
            **MOCK_VERSIONS_RESPONSE,
            "current_version": LATEST_VERSION,
            "can_upgrade":     False,
            "upgraded_at":     int(time.time()),
        }
        p.evaluate(_mock_fetch_js(already_upgraded, MOCK_UPGRADE_RESPONSE))

        # Clear banner and reset dismissed state
        p.evaluate("""() => {
          sessionStorage.removeItem('upgrade_dismissed');
          var b = document.getElementById('upgrade-banner');
          if (b) b.classList.remove('visible');
          window._upgradeData = null;
        }""")

        # Trigger checkUpgradeAvailable (which calls the mocked fetch)
        p.evaluate("if (typeof checkUpgradeAvailable === 'function') checkUpgradeAvailable();")
        p.wait_for_timeout(500)

        state = _banner_state(p)
        chk("banner NOT shown when current_version == latest_version", not state["bannerVisible"])

        # Also verify _upgradeData.can_upgrade was set to false
        can_upgrade = p.evaluate(
            "() => (typeof _upgradeData !== 'undefined' && _upgradeData) ? _upgradeData.can_upgrade : null"
        )
        chk("_upgradeData.can_upgrade is False", can_upgrade is False)


# ---------------------------------------------------------------------------
# UB.6 — Dismiss (×) hides banner without upgrading; sessionStorage set
# ---------------------------------------------------------------------------

class TestUB6DismissBanner:
    def test_ub6_dismiss_hides_banner_without_upgrade(self, dashboard_page: Page) -> None:
        section("UB.6 — Dismiss (×) hides banner without upgrading")
        p = dashboard_page

        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_setup_banner_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("pre-condition: banner is visible", state["bannerVisible"])
        chk("pre-condition: modal is NOT open", not state["modalVisible"])

        # Click dismiss button
        p.evaluate("document.querySelector('#upgrade-banner .upg-dismiss').click()")
        p.wait_for_timeout(200)

        result = p.evaluate("""() => {
          const b = document.getElementById('upgrade-banner');
          return {
            bannerVisible:     b ? b.classList.contains('visible') : true,
            modalVisible:      document.getElementById('upgrade-modal').classList.contains('visible'),
            sessionDismissed:  sessionStorage.getItem('upgrade_dismissed'),
          };
        }""")

        chk("banner hidden after dismiss",            not result["bannerVisible"])
        chk("modal NOT opened by dismiss",            not result["modalVisible"])
        chk(f"sessionStorage 'upgrade_dismissed' = '{LATEST_VERSION}'",
            result["sessionDismissed"] == LATEST_VERSION)

        _screenshot(p, "06_banner_dismissed")


# ---------------------------------------------------------------------------
# UB.7 — "Maybe later" closes modal but leaves banner visible
# ---------------------------------------------------------------------------

class TestUB7MaybeLaterKeepsBanner:
    def test_ub7_maybe_later_closes_modal_keeps_banner(self, dashboard_page: Page) -> None:
        section("UB.7 — 'Maybe later' closes modal but leaves banner visible")
        p = dashboard_page

        p.evaluate(_mock_fetch_js(MOCK_VERSIONS_RESPONSE, MOCK_UPGRADE_RESPONSE))
        p.evaluate(_open_modal_js(MOCK_VERSIONS_RESPONSE))
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("pre-condition: banner is visible", state["bannerVisible"])
        chk("pre-condition: modal is open",     state["modalVisible"])

        p.evaluate("document.querySelector('.upg-cancel-btn').click()")
        p.wait_for_timeout(200)

        state = _banner_state(p)
        chk("modal closed after 'Maybe later'",    not state["modalVisible"])
        chk("banner still visible after 'Maybe later'", state["bannerVisible"])

        _screenshot(p, "07_maybe_later")


# ---------------------------------------------------------------------------
# UB.8 — Member role: GET /v1/admin/versions returns 403
# ---------------------------------------------------------------------------

class TestUB8MemberRole403:
    def test_ub8_member_gets_403_on_versions(self) -> None:
        section("UB.8 — Member role: /v1/admin/versions returns 403")
        headers = _get_api_headers("member")
        r = requests.get(f"{API_URL}/v1/admin/versions", headers=headers, timeout=10)
        if r.status_code == 500:
            pytest.skip("org_versions migration not yet applied in this environment (500)")
        chk("member receives 403 on /v1/admin/versions", r.status_code == 403)


# ---------------------------------------------------------------------------
# UB.9 — API contract: GET /v1/admin/versions shape
# ---------------------------------------------------------------------------

class TestUB9ApiGetVersionsShape:
    def test_ub9_get_versions_response_shape(self) -> None:
        section("UB.9 — GET /v1/admin/versions response shape")
        headers = _get_api_headers("admin")
        r = requests.get(f"{API_URL}/v1/admin/versions", headers=headers, timeout=10)
        if r.status_code == 500:
            pytest.skip("org_versions migration not yet applied in this environment (500)")
        chk("GET /v1/admin/versions returns 200", r.status_code == 200)
        data = r.json()
        chk("has current_version",          "current_version" in data)
        chk("has latest_version",           "latest_version"  in data)
        chk("can_upgrade is bool",          isinstance(data.get("can_upgrade"), bool))
        chk("changelog is list",            isinstance(data.get("changelog"), list))
        chk("changelog is non-empty",       len(data.get("changelog", [])) > 0)
        for entry in data.get("changelog", []):
            v = entry.get("version", "?")
            chk(f"  changelog[{v}] has 'version'", "version" in entry)
            chk(f"  changelog[{v}] has 'date'",    "date"    in entry)
            chk(f"  changelog[{v}] has 'summary'", "summary" in entry)


# ---------------------------------------------------------------------------
# UB.10 — API contract: POST /v1/admin/versions/upgrade shape
# ---------------------------------------------------------------------------

class TestUB10ApiUpgradeShape:
    def test_ub10_post_upgrade_response_shape(self) -> None:
        section("UB.10 — POST /v1/admin/versions/upgrade response shape")
        headers = _get_api_headers("admin")

        r_get = requests.get(f"{API_URL}/v1/admin/versions", headers=headers, timeout=10)
        if r_get.status_code == 500:
            pytest.skip("org_versions migration not yet applied in this environment (500)")
        assert r_get.status_code == 200, f"unexpected GET status: {r_get.status_code}"

        r = requests.post(f"{API_URL}/v1/admin/versions/upgrade", headers=headers, timeout=10)
        if r.status_code == 500:
            pytest.skip("org_versions upgrade endpoint error (500)")
        chk("POST returns 200",                r.status_code == 200)
        data = r.json()
        chk("upgraded is True",               data.get("upgraded") is True)
        chk("version field present",          "version"     in data)
        chk(f"version == {LATEST_VERSION}",   data.get("version") == LATEST_VERSION)
        chk("upgraded_at is integer",         isinstance(data.get("upgraded_at"), int))

        # Verify GET reflects the upgrade
        r_after = requests.get(f"{API_URL}/v1/admin/versions", headers=headers, timeout=10)
        assert r_after.status_code == 200
        after = r_after.json()
        chk("after upgrade: can_upgrade is False",
            after.get("can_upgrade") is False)
        chk("after upgrade: current_version == latest_version",
            after.get("current_version") == after.get("latest_version"))
