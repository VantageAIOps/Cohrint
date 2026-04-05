"""conftest.py — Pytest fixtures for audit log tests (32_audit_log)"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, get_headers


@pytest.fixture(scope="module")
def account():
    return fresh_account(prefix="al32")


@pytest.fixture(scope="module")
def headers(account):
    api_key, _, _ = account
    return get_headers(api_key)


@pytest.fixture(scope="module")
def member_account():
    return fresh_account(prefix="al32b")
