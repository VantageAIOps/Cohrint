"""
test_console_frontend.py — 10 contract tests for routes consumed by the
Cross-Platform tab: /summary, /developers, /developer/:id, /live, /connections.
"""

import uuid
import requests

from config.settings import API_URL
from helpers.api import fresh_account, get_headers


# ── /summary ──────────────────────────────────────────────────────────────────

def test_summary_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "total_cost_usd" in data
    assert "by_provider" in data and isinstance(data["by_provider"], list)
    assert "budget" in data


def test_summary_invalid_days_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     headers=headers, params={"days": 999}, timeout=15)
    assert r.status_code == 400


def test_summary_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/summary",
                     params={"days": 30}, timeout=15)
    assert r.status_code == 401


# ── /developers ───────────────────────────────────────────────────────────────

def test_developers_includes_developer_id(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                     headers=hdrs, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    devs = r.json().get("developers", [])
    assert len(devs) >= 1
    assert "developer_id" in devs[0], "developer_id must be present"
    assert "by_provider" in devs[0] and isinstance(devs[0]["by_provider"], list)


def test_developers_no_null_developer_id(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    for dev in r.json().get("developers", []):
        assert dev.get("developer_id") is not None


# ── /developer/:id ────────────────────────────────────────────────────────────

def test_developer_detail_shape(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    devs = requests.get(f"{API_URL}/v1/cross-platform/developers",
                        headers=hdrs, params={"days": 30}, timeout=15).json().get("developers", [])
    assert devs, "No developers seeded"
    dev_id = devs[0]["developer_id"]

    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{dev_id}",
                     headers=hdrs, params={"days": 30}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "by_provider" in data and isinstance(data["by_provider"], list)
    assert "daily_trend" in data and isinstance(data["daily_trend"], list)
    assert "productivity" in data


def test_developer_detail_invalid_uuid_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/not-a-uuid",
                     headers=headers, params={"days": 30}, timeout=15)
    assert r.status_code == 400


def test_developer_detail_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{uuid.uuid4()}",
                     params={"days": 30}, timeout=15)
    assert r.status_code == 401


def test_developer_detail_member_cannot_view_other_dev(seeded_account, member_headers):
    """member role querying a dev_id that belongs to another user → 403."""
    _, _, hdrs, _, dev_id = seeded_account
    m_hdrs, _ = member_headers
    # dev_id was seeded under a different email than the member's email
    r = requests.get(f"{API_URL}/v1/cross-platform/developer/{dev_id}",
                     headers=m_hdrs, params={"days": 30}, timeout=15)
    assert r.status_code == 403


# ── /live ─────────────────────────────────────────────────────────────────────

def test_live_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/live",
                     headers=headers, params={"limit": 5}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "events" in data and isinstance(data["events"], list)
    assert "is_stale" in data


def test_live_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/live",
                     params={"limit": 5}, timeout=15)
    assert r.status_code == 401


def test_live_redacts_email_for_member(member_headers):
    """Non-admin roles must receive redacted developer_email (u***@domain)."""
    m_hdrs, _ = member_headers
    r = requests.get(f"{API_URL}/v1/cross-platform/live",
                     headers=m_hdrs, params={"limit": 50}, timeout=15)
    assert r.status_code == 200
    events = r.json().get("events", [])
    for ev in events:
        email = ev.get("developer_email")
        if email is not None:
            assert "***" in email, f"expected redacted email, got: {email}"
            at = email.index("@") if "@" in email else -1
            assert at > 0, f"redacted email missing domain: {email}"


# ── /connections ──────────────────────────────────────────────────────────────

def test_connections_shape(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/connections",
                     headers=headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "billing_connections" in data and isinstance(data["billing_connections"], list)
    assert "otel_sources" in data and isinstance(data["otel_sources"], list)


def test_connections_no_auth_returns_401():
    r = requests.get(f"{API_URL}/v1/cross-platform/connections", timeout=15)
    assert r.status_code == 401


# ── days=999 on all ?days= routes ─────────────────────────────────────────────

def test_days_invalid_on_developers_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/developers",
                     headers=headers, params={"days": 999}, timeout=15)
    assert r.status_code == 400


def test_days_invalid_on_trend_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/trend",
                     headers=headers, params={"days": 999}, timeout=15)
    assert r.status_code == 400


def test_days_invalid_on_models_returns_400(headers):
    r = requests.get(f"{API_URL}/v1/cross-platform/models",
                     headers=headers, params={"days": 999}, timeout=15)
    assert r.status_code == 400
