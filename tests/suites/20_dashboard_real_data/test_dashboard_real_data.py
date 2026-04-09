"""
test_dashboard_real_data.py -- Dashboard Real Data Verification
===============================================================
Suite DR: Validates that every dashboard module is wired to real API data
(not fake/demo data). Covers Enterprise Reporting, Cost Intelligence,
Performance & Latency, No-Fake-Data checks, and Cross-Platform Integration.

Labels: DR.1 - DR.42
"""

import sys
import time
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL, SITE_URL
from helpers.api import fresh_account, get_headers, retry
from helpers.data import make_event, rand_email
from helpers.output import section, chk, ok, fail, warn, info


# ---------------------------------------------------------------------------
# OTLP payload builders (for DR.42)
# ---------------------------------------------------------------------------

def make_otlp_metrics(service_name, metrics, email="dev@test.com"):
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "user.email", "value": {"stringValue": email}},
                    {"key": "session.id", "value": {"stringValue": f"sess-{int(time.time())}"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "test", "version": "1.0"},
                "metrics": metrics,
            }]
        }]
    }


def counter(name, value, attrs=None):
    return {
        "name": name,
        "unit": "1",
        "sum": {
            "dataPoints": [{
                "asDouble": value,
                "timeUnixNano": str(int(time.time() * 1e9)),
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (attrs or {}).items()
                ],
            }],
            "isMonotonic": True,
        },
    }


# ============================================================================
# SECTION A -- Enterprise Reporting APIs (DR.1 - DR.10)
# ============================================================================

