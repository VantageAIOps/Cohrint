"""conftest.py — Pytest fixtures for org-level admin tests (05_user_org)"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account


@pytest.fixture(scope="module")
def _account():
    return fresh_account(prefix="oa05")


@pytest.fixture(scope="module")
def owner_key(_account):
    return _account[0]


@pytest.fixture(scope="module")
def org_id(_account):
    return _account[1]
