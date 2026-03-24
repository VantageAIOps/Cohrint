import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.api import fresh_account, get_headers, signup_api
from helpers.data import rand_email

@pytest.fixture(scope="module")
def admin_account():
    """Create a fresh admin account, return (api_key, org_id, cookies, headers)."""
    api_key, org_id, cookies = fresh_account(prefix="secgov")
    headers = get_headers(api_key)
    return api_key, org_id, cookies, headers

@pytest.fixture(scope="module")
def headers(admin_account):
    return admin_account[3]