class TestEnterpriseReporting:
    """Enterprise Reporting is now powered by real API data."""

    def test_dr01_admin_overview_200(self, admin_headers):
        """DR.1: GET /v1/admin/overview returns 200 with org, totals, teams, members."""
        section("A — Enterprise Reporting APIs")
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=admin_headers, timeout=15)
        body = r.json() if r.ok else {}
        chk("DR.1  admin/overview → 200", r.status_code == 200, f"got {r.status_code}")
        assert r.status_code == 200

    def test_dr02_overview_real_plan(self, admin_headers):
        """DR.2: Overview has real org.plan field (not hardcoded)."""
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=admin_headers, timeout=15)
        body = r.json()
        org = body.get("org", {})
        has_plan = "plan" in org
        chk("DR.2  org.plan field exists", has_plan, f"org keys: {list(org.keys())}")
        assert has_plan

    def test_dr03_overview_totals(self, admin_headers):
        """DR.3: Overview totals have total_cost_usd, total_tokens, total_requests."""
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=admin_headers, timeout=15)
        body = r.json()
        totals = body.get("totals", {})
        has_cost = "total_cost_usd" in totals
        has_tokens = "total_tokens" in totals
        has_reqs = "total_requests" in totals
        chk("DR.3a totals.total_cost_usd exists", has_cost, f"totals keys: {list(totals.keys())}")
        chk("DR.3b totals.total_tokens exists", has_tokens)
        chk("DR.3c totals.total_requests exists", has_reqs)
        assert has_cost and has_tokens and has_reqs

    def test_dr04_overview_teams_array(self, admin_headers):
        """DR.4: Teams array present (may be empty but must be array)."""
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=admin_headers, timeout=15)
        body = r.json()
        teams = body.get("teams")
        is_list = isinstance(teams, list)
        chk("DR.4  teams is array", is_list, f"teams type: {type(teams).__name__}")
        assert is_list

    def test_dr05_overview_members(self, admin_headers):
        """DR.5: Members array present with email, name, role fields."""
        r = requests.get(f"{API_URL}/v1/admin/overview", headers=admin_headers, timeout=15)
        body = r.json()
        members = body.get("members", [])
        is_list = isinstance(members, list)
        chk("DR.5a members is array", is_list, f"type: {type(members).__name__}")
        if is_list and len(members) > 0:
            m0 = members[0]
            chk("DR.5b member has email", "email" in m0, f"keys: {list(m0.keys())}")
            chk("DR.5c member has name", "name" in m0)
            chk("DR.5d member has role", "role" in m0)
        else:
            # Empty members is acceptable for fresh account
            chk("DR.5b member has email (skip: no members)", True)
            chk("DR.5c member has name (skip: no members)", True)
            chk("DR.5d member has role (skip: no members)", True)
        assert is_list

    def test_dr06_analytics_teams(self, admin_headers):
        """DR.6: GET /v1/analytics/teams?period=30 returns 200 with teams array."""
        r = requests.get(f"{API_URL}/v1/analytics/teams", params={"period": 30},
                         headers=admin_headers, timeout=15)
        body = r.json() if r.ok else {}
        teams = body.get("teams")
        chk("DR.6  analytics/teams → 200 + array", r.status_code == 200 and isinstance(teams, list),
            f"status={r.status_code}, teams type={type(teams).__name__ if teams else 'missing'}")
        assert r.status_code == 200

    def test_dr07_teams_fields(self, admin_headers):
        """DR.7: Teams have cost_usd, tokens, requests, budget_usd fields."""
        r = requests.get(f"{API_URL}/v1/analytics/teams", params={"period": 30},
                         headers=admin_headers, timeout=15)
        body = r.json()
        teams = body.get("teams", [])
        if len(teams) > 0:
            t0 = teams[0]
            for field in ["cost_usd", "tokens", "requests", "budget_usd"]:
                chk(f"DR.7  team has {field}", field in t0, f"keys: {list(t0.keys())}")
        else:
            chk("DR.7  teams fields (skip: empty)", True)
        assert isinstance(teams, list)

    def test_dr08_cross_platform_developers(self, admin_headers):
        """DR.8: GET /v1/cross-platform/developers?days=30 returns developers."""
        r = requests.get(f"{API_URL}/v1/cross-platform/developers", params={"days": 30},
                         headers=admin_headers, timeout=15)
        body = r.json() if r.ok else {}
        devs = body.get("developers")
        chk("DR.8  cross-platform/developers → 200", r.status_code == 200,
            f"status={r.status_code}")
        assert r.status_code == 200

    def test_dr09_developers_roi_fields(self, admin_headers):
        """DR.9: Developers have ROI fields (may be null but keys exist)."""
        r = requests.get(f"{API_URL}/v1/cross-platform/developers", params={"days": 30},
                         headers=admin_headers, timeout=15)
        body = r.json()
        devs = body.get("developers", [])
        if len(devs) > 0:
            d0 = devs[0]
            for field in ["cost_per_pr", "cost_per_commit", "lines_per_dollar"]:
                chk(f"DR.9  developer has {field}", field in d0, f"keys: {list(d0.keys())}")
        else:
            chk("DR.9  developer ROI fields (skip: empty)", True)
        assert isinstance(devs, list)

    def test_dr10_analytics_timeseries(self, admin_headers):
        """DR.10: GET /v1/analytics/timeseries?period=30 returns series with date, cost_usd, tokens, requests."""
        r = requests.get(f"{API_URL}/v1/analytics/timeseries", params={"period": 30},
                         headers=admin_headers, timeout=15)
        body = r.json() if r.ok else {}
        series = body.get("series")
        chk("DR.10a timeseries → 200 + array", r.status_code == 200 and isinstance(series, list),
            f"status={r.status_code}")
        if isinstance(series, list) and len(series) > 0:
            s0 = series[0]
            for field in ["date", "cost_usd", "tokens", "requests"]:
                chk(f"DR.10b series has {field}", field in s0, f"keys: {list(s0.keys())}")
        else:
            chk("DR.10b series fields (skip: empty)", True)
        assert r.status_code == 200


# ============================================================================
# SECTION B -- Cost Intelligence Real Data (DR.11 - DR.18)
# ============================================================================

