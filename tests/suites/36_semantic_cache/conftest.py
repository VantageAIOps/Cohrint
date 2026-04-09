"""conftest.py — Pytest fixtures for semantic cache test suite (36_semantic_cache)"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def headers():
    """Create a fresh test account and return Bearer-auth headers."""
    api_key, _org_id, _cookies = fresh_account(prefix="sc")
    return get_headers(api_key)
