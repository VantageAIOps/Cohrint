"""
conftest.py -- Pytest fixtures for Dashboard Real Data test suite (20_dashboard_real_data)
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
    api_key, _org_id, _cookies = fresh_account(prefix="dash")
    return get_headers(api_key)


@pytest.fixture(scope="module")
def admin_headers():
    """Admin account for enterprise reporting tests."""
    api_key, _org_id, _cookies = fresh_account(prefix="admin")
    return get_headers(api_key)
