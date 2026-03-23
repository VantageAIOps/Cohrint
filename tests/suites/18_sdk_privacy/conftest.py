"""
conftest.py — Pytest fixtures for SDK Privacy & OTel Pricing tests (18_sdk_privacy)
"""

import sys
from pathlib import Path

import pytest

# Ensure the tests root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers
from helpers.data import rand_email


@pytest.fixture(scope="module")
def headers():
    """Create a fresh test account and return Bearer-auth headers."""
    api_key, _org_id, _cookies = fresh_account(prefix="priv")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def dev_emails():
    """Generate a stable set of developer emails for privacy / pricing tests."""
    return {
        "alice": rand_email("alice"),
        "bob": rand_email("bob"),
        "carol": rand_email("carol"),
    }
