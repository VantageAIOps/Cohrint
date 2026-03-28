"""
helpers.py — Shared test infrastructure for VantageAI test suite
================================================================
Provides:
  - Constants (SITE_URL, API_URL)
  - Random data generators (emails, org names, test tags)
  - API session helpers (sign up, sign in, get headers)
  - Playwright browser factory (headless chromium)
  - Base test class with per-test user isolation
  - Console error collector for browser tests

Usage:
  from helpers import (
      API_URL, SITE_URL,
      rand_email, rand_org, rand_tag,
      signup_api, get_headers, get_session_cookie,
      make_browser_ctx, BaseAPITest, BaseUITest,
      ok, fail, warn, info, section
  )

Every test file imports from here — do not add test logic here.
"""

import os
import sys
import json
import time
import uuid
import string
import random
import requests
from typing import Optional, Tuple

# ── URLs ─────────────────────────────────────────────────────────────────────
SITE_URL = "https://vantageaiops.com"
API_URL  = "https://api.vantageaiops.com"

# ── Console colour helpers ────────────────────────────────────────────────────
G  = "\033[32m✓\033[0m"
R  = "\033[31m✗\033[0m"
W  = "\033[33m⚠\033[0m"
B  = "\033[34mℹ\033[0m"

_results = {"passed": 0, "failed": 0, "warned": 0, "skipped": 0}

def ok(msg):
    _results["passed"] += 1
    print(f"  {G}  {msg}")

def fail(msg, detail=""):
    _results["failed"] += 1
    d = f"\n       └─ {detail}" if detail else ""
    print(f"  {R}  {msg}{d}")

def warn(msg):
    _results["warned"] += 1
    print(f"  {W}  {msg}")

def info(msg):
    print(f"  {B}  {msg}")

def section(title):
    print(f"\n{'━'*66}")
    print(f"  {title}")
    print(f"{'━'*66}")

def chk(label, cond, detail=""):
    if cond: ok(label)
    else:    fail(label, detail)

def get_results():
    return dict(_results)

def reset_results():
    _results.update({"passed": 0, "failed": 0, "warned": 0, "skipped": 0})

# ── Random generators ─────────────────────────────────────────────────────────
def rand_tag(n=8) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def rand_email(prefix="test") -> str:
    return f"{prefix}_{rand_tag()}@vantage-test.dev"

def rand_org(prefix="org") -> str:
    return f"{prefix}{rand_tag(6)}"

def rand_name() -> str:
    first = random.choice(["Alice","Bob","Carol","Dave","Eve","Frank","Grace","Hank"])
    last  = random.choice(["Smith","Jones","Lee","Chen","Kim","Patel","Brown","Taylor"])
    return f"{first} {last}"

# ── API helpers ───────────────────────────────────────────────────────────────
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
    _ci_secret = os.environ.get("VANTAGE_CI_SECRET", "")
    if _ci_secret:
        hdrs["X-Vantage-CI"] = _ci_secret
    r = requests.post(f"{API_URL}/v1/auth/signup", json=payload, headers=hdrs, timeout=timeout)
    if r.status_code != 201:
        raise RuntimeError(f"signup_api failed {r.status_code}: {r.text[:200]}")
    return r.json()

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

# ── Playwright browser factory ────────────────────────────────────────────────
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

def make_browser_ctx(playwright, viewport=(1280, 800)):
    """
    Return (browser, context, page) for a fresh Chromium session.
    Caller is responsible for closing browser when done.
    """
    browser = playwright.chromium.launch(headless=HEADLESS)
    ctx = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        ignore_https_errors=False,
    )
    page = ctx.new_page()
    return browser, ctx, page

# Noise patterns that should NOT count as test failures
_KNOWN_NOISE = (
    # Cloudflare Pages auto-injects this beacon; old CSP versions blocked it
    "cloudflareinsights.com",
    "beacon.min.js",
    # Auth pages probing session on load — 401 is expected when not signed in
    "status of 401",
    "401 ()",
    # Browser extension interference (seen in some CI environments)
    "extension://",
)


def _is_noise(msg: str) -> bool:
    return any(n in msg for n in _KNOWN_NOISE)


def collect_console_errors(page):
    """
    Attach a console-error listener to a Playwright page.
    Returns a list that fills as errors arrive.
    Known noise (Cloudflare beacon CSP blocks, expected 401s) is filtered
    automatically so 'len(errors) == 0' assertions pass on clean pages.
    Use collect_all_errors() if you need the raw unfiltered list.
    """
    all_errors = []
    page.on("pageerror", lambda e: all_errors.append(f"JS: {e}"))
    page.on("console", lambda m: all_errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)

    # Return a live-filtered view backed by the same list
    class _FilteredList(list):
        """Proxy that reads from all_errors but only exposes non-noise entries."""
        def __len__(self):
            return sum(1 for e in all_errors if not _is_noise(e))
        def __iter__(self):
            return (e for e in all_errors if not _is_noise(e))
        def __getitem__(self, idx):
            return [e for e in all_errors if not _is_noise(e)][idx]
        @property
        def _all(self):
            return all_errors

    return _FilteredList()


def collect_all_errors(page):
    """
    Like collect_console_errors but returns every error including known noise.
    Use for debugging or when you intentionally want to see all console errors.
    """
    errors = []
    page.on("pageerror", lambda e: errors.append(f"JS: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)
    return errors


def collect_critical_errors(page):
    """
    Attach listeners and return (all_errors_list, critical_errors_list).
    critical_errors filters out known noise (beacon, expected 401s).
    Use this when you need both lists (e.g. for informational logging + assertions).
    """
    all_errors = []
    page.on("pageerror", lambda e: all_errors.append(f"JS: {e}"))
    page.on("console", lambda m: all_errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)
    return all_errors, [e for e in all_errors if not _is_noise(e)]

def signin_ui(page, api_key: str, timeout=15_000):
    """
    Navigate to /auth and sign in using the given API key via the UI.
    Returns True if redirected to /app, False otherwise.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    try:
        page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
        page.fill("#inp-key", api_key)
        with page.expect_response(
            lambda r: "/v1/auth/session" in r.url and r.request.method == "POST",
            timeout=timeout,
        ):
            page.click("#signin-btn")
        page.wait_for_url(f"{SITE_URL}/app**", timeout=10_000)
        return "/app" in page.url
    except PWTimeout:
        return False

# ── Retry helper ──────────────────────────────────────────────────────────────
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
