# Cohrint Security Audit — 2026-04-09
_Internal report. Not for public distribution._

---

## Scope

Static frontend (`vantage-final-v4/`), Cloudflare Worker API (`vantage-worker/src/`), and public documentation (`vantage-final-v4/docs.html`). Audit performed as part of the website enterprise overhaul (Phase 4 of the 2026-04-09 overhaul plan).

Out of scope: penetration testing, third-party scanning, Cloudflare WAF/firewall rules, dependency vulnerability scanning.

---

## Findings

### FIND-001 — HSTS header missing (Medium → Fixed)
**Area:** HTTP headers (`_headers`)  
**Severity:** Medium  
**Description:** `Strict-Transport-Security` header was absent. Browsers would not enforce HTTPS-only connections on future visits, enabling protocol downgrade attacks on first visit.  
**Fix applied:** Added `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` to the global `/*` rule in `vantage-final-v4/_headers`.  
**Commit:** `03a344c`

---

### FIND-002 — COOP/CORP headers missing (Low → Fixed)
**Area:** HTTP headers (`_headers`)  
**Severity:** Low  
**Description:** `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` were absent, leaving the app exposed to cross-origin window reference attacks (Spectre-class) and cross-origin resource embedding.  
**Fix applied:** Added `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` to global `/*` rule.  
**Commit:** `03a344c`

---

### FIND-003 — CSP missing `frame-ancestors` directive (Medium → Fixed)
**Area:** HTTP headers (`_headers`)  
**Severity:** Medium  
**Description:** The `Content-Security-Policy` on `/app.html` and `/app` routes did not include `frame-ancestors 'none'`. The `X-Frame-Options: DENY` header was set but CSP `frame-ancestors` is the modern replacement and takes precedence in modern browsers. Without it, the CSP is incomplete.  
**Fix applied:** Added `frame-ancestors 'none'` to all CSP directives on `/app.html`, `/app`, and `/superadmin.html` routes.  
**Commit:** `03a344c`

---

### FIND-004 — No brute-force protection on `/v1/auth/session` (High → Fixed)
**Area:** Auth surface (`vantage-worker/src/routes/auth.ts`)  
**Severity:** High  
**Description:** The `POST /v1/auth/session` endpoint had no rate limiting. An attacker could attempt unlimited API key guesses. The `/v1/auth/signup` and `/v1/auth/recover` endpoints already had rate limiting; this endpoint was missed.  
**Fix applied:** Added KV-backed IP rate limiting: 10 attempts per IP per 5-minute window (TTL=300s). Returns HTTP 429 with `Retry-After: 300` on breach. Degrades gracefully if KV is unavailable.  
**Commit:** `03a344c`

---

### FIND-005 — `prompt_hash` field accepts arbitrary strings (Low → Fixed)
**Area:** API input validation (`vantage-worker/src/routes/events.ts`)  
**Severity:** Low  
**Description:** The `prompt_hash` field accepted any string value. A malformed hash (e.g., excessively long or containing non-hex characters) could produce unexpected KV key collisions or bloated KV storage.  
**Fix applied:** Added format validation: must be a hex string between 32 and 128 characters (`/^[0-9a-f]{32,128}$/i`). Applied to both single-event (`POST /v1/events`) and batch (`POST /v1/events/batch`) endpoints. Returns HTTP 400 on invalid format.  
**Commit:** `03a344c`

---

### FIND-006 — Competitive intelligence exposed in public docs (Low → Fixed)
**Area:** Public documentation (`vantage-final-v4/docs.html`)  
**Severity:** Low  
**Description:** Two implementation details were visible to competitors in the public docs:
1. **Line ~1736:** Described the fuzzy substring-matching pricing algorithm including an exact example (`claude-sonnet-4-6-20260301` → `claude-sonnet-4-6`).
2. **Line ~1268:** Named the `MD5` algorithm used for `user_id` hashing in the privacy mode table.

