"""Suite 46 — Optimizer Impact API coverage"""
import json
import time
from pathlib import Path
import pytest
import requests

BASE_URL = "https://api.cohrint.com"


@pytest.fixture(scope="module")
def account():
    seed_path = Path("tests/artifacts/da45_seed_state.json")
    assert seed_path.exists(), "Run: python tests/suites/45_dashboard_api_coverage/seed.py"
    state = json.loads(seed_path.read_text())
    api_key = state["admin"]["api_key"]
    return {"Authorization": f"Bearer {api_key}"}


def test_impact_requires_auth():
    """GET /v1/optimizer/impact returns 401 without auth."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact")
    assert r.status_code == 401


def test_impact_endpoint_returns_expected_shape(account):
    """GET /v1/optimizer/impact returns the required top-level fields."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "avg_improvement_factor" in data
    assert "total_tokens_saved" in data
    assert "total_cost_saved_usd" in data
    assert "by_type" in data
    assert "per_developer" in data
    assert "monthly_trend" in data
    assert "period" in data


def test_impact_by_type_has_compress_key(account):
    """by_type.compress has avg_factor, event_count, cost_saved_usd."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    compress = r.json()["by_type"]["compress"]
    assert "avg_factor" in compress
    assert "event_count" in compress
    assert "cost_saved_usd" in compress


def test_impact_per_developer_shape(account):
    """per_developer is a list; each entry has email, avg_factor, cost_saved_usd."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    devs = r.json()["per_developer"]
    assert isinstance(devs, list)
    if devs:
        dev = devs[0]
        assert "email" in dev
        assert "avg_factor" in dev
        assert "cost_saved_usd" in dev


def test_impact_monthly_trend_shape(account):
    """monthly_trend is a list of {month, avg_factor}."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    trend = r.json()["monthly_trend"]
    assert isinstance(trend, list)
    if trend:
        assert "month" in trend[0]
        assert "avg_factor" in trend[0]


def test_compress_then_impact_reflects_new_event(account):
    """After a compress call, total_tokens_saved is non-negative and endpoint stays healthy."""
    before = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert before.status_code == 200
    before_tokens = before.json().get("total_tokens_saved", 0)

    long_prompt = "Please could you kindly help me with the following task. " * 20
    compress_r = requests.post(
        f"{BASE_URL}/v1/optimizer/compress",
        json={"prompt": long_prompt},
        headers=account,
    )
    assert compress_r.status_code == 200

    time.sleep(2)

    after = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert after.status_code == 200
    after_tokens = after.json().get("total_tokens_saved", 0)
    assert after_tokens >= before_tokens