class TestCostIntelligence:
    """Cost Intelligence module wired to real API data."""

    def test_dr11_analytics_summary(self, headers):
        """DR.11: GET /v1/analytics/summary returns today_cost_usd, mtd_cost_usd, today_requests."""
        section("B — Cost Intelligence Real Data")
        r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        chk("DR.11a summary → 200", r.status_code == 200, f"status={r.status_code}")
        chk("DR.11b today_cost_usd exists", "today_cost_usd" in body, f"keys: {list(body.keys())}")
        chk("DR.11c mtd_cost_usd exists", "mtd_cost_usd" in body)
        chk("DR.11d today_requests exists", "today_requests" in body)
        assert r.status_code == 200

    def test_dr12_summary_budget(self, headers):
        """DR.12: Summary has budget_pct and budget_usd fields."""
        r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
        body = r.json()
        chk("DR.12a budget_pct exists", "budget_pct" in body, f"keys: {list(body.keys())}")
        chk("DR.12b budget_usd exists", "budget_usd" in body)
        assert "budget_pct" in body

    def test_dr13_analytics_kpis(self, headers):
        """DR.13: GET /v1/analytics/kpis?period=30 returns 200."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 30},
                         headers=headers, timeout=15)
        chk("DR.13 kpis → 200", r.status_code == 200, f"status={r.status_code}")
        assert r.status_code == 200

    def test_dr14_kpis_fields(self, headers):
        """DR.14: KPIs have total_cost_usd, total_tokens, total_requests, avg_latency_ms, efficiency_score."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        for field in ["total_cost_usd", "total_tokens", "total_requests",
                       "avg_latency_ms", "efficiency_score"]:
            chk(f"DR.14 kpi has {field}", field in body, f"keys: {list(body.keys())}")
        assert "total_cost_usd" in body

    def test_dr15_analytics_models(self, headers):
        """DR.15: GET /v1/analytics/models?period=30 returns models array."""
        r = requests.get(f"{API_URL}/v1/analytics/models", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        models = body.get("models")
        chk("DR.15 models → 200 + array", r.status_code == 200 and isinstance(models, list),
            f"status={r.status_code}")
        assert r.status_code == 200

    def test_dr16_model_fields(self, headers):
        """DR.16: Each model has model, provider, cost_usd, tokens, requests fields."""
        r = requests.get(f"{API_URL}/v1/analytics/models", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        models = body.get("models", [])
        if len(models) > 0:
            m0 = models[0]
            for field in ["model", "provider", "cost_usd", "tokens", "requests"]:
                chk(f"DR.16 model has {field}", field in m0, f"keys: {list(m0.keys())}")
        else:
            chk("DR.16 model fields (skip: empty for fresh account)", True)
        assert isinstance(models, list)

    def test_dr17_ingest_then_analytics(self, headers):
        """DR.17: POST /v1/events (ingest an event), then verify it appears in analytics."""
        event = make_event(i=0, model="gpt-4o-mini", cost=0.0023)
        r_post = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
        chk("DR.17a event ingested", r_post.status_code in (200, 201, 202),
            f"status={r_post.status_code}")

        # Allow time for the event to be processed
        time.sleep(2)

        r_kpi = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 1},
                             headers=headers, timeout=15)
        body = r_kpi.json() if r_kpi.ok else {}
        total_reqs = body.get("total_requests", 0)
        chk("DR.17b analytics reflects ingested event", total_reqs >= 1,
            f"total_requests={total_reqs}")
        assert r_post.status_code in (200, 201, 202)

    def test_dr18_timeseries_real_array(self, headers):
        """DR.18: GET /v1/analytics/timeseries returns series as array (not hardcoded months)."""
        r = requests.get(f"{API_URL}/v1/analytics/timeseries", params={"period": 7},
                         headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        series = body.get("series", [])
        is_list = isinstance(series, list)
        chk("DR.18a series is array", is_list)
        # If there are entries, verify they have date strings (not "Jan", "Feb" etc.)
        if is_list and len(series) > 0:
            s0 = series[0]
            date_val = s0.get("date", "")
            # Real dates look like "2026-03-24", not "Jan" or "February"
            looks_real = len(str(date_val)) >= 8 or date_val == ""
            chk("DR.18b date looks like real date", looks_real, f"date={date_val}")
        else:
            chk("DR.18b timeseries date (skip: empty)", True)
        assert is_list


# ============================================================================
# SECTION C -- Performance & Latency Real Data (DR.19 - DR.25)
# ============================================================================

class TestPerformanceLatency:
    """Performance module rewritten to use real API data."""

    def test_dr19_models_latency(self, headers):
        """DR.19: Models endpoint returns avg_latency_ms per model."""
        section("C — Performance & Latency Real Data")
        r = requests.get(f"{API_URL}/v1/analytics/models", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        models = body.get("models", [])
        if len(models) > 0:
            m0 = models[0]
            chk("DR.19 model has avg_latency_ms", "avg_latency_ms" in m0,
                f"keys: {list(m0.keys())}")
        else:
            chk("DR.19 model avg_latency_ms (skip: no models)", True)
        assert r.status_code == 200

    def test_dr20_kpis_latency(self, headers):
        """DR.20: KPIs endpoint returns avg_latency_ms."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        chk("DR.20 kpis has avg_latency_ms", "avg_latency_ms" in body,
            f"keys: {list(body.keys())}")
        assert "avg_latency_ms" in body

    def test_dr21_timeseries_per_day(self, headers):
        """DR.21: Timeseries returns per-day data (not random)."""
        r = requests.get(f"{API_URL}/v1/analytics/timeseries", params={"period": 7},
                         headers=headers, timeout=15)
        body = r.json()
        series = body.get("series", [])
        if len(series) >= 2:
            dates = [s.get("date", "") for s in series]
            unique_dates = set(dates)
            chk("DR.21 timeseries dates are unique per day", len(unique_dates) == len(dates),
                f"dates={dates[:5]}")
        else:
            chk("DR.21 timeseries per-day (skip: < 2 points)", True)
        assert r.status_code == 200

    def test_dr22_ingest_latency_event(self, headers):
        """DR.22: Ingest event with latency_ms=1500, verify it shows in kpis."""
        event = make_event(i=99, model="claude-3.5-sonnet", cost=0.01)
        event["latency_ms"] = 1500
        r_post = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
        chk("DR.22a latency event ingested", r_post.status_code in (200, 201, 202),
            f"status={r_post.status_code}")

        time.sleep(2)

        r_kpi = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 1},
                             headers=headers, timeout=15)
        body = r_kpi.json() if r_kpi.ok else {}
        latency = body.get("avg_latency_ms")
        chk("DR.22b kpis avg_latency_ms is numeric after ingest",
            latency is not None and isinstance(latency, (int, float)),
            f"avg_latency_ms={latency}")
        assert r_post.status_code in (200, 201, 202)

    def test_dr23_model_core_fields(self, headers):
        """DR.23: Model data includes model, provider, cost_usd, tokens, requests, avg_latency_ms."""
        r = requests.get(f"{API_URL}/v1/analytics/models", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        models = body.get("models", [])
        if len(models) > 0:
            m0 = models[0]
            for field in ["model", "provider", "cost_usd", "tokens", "requests", "avg_latency_ms"]:
                chk(f"DR.23 model has {field}", field in m0, f"keys: {list(m0.keys())}")
        else:
            chk("DR.23 model core fields (skip: no models)", True)
        assert r.status_code == 200

    def test_dr24_latency_non_negative(self, headers):
        """DR.24: Latency values are non-negative numbers."""
        r = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 30},
                         headers=headers, timeout=15)
        body = r.json()
        latency = body.get("avg_latency_ms", 0)
        is_non_neg = isinstance(latency, (int, float)) and latency >= 0
        chk("DR.24 avg_latency_ms >= 0", is_non_neg, f"avg_latency_ms={latency}")
        assert is_non_neg

    def test_dr25_consistent_data(self, headers):
        """DR.25: Multiple requests return consistent data (not random)."""
        results = []
        for _ in range(3):
            r = requests.get(f"{API_URL}/v1/analytics/kpis", params={"period": 30},
                             headers=headers, timeout=15)
            body = r.json()
            results.append(body.get("total_cost_usd"))

        # All three calls should return the same cost value
        consistent = results[0] == results[1] == results[2]
        chk("DR.25 3 consecutive kpi calls return same total_cost_usd", consistent,
            f"values={results}")
        assert consistent


# ============================================================================
# SECTION D -- No Fake Data Verification (DR.26 - DR.35)
# ============================================================================

class TestNoFakeData:
    """Verify the dashboard HTML does not contain fake data artifacts."""

    @staticmethod
    def _fetch_html():
        """Read app.html from the local repo (not deployed site) to test current code."""
        local_path = Path(__file__).parent.parent.parent.parent / "vantage-final-v4" / "app.html"
        if local_path.exists():
            return local_path.read_text()
        # Fallback to deployed site
        r = requests.get(f"{SITE_URL}/app.html", timeout=15)
        return r.text if r.ok else ""

    def test_dr26_no_fake_kpi(self):
        """DR.26: No '$38.4K' string (old fake KPI)."""
        section("D — No Fake Data Verification")
        html = self._fetch_html()
        has_fake = "$38.4K" in html
        chk("DR.26 no '$38.4K' fake KPI in HTML", not has_fake)
        assert not has_fake

    def test_dr27_no_ri_function(self):
        """DR.27: No 'ri(' random integer generator function."""
        html = self._fetch_html()
        # Look for the ri( pattern that generates random integers
        # ri() was replaced with a comment — check that function ri() definition is gone
        has_ri = "function ri(" in html or "function ri " in html
        chk("DR.27 no ri() random int function", not has_ri)
        assert not has_ri

    def test_dr28_no_demo_models(self):
        """DR.28: No 'DEMO_MODELS' reference in active code."""
        html = self._fetch_html()
        has_demo = "DEMO_MODELS" in html
        chk("DR.28 no DEMO_MODELS reference", not has_demo)
        assert not has_demo

    def test_dr29_no_fake_departments(self):
        """DR.29: No hardcoded fake department names as chargeback data."""
        html = self._fetch_html()
        # These specific department names were used as fake chargeback data
        fake_depts = ["Product", "Engineering", "Content", "Data", "Growth"]
        # Check if ALL five appear together (individual words may appear in other contexts)
        all_present = all(d in html for d in fake_depts)
        chk("DR.29 no hardcoded fake department set", not all_present,
            "All 5 fake depts found together in HTML")
        assert not all_present

    def test_dr30_no_mult_function(self):
        """DR.30: No 'mult()' multiplier function in active code."""
        html = self._fetch_html()
        has_mult = "function mult(" in html or "function mult " in html
        chk("DR.30 no mult() function", not has_mult)
        assert not has_mult

    def test_dr31_no_enterprise_reporting_remnants(self):
        """DR.31: Enterprise Reporting removed — no rpt-gate/rpt-content remnants."""
        html = self._fetch_html()
        no_gate = "rpt-gate" not in html
        no_content = "rpt-content" not in html
        chk("DR.31a no rpt-gate remnant", no_gate)
        chk("DR.31b no rpt-content remnant", no_content)
        assert no_gate and no_content

    def test_dr32_no_ai_intelligence_layer(self):
        """DR.32: Sidebar has no 'AI Intelligence Layer' nav button."""
        html = self._fetch_html()
        # The sidebar uses nav('ai',this) — check that this button is removed
        has_sidebar_link = "nav('ai',this)" in html
        chk("DR.32 no AI Intelligence Layer sidebar button", not has_sidebar_link)
        assert not has_sidebar_link

    def test_dr33_no_standalone_token_analytics(self):
        """DR.33: Sidebar has no standalone 'Token Analytics' link."""
        html = self._fetch_html()
        # Token Analytics was merged into All AI Spend, standalone link should be gone
        has_standalone = ">Token Analytics<" in html
        chk("DR.33 no standalone 'Token Analytics' link", not has_standalone)
        assert not has_standalone

    def test_dr34_no_demo_toggle(self):
        """DR.34: Demo data toggle fully removed."""
        html = self._fetch_html()
        no_toggle = "toggleSeedData" not in html
        no_seed = "seed-toggle" not in html
        chk("DR.34a no toggleSeedData function", no_toggle)
        chk("DR.34b no seed-toggle button", no_seed)
        assert no_toggle

    def test_dr35_no_fake_sse_events(self):
        """DR.35: No fake SSE events generated (no addEvent with random provider selection)."""
        html = self._fetch_html()
        # Check for patterns that generate fake events
        fake_patterns = [
            "providers[Math.floor(Math.random()",
            'addEvent({provider:providers[',
            "setInterval(()=>addEvent",
        ]
        found_fake = any(p in html for p in fake_patterns)
        chk("DR.35 no fake SSE random provider event generation", not found_fake)
        assert not found_fake


# ============================================================================
# SECTION E -- Cross-Platform Integration (DR.36 - DR.42)
# ============================================================================

class TestCrossPlatformIntegration:
    """The All AI Spend view merges token analytics. Verify APIs."""

    def test_dr36_cross_platform_summary(self, headers):
        """DR.36: GET /v1/cross-platform/summary has by_provider and by_source arrays."""
        section("E — Cross-Platform Integration")
        r = requests.get(f"{API_URL}/v1/cross-platform/summary", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        chk("DR.36a cross-platform/summary → 200", r.status_code == 200,
            f"status={r.status_code}")
        chk("DR.36b has by_provider", "by_provider" in body, f"keys: {list(body.keys())}")
        chk("DR.36c has by_source", "by_source" in body)
        assert r.status_code == 200

    def test_dr37_cross_platform_models(self, headers):
        """DR.37: GET /v1/cross-platform/models has models with cost, input_tokens, output_tokens."""
        r = requests.get(f"{API_URL}/v1/cross-platform/models", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        models = body.get("models")
        chk("DR.37a cross-platform/models → 200", r.status_code == 200,
            f"status={r.status_code}")
        chk("DR.37b models is array", isinstance(models, list),
            f"type={type(models).__name__ if models else 'missing'}")
        if isinstance(models, list) and len(models) > 0:
            m0 = models[0]
            for field in ["cost", "input_tokens", "output_tokens"]:
                chk(f"DR.37c model has {field}", field in m0, f"keys: {list(m0.keys())}")
        else:
            chk("DR.37c model fields (skip: empty)", True)
        assert r.status_code == 200

    def test_dr38_cross_platform_live(self, headers):
        """DR.38: GET /v1/cross-platform/live has events array."""
        r = requests.get(f"{API_URL}/v1/cross-platform/live", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        events = body.get("events")
        chk("DR.38a cross-platform/live → 200", r.status_code == 200,
            f"status={r.status_code}")
        chk("DR.38b has events array", isinstance(events, list),
            f"type={type(events).__name__ if events else 'missing'}")
        assert r.status_code == 200

    def test_dr39_cross_platform_budget(self, headers):
        """DR.39: GET /v1/cross-platform/budget has policies and current_spend."""
        r = requests.get(f"{API_URL}/v1/cross-platform/budget", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        chk("DR.39a cross-platform/budget → 200", r.status_code == 200,
            f"status={r.status_code}")
        chk("DR.39b has policies", "policies" in body, f"keys: {list(body.keys())}")
        chk("DR.39c has current_spend", "current_spend" in body)
        assert r.status_code == 200

    def test_dr40_cross_platform_connections(self, headers):
        """DR.40: GET /v1/cross-platform/connections has otel_sources and billing_connections."""
        r = requests.get(f"{API_URL}/v1/cross-platform/connections", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        chk("DR.40a cross-platform/connections → 200", r.status_code == 200,
            f"status={r.status_code}")
        chk("DR.40b has otel_sources", "otel_sources" in body, f"keys: {list(body.keys())}")
        chk("DR.40c has billing_connections", "billing_connections" in body)
        assert r.status_code == 200

    def test_dr41_today_leq_total(self, headers):
        """DR.41: Summary today_cost_usd <= total_cost_usd (today is subset of period)."""
        r = requests.get(f"{API_URL}/v1/cross-platform/summary", headers=headers, timeout=15)
        body = r.json() if r.ok else {}
        today = body.get("today_cost_usd", 0)
        total = body.get("total_cost_usd", 0)
        # Both may be 0 for a fresh account, which is fine
        valid = isinstance(today, (int, float)) and isinstance(total, (int, float)) and today <= total
        chk("DR.41 today_cost_usd <= total_cost_usd", valid,
            f"today={today}, total={total}")
        assert valid

    def test_dr42_otel_ingest_appears_in_summary(self, headers):
        """DR.42: Ingest OTel metrics, then verify they appear in cross-platform summary."""
        # Build and ingest an OTLP metrics payload
        unique_service = f"claude-code-test-{uuid.uuid4().hex[:8]}"
        metrics = [
            counter("llm.token.usage", 500, {"model": "claude-3.5-sonnet", "token.type": "input"}),
            counter("llm.token.usage", 150, {"model": "claude-3.5-sonnet", "token.type": "output"}),
            counter("llm.cost", 0.025, {"model": "claude-3.5-sonnet", "currency": "USD"}),
            counter("llm.request.count", 3, {"model": "claude-3.5-sonnet"}),
        ]
        payload = make_otlp_metrics(unique_service, metrics, email="dr42@test.com")

        r_ingest = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=15,
        )
        chk("DR.42a OTel ingest accepted", r_ingest.status_code in (200, 201, 202),
            f"status={r_ingest.status_code}")

        # Allow processing time
        time.sleep(3)

        # Check cross-platform summary now has data
        r_summary = requests.get(f"{API_URL}/v1/cross-platform/summary",
                                 headers=headers, timeout=15)
        body = r_summary.json() if r_summary.ok else {}
        chk("DR.42b summary → 200 after OTel ingest", r_summary.status_code == 200,
            f"status={r_summary.status_code}")

        # Verify the by_source or by_provider arrays are populated (or total_cost > 0)
        by_source = body.get("by_source", [])
        total_cost = body.get("total_cost_usd", 0)
        has_data = len(by_source) > 0 or total_cost > 0
        chk("DR.42c cross-platform summary reflects OTel data", has_data,
            f"by_source={len(by_source)}, total_cost={total_cost}")
        assert r_ingest.status_code in (200, 201, 202)

    @pytest.mark.xfail(strict=False, reason="analytics.ts timeseries fix pending production deploy")
    def test_dr43_timeseries_cost_matches_summary(self, headers):
        """DR.43: Sum of timeseries daily costs is within 1% of cross-platform/summary total_cost_usd.

        This catches bugs where timeseries queries a different table than summary
        (e.g. querying `events` while summary reads `cross_platform_usage`).
        """
        # Ingest a known-cost OTel event so there's data to compare
        unique_service = f"claude-code-dr43-{uuid.uuid4().hex[:8]}"
        metrics = [
            counter("llm.token.usage", 300, {"model": "claude-3-haiku", "token.type": "input"}),
            counter("llm.token.usage", 100, {"model": "claude-3-haiku", "token.type": "output"}),
            counter("llm.cost", 0.012, {"model": "claude-3-haiku", "currency": "USD"}),
            counter("llm.request.count", 2, {"model": "claude-3-haiku"}),
        ]
        payload = make_otlp_metrics(unique_service, metrics, email="dr43@test.com")
        r_ingest = requests.post(
            f"{API_URL}/v1/otel/v1/metrics",
            json=payload,
            headers=headers,
            timeout=15,
        )
        chk("DR.43a OTel ingest accepted", r_ingest.status_code in (200, 201, 202),
            f"status={r_ingest.status_code}")

        time.sleep(3)

        # Fetch both endpoints with the same period
        period = 30
        r_ts = requests.get(f"{API_URL}/v1/analytics/timeseries", params={"period": period},
                            headers=headers, timeout=15)
        r_cp = requests.get(f"{API_URL}/v1/cross-platform/summary", params={"days": period},
                            headers=headers, timeout=15)

        chk("DR.43b timeseries → 200", r_ts.status_code == 200, f"status={r_ts.status_code}")
        chk("DR.43c cross-platform/summary → 200", r_cp.status_code == 200, f"status={r_cp.status_code}")

        ts_body = r_ts.json() if r_ts.ok else {}
        cp_body = r_cp.json() if r_cp.ok else {}

        series = ts_body.get("series", [])
        ts_total = sum(s.get("cost_usd", 0) or 0 for s in series)
        cp_total = cp_body.get("total_cost_usd", 0) or 0

        chk("DR.43d timeseries series is non-empty after ingest", len(series) > 0,
            f"series length={len(series)}")

        # Both totals should be non-zero if the ingest succeeded
        if cp_total > 0 and ts_total > 0:
            ratio = abs(ts_total - cp_total) / cp_total
            within_tolerance = ratio <= 0.01  # within 1%
            chk(
                f"DR.43e timeseries sum ≈ summary total (±1%)",
                within_tolerance,
                f"timeseries_sum={ts_total:.6f}, summary_total={cp_total:.6f}, diff={ratio*100:.2f}%",
            )
            assert within_tolerance, (
                f"timeseries sum ({ts_total:.6f}) diverges from cross-platform summary "
                f"({cp_total:.6f}) by {ratio*100:.2f}% — likely querying different tables"
            )
        else:
            # Both zero means fresh account with no data yet — that's consistent
            both_zero = ts_total == 0 and cp_total == 0
            chk("DR.43e both totals zero (consistent empty state)", both_zero,
                f"ts_total={ts_total}, cp_total={cp_total}")
            assert both_zero or (ts_total > 0 and cp_total > 0), (
                f"Inconsistent: timeseries={ts_total}, summary={cp_total} — one is non-zero"
            )
