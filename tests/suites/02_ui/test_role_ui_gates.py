"""
test_role_ui_gates.py — Role-based UI visibility tests (Playwright)
====================================================================
Suite RG: Validates that Settings tab and Team Management card are
gated correctly by role and account_type.

Rules under test:
  - Settings tab visible: admin+ only
  - Team Management card visible: admin+ AND account_type=organization
  - Individual accounts: Settings visible (owner), no Team card
  - member/viewer: no Settings tab, no Team card

Labels: RG.1 – RG.N

Runs against live site (https://cohrint.com).
Requires: VANTAGE_CI_SECRET env var for signup rate-limit bypass.
"""

import sys
import uuid
import requests
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL, CI_SECRET
from helpers.browser import make_browser_ctx, signin_ui, collect_console_errors


TIMEOUT = 20

def _ci_headers():
    h = {"Content-Type": "application/json"}
    if CI_SECRET:
        h["X-Vantage-CI"] = CI_SECRET
    return h

def rand_email(p="rg"): return f"{p}-{uuid.uuid4().hex[:8]}@test.cohrint.com"
def rand_name():         return f"Test-{uuid.uuid4().hex[:4]}"
def rand_org(p="rg"):   return f"{p}-{uuid.uuid4().hex[:6]}"

def signup(account_type: str, prefix: str = "rg") -> dict:
    r = requests.post(f"{API_URL}/v1/auth/signup", json={
        "email": rand_email(prefix),
        "name":  rand_name(),
        "org":   rand_org(prefix),
        "account_type": account_type,
    }, headers=_ci_headers(), timeout=TIMEOUT)
    assert r.status_code == 201, f"signup failed: {r.text[:200]}"
    return r.json()

def create_team(api_key: str, name: str) -> str:
    r = requests.post(f"{API_URL}/v1/teams",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"name": name}, timeout=TIMEOUT)
    assert r.status_code == 201, f"create_team failed: {r.text[:200]}"
    return r.json()["team_id"]

def invite_member(api_key: str, role: str, team_id: str) -> dict:
    r = requests.post(f"{API_URL}/v1/auth/members",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"email": rand_email("rg-inv"), "name": rand_name(),
                            "role": role, "team_id": team_id}, timeout=TIMEOUT)
    assert r.status_code == 201, f"invite failed: {r.text[:200]}"
    return r.json()

def _settings_visible(page) -> bool:
    el = page.query_selector("#sb-settings")
    if not el:
        return False
    return page.evaluate("el => getComputedStyle(el).display !== 'none'", el)

def _team_card_visible(page) -> bool:
    el = page.query_selector("#teamMgmtCard")
    if not el:
        return False
    return page.evaluate("el => getComputedStyle(el).display !== 'none'", el)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def org_owner():
    d = signup("organization", prefix="rg-owner")
    team_id = create_team(d["api_key"], "Engineering")
    return {"api_key": d["api_key"], "team_id": team_id}

@pytest.fixture(scope="module")
def org_member(org_owner):
    d = invite_member(org_owner["api_key"], "member", org_owner["team_id"])
    return {"api_key": d["api_key"]}

@pytest.fixture(scope="module")
def org_viewer(org_owner):
    d = invite_member(org_owner["api_key"], "viewer", org_owner["team_id"])
    return {"api_key": d["api_key"]}

@pytest.fixture(scope="module")
def individual_owner():
    return signup("individual", prefix="rg-ind")


# ══════════════════════════════════════════════════════════════════════════════
# RG-A: Owner on org account
# ══════════════════════════════════════════════════════════════════════════════

class TestOrgOwner:

    def test_settings_tab_visible(self, org_owner):
        """RG.A.1 — org owner sees Settings tab."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_owner["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            assert _settings_visible(page), "Settings tab should be visible for org owner"
            browser.close()

    def test_team_card_visible_in_settings(self, org_owner):
        """RG.A.2 — org owner sees Team Management card in Settings."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_owner["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            page.click("#sb-settings")
            page.wait_for_timeout(1000)
            assert _team_card_visible(page), "Team card should be visible for org owner"
            browser.close()

    def test_team_card_has_new_team_button(self, org_owner):
        """RG.A.3 — Team card shows '+ New Team' button for org owner."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_owner["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            page.click("#sb-settings")
            page.wait_for_timeout(1000)
            assert page.is_visible("#teamMgmtCard button"), "New Team button missing"
            browser.close()


# ══════════════════════════════════════════════════════════════════════════════
# RG-B: Member on org account
# ══════════════════════════════════════════════════════════════════════════════

class TestOrgMember:

    def test_settings_tab_hidden(self, org_member):
        """RG.B.1 — org member does NOT see Settings tab."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_member["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            assert not _settings_visible(page), "Settings tab should be hidden for member"
            browser.close()

    def test_team_card_hidden(self, org_member):
        """RG.B.2 — org member does NOT see Team Management card."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_member["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            page.evaluate("if (typeof nav === 'function') nav('settings', null);")
            page.wait_for_timeout(800)
            assert not _team_card_visible(page), "Team card should be hidden for member"
            browser.close()


# ══════════════════════════════════════════════════════════════════════════════
# RG-C: Viewer on org account
# ══════════════════════════════════════════════════════════════════════════════

class TestOrgViewer:

    def test_settings_tab_hidden(self, org_viewer):
        """RG.C.1 — org viewer does NOT see Settings tab."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_viewer["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            assert not _settings_visible(page), "Settings tab should be hidden for viewer"
            browser.close()

    def test_team_card_hidden(self, org_viewer):
        """RG.C.2 — org viewer does NOT see Team Management card."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, org_viewer["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            page.evaluate("if (typeof nav === 'function') nav('settings', null);")
            page.wait_for_timeout(800)
            assert not _team_card_visible(page), "Team card should be hidden for viewer"
            browser.close()


# ══════════════════════════════════════════════════════════════════════════════
# RG-D: Owner on individual account
# ══════════════════════════════════════════════════════════════════════════════

class TestIndividualOwner:

    def test_settings_tab_visible(self, individual_owner):
        """RG.D.1 — individual owner sees Settings tab."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, individual_owner["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            assert _settings_visible(page), "Settings tab should be visible for individual owner"
            browser.close()

    def test_team_card_hidden(self, individual_owner):
        """RG.D.2 — individual account does NOT see Team Management card."""
        with sync_playwright() as pw:
            browser, ctx, page = make_browser_ctx(pw)
            assert signin_ui(page, individual_owner["api_key"]), "login failed"
            page.wait_for_timeout(2000)
            page.click("#sb-settings")
            page.wait_for_timeout(1000)
            assert not _team_card_visible(page), "Team card should be hidden for individual account"
            browser.close()
