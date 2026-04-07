"""conftest.py — Pytest fixtures for API endpoint tests (01_api)"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def _account():
    return fresh_account(prefix="e01")


@pytest.fixture(scope="module")
def api_key(_account):
    return _account[0]


@pytest.fixture(scope="module")
def org_id(_account):
    return _account[1]


@pytest.fixture(scope="module")
def cookies(_account):
    return _account[2]


@pytest.fixture(scope="module")
def headers(api_key):
    return get_headers(api_key)
