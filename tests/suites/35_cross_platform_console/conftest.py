"""
conftest.py — Fixtures for Cross-Platform Console test suite (35)
Provides seeded_account (org with OTel data) and empty_headers (fresh org, no data).
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


def _otel_payload(email: str, provider: str, model: str, cost: float, dev_id: str) -> dict:
    return {
        "resourceMetrics": [{
            "resource": {
                "attributes": [
                    {"key": "service.name",  "value": {"stringValue": provider}},
                    {"key": "user.email",    "value": {"stringValue": email}},
                    {"key": "developer.id",  "value": {"stringValue": dev_id}},
                    {"key": "session.id",    "value": {"stringValue": f"sess-{uuid.uuid4().hex[:8]}"}},
                ]
            },
            "scopeMetrics": [{
                "scope": {"name": "vantage-test", "version": "1.0"},
                "metrics": [{
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
                }]
            }]
        }]
    }


@pytest.fixture(scope="module")
def seeded_account():
    """
    Fresh org with two OTel events (claude_code + copilot_chat) seeded today.
    Returns (api_key, org_id, headers, dev_email, dev_id).
    """
    api_key, org_id, _cookies = fresh_account(prefix="cp35")
    hdrs = get_headers(api_key)
    dev_email = f"cp35dev_{uuid.uuid4().hex[:6]}@test.local"
    dev_id = str(uuid.uuid4())

    for provider, model, cost in [
        ("claude_code",  "claude-sonnet-4-6", 0.05),
        ("copilot_chat", "gpt-4o",             0.02),
    ]:
        payload = _otel_payload(dev_email, provider, model, cost, dev_id)
        r = requests.post(f"{API_URL}/v1/otel/v1/metrics",
                          json=payload, headers=hdrs, timeout=15)
        assert r.status_code in (200, 201), f"OTel seed failed: {r.status_code} {r.text}"

    time.sleep(5)
    return api_key, org_id, hdrs, dev_email, dev_id


@pytest.fixture(scope="module")
def headers(seeded_account):
    _, _, hdrs, _, _ = seeded_account
    return hdrs


@pytest.fixture(scope="module")
def empty_headers():
    """Fresh org with absolutely no data — for testing full calendar spine."""
    api_key, _, _cookies = fresh_account(prefix="cp35e")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def member_headers(seeded_account):
    """
    A 'member' role key in the same org as seeded_account.
    Used for 403 and email-redaction tests.
    Returns (member_headers, member_email).
    """
    api_key, org_id, hdrs, _, _ = seeded_account
    member_email = f"cp35member_{uuid.uuid4().hex[:6]}@test.local"
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": member_email, "name": "Test Member", "role": "member"},
        headers=hdrs,
        timeout=15,
    )
    assert r.status_code == 201, f"member invite failed: {r.status_code} {r.text}"
    member_api_key = r.json()["api_key"]
    return get_headers(member_api_key), member_email
