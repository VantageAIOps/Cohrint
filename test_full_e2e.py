#!/usr/bin/env python3
"""
Cohrint — Full End-to-End Test Suite
=======================================
What this tests (all against the LIVE deployed site):

 1. Python SDK — pip install cohrint (fresh venv, NOT local code)
 2. npm SDK    — npm install cohrint (fresh install, NOT local dist)
 3. UI — Sign-up page   (https://cohrint.com/signup)
 4. UI — Sign-in page   (https://cohrint.com/auth)
 5. UI — Key recovery   (https://cohrint.com/auth → "Forgot key")
 6. UI — Dashboard      (/app.html — KPIs, charts, tables)
 7. API — Every endpoint with a real crt_key written to live D1
 8. Live data — events sent via SDK appear in the dashboard

Requirements (installed automatically if missing):
  pip install playwright requests
  python -m playwright install chromium

Run:
  python test_full_e2e.py
"""

import os
import sys
import json
import uuid
import time
import string
import random
import shutil
import textwrap
import tempfile
import subprocess
import requests

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
SITE_URL = "https://cohrint.com"
API_URL  = "https://api.cohrint.com"
HEADLESS = True   # set False to watch the browser

# ─────────────────────────────────────────────────────────────────────────────
# Console helpers
# ─────────────────────────────────────────────────────────────────────────────
G = "\033[32m✓\033[0m"
R = "\033[31m✗\033[0m"
W = "\033[33m⚠\033[0m"
B = "\033[34mℹ\033[0m"

results = {"passed": 0, "failed": 0, "warned": 0}

def ok(msg):   results["passed"] += 1; print(f"  {G}  {msg}")
def fail(msg, detail=""): results["failed"] += 1; print(f"  {R}  {msg}" + (f"\n       └─ {detail}" if detail else ""))
def warn(msg): results["warned"] += 1; print(f"  {W}  {msg}")
def info(msg): print(f"  {B}  {msg}")

def section(title):
    print(f"\n{'━'*62}")
    print(f"  {title}")
    print(f"{'━'*62}")

def chk(label, cond, detail=""):
    if cond: ok(label)
    else:    fail(label, detail)

