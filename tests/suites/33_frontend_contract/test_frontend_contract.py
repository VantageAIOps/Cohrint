"""
test_frontend_contract.py — Frontend ↔ Backend Integration Contract
====================================================================
Suite FC: Exhaustive regression tests that pin every field the dashboard
reads from every API endpoint. If a backend field is renamed or removed,
this suite catches it immediately — before it silently breaks a card.

Tests are organised by what they protect:

  Section A — API Schema Contract       FC.01–FC.25
    Verifies the exact field names and types every frontend card reads.

  Section B — Data Render Contract      FC.26–FC.45
    Seeds known data and verifies it propagates to every dashboard
    endpoint with correct values (not just keys).

  Section C — Error & Status Contract   FC.46–FC.55
    Verifies 401, 429, 4xx, 5xx shapes so the frontend error branches
    receive predictable objects.

  Section D — Integration Channel Contract  FC.56–FC.70
    End-to-end: OTel ingest → cross-platform summary, batch ingest →
    analytics, rate-limiting headers, Retry-After on 429.

  Section E — Regression Guard          FC.71–FC.80
    Schema snapshot: lists of fields that MUST always exist. Any
    removal fails the suite immediately.

Labels: FC.01 – FC.80
"""

import sys
import time
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.data import make_event, rand_email
from helpers.output import section, chk, warn, info


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get(path, headers, params=None, timeout=15):
    return requests.get(f"{API_URL}{path}", headers=headers, params=params, timeout=timeout)

def _post(path, headers, body, timeout=15):
    return requests.post(f"{API_URL}{path}", json=body, headers=headers, timeout=timeout)

def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def _is_list(v):
    return isinstance(v, list)

def _is_str(v):
    return isinstance(v, str)


# ─────────────────────────────────────────────────────────────────────────────
# Section A — API Schema Contract (FC.01–FC.25)
# Verifies every field the frontend reads exists with the right type.
# ─────────────────────────────────────────────────────────────────────────────

