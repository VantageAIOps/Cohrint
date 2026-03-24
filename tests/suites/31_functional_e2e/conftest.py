"""
conftest.py — Fixtures for Functional E2E tests (31_functional_e2e)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers, signup_api
from helpers.data import rand_email


@pytest.fixture(scope="module")
def org_a():
    """Fresh org A with full credentials."""
    api_key, org_id, cookies = fresh_account(prefix="fn31a")
    return {"api_key": api_key, "org_id": org_id, "cookies": cookies}


@pytest.fixture(scope="module")
def org_b():
    """Fresh org B for isolation tests."""
    api_key, org_id, cookies = fresh_account(prefix="fn31b")
    return {"api_key": api_key, "org_id": org_id, "cookies": cookies}


@pytest.fixture(scope="module")
def headers_a(org_a):
    return get_headers(org_a["api_key"])


@pytest.fixture(scope="module")
def headers_b(org_b):
    return get_headers(org_b["api_key"])