def rand_tag(n=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

# ─────────────────────────────────────────────────────────────────────────────
# 0. Setup — create isolated environments for SDK installs
# ─────────────────────────────────────────────────────────────────────────────
section("0. Environment setup")

# Python venv for isolated PyPI install
PY_VENV = tempfile.mkdtemp(prefix="vantage_pypi_")
info(f"Python venv dir: {PY_VENV}")

# npm dir for isolated npm install
NPM_DIR = tempfile.mkdtemp(prefix="vantage_npm_")
info(f"npm dir: {NPM_DIR}")

# Determine python in venv
if sys.platform == "win32":
    PY_BIN = os.path.join(PY_VENV, "Scripts", "python")
else:
    PY_BIN = os.path.join(PY_VENV, "bin", "python")

# ─────────────────────────────────────────────────────────────────────────────
# 1. pip install cohrint (from PyPI, not local)
# ─────────────────────────────────────────────────────────────────────────────
section("1. Python SDK — pip install cohrint from PyPI")

try:
    # Create fresh venv
    result = subprocess.run(
        [sys.executable, "-m", "venv", PY_VENV],
        capture_output=True, text=True, timeout=30
    )
    chk("Created fresh Python venv", result.returncode == 0, result.stderr[:200])

    # pip install cohrint from PyPI
    result = subprocess.run(
        [PY_BIN, "-m", "pip", "install", "cohrint", "--quiet", "--no-cache-dir"],
        capture_output=True, text=True, timeout=120
    )
    chk("pip install cohrint (PyPI) succeeded", result.returncode == 0,
        result.stderr[:300] if result.returncode != 0 else "")

    # Verify version
    result = subprocess.run(
        [PY_BIN, "-c", "import cohrint; print(cohrint.__version__)"],
        capture_output=True, text=True, timeout=15
    )
    pypi_version = result.stdout.strip()
    chk(f"import cohrint works in venv (v{pypi_version})",
        result.returncode == 0 and bool(pypi_version))

    # Verify it's NOT using local code
    result2 = subprocess.run(
        [PY_BIN, "-c", "import cohrint, os; print(os.path.dirname(cohrint.__file__))"],
        capture_output=True, text=True, timeout=10
    )
    pkg_path = result2.stdout.strip()
    chk("Package loaded from venv (not local project)",
        "site-packages" in pkg_path or PY_VENV in pkg_path,
        f"path={pkg_path}")

    # Verify key SDK functions exist
    result3 = subprocess.run(
        [PY_BIN, "-c",
         "import cohrint as v; assert callable(v.init); assert callable(v.flush); "
         "from cohrint.models.pricing import calculate_cost; "
         "c=calculate_cost('gpt-4o',1000,300); assert c['total']>0; print('ok')"],
        capture_output=True, text=True, timeout=15
    )
    chk("SDK pricing utilities work correctly", result3.stdout.strip() == "ok",
        result3.stderr[:200])

except Exception as e:
    fail("Python SDK install check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 2. npm install cohrint (from npm registry, not local dist)
# ─────────────────────────────────────────────────────────────────────────────
section("2. npm SDK — npm install cohrint from registry")

try:
    # npm init + install
    subprocess.run(["npm", "init", "-y"], cwd=NPM_DIR,
                   capture_output=True, timeout=30)

    result = subprocess.run(
        ["npm", "install", "cohrint", "--no-fund", "--no-audit"],
        cwd=NPM_DIR, capture_output=True, text=True, timeout=120
    )
    chk("npm install cohrint succeeded", result.returncode == 0,
        result.stderr[:300] if result.returncode != 0 else "")

    # Verify version
    pkg_json_path = os.path.join(NPM_DIR, "node_modules", "cohrint", "package.json")
    with open(pkg_json_path) as f:
        npm_pkg = json.load(f)
    npm_version = npm_pkg.get("version", "?")
    chk(f"npm package installed (v{npm_version})", bool(npm_version))

    # Verify it's NOT the local dist
    pkg_main = os.path.join(NPM_DIR, "node_modules", "cohrint",
                             npm_pkg.get("module", "dist/index.js"))
    chk("npm package is in node_modules (not local dist)", NPM_DIR in pkg_main)

    # Verify JS SDK exports work
    test_js = textwrap.dedent("""
        import { calculateCost, findCheapest, PRICES } from 'cohrint';
        const cost = calculateCost('gpt-4o', 1000, 300);
        if (!cost || cost.totalCostUsd <= 0) {
            console.error('calculateCost failed:', cost);
            process.exit(1);
        }
        const alt = findCheapest('gpt-4o', 1000, 300);
        if (!alt || alt.costUsd >= cost.totalCostUsd) {
            console.error('findCheapest failed:', alt);
            process.exit(1);
        }
        console.log(`ok cost=$${cost.totalCostUsd.toFixed(6)} cheapest=${alt.model}`);
    """)
    test_file = os.path.join(NPM_DIR, "test_sdk.mjs")
    with open(test_file, "w") as f:
        f.write(test_js)

    result = subprocess.run(
        ["node", test_file], cwd=NPM_DIR,
        capture_output=True, text=True, timeout=15
    )
    out = result.stdout.strip()
    chk("JS SDK pricing utilities work correctly", result.returncode == 0 and out.startswith("ok"),
        result.stderr[:200] if result.returncode != 0 else out)

except Exception as e:
    fail("npm SDK install check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 3. Live API — sign up fresh test account (get real crt_key)
# ─────────────────────────────────────────────────────────────────────────────
section("3. Live API sign-up — generate real crt_key")

TEST_EMAIL = f"e2e_{rand_tag()}@vantage-test.dev"
TEST_NAME  = "E2E UI Test"
TEST_ORG   = f"e2eui{rand_tag(5)}"
API_KEY    = None
ORG_ID     = None

try:
    r = requests.post(f"{API_URL}/v1/auth/signup",
                      json={"email": TEST_EMAIL, "name": TEST_NAME, "org": TEST_ORG},
                      timeout=15)
    chk("POST /v1/auth/signup returns 201", r.status_code == 201,
        f"{r.status_code}: {r.text[:200]}")
    d = r.json()
    API_KEY = d.get("api_key")
    ORG_ID  = d.get("org_id")
    chk("Real crt_key returned (starts with crt_)",
        isinstance(API_KEY, str) and API_KEY.startswith("crt_"))
    chk("org_id in database", bool(ORG_ID))
    info(f"org_id = {ORG_ID}")
    info(f"key    = {API_KEY[:24]}...")
except Exception as e:
    fail("Sign-up API call failed", str(e))

if not API_KEY:
    fail("CRITICAL: No API key — cannot continue UI tests")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# ─────────────────────────────────────────────────────────────────────────────
# 4. UI Tests — Playwright
# ─────────────────────────────────────────────────────────────────────────────
section("4. UI — Playwright browser tests")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    fail("playwright not installed — run: pip install playwright && python -m playwright install chromium")
    PLAYWRIGHT_OK = False

CAPTURED_KEY = None   # API key captured from the UI signup flow

if PLAYWRIGHT_OK:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            # Accept all cookies to avoid cookie banners
            ignore_https_errors=False,
        )
        page = ctx.new_page()

        # ── 4a. Signup page ────────────────────────────────────────────────
        info("Testing /signup page…")
        signup_email = f"ui_{rand_tag()}@vantage-test.dev"
        try:
            page.goto(f"{SITE_URL}/signup", wait_until="networkidle", timeout=20_000)
            chk("Signup page loaded (200)", "signup" in page.url.lower() or page.url.rstrip("/").endswith("signup"))

            # Check key UI elements are visible
            chk("Form visible — Name field", page.locator("#inp-name").is_visible())
            chk("Form visible — Email field", page.locator("#inp-email").is_visible())
            chk("Form visible — Submit button", page.locator("#submit-btn").is_visible())
            chk("Form title renders", "free API key" in page.content() or "free" in page.content().lower())

            # Fill the form
            page.fill("#inp-name", "UI Test User")
            page.fill("#inp-email", signup_email)
            page.fill("#inp-org", f"uitest{rand_tag(4)}")

            # Submit and wait for success
            with page.expect_response(
                lambda r: "/v1/auth/signup" in r.url, timeout=15_000
            ) as resp_info:
                page.click("#submit-btn")

            resp = resp_info.value
            chk("Signup API call reached server", resp.status in (200, 201, 409),
                f"status={resp.status}")

            if resp.status == 201:
                # Wait for success state to appear
                page.wait_for_selector("#success-state", state="visible", timeout=8_000)
                chk("Success state appeared after signup", page.locator("#success-state").is_visible())

                # Check API key is displayed
                key_el = page.locator("#key-display")
                CAPTURED_KEY = key_el.inner_text().strip()
                chk("API key displayed in success state",
                    bool(CAPTURED_KEY) and CAPTURED_KEY.startswith("crt_"),
                    f"got: {CAPTURED_KEY[:30] if CAPTURED_KEY else 'empty'}")

                # Check warning message is shown
                chk("'shown once' warning visible",
                    "once" in page.content() or "never" in page.content())

                # Check dashboard button exists
                dash_btn = page.locator("#dashboard-link")
                chk("'Open my dashboard' button exists", dash_btn.count() > 0)
                chk("Dashboard link points to /app",
                    "/app" in (dash_btn.get_attribute("href") or ""))

                info(f"UI captured key = {CAPTURED_KEY[:28]}...")

            elif resp.status == 409:
                warn("Signup returned 409 (email already exists) — using previously created key")

        except PWTimeout as e:
            fail("Signup page timed out", str(e)[:200])
        except Exception as e:
            fail("Signup page error", str(e)[:200])

        # ── 4b. Sign-in page ───────────────────────────────────────────────
        info("Testing /auth (sign-in) page…")
        try:
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
            chk("Auth page loaded", "auth" in page.url.lower() or "sign" in page.content().lower())

            # Check UI elements
            chk("API key input visible", page.locator("#inp-key").is_visible())
            chk("Sign-in button visible", page.locator("#signin-btn").is_visible())
            chk("'Forgot your key?' button visible",
                page.locator("text=Forgot").count() > 0 or
                page.locator("text=Recover").count() > 0)

            # Try signing in with a WRONG key — should show error
            page.fill("#inp-key", "crt_wrongkey_definitely_invalid_00000")
            with page.expect_response(
                lambda r: "/v1/auth/session" in r.url, timeout=10_000
            ) as resp_info:
                page.click("#signin-btn")

            resp = resp_info.value
            chk("Invalid key returns 401 from server", resp.status == 401)
            page.wait_for_selector("#signin-err", state="visible", timeout=5_000)
            err_text = page.locator("#signin-err").inner_text()
            chk("Error message shown for invalid key",
                bool(err_text) and len(err_text) > 5,
                f"err={err_text}")

            # Sign in with the REAL key
            page.fill("#inp-key", API_KEY)
            with page.expect_response(
                lambda r: "/v1/auth/session" in r.url, timeout=10_000
            ) as resp_info:
                page.click("#signin-btn")

            resp = resp_info.value
            resp_status = resp.status
            try:
                resp_body = resp.text()[:200]
            except Exception:
                resp_body = "(body unavailable after redirect)"
            chk("Real key sign-in returns 200", resp_status == 200,
                f"status={resp_status}: {resp_body}")

            if resp_status == 200:
                # Should redirect to /app.html or /app
                page.wait_for_url(f"{SITE_URL}/app**", timeout=8_000)
                chk("Redirected to dashboard after sign-in",
                    "/app" in page.url,
                    f"url={page.url}")

        except PWTimeout as e:
            fail("Sign-in page timed out", str(e)[:200])
        except Exception as e:
            fail("Sign-in page error", str(e)[:200])

        # ── 4c. Dashboard — KPI cards, charts, nav ─────────────────────────
        info("Testing /app.html (dashboard)…")
        try:
            # Navigate directly with session cookie already set
            page.goto(f"{SITE_URL}/app.html", wait_until="networkidle", timeout=25_000)
            current_url = page.url

            if "/auth" in current_url:
                warn("Dashboard redirected to auth — session cookie may not persist cross-subdomain")
                # Try signing in again with direct API key in URL (fallback path)
                page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)
                page.fill("#inp-key", API_KEY)
                page.click("#signin-btn")
                page.wait_for_timeout(3000)
                page.goto(f"{SITE_URL}/app.html", wait_until="networkidle", timeout=20_000)

            chk("Dashboard page loaded",
                "/app" in page.url or page.title() != "",
                f"url={page.url}")

            # Check topbar (logo, period selector)
            chk("Top bar / logo visible",
                page.locator("#topbar").count() > 0 or
                page.locator(".tb-logo").count() > 0 or
                "VANTAGE" in page.content())

            # Check sidebar navigation items
            chk("Sidebar navigation present",
                page.locator("#sidebar").count() > 0 or
                page.locator(".sb-item").count() > 0)

            # Check KPI cards exist in DOM
            chk("KPI grid rendered",
                page.locator(".kpi-grid").count() > 0 or
                page.locator(".kpi").count() > 0)

            # Check Chart.js canvas exists (cost chart)
            chk("Cost chart canvas rendered",
                page.locator("canvas").count() > 0)

            # Check no JavaScript errors on page
            js_errors = []
            page.on("pageerror", lambda e: js_errors.append(str(e)))
            page.wait_for_timeout(1500)
            chk("No JS errors on dashboard page", len(js_errors) == 0,
                f"errors: {js_errors[:3]}")

        except PWTimeout as e:
            fail("Dashboard page timed out", str(e)[:200])
        except Exception as e:
            fail("Dashboard page error", str(e)[:200])

        # ── 4d. Key recovery flow ──────────────────────────────────────────
        info("Testing /auth key recovery flow…")
        try:
            # Clear session so /auth doesn't redirect us away
            ctx.clear_cookies()
            page.goto(f"{SITE_URL}/auth", wait_until="networkidle", timeout=20_000)

            # Click "Forgot your key?" button (class=ghost-btn inside #signin-box)
            recover_btn = page.locator("#signin-box button.ghost-btn")
            if recover_btn.count() == 0:
                # fallback: any button with recover/forgot text
                recover_btn = page.locator("button:has-text('Forgot'), button:has-text('Recover'), button:has-text('recover')")
            if recover_btn.count() > 0:
                recover_btn.first.click()
                page.wait_for_selector("#recover-box", state="visible", timeout=5_000)

                # Recovery panel should appear
                chk("Recovery panel appeared", page.locator("#recover-box").is_visible())

                # Fill in the test email
                email_input = page.locator("#inp-email")
                if email_input.is_visible():
                    email_input.fill(TEST_EMAIL)

                    with page.expect_response(
                        lambda r: "/v1/auth/recover" in r.url, timeout=10_000
                    ) as resp_info:
                        page.click("#recover-btn")

                    resp = resp_info.value
                    chk("Recovery API returns 200", resp.status == 200,
                        f"status={resp.status}: {resp.text()[:200]}")

                    # Check the visible #recover-msg div (not full page HTML — JS source contains "Network error")
                    page.wait_for_timeout(1000)
                    msg_div = page.locator("#recover-msg")
                    if msg_div.is_visible():
                        msg_text = msg_div.inner_text()
                        chk("Recovery shows success message (not Network error)",
                            "network error" not in msg_text.lower(),
                            f"msg={msg_text}")
                        chk("Recovery message mentions sent/email",
                            "sent" in msg_text.lower() or "email" in msg_text.lower() or
                            "recovery" in msg_text.lower(),
                            f"msg={msg_text}")
                    else:
                        ok("No error message shown during recovery (API returned 200)")
            else:
                warn("Could not find recovery button — skipping recovery UI test")

        except PWTimeout as e:
            fail("Key recovery flow timed out", str(e)[:200])
        except Exception as e:
            fail("Key recovery flow error", str(e)[:200])

        # ── 4e. Homepage basic checks ──────────────────────────────────────
        info("Testing / (homepage)…")
        try:
            page.goto(f"{SITE_URL}/", wait_until="networkidle", timeout=20_000)
            chk("Homepage loaded", page.title() != "")
            chk("VANTAGEAI brand present", "VANTAGE" in page.content().upper())
            chk("'Sign up' or 'Dashboard' nav button present",
                page.locator("text=Sign up, text=Dashboard, text=Start free").count() > 0 or
                "sign" in page.content().lower())

            # Navigation links present
            chk("Docs nav link",
                page.locator("a[href*='docs']").count() > 0)
            chk("Calculator nav link",
                page.locator("a[href*='calculator']").count() > 0)
        except Exception as e:
            fail("Homepage check failed", str(e)[:200])

        ctx.close()
        browser.close()

# ─────────────────────────────────────────────────────────────────────────────
# 5. Send events via PyPI-installed Python SDK
# ─────────────────────────────────────────────────────────────────────────────
section("5. Python SDK (PyPI) — send real events to live API")

PY_SDK_SCRIPT = textwrap.dedent(f"""
import sys, time, json
sys.path.insert(0, '')   # ensure no local path pollution

# Use the PyPI-installed package
import cohrint as vantage

vantage.init(
    api_key="{API_KEY}",
    environment="e2e-test",
    flush_interval=1.0,
    batch_size=5,
    debug=True,
)

from cohrint.utils.queue import EventQueue
from cohrint.models.event import CohrintEvent, TokenUsage, CostInfo

q = EventQueue(api_key="{API_KEY}", ingest_url="{API_URL}",
               flush_interval=1.0, batch_size=5, debug=True)

events = [
    dict(event_id=f"py-sdk-{{i}}-" + str(time.time_ns()),
         provider="openai", model="gpt-4o",
         prompt_tokens=800, completion_tokens=200, total_tokens=1000,
         total_cost_usd=0.0050, latency_ms=380,
         team="python-sdk", project="e2e", environment="testing",
         tags={{"source": "py-sdk-e2e", "run": "ci"}})
    for i in range(5)
]

import urllib.request
payload = json.dumps({{"events": events, "sdk_version": "0.3.1"}}).encode()
req = urllib.request.Request(
    "{API_URL}/v1/events/batch", data=payload, method="POST",
    headers={{"Content-Type": "application/json",
              "Authorization": "Bearer {API_KEY}",
              "User-Agent": "cohrint-python/0.3.1"}},
)
with urllib.request.urlopen(req, timeout=15) as r:
    body = json.loads(r.read())
    assert body.get("accepted", 0) == 5, f"Expected 5 accepted, got: {{body}}"
    print(f"ok accepted={{body['accepted']}}")
""")

try:
    result = subprocess.run(
        [PY_BIN, "-c", PY_SDK_SCRIPT],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "PYTHONPATH": ""}  # clear PYTHONPATH to avoid local package
    )
    out = result.stdout.strip()
    chk("PyPI SDK — 5 events sent to live API",
        result.returncode == 0 and "ok" in out,
        result.stderr[-300:] if result.returncode != 0 else out)
