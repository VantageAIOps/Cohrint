"""
test_trend.py — 12 tests for GET /v1/cross-platform/trend
"""

import datetime
import requests

from config.settings import API_URL

BASE = f"{API_URL}/v1/cross-platform/trend"


# ── Response shape ────────────────────────────────────────────────────────────

def test_trend_has_required_keys(headers):
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    for key in ("days", "providers", "series", "period_days"):
        assert key in data, f"Missing key: {key}"


def test_trend_series_data_length_matches_days(headers):
    r = requests.get(BASE, headers=headers, params={"days": 7}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    n = len(data["days"])
    for entry in data["series"]:
        assert len(entry["data"]) == n, (
            f"provider {entry['provider']}: data[{len(entry['data'])}] != days[{n}]"
        )


def test_trend_period_days_field_matches_param(headers):
    for days in (7, 30, 90):
        r = requests.get(BASE, headers=headers, params={"days": days}, timeout=15)
        assert r.status_code == 200
        assert r.json()["period_days"] == days


# ── Full calendar spine ───────────────────────────────────────────────────────

def test_trend_empty_org_returns_full_7d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 7}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert len(data["days"]) == 7
    assert data["series"] == []


def test_trend_empty_org_returns_full_30d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["days"]) == 30


def test_trend_empty_org_returns_full_90d_spine(empty_headers):
    r = requests.get(BASE, headers=empty_headers, params={"days": 90}, timeout=15)
    assert r.status_code == 200
    assert len(r.json()["days"]) == 90


def test_trend_days_are_in_ascending_order(headers):
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    days = r.json()["days"]
    assert days == sorted(days)


def test_trend_non_today_entries_are_zero(headers):
    """Seeded account has data for today only. All other days must be 0.0."""
    r = requests.get(BASE, headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    today = datetime.date.today().isoformat()
    today_idx = data["days"].index(today) if today in data["days"] else None
    for entry in data["series"]:
        for i, v in enumerate(entry["data"]):
            if today_idx is not None and i == today_idx:
                continue
            assert v == 0 or v == 0.0, f"Expected 0.0 at index {i}, got {v}"


# ── Parameter validation ──────────────────────────────────────────────────────

def test_trend_days_91_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": 91}, timeout=15)
    assert r.status_code == 400
    assert "error" in r.json()


def test_trend_days_0_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": 0}, timeout=15)
    assert r.status_code == 400


def test_trend_days_abc_returns_400(headers):
    r = requests.get(BASE, headers=headers, params={"days": "abc"}, timeout=15)
    assert r.status_code == 400


def test_trend_no_auth_returns_401():
    r = requests.get(BASE, params={"days": 7}, timeout=15)
    assert r.status_code == 401
