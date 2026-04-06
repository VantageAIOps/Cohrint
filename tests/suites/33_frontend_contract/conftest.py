"""
conftest.py — Fixtures for Frontend Contract test suite (33_frontend_contract)

These fixtures seed a real account with known data so every test can
assert exact values propagate from ingest → API → frontend field.
"""

import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import fresh_account, get_headers
from helpers.data import make_event, rand_email


def _make_otlp_metrics(email: str, provider: str, model: str, cost: float,
                        input_tokens: int, output_tokens: int) -> dict:
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",      "value": {"stringValue": provider}},
                    {"key": "user.email",         "value": {"stringValue": email}},
                    {"key": "session.id",         "value": {"stringValue": f"sess-{uuid.uuid4().hex[:8]}"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-test", "version": "1.0"},
                "metrics": [
                    {
                        "name": "gen_ai.client.token.usage",
                        "unit": "1",
                        "sum": {
                            "dataPoints": [{
                                "asDouble": input_tokens,
                                "timeUnixNano": str(int(time.time() * 1e9)),
                                "attributes": [
                                    {"key": "gen_ai.token.type", "value": {"stringValue": "input"}},
                                    {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                                ]
                            }],
                            "isMonotonic": True,
                        }
                    },
                    {
                        "name": "claude_code.cost.usage",
                        "unit": "USD",
                        "sum": {
                            "dataPoints": [{
                                "asDouble": cost,
                                "timeUnixNano": str(int(time.time() * 1e9)),
                                "attributes": [
                                    {"key": "gen_ai.request.model", "value": {"stringValue": model}},
                                ]
                            }],
                            "isMonotonic": True,
                        }
                    },
                ]
            }]
        }]
    }


@pytest.fixture(scope="module")
def seeded_account():
    """
    Create a fresh account and seed it with:
    - 5 events via /v1/events (SDK path)
    - 1 OTel metrics payload (OTel path)
    Returns (api_key, org_id, headers, dev_email).
    """
    api_key, org_id, _cookies = fresh_account(prefix="fc")
    hdrs = get_headers(api_key)
    dev_email = rand_email("fc_dev")

    # Seed 5 events via SDK/batch path
    events = []
    for i in range(5):
        ev = make_event(i, model="claude-sonnet-4-6", cost=0.02, prompt_tokens=500,
                        completion_tokens=200, team="backend")
        ev["provider"] = "anthropic"
        ev["developer_email"] = dev_email
        events.append(ev)

    r = requests.post(f"{API_URL}/v1/events/batch",
                      json={"events": events, "sdk_version": "test", "sdk_language": "python"},
                      headers=hdrs, timeout=15)
    assert r.status_code in (200, 201, 207), f"Batch ingest failed: {r.status_code} {r.text}"

    # Seed 1 OTel payload (different provider, same dev)
    otlp = _make_otlp_metrics(dev_email, "openai", "gpt-4o", 0.015, 300, 100)
    requests.post(f"{API_URL}/v1/otel/v1/metrics", json=otlp, headers=hdrs, timeout=15)

    # Allow D1 writes to settle
    time.sleep(2)

    return api_key, org_id, hdrs, dev_email


@pytest.fixture(scope="module")
def headers(seeded_account):
    _, _, hdrs, _ = seeded_account
    return hdrs


@pytest.fixture(scope="module")
def admin_headers():
    api_key, _org_id, _cookies = fresh_account(prefix="fc_admin")
    return get_headers(api_key)
