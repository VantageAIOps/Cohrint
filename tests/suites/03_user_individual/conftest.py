"""conftest.py — Pytest fixtures for individual user tests (03_user_individual)"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, signup_api, get_headers
from helpers.data import rand_email, rand_name, rand_org


@pytest.fixture(scope="module")
def _account():
    return fresh_account(prefix="u03")


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
def email():
    """A random email (used for duplicate-signup tests)."""
    return rand_email("u03dup")


@pytest.fixture(scope="module")
def registered_email():
    """An email that has been registered in the system."""
    addr = rand_email("u03reg")
    signup_api(email=addr, name=rand_name(), org=rand_org("u03reg"))
    return addr


@pytest.fixture(scope="module")
def unregistered_email():
    """An email that has never been registered."""
    return rand_email("u03unreg")
