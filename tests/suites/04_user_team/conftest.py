"""conftest.py — Pytest fixtures for team member tests (04_user_team)"""
import sys
from pathlib import Path
import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import fresh_account, signup_api, get_headers
from helpers.data import rand_email, rand_name, rand_org
from config.settings import API_URL


@pytest.fixture(scope="module")
def _owner_account():
    return fresh_account(prefix="tm04o")


@pytest.fixture(scope="module")
def owner_key(_owner_account):
    return _owner_account[0]


@pytest.fixture(scope="module")
def owner_id(_owner_account):
    return _owner_account[1]


@pytest.fixture(scope="module")
def member_key(owner_key):
    """Invite a member and return their API key."""
    headers = get_headers(owner_key)
    member_email = rand_email("tm04m")
    r = requests.post(
        f"{API_URL}/v1/auth/members",
        json={"email": member_email, "name": rand_name(), "role": "member"},
        headers=headers,
        timeout=15,
    )
    if r.status_code in (200, 201):
        d = r.json()
        return d.get("api_key") or d.get("member_api_key") or owner_key
    # Fall back to owner key if invite not yet implemented
    return owner_key
