"""
api.py — API helpers for VantageAI test suite
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import requests
from typing import Optional, Tuple

from config.settings import API_URL, SITE_URL, CI_SECRET
from helpers.data import rand_email, rand_name, rand_org


def signup_api(email=None, name=None, org=None, timeout=15) -> dict:
    """
    POST /v1/auth/signup — create a fresh test account.
    Returns the full response dict including api_key and org_id.
    Raises on non-201 status.
    """
    payload = {
        "email": email or rand_email(),
        "name":  name  or rand_name(),
        "org":   org   or rand_org(),
    }
    hdrs = {"Content-Type": "application/json"}
    if CI_SECRET:
        hdrs["X-Vantage-CI"] = CI_SECRET
    last_err = None
    for attempt in range(4):
        r = requests.post(f"{API_URL}/v1/auth/signup", json=payload, headers=hdrs, timeout=timeout)
        if r.status_code == 201:
            return r.json()
        if r.status_code == 429 and attempt < 3:
            time.sleep(2 ** attempt)
            last_err = f"signup_api failed {r.status_code}: {r.text[:200]}"
            continue
        raise RuntimeError(f"signup_api failed {r.status_code}: {r.text[:200]}")
    raise RuntimeError(last_err or "signup_api failed after retries")


def get_headers(api_key: str) -> dict:
    """Bearer auth headers for a given API key."""
    return {"Authorization": f"Bearer {api_key}"}


def get_session_cookie(api_key: str, timeout=15) -> Optional[requests.cookies.RequestsCookieJar]:
    """
    POST /v1/auth/session and return the cookie jar.
    Returns None if the key is invalid.
    """
    r = requests.post(
        f"{API_URL}/v1/auth/session",
        json={"api_key": api_key},
        timeout=timeout,
    )
    if not r.ok:
        return None
    return r.cookies


def session_get(api_key: str, timeout=15) -> Optional[dict]:
    """
    Full sign-in flow: POST session, then GET session.
    Returns parsed session JSON or None.
    """
    cookies = get_session_cookie(api_key, timeout)
    if cookies is None:
        return None
    r = requests.get(
        f"{API_URL}/v1/auth/session",
        cookies=cookies,
        timeout=timeout,
    )
    if not r.ok:
        return None
    return r.json()


def fresh_account(prefix="t") -> Tuple[str, str, dict]:
    """
    Create a brand-new test account and sign in.
    Returns (api_key, org_id, cookies).
    """
    d = signup_api(email=rand_email(prefix))
    api_key = d["api_key"]
    org_id  = d["org_id"]
    cookies = get_session_cookie(api_key)
    return api_key, org_id, cookies


def retry(fn, tries=3, delay=1.0):
    """Call fn() up to `tries` times, sleeping `delay` seconds between attempts."""
    last_exc = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < tries - 1:
                time.sleep(delay)
    raise last_exc
