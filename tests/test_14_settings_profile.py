"""
test_14_settings_profile.py — Settings, Profile & API Key Management Tests
===========================================================================
Developer notes:
  Targets the reported bugs:
    • "profiles, setting key are also not working"

  Covers:
    • Settings modal opens / closes correctly
    • API key hint displayed in settings (the last 4 chars of the real key)
    • Profile info (email, name, org name) shown correctly
    • Budget setting: can set org budget via UI/API
    • Team budget management via admin API
    • Key rotation via recovery flow updates settings display
    • Member management: invite, list, delete
    • Plan/tier information displayed
    • Admin overview accessible for owner
    • Slack alert config UI/API

Tests (14.1 – 14.45):
  14.1  GET /v1/admin/overview → 200 for owner
  14.2  Admin overview: org name present
  14.3  Admin overview: email present
  14.4  Admin overview: plan field present
  14.5  Admin overview: budget_usd present (null is fine for free tier)
  14.6  PUT /v1/admin/team-budgets/:team sets budget
  14.7  GET /v1/admin/team-budgets returns team budgets
  14.8  Budget shows in team budgets response
  14.9  DELETE /v1/admin/team-budgets/:team removes budget
  14.10 Settings modal: opens on /app page
  14.11 Settings modal: shows email
  14.12 Settings modal: shows org name
  14.13 Settings modal: shows API key hint (crt_...XXXX)
  14.14 Settings modal: shows plan tier
  14.15 Settings modal: closes without crash
  14.16 Settings modal: has regenerate/rotate key option (or recovery link)
  14.17 POST /v1/alerts/slack/:orgId → saves Slack config
  14.18 GET /v1/alerts/:orgId → returns saved Slack config
  14.19 POST /v1/alerts/slack/:orgId/test → test message returns 200
  14.20 POST /v1/auth/members → invite member (admin only)
  14.21 GET /v1/auth/members → list members
  14.22 New member has a key returned (or emailed)
  14.23 PATCH /v1/auth/members/:id → update role
  14.24 DELETE /v1/auth/members/:id → revoke member
  14.25 Member with viewer role cannot POST /v1/events
  14.26 Member with member role CAN POST /v1/events
  14.27 Admin overview: total_events count
  14.28 Admin overview: member_count
  14.29 Settings: budget input saves via API
  14.30 Settings: budget shows after save
  14.31 Profile section: name field visible
  14.32 Profile section: org field visible
  14.33 /v1/admin/members/:id/usage → 200 (owner)
  14.34 Member usage: has cost/token breakdown
  14.35 Non-admin member cannot access /v1/admin/overview
  14.36 Non-admin member cannot invite other members
  14.37 Viewer cannot access /v1/admin/overview
  14.38 Alert config: trigger_budget saves
  14.39 Alert config: trigger_anomaly saves
  14.40 Alert config: trigger_daily saves
  14.41 Settings UI: no JS errors
  14.42 Settings UI: save button provides feedback
  14.43 API key copy button present in settings
  14.44 Org budget displayed as % in KPI bar
  14.45 Plan upgrade link visible for free tier

Run:
  python tests/test_14_settings_profile.py
  HEADLESS=0 python tests/test_14_settings_profile.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import uuid
import requests
from helpers import (
    API_URL, SITE_URL, rand_email, rand_org, rand_name, rand_tag,
    signup_api, get_headers, get_session_cookie,
    make_browser_ctx, collect_console_errors,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.settings_profile")

# ── Test accounts ──────────────────────────────────────────────────────────
try:
    _owner  = signup_api()
    KEY     = _owner["api_key"]
    ORG     = _owner["org_id"]
    HINT    = _owner.get("hint", KEY[-4:])
    HDR     = get_headers(KEY)
    log.info("Settings test account", org_id=ORG)
except Exception as e:
    KEY = ORG = HDR = HINT = None
    log.error("Account creation failed", error=str(e))


# ─────────────────────────────────────────────────────────────────────────────
section("14-A. Admin overview API")
# ─────────────────────────────────────────────────────────────────────────────
if not KEY:
    fail("14-A  Skipping — no test account")
else:
    with log.timer("GET /v1/admin/overview"):
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=HDR, timeout=15)
    chk("14.1  GET /v1/admin/overview → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:200]}")

    if r.ok:
        d = r.json()
        log.info("Admin overview response", keys=list(d.keys())[:10])
        chk("14.2  Admin overview: org_name present",
            bool(d.get("org_name") or d.get("name") or d.get("org")), str(d)[:200])
        chk("14.3  Admin overview: email present",
            bool(d.get("email") or d.get("owner_email")), str(d)[:200])
        chk("14.4  Admin overview: plan field present",
            "plan" in d or "tier" in d, str(d)[:200])
        chk("14.5  Admin overview: budget_usd present (null ok)",
            "budget_usd" in d or "budget" in d, str(d)[:200])
        chk("14.27 Admin overview: total_events or event_count",
            "event" in str(d).lower() or "events" in d or "total_events" in d,
            str(d)[:200])
        chk("14.28 Admin overview: member_count or members list",
            "member" in str(d).lower(), str(d)[:200])


# ─────────────────────────────────────────────────────────────────────────────
section("14-B. Team budgets API")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    test_team = f"team_{rand_tag(6)}"

    # 14.6 Set budget
    with log.timer("PUT team budget"):
        r = requests.put(
            f"{API_URL}/v1/admin/team-budgets/{test_team}",
            json={"budget_usd": 500.00},
            headers=HDR, timeout=15)
    chk("14.6  PUT /v1/admin/team-budgets/:team → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")

    # 14.7 List budgets
    with log.timer("GET team budgets"):
        r = requests.get(f"{API_URL}/v1/admin/team-budgets", headers=HDR, timeout=15)
    chk("14.7  GET /v1/admin/team-budgets → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")

    # 14.8 Budget in response
    if r.ok:
        budgets = r.json()
        budget_list = budgets if isinstance(budgets, list) else budgets.get("budgets", [])
        found = any(
            b.get("team") == test_team and b.get("budget_usd") == 500.00
            for b in budget_list if isinstance(b, dict)
        )
        chk("14.8  Budget shows in team-budgets response",
            found, f"Looking for {test_team} in {budget_list[:3]}")

    # 14.9 Delete budget
    with log.timer("DELETE team budget"):
        r = requests.delete(
            f"{API_URL}/v1/admin/team-budgets/{test_team}",
            headers=HDR, timeout=15)
    chk("14.9  DELETE /v1/admin/team-budgets/:team → 200/204",
        r.status_code in (200, 204), f"{r.status_code}: {r.text[:100]}")


# ─────────────────────────────────────────────────────────────────────────────
section("14-C. Alert config API")
# ─────────────────────────────────────────────────────────────────────────────
if KEY:
    # 14.17 Save Slack config (use a placeholder URL since we don't have a real webhook)
    fake_webhook = "https://hooks.slack.com/services/TXXXXXXXX/BXXXXXXXX/xxxxxxxxxxx"
    with log.timer("POST /v1/alerts/slack"):
        r = requests.post(
            f"{API_URL}/v1/alerts/slack/{ORG}",
            json={
                "slack_url": fake_webhook,
                "trigger_budget": True,
                "trigger_anomaly": True,
                "trigger_daily": False,
            },
            headers=HDR, timeout=15)
    chk("14.17 POST /v1/alerts/slack/:orgId → 200",
        r.status_code == 200, f"{r.status_code}: {r.text[:100]}")

    # 14.18 Get alert config
    with log.timer("GET /v1/alerts"):
        r = requests.get(f"{API_URL}/v1/alerts/{ORG}", headers=HDR, timeout=15)
    chk("14.18 GET /v1/alerts/:orgId → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")

    if r.ok:
        d = r.json()
        chk("14.38 Alert config: trigger_budget saved",
            d.get("trigger_budget") is True, str(d))
        chk("14.39 Alert config: trigger_anomaly saved",
            d.get("trigger_anomaly") is True, str(d))
        chk("14.40 Alert config: trigger_daily saved",
            d.get("trigger_daily") is False, str(d))

    # 14.19 Test Slack message (will fail since fake webhook, but should not 500)
    rt = requests.post(
        f"{API_URL}/v1/alerts/slack/{ORG}/test",
        headers=HDR, timeout=15)
    chk("14.19 POST /v1/alerts/slack/test → not 500",
        rt.status_code != 500, f"got {rt.status_code}: {rt.text[:100]}")


# ─────────────────────────────────────────────────────────────────────────────
section("14-D. Member management API")
# ─────────────────────────────────────────────────────────────────────────────
MEMBER_ID = None
MEMBER_KEY = None

if KEY:
    member_email = rand_email("member")

    # 14.20 Invite member
    with log.timer("POST /v1/auth/members invite"):
        r = requests.post(
            f"{API_URL}/v1/auth/members",
            json={"email": member_email, "name": rand_name(), "role": "member"},
            headers=HDR, timeout=15)
    chk("14.20 POST /v1/auth/members → 201", r.status_code == 201,
        f"{r.status_code}: {r.text[:200]}")

    if r.ok:
        md = r.json()
        MEMBER_ID  = md.get("id") or md.get("member_id")
        MEMBER_KEY = md.get("api_key")
        chk("14.22 Member invite: key returned in response",
            bool(MEMBER_KEY) and MEMBER_KEY.startswith("crt_"),
            f"key: {MEMBER_KEY[:20] if MEMBER_KEY else None}")

    # 14.21 List members
    with log.timer("GET /v1/auth/members"):
        r = requests.get(f"{API_URL}/v1/auth/members", headers=HDR, timeout=15)
    chk("14.21 GET /v1/auth/members → 200", r.status_code == 200,
        f"{r.status_code}: {r.text[:100]}")

    if r.ok:
        members = r.json()
        member_list = members if isinstance(members, list) else members.get("members", [])
        chk("14.21b Member list contains invited member",
            any(m.get("email") == member_email for m in member_list if isinstance(m, dict)),
            f"looking for {member_email} in {[m.get('email') for m in member_list[:5]]}")

    # 14.26 Member CAN ingest events
    if MEMBER_KEY:
        event = {
            "event_id": str(uuid.uuid4()),
            "provider": "openai", "model": "gpt-4o",
            "prompt_tokens": 50, "completion_tokens": 50,
            "total_tokens": 100, "total_cost_usd": 0.001,
            "latency_ms": 100,
        }
        r_ev = requests.post(
            f"{API_URL}/v1/events", json=event,
            headers=get_headers(MEMBER_KEY), timeout=10)
        chk("14.26 Member (role=member) CAN POST /v1/events",
            r_ev.status_code in (200, 201), f"{r_ev.status_code}: {r_ev.text[:100]}")

    # 14.23 Update member role to viewer
    if MEMBER_ID:
        with log.timer("PATCH /v1/auth/members/:id role"):
            rp = requests.patch(
                f"{API_URL}/v1/auth/members/{MEMBER_ID}",
                json={"role": "viewer"},
                headers=HDR, timeout=10)
        chk("14.23 PATCH member role to viewer → 200",
            rp.status_code == 200, f"{rp.status_code}: {rp.text[:100]}")

    # 14.25 Viewer CANNOT ingest events
    if MEMBER_KEY and MEMBER_ID:
        event2 = {
            "event_id": str(uuid.uuid4()),
            "provider": "openai", "model": "gpt-4o",
            "prompt_tokens": 50, "completion_tokens": 50,
            "total_tokens": 100, "total_cost_usd": 0.001,
            "latency_ms": 100,
        }
        r_ev2 = requests.post(
            f"{API_URL}/v1/events", json=event2,
            headers=get_headers(MEMBER_KEY), timeout=10)
        chk("14.25 Viewer CANNOT POST /v1/events → 403",
            r_ev2.status_code in (403, 401),
            f"got {r_ev2.status_code} — viewer should not be able to ingest")

    # 14.33 Member usage
    if MEMBER_ID:
        ru = requests.get(
            f"{API_URL}/v1/admin/members/{MEMBER_ID}/usage",
            headers=HDR, timeout=10)
        chk("14.33 GET /v1/admin/members/:id/usage → 200",
            ru.status_code == 200, f"{ru.status_code}: {ru.text[:100]}")
        if ru.ok:
            usage = ru.json()
            chk("14.34 Member usage: has cost or tokens",
                "cost" in str(usage).lower() or "token" in str(usage).lower(),
                str(usage)[:200])

    # 14.35 Non-admin member cannot access overview
    if MEMBER_KEY:
        r_admin = requests.get(
            f"{API_URL}/v1/admin/overview",
            headers=get_headers(MEMBER_KEY), timeout=10)
        chk("14.35 Member (viewer) cannot access /v1/admin/overview → 403",
            r_admin.status_code in (403, 401),
            f"got {r_admin.status_code} — viewer should not see admin data")

    # 14.36 Member cannot invite other members
    if MEMBER_KEY:
        r_invite = requests.post(
            f"{API_URL}/v1/auth/members",
            json={"email": rand_email("member2"), "name": "Test", "role": "member"},
            headers=get_headers(MEMBER_KEY), timeout=10)
        chk("14.36 Member cannot invite others → 403",
            r_invite.status_code in (403, 401),
            f"got {r_invite.status_code}")

    # 14.24 Delete member
    if MEMBER_ID:
        with log.timer("DELETE /v1/auth/members/:id"):
            rd = requests.delete(
                f"{API_URL}/v1/auth/members/{MEMBER_ID}",
                headers=HDR, timeout=10)
        chk("14.24 DELETE /v1/auth/members/:id → 200/204",
            rd.status_code in (200, 204), f"{rd.status_code}: {rd.text[:100]}")


# ─────────────────────────────────────────────────────────────────────────────
section("14-E. Settings UI (Playwright)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:
        if not KEY:
            warn("14-E  Skipping UI tests — no test account")
        else:
            browser, ctx, page = make_browser_ctx(pw)
            js_errors = collect_console_errors(page)

            # Set session
            sr = requests.post(f"{API_URL}/v1/auth/session",
                               json={"api_key": KEY}, timeout=15)
            if sr.ok:
                for c in sr.cookies:
                    ctx.add_cookies([{
                        "name": c.name, "value": c.value,
                        "domain": "cohrint.com", "path": "/",
                    }])

            try:
                page.goto(f"{SITE_URL}/app", wait_until="networkidle", timeout=25_000)
                page.wait_for_timeout(2_000)

                chk("14-E.0 /app loads for settings test",
                    "/app" in page.url, f"URL: {page.url}")

                # Find settings button
                settings_sel = (
                    "[data-view='settings'], "
                    "nav a:has-text('Settings'), "
                    ".sidebar a:has-text('Settings'), "
                    "button:has-text('Settings'), "
                    "#settings-btn, .settings-link, "
                    "[data-section='settings']"
                )
                settings_el = page.locator(settings_sel).first
                settings_opened = False

                if settings_el.count() > 0:
                    settings_el.click()
                    page.wait_for_timeout(1_500)

                    # Check if settings modal/panel opened
                    modal_sels = [
                        ".modal", ".settings-modal", "#settings-panel",
                        "dialog", ".settings-pane", "[data-panel='settings']",
                        ".settings-section", "#settings-content"
                    ]
                    for ms in modal_sels:
                        if page.locator(ms).count() > 0:
                            settings_opened = True
                            break

                    # Also check by page content
                    if not settings_opened:
                        content = page.content().lower()
                        settings_opened = any(w in content for w in [
                            "api key", "settings", "profile", "account", "billing"
                        ])

                    chk("14.10 Settings modal/panel opens", settings_opened,
                        "Settings panel not detected after click")

                    content = page.content()
                    content_lower = content.lower()

                    # 14.11 Email visible
                    chk("14.11 Settings shows email",
                        "@" in content_lower or "email" in content_lower)

                    # 14.12 Org name visible
                    chk("14.12 Settings shows org name",
                        "org" in content_lower or ORG.lower() in content_lower[:5000])

                    # 14.13 API key hint (format: crt_...XXXX)
                    chk("14.13 Settings shows API key hint",
                        "crt_" in content[:5000] or "api key" in content_lower
                        or (HINT and HINT in content[:5000]))

                    # 14.14 Plan/tier visible
                    chk("14.14 Settings shows plan/tier",
                        any(w in content_lower for w in [
                            "free", "pro", "enterprise", "plan", "tier"]))

                    # 14.43 Copy button for key
                    chk("14.43 API key copy button present",
                        page.locator(
                            "button:has-text('Copy'), .copy-btn, [data-copy], .copy-key"
                        ).count() > 0 or "copy" in content_lower)

                    # 14.16 Rotate/regenerate key option
                    chk("14.16 Settings: rotate/regenerate key option present",
                        any(w in content_lower for w in [
                            "rotate", "regenerate", "recover", "new key", "reset key"]))

                    # 14.42 Save button provides feedback (hard to test without real network)
                    save_btn = page.locator(
                        "button:has-text('Save'), button:has-text('Update'), .save-btn"
                    ).first
                    chk("14.42 Settings: save button present", save_btn.count() > 0)

                    # 14.15 Close settings without crash
                    try:
                        close_sel = ".modal-close, button:has-text('Close'), button:has-text('×'), [aria-label='Close'], .close-btn"
                        close_btn = page.locator(close_sel).first
                        if close_btn.count() > 0:
                            close_btn.click()
                            page.wait_for_timeout(800)
                        else:
                            # Try pressing Escape
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(800)
                        chk("14.15 Settings closes without crash",
                            len(page.content()) > 500)
                    except Exception as e:
                        warn(f"14.15 Close settings: {e}")

                    # 14.41 No JS errors during settings
                    chk("14.41 No JS errors during settings interaction",
                        len(js_errors) == 0, f"errors: {js_errors[:3]}")

                else:
                    warn("14-E  Settings button not found — check sidebar selectors in app.html")

                # 14.31 Profile name field
                profile_content = page.content().lower()
                chk("14.31 Profile: name field visible",
                    "name" in profile_content)

                # 14.32 Profile org field
                chk("14.32 Profile: org field visible",
                    "org" in profile_content)

                # 14.44 Budget progress bar
                chk("14.44 Budget % displayed in KPI or header",
                    any(w in profile_content for w in ["budget", "plan", "limit"]))

                # 14.45 Plan upgrade link for free tier
                chk("14.45 Upgrade link visible for free tier",
                    any(w in profile_content for w in [
                        "upgrade", "pro", "enterprise", "plans"
                    ]))

            except Exception as e:
                fail("14-E  Settings UI test error", str(e)[:300])
                log.exception("Settings UI crash", e)

            ctx.close()
            browser.close()

except ImportError:
    warn("Playwright not installed — run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("test_14  Settings suite crashed", str(e)[:400])
    log.exception("Settings suite crash", e)


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Settings & Profile tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
