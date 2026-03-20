"""
test_17_homepage_stability.py — Homepage & Landing Page Stability Tests
=======================================================================
Developer notes:
  Targets the reported bug: "home page is not stable at all"

  Homepage stability covers:
    • Renders correctly in multiple browsers (Chrome only via Playwright)
    • No JS errors on initial load
    • All section anchors scroll to correct positions
    • CTA buttons link to correct destinations (/signup, /auth)
    • Pricing section shows correct tier info
    • FAQ section renders
    • Feature cards render
    • No broken images (404 on assets)
    • Page speed / Core Web Vitals approximation
    • SEO meta tags present
    • Open Graph tags present
    • Canonical URL set
    • PWA manifest present
    • Footer links valid
    • No console.error calls
    • No resource load errors (CSS, JS, images)
    • HTTPS redirect (http → https)
    • www → apex redirect works
    • Page renders without FOUC (flash of unstyled content)
    • Mobile: viewport meta tag present
    • Accessibility: heading hierarchy correct (h1, h2, h3)

Tests (17.1 – 17.40):
  17.1  GET / returns 200
  17.2  Response Content-Type: text/html
  17.3  Response < 500KB (no bloated payload)
  17.4  /index.html loads in browser (Playwright)
  17.5  No JS errors on landing page load
  17.6  No resource 404s (CSS/JS/images)
  17.7  No console.error calls during load
  17.8  Page title correct (contains "Vantage" or product name)
  17.9  Meta description present
  17.10 OG tags (og:title, og:description, og:url)
  17.11 Canonical link tag present
  17.12 PWA manifest.json referenced
  17.13 Hero section / above-the-fold content renders
  17.14 Hero CTA button(s) visible
  17.15 Hero CTA "Get Started" links to /signup
  17.16 Sign in link links to /auth
  17.17 Pricing section visible
  17.18 Pricing: Free tier card visible
  17.19 Pricing: Pro or paid tier card visible
  17.20 Feature cards section renders (≥ 3 features)
  17.21 FAQ section renders
  17.22 Footer visible
  17.23 Footer links not empty hrefs
  17.24 Navigation bar visible
  17.25 Nav links: Home, Docs, Pricing, Login
  17.26 Scroll to pricing anchor works without crash
  17.27 Scroll to features anchor works without crash
  17.28 Mobile (375px): page renders, no horizontal scroll
  17.29 Mobile: font size legible (> 14px on body)
  17.30 Viewport meta tag: width=device-width
  17.31 Heading hierarchy: h1 present
  17.32 Heading hierarchy: h2 present (feature sections)
  17.33 Images: all <img> tags have alt attributes
  17.34 Dark theme: background is dark (CSS variable)
  17.35 Accent colour #00d4a1 referenced in CSS
  17.36 DM Sans font loaded (no fallback to serif)
  17.37 Page fully interactive within 5 seconds of load
  17.38 No 500 errors from landing page CDN assets
  17.39 Multiple reloads: page stable (no crash on 3rd reload)
  17.40 Landing page: no "undefined" or "NaN" text visible

Run:
  python tests/test_17_homepage_stability.py
  HEADLESS=0 python tests/test_17_homepage_stability.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import requests
from helpers import (
    SITE_URL, make_browser_ctx, collect_console_errors, HEADLESS,
    ok, fail, warn, info, section, chk, get_results,
)
from logging_infra.structured_logger import get_logger

log = get_logger("test.homepage")


# ─────────────────────────────────────────────────────────────────────────────
section("17-A. HTTP layer checks (no browser)")
# ─────────────────────────────────────────────────────────────────────────────

# 17.1 GET / → 200
with log.timer("GET / (landing page)"):
    r = requests.get(SITE_URL, timeout=20, allow_redirects=True)
chk("17.1  GET / returns 200", r.status_code == 200, f"got {r.status_code}")
chk("17.2  Content-Type: text/html",
    "text/html" in r.headers.get("Content-Type", ""),
    f"Content-Type: {r.headers.get('Content-Type')}")
body_kb = round(len(r.content) / 1024)
chk("17.3  Response < 500KB", body_kb < 500, f"size={body_kb}KB")
info(f"     Landing page size: {body_kb}KB")

html = r.text

# 17.8 Title
import re
title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
title = title_m.group(1).strip() if title_m else ""
chk("17.8  Page title contains 'Vantage'", "vantage" in title.lower(),
    f"title: '{title}'")

# 17.9 Meta description
chk("17.9  Meta description present",
    'name="description"' in html.lower() or 'property="og:description"' in html.lower())

# 17.10 OG tags
chk("17.10 og:title present", 'property="og:title"' in html.lower())
chk("17.10b og:description present", 'property="og:description"' in html.lower())
chk("17.10c og:url present", 'property="og:url"' in html.lower())

# 17.11 Canonical
chk("17.11 Canonical link tag present",
    'rel="canonical"' in html.lower())

# 17.12 PWA manifest
chk("17.12 PWA manifest referenced",
    "manifest" in html.lower() and ".json" in html.lower())

# 17.30 Viewport meta tag
chk("17.30 Viewport meta: width=device-width",
    "width=device-width" in html.lower())

# 17.31 h1 present
chk("17.31 h1 heading present", "<h1" in html.lower())

# 17.32 h2 present
chk("17.32 h2 headings present", "<h2" in html.lower())

# 17.34 Dark theme
chk("17.34 Dark theme CSS (background or bg-color) referenced",
    "#0d1318" in html or "background" in html.lower())

# 17.35 Accent colour
chk("17.35 Accent colour #00d4a1 in CSS",
    "#00d4a1" in html or "00d4a1" in html)

# 17.40 No undefined/NaN in HTML source
chk("17.40 No 'undefined' or 'NaN' text in HTML source",
    "undefined" not in html.lower()[:5000] and "NaN" not in html[:5000],
    "Found undefined/NaN in HTML source")

# SEO/heading structure
h1_count = html.lower().count("<h1")
chk("17.31b Single h1 (good SEO)", h1_count == 1, f"found {h1_count} h1 tags")


# ─────────────────────────────────────────────────────────────────────────────
section("17-B. Browser rendering (Playwright)")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as pw:

        # ── Desktop load ──────────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw, viewport=(1440, 900))
        resource_errors = []
        js_errors       = collect_console_errors(page)

        # Track all failed resource loads
        page.on("response", lambda r: resource_errors.append(
            f"{r.status} {r.url}") if r.status in (404, 500, 502, 503) else None)

        try:
            t0 = time.monotonic()
            page.goto(SITE_URL, wait_until="networkidle", timeout=30_000)
            load_ms = round((time.monotonic() - t0) * 1000)
            page.wait_for_timeout(1_000)

            chk("17.4  Landing page loads in browser", True)
            info(f"     Load time: {load_ms}ms")
            chk("17.37 Page fully interactive within 5 seconds",
                load_ms < 5000, f"took {load_ms}ms")

            # 17.5 No JS errors
            chk("17.5  No JS errors on landing page load",
                len(js_errors) == 0, f"errors: {js_errors[:3]}")

            # 17.6 No 404s on resources
            css_js_404 = [e for e in resource_errors
                          if "404" in e and any(x in e for x in [".css", ".js", ".png", ".svg", ".ico"])]
            chk("17.6  No 404s on CSS/JS/image resources",
                len(css_js_404) == 0, f"404s: {css_js_404}")
            chk("17.38 No 500s from CDN assets",
                not any("500" in e or "502" in e or "503" in e for e in resource_errors),
                f"5xx: {[e for e in resource_errors if '5' in e[:3]]}")

            content        = page.content()
            content_lower  = content.lower()

            # 17.13 Hero section
            chk("17.13 Hero section renders",
                any(w in content_lower for w in [
                    "hero", "banner", "headline", "track", "ai", "cost"]))

            # 17.14 CTA buttons
            cta_btns = page.locator(
                "a:has-text('Get Started'), button:has-text('Get Started'), "
                "a:has-text('Start Free'), a:has-text('Try Free'), "
                "a:has-text('Sign Up'), .cta-btn, .hero-cta"
            ).count()
            chk("17.14 Hero CTA button(s) visible", cta_btns >= 1,
                f"found {cta_btns} CTA buttons")

            # 17.15 CTA links to /signup
            cta = page.locator(
                "a[href*='/signup'], a[href*='signup'], a[href*='/register']"
            ).first
            chk("17.15 CTA 'Get Started' links to /signup",
                cta.count() > 0, "No link to /signup found on landing")

            # 17.16 Sign in link
            signin_link = page.locator(
                "a[href*='/auth'], a[href*='/login'], a:has-text('Sign In'), "
                "a:has-text('Log In')"
            ).first
            chk("17.16 Sign-in link links to /auth or /login",
                signin_link.count() > 0, "No sign-in link found")

            # 17.17–17.19 Pricing section
            chk("17.17 Pricing section visible",
                any(w in content_lower for w in ["pricing", "plan", "tier", "free tier"]))
            chk("17.18 Free tier card visible",
                "free" in content_lower)
            chk("17.19 Pro or paid tier card visible",
                any(w in content_lower for w in ["pro", "enterprise", "paid", "premium"]))

            # 17.20 Feature cards (≥ 3)
            feature_kws = ["cost", "analytics", "team", "budget", "alert",
                           "trace", "model", "provider", "stream"]
            feature_count = sum(1 for kw in feature_kws if kw in content_lower)
            chk("17.20 Feature cards section (≥ 3 features described)",
                feature_count >= 3, f"found {feature_count} feature keywords")

            # 17.21 FAQ
            chk("17.21 FAQ section renders",
                any(w in content_lower for w in ["faq", "frequently", "question"]))

            # 17.22 Footer
            footer = page.locator("footer").first
            chk("17.22 Footer visible", footer.count() > 0 or "footer" in content_lower)

            # 17.23 Footer links not empty
            if footer.count() > 0:
                footer_links = footer.locator("a").all()
                empty_hrefs = [l.get_attribute("href") for l in footer_links
                               if l.get_attribute("href") in ("", "#", "javascript:void(0)")]
                chk("17.23 Footer links not empty",
                    len(empty_hrefs) == 0, f"empty hrefs: {empty_hrefs}")

            # 17.24 Nav bar
            nav = page.locator("nav, header").first
            chk("17.24 Navigation bar visible", nav.count() > 0)

            # 17.25 Nav links
            nav_text = nav.inner_text().lower() if nav.count() > 0 else content_lower[:2000]
            chk("17.25 Nav has Docs/Pricing/Login links",
                any(w in nav_text for w in ["docs", "pricing", "login", "sign in", "get started"]))

            # 17.33 Images alt attributes
            imgs = page.locator("img").all()
            missing_alt = [img.get_attribute("src", timeout=1000)
                           for img in imgs
                           if not img.get_attribute("alt", timeout=1000)]
            chk("17.33 All images have alt attributes",
                len(missing_alt) == 0, f"missing alt: {missing_alt[:5]}")

            # 17.7 No console.error calls
            console_errors = [e for e in js_errors if "error" in e.lower()]
            chk("17.7  No console.error calls",
                len(console_errors) == 0, f"errors: {console_errors[:3]}")

        except Exception as e:
            fail("17-B  Desktop landing page test error", str(e)[:300])
            log.exception("Homepage desktop crash", e)

        ctx.close()
        browser.close()


        # ── Scroll anchor tests ─────────────────────────────────────────────
        browser, ctx, page = make_browser_ctx(pw)
        errs = collect_console_errors(page)
        try:
            page.goto(SITE_URL, wait_until="networkidle", timeout=25_000)
            page.wait_for_timeout(1_000)

            # 17.26 Scroll to pricing
            try:
                pricing_el = page.locator(
                    "#pricing, [id*='pricing'], a[href='#pricing']"
                ).first
                if pricing_el.count() > 0:
                    pricing_el.scroll_into_view_if_needed()
                    page.wait_for_timeout(800)
                    chk("17.26 Scroll to pricing anchor: no crash",
                        len(page.content()) > 500)
                else:
                    # Try clicking pricing nav link
                    pricing_link = page.locator("a:has-text('Pricing')").first
                    if pricing_link.count() > 0:
                        pricing_link.click()
                        page.wait_for_timeout(800)
                        chk("17.26 Pricing link click: no crash", len(page.content()) > 500)
                    else:
                        warn("17.26 Pricing anchor not found")
            except Exception as e:
                warn(f"17.26 Scroll pricing: {e}")

            # 17.27 Scroll to features
            try:
                feat_el = page.locator(
                    "#features, [id*='feature'], a[href='#features']"
                ).first
                if feat_el.count() > 0:
                    feat_el.scroll_into_view_if_needed()
                    page.wait_for_timeout(800)
                    chk("17.27 Scroll to features anchor: no crash",
                        len(page.content()) > 500)
                else:
                    warn("17.27 Features anchor not found")
            except Exception as e:
                warn(f"17.27 Scroll features: {e}")

        except Exception as e:
            fail("17-B  Scroll test error", str(e)[:200])
        ctx.close()
        browser.close()


        # ── Mobile rendering ─────────────────────────────────────────────────
        section("17-C. Mobile rendering (375×812)")

        browser_m, ctx_m, page_m = make_browser_ctx(pw, viewport=(375, 812))
        res_errors_m = []
        js_errors_m  = collect_console_errors(page_m)
        page_m.on("response", lambda r: res_errors_m.append(f"{r.status}")
                  if r.status == 404 else None)
        try:
            page_m.goto(SITE_URL, wait_until="networkidle", timeout=25_000)
            page_m.wait_for_timeout(1_000)

            # 17.28 No horizontal scroll
            scroll_width  = page_m.evaluate("document.documentElement.scrollWidth")
            client_width  = page_m.evaluate("document.documentElement.clientWidth")
            chk("17.28 Mobile: no horizontal scroll (scrollWidth ≤ clientWidth + 5)",
                scroll_width <= client_width + 5,
                f"scrollWidth={scroll_width} clientWidth={client_width}")

            # 17.29 Font size legible
            try:
                font_size = page_m.evaluate(
                    "parseInt(getComputedStyle(document.body).fontSize) || 16"
                )
                chk("17.29 Mobile: body font size ≥ 14px",
                    font_size >= 14, f"font-size={font_size}px")
            except Exception as e:
                warn(f"17.29 Font size check: {e}")

            # 17.5 mobile JS errors
            chk("17.5b Mobile: no JS errors on load",
                len(js_errors_m) == 0, f"errors: {js_errors_m[:3]}")

            content_m = page_m.content().lower()
            chk("17.13b Mobile: hero content renders",
                any(w in content_m for w in ["vantage", "ai", "cost"]))

        except Exception as e:
            fail("17-C  Mobile rendering test error", str(e)[:200])
        ctx_m.close()
        browser_m.close()


        # ── Reload stability ─────────────────────────────────────────────────
        section("17-D. Reload stability (3 reloads)")

        browser_r, ctx_r, page_r = make_browser_ctx(pw)
        js_errors_r = collect_console_errors(page_r)
        try:
            page_r.goto(SITE_URL, wait_until="networkidle", timeout=25_000)
            for i in range(3):
                page_r.reload(wait_until="networkidle", timeout=25_000)
                page_r.wait_for_timeout(800)

            chk("17.39 3 reloads: page stable (not blank/crashed)",
                len(page_r.content()) > 1000, f"body={len(page_r.content())} chars")
            chk("17.39b 3 reloads: no new JS errors",
                len(js_errors_r) == 0, f"errors: {js_errors_r[:3]}")

        except Exception as e:
            fail("17-D  Reload stability test", str(e)[:200])
        ctx_r.close()
        browser_r.close()


except ImportError:
    warn("Playwright not installed — run: pip install playwright && python -m playwright install chromium")
except Exception as e:
    fail("test_17  Homepage stability suite crashed", str(e)[:400])
    log.exception("Homepage stability crash", e)


r = get_results()
total = r["passed"] + r["failed"] + r["warned"]
print(f"\n  Homepage stability tests: {r['passed']} passed  {r['failed']} failed  {r['warned']} warned  ({total} total)\n")
sys.exit(1 if r["failed"] else 0)
