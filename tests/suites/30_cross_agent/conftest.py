"""
conftest.py — Pytest fixtures for Cross-Agent Integration tests (30_cross_agent)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def headers():
    """Create a fresh test account and return Bearer-auth headers."""
    api_key, _org_id, _cookies = fresh_account(prefix="xagt30")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def account():
    """Create a fresh test account and return (api_key, org_id, cookies)."""
    return fresh_account(prefix="xagt30")