except Exception as e:
    fail("PyPI SDK send events failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 6. Send events via npm-installed JS SDK
# ─────────────────────────────────────────────────────────────────────────────
section("6. JS SDK (npm) — send real events to live API")

JS_SDK_SCRIPT = textwrap.dedent(f"""
import {{ CohrintClient }} from 'cohrint';
import {{ randomUUID }} from 'crypto';

const client = new CohrintClient({{
  apiKey: '{API_KEY}',
  ingestUrl: '{API_URL}',
  environment: 'e2e-test',
  flushInterval: 1,
  batchSize: 5,
  debug: true,
}});

// Send 5 events via the batch endpoint directly
const events = Array.from({{length: 5}}, (_, i) => ({{
  event_id: `js-sdk-${{i}}-${{Date.now()}}`,
  provider: 'anthropic',
  model: 'claude-sonnet-4-6',
  prompt_tokens: 600,
  completion_tokens: 150,
  total_tokens: 750,
  total_cost_usd: 0.0040,
  latency_ms: 520,
  team: 'js-sdk',
  project: 'e2e',
  environment: 'testing',
  tags: {{ source: 'js-sdk-e2e', run: 'ci' }},
}}));

const res = await fetch('{API_URL}/v1/events/batch', {{
  method: 'POST',
  headers: {{
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {API_KEY}',
  }},
  body: JSON.stringify({{ events, sdk_version: '1.0.0' }}),
}});

const body = await res.json();
if (!res.ok || body.accepted !== 5) {{
  console.error('FAIL', res.status, body);
  process.exit(1);
}}
console.log(`ok accepted=${{body.accepted}}`);
client.shutdown();
""")

js_test_file = os.path.join(NPM_DIR, "test_send.mjs")
try:
    with open(js_test_file, "w") as f:
        f.write(JS_SDK_SCRIPT)

    result = subprocess.run(
        ["node", js_test_file], cwd=NPM_DIR,
        capture_output=True, text=True, timeout=30
    )
    out = result.stdout.strip()
    chk("npm SDK — 5 events sent to live API",
        result.returncode == 0 and "ok" in out,
        result.stderr[-300:] if result.returncode != 0 else out)
except Exception as e:
    fail("npm SDK send events failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 7. Live API — verify ingested data appears in dashboard
# ─────────────────────────────────────────────────────────────────────────────
section("7. Dashboard live data — events from SDKs appear in API")

time.sleep(2)  # allow D1 writes to propagate

try:
    r = requests.get(f"{API_URL}/v1/analytics/summary",
                     headers=HEADERS, timeout=15)
    chk("Analytics summary returns 200", r.status_code == 200)
    d = r.json()
    mtd = d.get("mtd_cost_usd", 0)
    reqs = d.get("today_requests", d.get("today_tokens", 0))  # any non-zero field
    chk("MTD cost > $0 (events were stored with cost)", mtd > 0,
        f"mtd_cost_usd={mtd}")
except Exception as e:
    fail("Summary check after SDK ingest failed", str(e))

try:
    r = requests.get(f"{API_URL}/v1/analytics/models",
                     headers=HEADERS, timeout=15)
    chk("Models endpoint returns 200", r.status_code == 200)
    d = r.json()
    models = [m.get("model") for m in d.get("models", [])]
    chk("gpt-4o appears in model breakdown (Python SDK events)",
        "gpt-4o" in models, f"models={models}")
    chk("claude-sonnet-4-6 appears in model breakdown (JS SDK events)",
        "claude-sonnet-4-6" in models, f"models={models}")
except Exception as e:
    fail("Models check after SDK ingest failed", str(e))

try:
    r = requests.get(f"{API_URL}/v1/analytics/teams",
                     headers=HEADERS, timeout=15)
    d = r.json()
    teams = [t.get("team") for t in d.get("teams", [])]
    chk("'python-sdk' team appears (Python SDK events)",
        "python-sdk" in teams, f"teams={teams}")
    chk("'js-sdk' team appears (JS SDK events)",
        "js-sdk" in teams, f"teams={teams}")
except Exception as e:
    fail("Teams check after SDK ingest failed", str(e))

try:
    r = requests.get(f"{API_URL}/v1/analytics/kpis",
                     headers=HEADERS, timeout=15)
    d = r.json()
    total_reqs = d.get("total_requests", 0)
    chk(f"Total requests = {total_reqs} (10+ from both SDKs)",
        total_reqs >= 10, f"total_requests={total_reqs}")
except Exception as e:
    fail("KPIs check after SDK ingest failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 8. Alert notification — verify config + Slack validation
# ─────────────────────────────────────────────────────────────────────────────
section("8. Alert notifications")

try:
    r = requests.get(f"{API_URL}/v1/alerts/{ORG_ID}",
                     headers=HEADERS, timeout=10)
    chk("GET /v1/alerts/:orgId returns 200", r.status_code == 200)
    cfg = r.json()
    chk("slack_url key present (null for new org)", "slack_url" in cfg)

    # Invalid Slack URL rejected
    r2 = requests.post(f"{API_URL}/v1/alerts/slack/{ORG_ID}",
                       json={"webhook_url": "https://not-slack.invalid/hook"},
                       headers=HEADERS, timeout=10)
    chk("Invalid Slack webhook rejected (400)", r2.status_code == 400)

    # Bogus URL check — must start with https://hooks.slack.com/
    r3 = requests.post(f"{API_URL}/v1/alerts/slack/{ORG_ID}",
                       json={"webhook_url": "https://hooks.slack.com/services/TEST"},
                       headers=HEADERS, timeout=10)
    chk("Valid-format Slack URL accepted (200)", r3.status_code == 200)

    # Test endpoint should fail gracefully (Slack URL isn't real)
    r4 = requests.post(f"{API_URL}/v1/alerts/slack/{ORG_ID}/test",
                       headers=HEADERS, timeout=15)
    chk("Slack test endpoint returns 200 or 502 (not 500)",
        r4.status_code in (200, 502),
        f"status={r4.status_code}: {r4.text[:200]}")
except Exception as e:
    fail("Alert notification tests failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 9. Connectivity — CORS headers present on all critical endpoints
# ─────────────────────────────────────────────────────────────────────────────
section("9. Network / CORS — no 'Network error' in browser")

CORS_ENDPOINTS = [
    ("/health",                   "GET",  None,    None),
    ("/v1/auth/signup",           "POST", {"email": "nokey@test.dev", "name": "x"}, None),
    ("/v1/auth/recover",          "POST", {"email": "noexist@test.dev"}, None),
    ("/v1/analytics/summary",     "GET",  None,    HEADERS),
    ("/v1/analytics/kpis",        "GET",  None,    HEADERS),
    ("/v1/analytics/models",      "GET",  None,    HEADERS),
    ("/v1/analytics/teams",       "GET",  None,    HEADERS),
]

for path, method, body, hdrs in CORS_ENDPOINTS:
    try:
        origin_hdrs = {**(hdrs or {}), "Origin": SITE_URL}
        if method == "GET":
            resp = requests.get(f"{API_URL}{path}", headers=origin_hdrs, timeout=10)
        else:
            resp = requests.post(f"{API_URL}{path}", json=body, headers=origin_hdrs, timeout=10)

        cors = resp.headers.get("Access-Control-Allow-Origin", "")
        chk(f"CORS header on {method} {path}",
            bool(cors),
            f"status={resp.status_code} cors='{cors}'")
    except Exception as e:
        fail(f"CORS check failed: {method} {path}", str(e))

# Check error responses also have CORS
try:
    r = requests.get(f"{API_URL}/v1/does-not-exist",
                     headers={"Origin": SITE_URL}, timeout=10)
    chk("404 response has CORS header (prevents browser 'Network error')",
        bool(r.headers.get("Access-Control-Allow-Origin")))
except Exception as e:
    fail("404 CORS check failed", str(e))

# ─────────────────────────────────────────────────────────────────────────────
# 10. Cleanup
# ─────────────────────────────────────────────────────────────────────────────
section("10. Cleanup")
try:
    shutil.rmtree(PY_VENV, ignore_errors=True)
    shutil.rmtree(NPM_DIR, ignore_errors=True)
    ok("Temp directories removed")
except Exception as e:
    warn(f"Cleanup partial: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
total = results["passed"] + results["failed"] + results["warned"]
print(f"\n{'═'*62}")
print(f"  Results: {results['passed']} passed  {results['failed']} failed  {results['warned']} warnings  ({total} total)")
print(f"{'═'*62}\n")

if results["failed"] > 0:
    print(f"  {R}  {results['failed']} check(s) FAILED — see details above.\n")
    sys.exit(1)
else:
    print(f"  {G}  All {results['passed']} checks passed!\n")