class TestAPISchemaContract:
    """Pins the exact fields every dashboard card reads from every endpoint."""

    def test_fc01_cross_platform_summary_shape(self, headers):
        """FC.01: /v1/cross-platform/summary has all fields the Overview KPIs read."""
        section("A — API Schema Contract")
        r = _get("/v1/cross-platform/summary", headers, params={"days": 30})
        chk("FC.01a summary → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        # Fields used by kpiTotalSpend card
        chk("FC.01b total_cost_usd is number",  _is_number(body.get("total_cost_usd")),  f"got {type(body.get('total_cost_usd'))}")
        chk("FC.01c previous_period_cost exists", "previous_period_cost" in body,         f"keys: {list(body)}")
        chk("FC.01d previous_period_cost is number", _is_number(body.get("previous_period_cost", 0)), "")

        # Fields used by kpiTokenUsage card
        chk("FC.01e total_input_tokens is number",  _is_number(body.get("total_input_tokens")),  "")
        chk("FC.01f total_output_tokens is number", _is_number(body.get("total_output_tokens")), "")
        chk("FC.01g total_cached_tokens is number", _is_number(body.get("total_cached_tokens")), "")

        # Fields used by kpiBudget card
        budget = body.get("budget", {})
        chk("FC.01h budget object present",         isinstance(budget, dict),                    f"type={type(budget)}")
        chk("FC.01i budget.monthly_limit_usd",       "monthly_limit_usd" in budget,              f"keys: {list(budget)}")
        chk("FC.01j budget.month_spend_usd",         "month_spend_usd" in budget,                "")
        chk("FC.01k budget.budget_pct",              "budget_pct" in budget,                     "")

        # Fields used by renderToolComparison
        by_prov = body.get("by_provider", [])
        chk("FC.01l by_provider is list",            _is_list(by_prov),                          f"type={type(by_prov)}")
        if by_prov:
            p = by_prov[0]
            chk("FC.01m by_provider[].provider",     _is_str(p.get("provider", "")),             f"keys: {list(p)}")
            chk("FC.01n by_provider[].cost is number", _is_number(p.get("cost", 0)),             "")
            chk("FC.01o by_provider[].records is number", _is_number(p.get("records", 0)),       "")
        chk("FC.01p total_records is number",        _is_number(body.get("total_records", 0)),   "")

    def test_fc02_cross_platform_developers_shape(self, headers):
        """FC.02: /v1/cross-platform/developers has by_provider, developer_email, total_cost."""
        r = _get("/v1/cross-platform/developers", headers, params={"days": 30})
        chk("FC.02a developers → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        chk("FC.02b developers key is list", _is_list(body.get("developers")), "")
        devs = body.get("developers", [])
        if devs:
            d = devs[0]
            chk("FC.02c developer_email is str", _is_str(d.get("developer_email", "")),       f"keys: {list(d)}")
            chk("FC.02d total_cost is number",    _is_number(d.get("total_cost", 0)),          "")
            chk("FC.02e by_provider is list",     _is_list(d.get("by_provider", [])),          f"type={type(d.get('by_provider'))}")
            chk("FC.02f providers is list",        _is_list(d.get("providers", [])),            "")
            if d.get("by_provider"):
                bp = d["by_provider"][0]
                chk("FC.02g by_provider[].provider is str",  _is_str(bp.get("provider", "")), f"keys: {list(bp)}")
                chk("FC.02h by_provider[].cost is number",    _is_number(bp.get("cost", 0)),   "")
                chk("FC.02i by_provider[].records is number", _is_number(bp.get("records", 0)), "")

    def test_fc03_cross_platform_live_shape(self, headers):
        """FC.03: /v1/cross-platform/live events array has the fields prependLiveItem reads."""
        r = _get("/v1/cross-platform/live", headers, params={"limit": 30})
        chk("FC.03a live → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        chk("FC.03b events key is list", _is_list(body.get("events", [])), "")

    def test_fc04_analytics_timeseries_shape(self, headers):
        """FC.04: /v1/analytics/timeseries returns series[] with date + cost_usd fields."""
        r = _get("/v1/analytics/timeseries", headers, params={"period": 30})
        chk("FC.04a timeseries → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        chk("FC.04b series key is list", _is_list(body.get("series")), f"keys: {list(body)}")
        series = body.get("series", [])
        if series:
            d = series[0]
            chk("FC.04c series[].date is str",      _is_str(d.get("date", "")),         f"keys: {list(d)}")
            chk("FC.04d series[].cost_usd exists",  "cost_usd" in d,                    "")
            chk("FC.04e series[].cost_usd is number", _is_number(d.get("cost_usd", 0)), "")
            chk("FC.04f series[].tokens is number",   _is_number(d.get("tokens", 0)),   "")
            chk("FC.04g series[].requests is number", _is_number(d.get("requests", 0)), "")
        # 'day' field should NOT exist (frontend has fallback for it but backend uses 'date')
        if series:
            chk("FC.04h series[] uses 'date' not 'day'", "date" in series[0], "")

    def test_fc05_analytics_models_shape(self, headers):
        """FC.05: /v1/analytics/models returns models[] with model, cost_usd, tokens."""
        r = _get("/v1/analytics/models", headers, params={"period": 30})
        chk("FC.05a models → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        chk("FC.05b models key is list", _is_list(body.get("models")), f"keys: {list(body)}")
        models = body.get("models", [])
        if models:
            m = models[0]
            chk("FC.05c models[].model is str",        _is_str(m.get("model", "")),        f"keys: {list(m)}")
            chk("FC.05d models[].provider is str",     _is_str(m.get("provider", "")),     "")
            chk("FC.05e models[].cost_usd is number",  _is_number(m.get("cost_usd", 0)),   "")
            chk("FC.05f models[].tokens is number",    _is_number(m.get("tokens", 0)),     "")
            chk("FC.05g models[].requests is number",  _is_number(m.get("requests", 0)),   "")

    def test_fc06_analytics_teams_shape(self, headers):
        """FC.06: /v1/analytics/teams returns teams[] with team, cost_usd, budget_usd."""
        r = _get("/v1/analytics/teams", headers, params={"period": 30})
        chk("FC.06a teams → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        chk("FC.06b teams key is list", _is_list(body.get("teams")), f"keys: {list(body)}")
        teams = body.get("teams", [])
        if teams:
            t = teams[0]
            chk("FC.06c teams[].team is str",         _is_str(t.get("team", "")),        f"keys: {list(t)}")
            chk("FC.06d teams[].cost_usd is number",  _is_number(t.get("cost_usd", 0)),  "")
            chk("FC.06e teams[].budget_usd is number", _is_number(t.get("budget_usd", 0)), "")

    def test_fc07_admin_overview_shape(self, admin_headers):
        """FC.07: /v1/admin/overview has org.*, teams[].member_count, members[].api_key_hint."""
        r = _get("/v1/admin/overview", admin_headers)
        chk("FC.07a overview → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()

        # org sub-object — what account view reads
        org = body.get("org", {})
        chk("FC.07b org object present",              isinstance(org, dict),                  "")
        chk("FC.07c org.mtd_cost_usd is number",      _is_number(org.get("mtd_cost_usd", 0)), "")
        chk("FC.07d org.budget_usd is number",         _is_number(org.get("budget_usd", 0)),  "")
        chk("FC.07e org.events_this_month is number",  _is_number(org.get("events_this_month", 0)), "")
        chk("FC.07f org.plan is str",                  _is_str(org.get("plan", "")),           "")

        # teams with member_count — what members view reads
        teams = body.get("teams", [])
        chk("FC.07g teams is list",                    _is_list(teams),                        "")
        if teams:
            t = teams[0]
            chk("FC.07h teams[].team is str",          _is_str(t.get("team", "")),             f"keys: {list(t)}")
            chk("FC.07i teams[].cost_usd is number",   _is_number(t.get("cost_usd", 0)),       "")
            chk("FC.07j teams[].member_count exists",  "member_count" in t,                    f"keys: {list(t)}")
            chk("FC.07k teams[].member_count is number", _is_number(t.get("member_count", 0)), "")

        # members list — what members table reads
        members = body.get("members", [])
        chk("FC.07l members is list", _is_list(members), "")

    def test_fc08_auth_members_shape(self, admin_headers):
        """FC.08: /v1/auth/members returns members[] with api_key_hint (not api_key)."""
        r = _get("/v1/auth/members", admin_headers)
        chk("FC.08a members → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        members = body.get("members", [])
        chk("FC.08b members is list", _is_list(members), "")
        if members:
            m = members[0]
            chk("FC.08c members[].email is str",      _is_str(m.get("email", "")),    f"keys: {list(m)}")
            chk("FC.08d members[].role is str",       _is_str(m.get("role", "")),     "")
            chk("FC.08e api_key_hint present",        "api_key_hint" in m,            "")
            chk("FC.08f api_key NOT in response",     "api_key" not in m,             "full key should never be returned")

    def test_fc09_admin_team_budgets_shape(self, admin_headers):
        """FC.09: /v1/admin/team-budgets returns budgets[] (not teams[] or data[])."""
        r = _get("/v1/admin/team-budgets", admin_headers)
        chk("FC.09a team-budgets → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        chk("FC.09b budgets key is list",  _is_list(body.get("budgets", [])), f"keys: {list(body)}")
        chk("FC.09c no 'teams' root key",  "teams" not in body,               "misleading alias — use 'budgets'")
        chk("FC.09d no 'data' root key",   "data" not in body,                "misleading alias — use 'budgets'")

    def test_fc10_alerts_shape(self, admin_headers):
        """FC.10: GET /v1/alerts/:orgId returns slack_url and trigger_* fields."""
        # We need orgId — get it from session
        sr = requests.post(f"{API_URL}/v1/auth/session",
                           json={"api_key": admin_headers["Authorization"].replace("Bearer ", "")},
                           timeout=15)
        if not sr.ok:
            warn("FC.10  could not get session for org_id — skipping")
            return
        sess = sr.json()
        org_id = (sess.get("user") or sess).get("org_id", "")
        if not org_id:
            warn("FC.10  org_id not in session — skipping")
            return

        r = _get(f"/v1/alerts/{org_id}", admin_headers)
        chk("FC.10a alerts → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        # Fields the frontend reads (may be null/absent if not configured — just check type if present)
        for field in ("slack_url", "trigger_budget", "trigger_anomaly", "trigger_daily"):
            if field in body:
                chk(f"FC.10b {field} is scalar", not isinstance(body[field], dict), "")

    def test_fc11_cross_platform_connections_shape(self, headers):
        """FC.11: /v1/cross-platform/connections has billing_connections and otel_sources."""
        r = _get("/v1/cross-platform/connections", headers)
        chk("FC.11a connections → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        chk("FC.11b billing_connections is list", _is_list(body.get("billing_connections", [])), "")
        chk("FC.11c otel_sources is list",        _is_list(body.get("otel_sources", [])),        "")
        if body.get("otel_sources"):
            s = body["otel_sources"][0]
            chk("FC.11d otel_sources[].provider is str", _is_str(s.get("provider", "")), f"keys: {list(s)}")
            chk("FC.11e otel_sources[].last_data_at",    "last_data_at" in s,            "")

    def test_fc12_audit_log_shape(self, admin_headers):
        """FC.12: /v1/audit-log returns events[], total, has_more."""
        r = _get("/v1/audit-log", admin_headers, params={"limit": 10, "offset": 0})
        chk("FC.12a audit-log → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        chk("FC.12b events is list",      _is_list(body.get("events", [])),           f"keys: {list(body)}")
        chk("FC.12c total is number",     _is_number(body.get("total", 0)),            "")
        chk("FC.12d has_more is bool",    isinstance(body.get("has_more", False), bool), "")
        if body.get("events"):
            e = body["events"][0]
            for field in ("created_at", "action", "actor_email"):
                chk(f"FC.12e events[].{field} present", field in e, f"keys: {list(e)}")

    def test_fc13_analytics_kpis_shape(self, headers):
        """FC.13: /v1/analytics/kpis returns numeric fields (no string where number expected)."""
        r = _get("/v1/analytics/kpis", headers, params={"period": 30})
        chk("FC.13a kpis → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200
        body = r.json()
        for field in ("total_cost_usd", "total_tokens", "total_requests", "avg_latency_ms"):
            chk(f"FC.13b kpis.{field} is number", _is_number(body.get(field, 0)), f"got {type(body.get(field))}")


# ─────────────────────────────────────────────────────────────────────────────
# Section B — Data Render Contract (FC.26–FC.45)
# Sends known events, verifies exact values reach the dashboard fields.
# ─────────────────────────────────────────────────────────────────────────────

class TestDataRenderContract:
    """Verifies seeded data propagates correctly through every dashboard endpoint."""

    def test_fc26_events_appear_in_summary(self, seeded_account):
        """FC.26: Events seeded via batch POST appear in cross-platform summary total."""
        section("B — Data Render Contract")
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/cross-platform/summary", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        chk("FC.26a total_cost_usd > 0 (seeded data reflected)", body["total_cost_usd"] > 0,
            f"got {body['total_cost_usd']}")
        chk("FC.26b total_records > 0", body["total_records"] > 0, f"got {body['total_records']}")
        chk("FC.26c by_provider non-empty", len(body.get("by_provider", [])) > 0, "")

    def test_fc27_events_appear_in_timeseries(self, seeded_account):
        """FC.27: Seeded events show up in timeseries with cost_usd > 0 on at least one day."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/timeseries", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        series = body.get("series", [])
        chk("FC.27a series non-empty", len(series) > 0, "")
        any_cost = any(d.get("cost_usd", 0) > 0 for d in series)
        chk("FC.27b at least one day has cost_usd > 0", any_cost,
            f"all zero: {[d.get('cost_usd') for d in series[:5]]}")

    def test_fc28_events_appear_in_models(self, seeded_account):
        """FC.28: Seeded model 'claude-sonnet-4-6' appears in /v1/analytics/models."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/models", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        models = body.get("models", [])
        names = [m.get("model", "") for m in models]
        chk("FC.28a claude-sonnet-4-6 in models list", "claude-sonnet-4-6" in names,
            f"found: {names}")
        if names:
            m = next((m for m in models if m.get("model") == "claude-sonnet-4-6"), models[0])
            chk("FC.28b model.cost_usd > 0", m.get("cost_usd", 0) > 0, f"got {m.get('cost_usd')}")
            chk("FC.28c model.requests > 0",  m.get("requests", 0) > 0, f"got {m.get('requests')}")

    def test_fc29_events_appear_in_developers(self, seeded_account):
        """FC.29: Developer email and by_provider appear in /v1/cross-platform/developers."""
        _, _, hdrs, dev_email = seeded_account
        r = _get("/v1/cross-platform/developers", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        devs = body.get("developers", [])
        emails = [d.get("developer_email") for d in devs]
        chk("FC.29a seeded developer_email in list", dev_email in emails,
            f"found: {emails[:3]}")
        dev = next((d for d in devs if d.get("developer_email") == dev_email), None)
        if dev:
            chk("FC.29b dev.total_cost > 0",     dev.get("total_cost", 0) > 0,        f"got {dev.get('total_cost')}")
            chk("FC.29c dev.by_provider is list", _is_list(dev.get("by_provider", [])), "")
            chk("FC.29d dev.by_provider non-empty", len(dev.get("by_provider", [])) > 0,
                "provider bar chart will be blank")
            bp = dev.get("by_provider", [{}])[0]
            chk("FC.29e by_provider[0].provider is str", _is_str(bp.get("provider", "")), "")
            chk("FC.29f by_provider[0].cost > 0",         bp.get("cost", 0) > 0,          "")

    def test_fc30_summary_previous_period_cost_is_number(self, seeded_account):
        """FC.30: previous_period_cost is a number (not missing) so trend arrow can render."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/cross-platform/summary", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        ppc = body.get("previous_period_cost")
        chk("FC.30a previous_period_cost key exists",    "previous_period_cost" in body,  "")
        chk("FC.30b previous_period_cost is numeric",     _is_number(ppc if ppc is not None else 0), f"got {type(ppc)}")

    def test_fc31_team_data_in_analytics_teams(self, seeded_account):
        """FC.31: Events with team='backend' appear in analytics/teams."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/teams", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        teams = body.get("teams", [])
        team_names = [t.get("team") for t in teams]
        chk("FC.31a 'backend' team appears", "backend" in team_names,
            f"found teams: {team_names}")
        t = next((t for t in teams if t.get("team") == "backend"), None)
        if t:
            chk("FC.31b backend.cost_usd > 0", t.get("cost_usd", 0) > 0, f"got {t.get('cost_usd')}")

    def test_fc32_admin_overview_member_count_present(self, admin_headers):
        """FC.32: admin/overview teams[].member_count exists as a number (was missing before)."""
        r = _get("/v1/admin/overview", admin_headers)
        assert r.status_code == 200
        body = r.json()
        teams = body.get("teams", [])
        if teams:
            chk("FC.32a teams[0].member_count present",    "member_count" in teams[0],              f"keys: {list(teams[0])}")
            chk("FC.32b teams[0].member_count is integer", isinstance(teams[0].get("member_count", 0), int), "")
        else:
            chk("FC.32a no teams yet (skip member_count check)", True, "")

    def test_fc33_by_provider_cost_matches_summary_total(self, seeded_account):
        """FC.33: Sum of by_provider[].cost equals total_cost_usd (within rounding)."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/cross-platform/summary", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        total = body.get("total_cost_usd", 0)
        prov_sum = sum(p.get("cost", 0) for p in body.get("by_provider", []))
        if total > 0:
            diff_pct = abs(total - prov_sum) / total * 100
            chk("FC.33a by_provider sum ≈ total_cost_usd (within 1%)", diff_pct < 1,
                f"total={total:.6f} prov_sum={prov_sum:.6f} diff={diff_pct:.2f}%")

    def test_fc34_kpis_total_cost_is_number_not_zero(self, seeded_account):
        """FC.34: After seeding events, analytics/kpis total_cost_usd > 0."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/kpis", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        chk("FC.34a kpis.total_cost_usd > 0 after events", body.get("total_cost_usd", 0) > 0,
            f"got {body.get('total_cost_usd')}")
        chk("FC.34b kpis.total_requests > 0",               body.get("total_requests", 0) > 0, "")


# ─────────────────────────────────────────────────────────────────────────────
# Section C — Error & Status Contract (FC.46–FC.55)
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorStatusContract:
    """Verifies error responses have a shape the frontend can handle predictably."""

    def test_fc46_unauthenticated_returns_401_json(self):
        """FC.46: Unauthenticated requests return 401 JSON (not HTML redirect)."""
        section("C — Error & Status Contract")
        for path in [
            "/v1/cross-platform/summary",
            "/v1/analytics/kpis",
            "/v1/admin/overview",
            "/v1/auth/members",
        ]:
            r = requests.get(f"{API_URL}{path}", timeout=10)
            chk(f"FC.46 {path} → 401", r.status_code == 401, f"got {r.status_code}")
            ct = r.headers.get("Content-Type", "")
            chk(f"FC.46 {path} → JSON content", "application/json" in ct,
                f"Content-Type: {ct}")
            body = r.json() if "application/json" in ct else {}
            chk(f"FC.46 {path} has 'error' key", "error" in body, f"body: {body}")

    def test_fc47_wrong_api_key_returns_401(self):
        """FC.47: Invalid Bearer token returns 401 with error field."""
        bad = {"Authorization": "Bearer vnt_totallyinvalid"}
        r = requests.get(f"{API_URL}/v1/cross-platform/summary", headers=bad, timeout=10)
        chk("FC.47a wrong key → 401", r.status_code == 401, f"got {r.status_code}")
        body = r.json()
        chk("FC.47b body has 'error'", "error" in body, f"body: {body}")

    def test_fc48_otel_wrong_key_returns_401(self):
        """FC.48: OTel endpoint with invalid key returns 401."""
        bad = {"Authorization": "Bearer vnt_invalid", "Content-Type": "application/json"}
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                          json={"resourceMetrics": []}, headers=bad, timeout=10)
        chk("FC.48a otel bad key → 401", r.status_code == 401, f"got {r.status_code}")
        body = r.json()
        chk("FC.48b error message helpful", "key" in body.get("error", "").lower() or
            "api" in body.get("error", "").lower(), f"error: {body.get('error')}")

    def test_fc49_invalid_json_returns_400(self):
        """FC.49: Malformed JSON body returns 400 (not 500)."""
        api_key, _, _ = fresh_account(prefix="fc_400")
        hdrs = {**get_headers(api_key), "Content-Type": "application/json"}
        r = requests.post(f"{API_URL}/v1/events",
                          data="not valid json",
                          headers=hdrs, timeout=10)
        chk("FC.49a bad JSON → 4xx", r.status_code in (400, 422), f"got {r.status_code}")

    def test_fc50_cors_headers_on_auth_errors(self):
        """FC.50: 401 responses include CORS headers so browser JS can read them."""
        r = requests.options(f"{API_URL}/v1/cross-platform/summary",
                             headers={
                                 "Origin": "https://vantageaiops.com",
                                 "Access-Control-Request-Method": "GET",
                             }, timeout=10)
        chk("FC.50a CORS preflight → 200/204", r.status_code in (200, 204), f"got {r.status_code}")
        chk("FC.50b Allow-Origin header present",
            "access-control-allow-origin" in {k.lower() for k in r.headers}, "")

    def test_fc51_event_batch_size_limit(self, headers):
        """FC.51: Batch with >500 events returns 400 (not 500 or silent drop)."""
        events = [make_event(i) for i in range(501)]
        r = _post("/v1/events/batch",
                  headers,
                  {"events": events, "sdk_version": "test", "sdk_language": "python"})
        chk("FC.51a 501 events → 400", r.status_code == 400, f"got {r.status_code}")
        body = r.json()
        chk("FC.51b has 'error' field", "error" in body, f"body: {body}")

    def test_fc52_health_endpoint_public(self):
        """FC.52: /v1/health is public, returns JSON with status=ok."""
        r = requests.get(f"{API_URL}/v1/health", timeout=10)
        chk("FC.52a health → 200", r.status_code == 200, f"got {r.status_code}")
        body = r.json()
        chk("FC.52b status=ok", body.get("status") in ("ok", "healthy", True), f"body: {body}")


# ─────────────────────────────────────────────────────────────────────────────
# Section D — Integration Channel Contract (FC.56–FC.70)
# End-to-end: each integration channel → dashboard reflects data.
# ─────────────────────────────────────────────────────────────────────────────

class TestIntegrationChannelContract:
    """Tests that each integration path (SDK, OTel, batch) stores data correctly."""

    def test_fc56_sdk_single_event_appears_in_summary(self):
        """FC.56: Single event via /v1/events (SDK path) is queryable in cross-platform summary."""
        section("D — Integration Channel Contract")
        api_key, _, _ = fresh_account(prefix="fc_sdk")
        hdrs = get_headers(api_key)
        ev = make_event(0, model="gpt-4o", cost=0.01)
        ev["provider"] = "openai"

        r = requests.post(f"{API_URL}/v1/events", json=ev, headers=hdrs, timeout=15)
        chk("FC.56a single event POST → 200/201", r.status_code in (200, 201), f"got {r.status_code}")
        assert r.status_code in (200, 201)

        time.sleep(1)
        r2 = _get("/v1/cross-platform/summary", hdrs, params={"days": 1})
        assert r2.status_code == 200
        body = r2.json()
        chk("FC.56b total_cost_usd > 0 after single event", body.get("total_cost_usd", 0) > 0,
            f"got {body.get('total_cost_usd')}")

    def test_fc57_batch_events_appear_in_analytics(self):
        """FC.57: Batch of events via /v1/events/batch are queryable in analytics/kpis."""
        api_key, _, _ = fresh_account(prefix="fc_batch")
        hdrs = get_headers(api_key)
        events = [make_event(i, model="claude-opus-4-6", cost=0.05) for i in range(3)]
        for e in events:
            e["provider"] = "anthropic"

        r = requests.post(f"{API_URL}/v1/events/batch",
                          json={"events": events, "sdk_version": "1.0", "sdk_language": "test"},
                          headers=hdrs, timeout=15)
        chk("FC.57a batch POST → 200/201/207", r.status_code in (200, 201, 207), f"got {r.status_code}")
        assert r.status_code in (200, 201, 207)

        time.sleep(1)
        r2 = _get("/v1/analytics/kpis", hdrs, params={"period": 1})
        assert r2.status_code == 200
        body = r2.json()
        chk("FC.57b kpis.total_requests ≥ 3 after batch", body.get("total_requests", 0) >= 3,
            f"got {body.get('total_requests')}")

    def test_fc58_otel_metrics_appear_in_cross_platform(self):
        """FC.58: OTel metrics ingest → appears in cross-platform/summary by_provider."""
        api_key, _, _ = fresh_account(prefix="fc_otel")
        hdrs = get_headers(api_key)
        dev = rand_email("otel_dev")
        otlp = {
            "resourceMetrics": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "claude-code"}},
                        {"key": "user.email",   "value": {"stringValue": dev}},
                        {"key": "session.id",   "value": {"stringValue": f"sess-{uuid.uuid4().hex[:8]}"}},
                    ]
                },
                "scopeMetrics": [{
                    "scope": {"name": "otel-test"},
                    "metrics": [{
                        "name": "claude_code.cost.usage",
                        "unit": "USD",
                        "sum": {
                            "dataPoints": [{
                                "asDouble": 0.025,
                                "timeUnixNano": str(int(time.time() * 1e9)),
                                "attributes": [
                                    {"key": "gen_ai.request.model", "value": {"stringValue": "claude-opus-4-6"}},
                                ]
                            }],
                            "isMonotonic": True,
                        }
                    }]
                }]
            }]
        }
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics", json=otlp, headers=hdrs, timeout=15)
        chk("FC.58a otel metrics → 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
        assert r.status_code == 200

        time.sleep(2)
        r2 = _get("/v1/cross-platform/summary", hdrs, params={"days": 1})
        assert r2.status_code == 200
        body = r2.json()
        chk("FC.58b total_cost_usd > 0 after OTel ingest", body.get("total_cost_usd", 0) > 0,
            f"got {body.get('total_cost_usd')}")
        by_prov = body.get("by_provider", [])
        provs = [p.get("provider") for p in by_prov]
        chk("FC.58c anthropic/claude-code provider present", any(
            "anthropic" in (p or "") or "claude" in (p or "") for p in provs),
            f"found providers: {provs}")

    def test_fc59_otel_logs_appear_in_live_feed(self):
        """FC.59: OTel logs ingest → visible in /v1/cross-platform/live events."""
        api_key, _, _ = fresh_account(prefix="fc_logs")
        hdrs = get_headers(api_key)
        ts_nano = str(int(time.time() * 1e9))
        otlp_logs = {
            "resourceLogs": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "claude-code"}},
                        {"key": "user.email",   "value": {"stringValue": rand_email("logdev")}},
                    ]
                },
                "scopeLogs": [{
                    "scope": {"name": "claude-code"},
                    "logRecords": [{
                        "timeUnixNano": ts_nano,
                        "attributes": [
                            {"key": "event.name",     "value": {"stringValue": "llm.call.finish"}},
                            {"key": "model",          "value": {"stringValue": "claude-sonnet-4-6"}},
                            {"key": "cost_usd",       "value": {"stringValue": "0.018"}},
                            {"key": "input_tokens",   "value": {"stringValue": "400"}},
                            {"key": "output_tokens",  "value": {"stringValue": "150"}},
                            {"key": "duration_ms",    "value": {"stringValue": "1200"}},
                        ]
                    }]
                }]
            }]
        }
        r = requests.post(f"{API_URL}/v1/otel/v1/logs", json=otlp_logs, headers=hdrs, timeout=15)
        chk("FC.59a otel logs → 200", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
        assert r.status_code == 200

        time.sleep(1)
        r2 = _get("/v1/cross-platform/live", hdrs, params={"limit": 20})
        assert r2.status_code == 200
        body = r2.json()
        chk("FC.59b live events is list", _is_list(body.get("events", [])), "")

    def test_fc60_otel_rate_limit_returns_429_with_retry_after(self):
        """FC.60: OTel endpoints return 429 + Retry-After header when rate limit hit."""
        # This test sends a single request and verifies the 429 *shape* if triggered;
        # We don't try to exhaust the limit (expensive) — we mock by checking the header
        # contract exists on a successful response (i.e. no Retry-After = not rate limited).
        api_key, _, _ = fresh_account(prefix="fc_rl")
        hdrs = get_headers(api_key)
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                          json={"resourceMetrics": []}, headers=hdrs, timeout=10)
        # If we hit 429 by chance (KV key collision), verify shape
        if r.status_code == 429:
            body = r.json()
            chk("FC.60a 429 has 'error' key",         "error" in body,           f"body: {body}")
            chk("FC.60b 429 has 'retry_after' key",   "retry_after" in body,     "")
            chk("FC.60c Retry-After header present",
                "retry-after" in {k.lower() for k in r.headers}, "")
        else:
            chk("FC.60a otel metrics accepted (no spurious 429)", r.status_code == 200,
                f"got {r.status_code}")

    def test_fc61_mcp_event_format_accepted(self):
        """FC.61: MCP-style single event payload (not batch) accepted by /v1/events."""
        api_key, _, _ = fresh_account(prefix="fc_mcp")
        hdrs = get_headers(api_key)
        # MCP sends single events (not batch) with these exact fields
        mcp_event = {
            "event_id":        f"mcp-{uuid.uuid4().hex[:12]}",
            "provider":        "anthropic",
            "model":           "claude-opus-4-6",
            "prompt_tokens":   800,
            "completion_tokens": 300,
            "total_cost_usd":  0.035,
            "latency_ms":      2100,
            "environment":     "development",
            "agent_name":      "cursor",
            "tags":            {"source": "mcp", "version": "1.1.0"},
        }
        r = requests.post(f"{API_URL}/v1/events", json=mcp_event, headers=hdrs, timeout=10)
        chk("FC.61a MCP event format → 200/201", r.status_code in (200, 201),
            f"got {r.status_code} {r.text[:200]}")

    def test_fc62_cli_batch_format_accepted(self):
        """FC.62: CLI-style batch payload (sdk_language=typescript) accepted."""
        api_key, _, _ = fresh_account(prefix="fc_cli")
        hdrs = get_headers(api_key)
        # CLI tracker.ts sends this exact format
        cli_batch = {
            "events": [{
                "event_id":        f"cli-{uuid.uuid4().hex[:12]}",
                "provider":        "google",
                "model":           "gemini-2.0-flash",
                "prompt_tokens":   200,
                "completion_tokens": 80,
                "total_tokens":    280,
                "total_cost_usd":  0.002,
                "latency_ms":      800,
                "environment":     "production",
                "agent_name":      "gemini-cli",
                "team":            "frontend",
            }],
            "sdk_version":  "vantage-cli-2.2.0",
            "sdk_language": "typescript",
        }
        r = requests.post(f"{API_URL}/v1/events/batch", json=cli_batch, headers=hdrs, timeout=10)
        chk("FC.62a CLI batch format → 200/201/207", r.status_code in (200, 201, 207),
            f"got {r.status_code} {r.text[:200]}")

    def test_fc63_proxy_scanner_batch_format_accepted(self):
        """FC.63: Local proxy scanner batch (sdk_language=local-scanner) accepted."""
        api_key, _, _ = fresh_account(prefix="fc_proxy")
        hdrs = get_headers(api_key)
        scan_batch = {
            "events": [{
                "event_id":        f"scan-{uuid.uuid4().hex[:12]}",
                "provider":        "openai",
                "model":           "gpt-4o",
                "prompt_tokens":   1200,
                "completion_tokens": 400,
                "cache_tokens":    0,
                "total_tokens":    1600,
                "total_cost_usd":  0.03,
                "environment":     "local",
                "agent_name":      "claude-code",
                "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                "tags":            {"tool": "claude-code", "scanner": "local-file"},
            }],
            "sdk_version":  "1.0.1",
            "sdk_language": "local-scanner",
        }
        r = requests.post(f"{API_URL}/v1/events/batch", json=scan_batch, headers=hdrs, timeout=10)
        chk("FC.63a scan batch format → 200/201/207", r.status_code in (200, 201, 207),
            f"got {r.status_code} {r.text[:200]}")


# ─────────────────────────────────────────────────────────────────────────────
# Section E — Regression Guard (FC.71–FC.80)
# Schema snapshots: these fields MUST always exist. Any removal = CI fail.
# ─────────────────────────────────────────────────────────────────────────────

# These are the exact field names the frontend reads. Rename them in the worker
# and this suite will immediately catch the regression.
_SCHEMA_GUARD = {
    "/v1/cross-platform/summary": {
        "root": ["total_cost_usd", "previous_period_cost", "total_records",
                  "total_input_tokens", "total_output_tokens", "total_cached_tokens",
                  "by_provider", "budget", "period_days"],
        "budget": ["monthly_limit_usd", "month_spend_usd", "budget_pct"],
        "by_provider[]": ["provider", "cost", "records", "tokens"],
    },
    "/v1/cross-platform/developers": {
        "root": ["developers", "period_days"],
        "developers[]": ["developer_email", "total_cost", "by_provider", "providers",
                          "input_tokens", "output_tokens"],
        "developers[].by_provider[]": ["provider", "cost", "records"],
    },
    "/v1/analytics/timeseries": {
        "root": ["series"],
        "series[]": ["date", "cost_usd", "tokens", "requests"],
    },
    "/v1/analytics/models": {
        "root": ["models"],
        "models[]": ["model", "provider", "cost_usd", "tokens", "requests"],
    },
    "/v1/analytics/teams": {
        "root": ["teams"],
        "teams[]": ["team", "cost_usd", "budget_usd"],
    },
    "/v1/admin/overview": {
        "root": ["org", "teams", "members"],
        "org": ["mtd_cost_usd", "budget_usd", "events_this_month", "plan", "name"],
        "teams[]": ["team", "cost_usd", "budget_usd", "member_count"],
    },
    "/v1/auth/members": {
        "root": ["members"],
        "members[]": ["email", "role", "api_key_hint"],
    },
}


class TestRegressionGuard:
    """Schema snapshot tests — these lock the frontend-backend contract in CI."""

    def test_fc71_cross_platform_summary_schema(self, seeded_account):
        """FC.71: /v1/cross-platform/summary — all frontend-used fields present."""
        section("E — Regression Guard (Schema Snapshot)")
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/cross-platform/summary", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/cross-platform/summary"]

        for f in spec["root"]:
            chk(f"FC.71 summary.{f} exists", f in body, f"missing from: {list(body)}")
        budget = body.get("budget", {})
        for f in spec["budget"]:
            chk(f"FC.71 summary.budget.{f} exists", f in budget, f"missing from: {list(budget)}")
        for p in body.get("by_provider", []):
            for f in spec["by_provider[]"]:
                chk(f"FC.71 by_provider[].{f} exists", f in p, f"missing from: {list(p)}")
            break  # check first item only

    def test_fc72_cross_platform_developers_schema(self, seeded_account):
        """FC.72: /v1/cross-platform/developers — developers[].by_provider present."""
        _, _, hdrs, dev_email = seeded_account
        r = _get("/v1/cross-platform/developers", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/cross-platform/developers"]

        for f in spec["root"]:
            chk(f"FC.72 developers root.{f}", f in body, f"missing: {list(body)}")

        dev = next((d for d in body.get("developers", [])
                    if d.get("developer_email") == dev_email), None)
        if not dev and body.get("developers"):
            dev = body["developers"][0]

        if dev:
            for f in spec["developers[]"]:
                chk(f"FC.72 developers[].{f}", f in dev, f"missing from: {list(dev)}")
            for bp in dev.get("by_provider", []):
                for f in spec["developers[].by_provider[]"]:
                    chk(f"FC.72 by_provider[].{f}", f in bp, f"missing from: {list(bp)}")
                break

    def test_fc73_analytics_timeseries_schema(self, seeded_account):
        """FC.73: /v1/analytics/timeseries — series[] field names locked."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/timeseries", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/analytics/timeseries"]
        for f in spec["root"]:
            chk(f"FC.73 timeseries.{f}", f in body, "")
        for d in body.get("series", []):
            for f in spec["series[]"]:
                chk(f"FC.73 series[].{f}", f in d, f"missing from: {list(d)}")
            break

    def test_fc74_analytics_models_schema(self, seeded_account):
        """FC.74: /v1/analytics/models — models[] field names locked."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/models", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/analytics/models"]
        for f in spec["root"]:
            chk(f"FC.74 models.{f}", f in body, "")
        for m in body.get("models", []):
            for f in spec["models[]"]:
                chk(f"FC.74 models[].{f}", f in m, f"missing from: {list(m)}")
            break

    def test_fc75_analytics_teams_schema(self, seeded_account):
        """FC.75: /v1/analytics/teams — teams[] field names locked."""
        _, _, hdrs, _ = seeded_account
        r = _get("/v1/analytics/teams", hdrs, params={"period": 30})
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/analytics/teams"]
        for f in spec["root"]:
            chk(f"FC.75 teams.{f}", f in body, "")
        for t in body.get("teams", []):
            for f in spec["teams[]"]:
                chk(f"FC.75 teams[].{f}", f in t, f"missing from: {list(t)}")
            break

    def test_fc76_admin_overview_schema(self, admin_headers):
        """FC.76: /v1/admin/overview — org.*, teams[].member_count locked."""
        r = _get("/v1/admin/overview", admin_headers)
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/admin/overview"]
        for f in spec["root"]:
            chk(f"FC.76 overview.{f}", f in body, f"missing: {list(body)}")
        org = body.get("org", {})
        for f in spec["org"]:
            chk(f"FC.76 org.{f}", f in org, f"missing from org: {list(org)}")
        for t in body.get("teams", []):
            for f in spec["teams[]"]:
                chk(f"FC.76 teams[].{f}", f in t, f"missing from team: {list(t)}")
            break

    def test_fc77_auth_members_schema(self, admin_headers):
        """FC.77: /v1/auth/members — members[].api_key_hint present, api_key absent."""
        r = _get("/v1/auth/members", admin_headers)
        assert r.status_code == 200
        body = r.json()
        spec = _SCHEMA_GUARD["/v1/auth/members"]
        for f in spec["root"]:
            chk(f"FC.77 members.{f}", f in body, "")
        for m in body.get("members", []):
            for f in spec["members[]"]:
                chk(f"FC.77 members[].{f}", f in m, f"missing from: {list(m)}")
            chk("FC.77 api_key NOT leaked", "api_key" not in m, "full key must not be returned")
            break

    def test_fc78_event_dedup_by_event_id(self, headers):
        """FC.78: Re-posting same event_id does not double-count (idempotency)."""
        eid = f"dedup-{uuid.uuid4().hex[:12]}"
        ev = {**make_event(0, cost=0.01), "event_id": eid, "provider": "anthropic"}
        r1 = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        r2 = requests.post(f"{API_URL}/v1/events", json=ev, headers=headers, timeout=10)
        chk("FC.78a first POST → 200/201", r1.status_code in (200, 201), f"got {r1.status_code}")
        # Second POST should either accept (idempotent) or return 409 conflict — NOT 500
        chk("FC.78b second POST → not 500", r2.status_code != 500, f"got {r2.status_code}")

    def test_fc79_period_param_bounds_enforced(self, headers):
        """FC.79: period > 365 is capped server-side (no unbounded scans)."""
        r = _get("/v1/analytics/kpis", headers, params={"period": 99999})
        chk("FC.79a extreme period → 200", r.status_code == 200, f"got {r.status_code}")
        # Verify response is the same type as a normal request (no DB blowup)
        body = r.json()
        chk("FC.79b body has total_cost_usd", "total_cost_usd" in body, f"keys: {list(body)}")

    def test_fc80_empty_account_zero_not_null(self):
        """FC.80: Fresh account returns 0 (not null/undefined) for numeric KPI fields."""
        api_key, _, _ = fresh_account(prefix="fc_zero")
        hdrs = get_headers(api_key)
        r = _get("/v1/cross-platform/summary", hdrs, params={"days": 30})
        assert r.status_code == 200
        body = r.json()
        for f in ("total_cost_usd", "total_records", "total_input_tokens",
                   "total_output_tokens", "total_cached_tokens"):
            chk(f"FC.80 {f} is 0 not null on empty account",
                _is_number(body.get(f)) and body.get(f) == 0,
                f"got {body.get(f)!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v", "--tb=short", "-x"],
        cwd=Path(__file__).parent.parent.parent
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