**Fix applied:**
- Fuzzy-match description replaced with: "Model variants are automatically resolved to their base pricing."
- MD5 replaced with "hashed identifier".  
**Commit:** `be7839b`

---

### FIND-007 — False compliance claims on landing page (High → Fixed)
**Area:** Frontend (`vantage-final-v4/index.html`)  
**Severity:** High  
**Description:** The landing page displayed SOC2 Ready, GDPR Compliant, and HIPAA Ready trust badges. None of these certifications are held. This constitutes a false claim that could expose the company to legal risk and damages user trust when scrutinized by enterprise procurement.  
**Fix applied:** Replaced badge grid with a list of actual implemented security controls (SHA-256 hashing, HTTP-only sessions, audit log, TLS, rate limiting, local proxy). Removed all certification badges.  
**Commit:** `a75c7e9`

---

### FIND-008 — Unshipped features advertised as shipped (High → Fixed)
**Area:** Frontend (`vantage-final-v4/index.html`)  
**Severity:** High  
**Description:** The following features were listed in pricing and comparison tables but are not built:
- AI model auto-router
- SSO / SAML
- Self-hosted deployment
- SOC2 + HIPAA compliance

**Fix applied:** All four removed from pricing feature lists and comparison table.  
**Commit:** `a75c7e9`

---

### FIND-009 — Fake testimonials with person names and dollar figures (Medium → Fixed)
**Area:** Frontend (`vantage-final-v4/index.html`)  
**Severity:** Medium  
**Description:** Three testimonials attributed to named individuals (Jordan Kim, Meera Patel, Alex Rivera) with specific dollar figures ($1,800/month, $40k/month). These are fabricated. FTC guidelines and general advertising standards prohibit fake testimonials.  
**Fix applied:** Entire testimonials section replaced with a factual stat block: "10+ AI tools tracked · 40+ metrics per call · Hosted on Cloudflare's global edge".  
**Commit:** `a75c7e9`

---

## Not Fixed / Deferred

### DEFER-001 — `localStorage` API key storage in app.html
**Area:** Frontend (app.html)  
**Severity:** Medium  
**Description:** `app.html` caches API responses in localStorage under a key prefixed with the org_id. The session authentication itself uses HTTP-only cookies (secure), but localStorage is accessible to any JS on the page, including XSS payloads. The current caching stores analytics response data, not the raw API key — the risk is data leakage rather than credential theft.  
**Why deferred:** Removing localStorage caching would require a meaningful refactor of the cache layer. The session cookie model is already XSS-resistant. This is tracked for a future hardening sprint.

### DEFER-002 — CSP `unsafe-inline` in app.html and docs.html
**Area:** HTTP headers  
**Severity:** Low  
**Description:** Both pages use `'unsafe-inline'` in their CSP `default-src`. Removing this would require moving all inline `<style>` and `<script>` to external files — a significant refactor given the current single-file static architecture.  
**Why deferred:** The `frame-ancestors 'none'` + `X-Frame-Options: DENY` combination significantly limits clickjacking risk. Full CSP nonce implementation tracked for a future hardening sprint.

---

## Summary

| Finding | Severity | Status |
|---------|----------|--------|
| FIND-001 HSTS missing | Medium | Fixed |
| FIND-002 COOP/CORP missing | Low | Fixed |
| FIND-003 CSP frame-ancestors missing | Medium | Fixed |
| FIND-004 /session brute-force unprotected | High | Fixed |
| FIND-005 prompt_hash no format validation | Low | Fixed |
| FIND-006 Competitive intel in public docs | Low | Fixed |
| FIND-007 False compliance badges | High | Fixed |
| FIND-008 Unshipped features advertised | High | Fixed |
| FIND-009 Fake testimonials | Medium | Fixed |
| DEFER-001 localStorage analytics cache | Medium | Deferred |
| DEFER-002 CSP unsafe-inline | Low | Deferred |

**High findings fixed: 3/3. Total findings fixed: 9/11.**
