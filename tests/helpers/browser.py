"""
browser.py — Playwright browser helpers for Cohrint test suite
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import HEADLESS, SITE_URL


# ── Standard desktop viewport ─────────────────────────────────────────────────

def make_browser_ctx(playwright, viewport=(1280, 800)):
    """
    Return (browser, context, page) for a fresh Chromium desktop session.
    Caller is responsible for closing browser when done.
    """
    browser = playwright.chromium.launch(headless=HEADLESS)
    ctx = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        ignore_https_errors=False,
    )
    page = ctx.new_page()
    return browser, ctx, page


# ── Multi-browser / device factory ───────────────────────────────────────────

# Desktop browser matrix — (engine_name, display_name, viewport)
DESKTOP_BROWSERS = [
    ("chromium", "Chrome (Desktop)",        (1440, 900)),
    ("firefox",  "Firefox (Desktop)",       (1440, 900)),
    ("webkit",   "Safari macOS (Desktop)",  (1440, 900)),
]

# Mobile device matrix — (playwright_device_name, display_name, engine)
# engine: 'chromium' for Android devices, 'webkit' for Apple devices
MOBILE_DEVICES = [
    ("Pixel 5",            "Android Chrome (Mobile)",  "chromium"),
    ("Pixel 7",            "Android Chrome (Pixel 7)", "chromium"),
    ("iPhone 14",          "Mobile Safari (iPhone 14)", "webkit"),
    ("iPhone 14 Pro Max",  "Mobile Safari (iPhone 14 Pro Max)", "webkit"),
    ("Galaxy S8",          "Samsung Internet (Mobile)", "chromium"),
]

# Tablet device matrix
TABLET_DEVICES = [
    ("iPad Pro 11",       "Safari iPad (Tablet)",         "webkit"),
    ("iPad (gen 7)",      "Safari iPad Mini (Tablet)",    "webkit"),
    ("Galaxy Tab S4",     "Android Chrome (Tablet)",      "chromium"),
    ("Nexus 10",          "Android Chrome (Large Tablet)", "chromium"),
]

# Linux/Ubuntu desktop — treated as Chromium on Linux CI
LINUX_BROWSERS = [
    ("chromium", "Chromium / Ubuntu (Linux)", (1920, 1080)),
    ("firefox",  "Firefox / Ubuntu (Linux)",  (1920, 1080)),
]


def make_desktop_ctx(playwright, engine="chromium", width=1440, height=900):
    """
    Launch a desktop browser context for the given engine.
    engine: 'chromium' | 'firefox' | 'webkit'
    Returns (browser, context, page).
    """
    launcher = getattr(playwright, engine)
    browser = launcher.launch(headless=HEADLESS)
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        ignore_https_errors=False,
    )
    page = ctx.new_page()
    return browser, ctx, page


def make_device_ctx(playwright, device_name, engine="chromium"):
    """
    Launch a mobile/tablet browser context using a Playwright device descriptor.
    Returns (browser, context, page).
    """
    from playwright.sync_api import sync_playwright
    device = playwright.devices.get(device_name)
    if device is None:
        # Fallback: try a close match
        matches = [k for k in playwright.devices if device_name.lower() in k.lower()]
        device = playwright.devices.get(matches[0]) if matches else None
    if device is None:
        raise ValueError(f"Unknown Playwright device: {device_name!r}")

    launcher = getattr(playwright, engine)
    browser = launcher.launch(headless=HEADLESS)
    ctx = browser.new_context(**device, ignore_https_errors=False)
    page = ctx.new_page()
    return browser, ctx, page


# ── Console error helpers ─────────────────────────────────────────────────────

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
    # Google Fonts download failures in CI (Firefox can't reach fonts.gstatic.com)
    "downloadable font",
    "fonts.gstatic.com",
    "fonts.googleapis.com",
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


# ── Auth helper ───────────────────────────────────────────────────────────────

def signin_ui(page, api_key: str, timeout=15_000) -> bool:
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
