# VantageAI Website & Security Overhaul — Design Spec
_2026-04-09 · Approved by Aman Jain_

---

## Overview

Four-phase overhaul of the VantageAI public website (`vantage-final-v4/`) and Worker security surface. Ordered by risk and effort: quick content fixes first, then enterprise redesign, then live demo, then security audit.

**Sales email:** vantageaiops@gmail.com (used for all pricing CTAs)

---

## Phase 1 — Content Cleanup (Quick Wins)

### 1.1 `index.html` — Tool Name Removal

Remove all mentions of **Windsurf**, **Zed**, and **JetBrains** from:
- Hero tagline
- MCP feature description row in comparison table
- Any feature bullets or integration lists

Replace with: "AI-native IDEs" or "MCP-compatible editors" where context requires specificity.

### 1.2 `index.html` — Remove Fake Reviews

Delete the three testimonial cards entirely:
- Jordan Kim (Engineering Lead, AI startup Series A)
- Meera Patel (CTO, 300-person SaaS)
- Alex Rivera (Senior ML Engineer, consultancy)

Replace the entire testimonials section with a single centered stat block:
> "10+ AI tools tracked · 40+ metrics per call · Hosted on Cloudflare's global edge"

No person names, no company names, no dollar figures until real testimonials exist.

### 1.3 `index.html` — Comparison Table

Rename competitor columns:
- "Helicone" → "API Gateway Tools"
- "LangSmith" → "LLM Observability SDKs"
- "Datadog LLM" → "General APM Platforms"

Add footnote below table:
> "Capabilities based on publicly documented features of top-rated tools in each category (G2, Capterra, vendor documentation). No competitor is specifically named or implied."

### 1.4 `index.html` — Footer Legal Links

Add a Legal column to the footer with:
- Terms of Service → `/terms.html`
- Privacy Policy → `/privacy.html`

### 1.5 `docs.html` — Tool Name Removal

Remove or rename:
- Nav item: "Zed / JetBrains" → remove entirely
- Section heading: "Windsurf" → remove section
- Section heading: "Zed & JetBrains" → remove section
- Replace removed sections with a generic note: "VantageAI MCP works with any MCP-compatible editor. See your editor's documentation for MCP server configuration."

### 1.6 `docs.html` — Competitive Intelligence Redaction

Remove these internal implementation details:
- **Line ~1736:** Fuzzy pricing match description ("tries substring matching, e.g. `claude-sonnet-4-6-20260301` matches `claude-sonnet-4-6`") → replace with: "VantageAI automatically resolves model variants to their base pricing."
- **Line ~1268:** Replace "MD5" with "hashed" in privacy mode table. The full-mode description should say "hashed identifier" not name the algorithm.

Keep (not sensitive):
- Model pricing table — public provider prices
- Admin API endpoints — expected developer documentation
- SHA-256 for API key hashing — standard practice

### 1.7 `app.html` — Docs Link in Nav

Add "Docs" link in the app navigation bar pointing to `/docs.html`. Opens in new tab.

---

## Phase 2 — Enterprise Redesign

### 2.1 Visual Direction

**Aesthetic:** Datadog/Snowflake — mostly light background, dark navy text, deep blue/indigo accent, minimal animation. Dense information hierarchy. Feels like a product procurement buyers and CTOs evaluate, not just a developer side project.

**Color palette:**
- Background: `#ffffff` / `#f8f9fb` (alternating sections)
- Primary text: `#0f172a` (slate-900)
- Accent: `#3b4ef8` (indigo-600)
- Borders: `#e2e8f0`
- CTA buttons: solid indigo, white text

### 2.2 Navigation

- Left: VantageAI logo
- Center links: Features · Pricing · Resources (dropdown: Docs, Calculator)
- Right: Sign In · **Request Access** (indigo button)
- Add "Security" link pointing to `#security` anchor on the page

### 2.3 Hero Section

**Replace** dark gradient hero with white background + subtle grid pattern.

**Headline:** "AI Spend Intelligence for Engineering Teams"
**Sub-headline:** "Real-time cost visibility across every AI coding tool — per developer, per model, per team. Built for engineering leaders who need answers before the bill arrives."

**CTAs:**
- Primary: **Request Access** → `/signup.html`
- Secondary: **View Live Demo** → triggers demo session (Phase 3)

Remove: "The first AI coding tool FinOps platform" badge — unverifiable claim.

### 2.4 Trust Bar

Replace fake social proof with:
- Label: "Works with"
- Logos/text pills: Claude Code · OpenAI Codex CLI · Gemini CLI · Cursor · Cline · GitHub Copilot

No person names, no company names.

### 2.5 Features Section

Three-column grid. Lead with enterprise priorities:
1. **Cost Control** — budget policies, per-team alerts, spend trending
2. **Developer Accountability** — per-developer breakdown, model usage, efficiency scoring
3. **Audit & Compliance** — full audit log, SHA-256 key hashing, HTTP-only sessions, TLS

Only describe features that are shipped. Remove:
- AI model auto-router (not built)
- SSO/SAML (not built)
- Self-hosted option (not built)

### 2.6 Comparison Table

