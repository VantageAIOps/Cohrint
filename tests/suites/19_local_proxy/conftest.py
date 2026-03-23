"""
conftest.py — Pytest fixtures for Local Proxy test suite (19_local_proxy)
"""

import sys
from pathlib import Path

import pytest

# Ensure the tests root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def headers():
    """Create a fresh test account and return Bearer-auth headers."""
    api_key, _org_id, _cookies = fresh_account(prefix="proxy")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def second_headers():
    """Create a second isolated org for cross-org isolation tests."""
    api_key, _org_id, _cookies = fresh_account(prefix="proxy2")
    return get_headers(api_key)
