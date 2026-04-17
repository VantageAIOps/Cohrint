"""
Test Suite 52 — Cost Forecasting
==================================

Tests the forecast fields added to GET /v1/analytics/summary.

  A. Field presence   (CF.1–CF.4)  — forecast fields present in response
  B. Logic            (CF.5–CF.8)  — values are mathematically correct
  C. Edge cases       (CF.9–CF.11) — no budget set, no spend, month boundary

Uses da45 persistent seed accounts. Never creates fresh accounts.
All tests hit https://api.cohrint.com (no mocking).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import API_URL
from helpers.output import section, chk, warn

SEED_FILE = Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json"
if not SEED_FILE.exists():
    pytest.skip("da45_seed_state.json not found — run seed.py first", allow_module_level=True)

_seed = json.loads(SEED_FILE.read_text())
ADMIN_KEY  = _seed["admin"]["api_key"]
MEMBER_KEY = _seed["member"]["api_key"]

BASE = API_URL.rstrip("/")


def _api(path: str, key: str = ADMIN_KEY, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {key}"
    return requests.get(f"{BASE}{path}", headers=headers, timeout=15, **kwargs)


# ── A. Field Presence ───────────────────────────────────────────────────────

class TestForecastFieldPresence:
    def test_CF01_summary_returns_200(self):
        """CF.1 — GET /v1/analytics/summary returns 200."""
        section("CF.1 — summary 200")
        r = _api("/v1/analytics/summary")
        chk("200", r.status_code == 200)

    def test_CF02_projected_month_end_present(self):
        """CF.2 — Response contains projected_month_end_usd field."""
        section("CF.2 — projected_month_end_usd present")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert "projected_month_end_usd" in body, f"missing projected_month_end_usd, got keys: {list(body.keys())}"
        chk("has projected_month_end_usd", True)

    def test_CF03_days_until_budget_exhausted_present(self):
        """CF.3 — Response contains days_until_budget_exhausted field."""
        section("CF.3 — days_until_budget_exhausted present")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert "days_until_budget_exhausted" in body, f"missing days_until_budget_exhausted, got keys: {list(body.keys())}"
        chk("has days_until_budget_exhausted", True)

    def test_CF04_daily_avg_cost_present(self):
        """CF.4 — Response contains daily_avg_cost_usd field."""
        section("CF.4 — daily_avg_cost_usd present")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert "daily_avg_cost_usd" in body, f"missing daily_avg_cost_usd, got keys: {list(body.keys())}"
        chk("has daily_avg_cost_usd", True)


# ── B. Logic ────────────────────────────────────────────────────────────────

class TestForecastLogic:
    def test_CF05_projected_non_negative(self):
        """CF.5 — projected_month_end_usd is >= 0."""
        section("CF.5 — projected >= 0")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        val = body.get("projected_month_end_usd")
        chk("projected >= 0", val is None or val >= 0)

    def test_CF06_projected_gte_mtd(self):
        """CF.6 — projected_month_end_usd >= mtd_cost_usd (can't spend less than already spent)."""
        section("CF.6 — projected >= mtd")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        projected = body.get("projected_month_end_usd")
        mtd = body.get("mtd_cost_usd", 0)
        if projected is not None:
            chk("projected >= mtd", projected >= mtd - 0.0001)  # float tolerance

    def test_CF07_daily_avg_equals_mtd_over_days_elapsed(self):
        """CF.7 — daily_avg_cost_usd is approximately mtd_cost_usd / days_elapsed."""
        section("CF.7 — daily_avg = mtd / days_elapsed")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        mtd = body.get("mtd_cost_usd", 0)
        daily_avg = body.get("daily_avg_cost_usd")
        if daily_avg is None:
            return
        now = datetime.now(timezone.utc)
        days_elapsed = max(now.day, 1)
        expected = round(mtd / days_elapsed, 6)
        chk("daily_avg approx correct", abs(daily_avg - expected) < 0.01)

    def test_CF08_days_until_exhausted_null_when_no_budget(self):
        """CF.8 — days_until_budget_exhausted is null when no budget is set."""
        section("CF.8 — null when no budget")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        budget = body.get("budget_usd", 0)
        days = body.get("days_until_budget_exhausted")
        if budget == 0:
            chk("null when no budget", days is None)
        else:
            warn("org has budget set — skipping null check")


# ── C. Edge Cases ────────────────────────────────────────────────────────────

class TestForecastEdgeCases:
    def test_CF09_projected_type_float_or_null(self):
        """CF.9 — projected_month_end_usd is float or null, never a string."""
        section("CF.9 — projected is float or null")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert "projected_month_end_usd" in body
        val = body["projected_month_end_usd"]
        assert val is None or isinstance(val, (int, float)), f"expected float or null, got {type(val)}: {val}"
        chk("float or null", True)

    def test_CF10_days_until_exhausted_positive_or_null(self):
        """CF.10 — days_until_budget_exhausted is non-negative int or null (0 = budget already exceeded)."""
        section("CF.10 — days > 0 or null")
        r = _api("/v1/analytics/summary")
        assert r.status_code == 200
        body = r.json()
        assert "days_until_budget_exhausted" in body
        days = body["days_until_budget_exhausted"]
        assert days is None or days >= 0, f"expected non-negative or null, got {days}"
        chk("positive or null", True)

    def test_CF11_member_also_gets_forecast_fields(self):
        """CF.11 — member-scoped token also receives forecast fields."""
        section("CF.11 — member gets forecast fields")
        r = _api("/v1/analytics/summary", key=MEMBER_KEY)
        assert r.status_code == 200
        body = r.json()
        assert "projected_month_end_usd" in body, "member missing projected_month_end_usd"
        assert "daily_avg_cost_usd" in body, "member missing daily_avg_cost_usd"
        chk("member has projected + daily_avg", True)
