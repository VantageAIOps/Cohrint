"""
conftest.py — Pytest fixtures for Local Proxy Advanced tests (29_local_proxy_advanced)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers
from helpers.data import rand_email


@pytest.fixture(scope="module")
def headers():
    """Create a fresh test account and return Bearer-auth headers."""
    api_key, _org_id, _cookies = fresh_account(prefix="prx29")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def second_headers():
    """Create a second isolated org for cross-org tests."""
    api_key, _org_id, _cookies = fresh_account(prefix="prx29b")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def dev_emails():
    """Generate developer emails for proxy tests."""
    return {
        "alice": rand_email("alice"),
        "bob": rand_email("bob"),
    }