Two columns only: "Category Leaders" vs "VantageAI".
Footnote as specified in §1.3.

### 2.7 Pricing Section

Three tiers. No payment gateway — all paid tiers use mailto CTA.

| Tier | What's included | CTA |
|------|----------------|-----|
| **Free** | Up to 10k events/month · All core analytics · 1 org | Sign Up free → `/signup.html` |
| **Team** | Unlimited events · Budget policies · MCP tools · Cross-platform OTel | Contact us → `mailto:vantageaiops@gmail.com?subject=Team Plan` |
| **Enterprise** | Volume pricing · Dedicated support · SLA discussion | Talk to sales → `mailto:vantageaiops@gmail.com?subject=Enterprise` |

Remove: seat counts, specific feature lists that aren't shipped, SOC2/HIPAA badges.

### 2.8 Security Section (new anchor `#security`)

Replaces the compliance badge grid. Lists actual implemented controls:
- API keys hashed with SHA-256 — raw key shown once, never stored
- HTTP-only, SameSite sessions — XSS-resistant
- Full audit log — every admin action recorded with timestamp and IP
- TLS everywhere — Cloudflare edge, no plaintext
- Rate limiting — per-org, per-minute via Cloudflare KV
- Privacy-first local proxy — prompts never leave your machine (opt-in)

No SOC2/HIPAA/GDPR badges until certified.

### 2.9 Footer

Three columns:
- **Product:** Features · Pricing · Calculator
- **Resources:** Docs · Changelog · Security
- **Legal:** Terms of Service · Privacy Policy

---

## Phase 3 — Live Demo Sandbox

### 3.1 Setup (One-Time Manual)

1. Create demo org manually in D1: `org_id = "demo"`, email = `demo@vantageaiops.com`
2. Seed fixed constant data via `vantage-final-v4/seed-data.js` (extend existing script):
   - 3 teams: `backend`, `ml-platform`, `product`
   - 4 models: `claude-sonnet-4-6`, `gpt-4o`, `gemini-2.0-flash`, `claude-haiku-4-5`
   - ~100 events across 30 days — fixed, not random
   - 1 budget alert triggered (backend team at 85%)
   - ~20 duplicate calls for semantic cache KPIs
3. Generate one permanent `viewer`-role member API key for the demo org
4. Hardcode that key in the "View Live Demo" button handler

### 3.2 Button Behavior

"View Live Demo" button in hero:
1. `POST /v1/auth/session` with hardcoded demo viewer key
2. On success: redirect to `/app.html`
3. On failure: show inline error "Demo temporarily unavailable — [Sign up free instead]"

### 3.3 App Banner

When `app.html` loads with the demo org session, show a non-dismissable slim banner at top:
> "You're viewing a live demo — read only. [Create your free account →]"

Write actions (invite member, set budget, rotate key) show: "Sign up to use this feature" tooltip/modal instead of erroring.

### 3.4 Maintenance

Re-seed manually if data needs refreshing. No automation needed — data is constant.

---

## Phase 4 — Security Audit

### 4.1 Audit Areas

| Area | What to check |
|------|--------------|
| HTTP headers (`_headers`) | HSTS missing, CSP gaps (unsafe-inline, missing directives), Permissions-Policy completeness |
| Auth surface | Brute-force protection on `/v1/auth/session`, session fixation risk, key rotation gaps |
| API hardening | CORS origin list completeness, error message leakage (stack traces), batch payload size enforcement |
| Input validation | Event field size limits, `prompt_hash` format validation, org_id injection via URL params |
| Frontend | localStorage usage for API keys (flagged in privacy.html as existing behavior — assess risk), open redirects, XSS vectors in Chart.js data rendering |
| Secrets | Verify wrangler.toml not committed, no keys in HTML/JS |
| Public docs | Already addressed in Phase 1 (redact fuzzy match + MD5) |

### 4.2 Output

- Fixes applied directly to affected files
- Internal report written to `docs/security-audit-2026-04-09.md`:
  - Finding ID, area, severity (Critical/High/Medium/Low), description, fix applied or deferred with reason

### 4.3 Out of Scope

- Penetration testing
- Third-party scanning tools
- Cloudflare WAF / firewall rules (requires dashboard access)
- Dependency vulnerability scanning (separate CI step)

---

## Files Changed Summary

| File | Phase | Change type |
|------|-------|-------------|
| `vantage-final-v4/index.html` | 1, 2 | Content + redesign |
| `vantage-final-v4/docs.html` | 1 | Content cleanup + redactions |
| `vantage-final-v4/app.html` | 1, 3 | Nav link + demo banner |
| `vantage-final-v4/_headers` | 4 | Security header fixes |
| `vantage-final-v4/seed-data.js` | 3 | Demo seed data |
| `vantage-worker/src/routes/*.ts` | 4 | Auth + API hardening |
| `docs/security-audit-2026-04-09.md` | 4 | Internal audit report (new) |

---

## Constraints

- No payment gateway — all paid tier CTAs use `mailto:vantageaiops@gmail.com`
- No false claims — only describe shipped features
- No fake reviews — no person names or company names until real testimonials
- No competitor names on landing page — use category labels only
- No SOC2/HIPAA/GDPR badges until certified
