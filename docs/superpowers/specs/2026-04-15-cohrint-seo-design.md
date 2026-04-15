# Cohrint SEO & Domain Redirect — Design Spec
**Date:** 2026-04-15  
**Status:** Approved

---

## Goal
Make cohrint.com discoverable on Google, Bing, DuckDuckGo, Safari, and other search engines when someone searches "cohrint" or related AI coding cost keywords. Redirect all vantageaiops.com traffic to cohrint.com permanently.

---

## 1. vantageaiops.com Redirect

**Approach:** New Cloudflare Pages project (`vantageaiops-redirect`) — no Worker needed.  
**Implementation:** Single `_redirects` file:
```
/* https://cohrint.com/:splat 301
```
Deploy and connect the `vantageaiops.com` custom domain to this Pages project.

---

## 2. Technical SEO Fixes (existing pages)

### Pages with missing/incomplete SEO
| Page | Issues |
|------|--------|
| `roadmap.html` | No canonical, no OG tags, no Twitter card, no JSON-LD, not in sitemap |
| `auth.html` | No `noindex` directive, no canonical |
| `superadmin.html` | No `noindex` directive |
| `docs.html` | Verify OG/Twitter completeness |
| `report.html` | Verify OG/Twitter completeness |

### Fixes
- Add canonical, OG, Twitter card, JSON-LD `WebPage` schema to `roadmap.html`
- Add `<meta name="robots" content="noindex, nofollow">` to `auth.html` and `superadmin.html`
- Ensure all public pages have consistent OG + Twitter + JSON-LD markup

---

## 3. Clean URLs (strip .html)

Cloudflare Pages auto-serves `/foo` from `foo.html`. To avoid duplicate content:
- Add reverse 301 redirects in `_redirects`: `/docs.html` → `/docs`, etc.
- Update all `<link rel="canonical">` to use clean URLs (no `.html`)
- Update `sitemap.xml` to use clean URLs
- Affects: `docs`, `calculator`, `roadmap`, `privacy`, `terms`, `report`, `trust`
- Do NOT clean `auth.html`, `app.html`, `superadmin.html` (no-index pages)

---

## 4. New Keyword Landing Pages

Four new static HTML pages, each with full SEO markup (title, description, canonical, OG, Twitter, JSON-LD `WebPage` + `SoftwareApplication`), added to sitemap:

| URL | Target Keyword | Intent |
|-----|---------------|--------|
| `/claude-code-cost` | "Claude Code cost tracking" | Users of Claude Code wanting spend visibility |
| `/gemini-cli-cost` | "Gemini CLI cost tracking" | Users of Gemini CLI wanting spend visibility |
| `/copilot-cost` | "GitHub Copilot cost analytics" | Teams tracking Copilot seat + usage spend |
| `/ai-coding-cost` | "AI coding tool cost" / "AI FinOps" | Umbrella page, broader audience |

Each page: hero section, feature highlights relevant to that tool, CTA to sign up.

---

## 5. Blog / Changelog

- `/blog` — static index page listing posts
- Initial posts (static HTML files under `/blog/`):
  - `ai-coding-cost-benchmarks-2026.html` — anchors to the existing benchmark report
  - `how-to-track-claude-code-spend.html` — tutorial post targeting long-tail search
- Each post: full SEO markup, JSON-LD `BlogPosting` schema, added to sitemap

---

## 6. Search Engine Submission

### Verification files needed (user must get codes from each console)
| Engine | Method | Coverage |
|--------|--------|----------|
| Google Search Console | HTML file + meta tag | Google |
| Bing Webmaster Tools | HTML file or DNS TXT | Bing, DuckDuckGo, Yahoo, Edge, Safari Spotlight |
| Yandex Webmaster | HTML file or meta tag | Yandex |
| IndexNow | `indexnow.txt` key file | Instant ping to Bing + Yandex on publish |

### Implementation
- Create placeholder verification HTML files for each engine
- Add Google + Bing + Yandex `<meta name="verification">` tags to `index.html`
- Add `indexnow.txt` key file to build output
- Add sitemap URL to all three consoles after verification
- Document the manual steps (getting codes, submitting sitemap) in `ADMIN_GUIDE.md`

---

## 7. Sitemap Updates

Update `sitemap.xml`:
- Switch all URLs to clean format (no `.html`)
- Add `roadmap`, `blog`, and 4 new landing pages
- Update `lastmod` to 2026-04-15
- Add `blog/*` posts

---

## Files to Create/Modify

### New files (in `vantage-final-v4/`)
- `claude-code-cost.html`
- `gemini-cli-cost.html`
- `copilot-cost.html`
- `ai-coding-cost.html`
- `blog.html`
- `blog/ai-coding-cost-benchmarks-2026.html`
- `blog/how-to-track-claude-code-spend.html`
- `google<hash>.html` (placeholder)
- `BingSiteAuth.xml` (placeholder)
- `yandex_<hash>.html` (placeholder)
- `indexnow.txt` (placeholder key)

### New files (Cloudflare Pages redirect project)
- `vantageaiops-redirect/_redirects`

### Modified files
- `vantage-final-v4/_redirects` — add `.html` → clean URL redirects
- `vantage-final-v4/sitemap.xml` — update URLs, add new pages
- `vantage-final-v4/roadmap.html` — add full SEO markup
- `vantage-final-v4/auth.html` — add noindex
- `vantage-final-v4/superadmin.html` — add noindex
- `vantage-final-v4/index.html` — add verification meta tags
- All pages with `.html` canonicals → update to clean URLs
- `ADMIN_GUIDE.md` — document GSC/Bing/Yandex setup steps

---

## Out of Scope
- Dynamic OG image generation per page (future)
- CMS for blog (future — static HTML only for now)
- Paid search / ads
- Multi-locale / hreflang
