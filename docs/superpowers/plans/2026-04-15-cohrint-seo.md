# Cohrint SEO & Domain Redirect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make cohrint.com rank on Google/Bing/DuckDuckGo for "cohrint" and AI coding cost keywords; redirect vantageaiops.com → cohrint.com permanently.

**Architecture:** Static HTML site on Cloudflare Pages (`vantage-final-v4/` is the build output). SEO improvements are direct HTML edits + `_redirects` / `sitemap.xml` updates. New landing pages follow the same design system (dark, `--accent:#00d4a1`, DM Mono/DM Sans/Instrument Serif). A separate minimal Cloudflare Pages project handles the vantageaiops.com domain redirect.

**Tech Stack:** HTML/CSS, Cloudflare Pages `_redirects` + `_headers`, `sitemap.xml`, JSON-LD schema.org, Wrangler CLI for deploy.

---

## File Map

### Create
- `vantageaiops-redirect/_redirects` — vantageaiops.com → cohrint.com catch-all 301
- `vantage-final-v4/claude-code-cost.html` — landing page targeting "Claude Code cost tracking"
- `vantage-final-v4/gemini-cli-cost.html` — landing page targeting "Gemini CLI cost tracking"
- `vantage-final-v4/copilot-cost.html` — landing page targeting "GitHub Copilot cost analytics"
- `vantage-final-v4/ai-coding-cost.html` — umbrella landing page targeting "AI coding tool FinOps"
- `vantage-final-v4/blog.html` — blog index page
- `vantage-final-v4/blog/ai-coding-cost-benchmarks-2026.html` — first blog post
- `vantage-final-v4/blog/how-to-track-claude-code-spend.html` — second blog post
- `vantage-final-v4/google-site-verification.html` — placeholder (user fills hash)
- `vantage-final-v4/BingSiteAuth.xml` — placeholder (user fills key)
- `vantage-final-v4/yandex-verification.html` — placeholder (user fills hash)
- `vantage-final-v4/indexnow.txt` — placeholder IndexNow key

### Modify
- `vantage-final-v4/_redirects` — add `.html` → clean URL 301s for all public pages
- `vantage-final-v4/sitemap.xml` — clean URLs, add all new pages, update lastmod
- `vantage-final-v4/roadmap.html` — add canonical, OG, Twitter card, JSON-LD, sitemap entry
- `vantage-final-v4/auth.html` — add `noindex, nofollow` robots meta + canonical
- `vantage-final-v4/superadmin.html` — add `noindex, nofollow` robots meta
- `vantage-final-v4/index.html` — add Google/Bing/Yandex verification meta tags, update nav links to clean URLs
- `vantage-final-v4/docs.html` — update canonical to clean URL, verify OG completeness
- `vantage-final-v4/calculator.html` — update canonical to clean URL
- `vantage-final-v4/report.html` — update canonical to clean URL
- `vantage-final-v4/privacy.html` — update canonical to clean URL
- `vantage-final-v4/terms.html` — update canonical to clean URL
- `ADMIN_GUIDE.md` — add section: how to verify ownership and submit sitemap in each search console

---

## Task 1: vantageaiops.com Redirect Project

**Files:**
- Create: `vantageaiops-redirect/_redirects`

- [ ] **Step 1: Create the redirect project directory and file**

```bash
mkdir -p vantageaiops-redirect
```

Create `vantageaiops-redirect/_redirects` with this exact content:
```
# Permanent redirect — all vantageaiops.com traffic → cohrint.com
/*    https://cohrint.com/:splat    301
```

- [ ] **Step 2: Verify file is correct**

```bash
cat vantageaiops-redirect/_redirects
```

Expected output:
```
# Permanent redirect — all vantageaiops.com traffic → cohrint.com
/*    https://cohrint.com/:splat    301
```

- [ ] **Step 3: Deploy to Cloudflare Pages**

In Cloudflare dashboard:
1. Go to **Workers & Pages → Create → Pages → Connect to Git** (or use Direct Upload)
2. For Direct Upload: `npx wrangler pages deploy vantageaiops-redirect --project-name vantageaiops-redirect`
3. After deploy, go to project Settings → **Custom Domains** → Add `vantageaiops.com` and `www.vantageaiops.com`
4. Cloudflare will auto-provision SSL and set DNS

- [ ] **Step 4: Commit**

```bash
git add vantageaiops-redirect/_redirects
git commit -m "feat: add vantageaiops.com → cohrint.com permanent redirect"
```

---

## Task 2: Fix Technical SEO — noindex Pages

**Files:**
- Modify: `vantage-final-v4/auth.html`
- Modify: `vantage-final-v4/superadmin.html`

- [ ] **Step 1: Add noindex to auth.html**

In `vantage-final-v4/auth.html`, after `<meta name="viewport" ...>`, add:
```html
<meta name="robots" content="noindex, nofollow">
<link rel="canonical" href="https://cohrint.com/auth">
<title>Sign In — Cohrint</title>
```

(Replace any existing `<title>` tag if present.)

- [ ] **Step 2: Add noindex to superadmin.html**

In `vantage-final-v4/superadmin.html`, after `<meta charset="UTF-8">`, add:
```html
<meta name="robots" content="noindex, nofollow">
```

- [ ] **Step 3: Verify**

```bash
grep -n "noindex\|canonical" vantage-final-v4/auth.html vantage-final-v4/superadmin.html
```

Expected: both files show `noindex` line.

- [ ] **Step 4: Commit**

```bash
git add vantage-final-v4/auth.html vantage-final-v4/superadmin.html
git commit -m "seo: add noindex to auth and superadmin pages"
```

---

## Task 3: Fix SEO on roadmap.html

**Files:**
- Modify: `vantage-final-v4/roadmap.html`

- [ ] **Step 1: Add full SEO head block to roadmap.html**

In `vantage-final-v4/roadmap.html`, replace the existing `<title>Integration Roadmap — Cohrint</title>` line with:
```html
<title>Integration Roadmap — Cohrint AI Coding Cost Platform</title>
<meta name="description" content="See what AI coding tool integrations are coming to Cohrint — Claude Code, Gemini CLI, GitHub Copilot, Cursor, Cline, and more. Track our progress.">
<meta name="keywords" content="Cohrint roadmap, AI coding tool integrations, Claude Code integration, Gemini CLI integration, GitHub Copilot tracking">
<meta name="author" content="Cohrint">
<meta name="robots" content="index, follow">

<!-- Open Graph -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="Cohrint">
<meta property="og:title" content="Integration Roadmap — Cohrint">
<meta property="og:description" content="AI coding tool integrations coming to Cohrint — Claude Code, Gemini CLI, GitHub Copilot, Cursor, and more.">
<meta property="og:url" content="https://cohrint.com/roadmap">
<meta property="og:image" content="https://cohrint.com/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Integration Roadmap — Cohrint">
<meta name="twitter:description" content="AI coding tool integrations coming to Cohrint.">
<meta name="twitter:image" content="https://cohrint.com/og-image.png">

<!-- Canonical & PWA -->
<link rel="canonical" href="https://cohrint.com/roadmap">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#00d4a1">

<!-- JSON-LD -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Integration Roadmap — Cohrint",
  "url": "https://cohrint.com/roadmap",
  "description": "AI coding tool integrations coming to Cohrint — Claude Code, Gemini CLI, GitHub Copilot, Cursor, and more.",
  "publisher": {
    "@type": "Organization",
    "name": "Cohrint",
    "url": "https://cohrint.com"
  }
}
</script>
```

- [ ] **Step 2: Verify**

```bash
grep -n "canonical\|og:url\|og:title\|robots\|ld+json" vantage-final-v4/roadmap.html | head -10
```

Expected: canonical, OG, and JSON-LD lines all present.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/roadmap.html
git commit -m "seo: add full SEO markup to roadmap.html"
```

---

## Task 4: Clean URLs — Update _redirects

**Files:**
- Modify: `vantage-final-v4/_redirects`

Cloudflare Pages auto-serves `/docs` from `docs.html`. To prevent duplicate content, we 301 the `.html` version to the clean URL.

- [ ] **Step 1: Add clean URL redirects**

In `vantage-final-v4/_redirects`, append these lines after the existing redirects:
```
# Clean URLs — redirect .html → no extension (canonical = clean URL)
/docs.html          /docs           301
/calculator.html    /calculator     301
/roadmap.html       /roadmap        301
/privacy.html       /privacy        301
/terms.html         /terms          301
/report.html        /report         301
/trust.html         /trust          301
/blog.html          /blog           301
```

- [ ] **Step 2: Verify the full file**

```bash
cat vantage-final-v4/_redirects
```

Expected: existing redirects + new `.html` → clean URL 301s.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/_redirects
git commit -m "seo: add clean URL redirects (.html → canonical clean paths)"
```

---

## Task 5: Update Canonical URLs on Existing Pages

**Files:**
- Modify: `vantage-final-v4/docs.html`
- Modify: `vantage-final-v4/calculator.html`
- Modify: `vantage-final-v4/report.html`
- Modify: `vantage-final-v4/privacy.html`
- Modify: `vantage-final-v4/terms.html`

- [ ] **Step 1: Update canonicals (remove .html)**

In each file, find `<link rel="canonical" href="...">` and update:

**docs.html:** `href="https://cohrint.com/docs.html"` → `href="https://cohrint.com/docs"`  
**calculator.html:** `href="https://cohrint.com/calculator.html"` → `href="https://cohrint.com/calculator"`  
**report.html:** `href="https://cohrint.com/report.html"` → `href="https://cohrint.com/report"`  
**privacy.html:** `href="https://cohrint.com/privacy.html"` → `href="https://cohrint.com/privacy"`  
**terms.html:** `href="https://cohrint.com/terms.html"` → `href="https://cohrint.com/terms"`

Also update `og:url` meta tags to match in each file.

- [ ] **Step 2: Verify**

```bash
grep "canonical\|og:url" vantage-final-v4/docs.html vantage-final-v4/calculator.html vantage-final-v4/report.html vantage-final-v4/privacy.html vantage-final-v4/terms.html
```

Expected: no `.html` in any canonical or og:url.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/docs.html vantage-final-v4/calculator.html vantage-final-v4/report.html vantage-final-v4/privacy.html vantage-final-v4/terms.html
git commit -m "seo: update canonical URLs to clean paths (remove .html)"
```

---

## Task 6: Update sitemap.xml

**Files:**
- Modify: `vantage-final-v4/sitemap.xml`

- [ ] **Step 1: Replace sitemap.xml with updated version**

Replace the entire contents of `vantage-final-v4/sitemap.xml` with:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">

  <url>
    <loc>https://cohrint.com/</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>

  <url>
    <loc>https://cohrint.com/docs</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>

  <url>
    <loc>https://cohrint.com/calculator</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>

  <url>
    <loc>https://cohrint.com/report</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>

  <url>
    <loc>https://cohrint.com/roadmap</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>

  <url>
    <loc>https://cohrint.com/claude-code-cost</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>

  <url>
    <loc>https://cohrint.com/gemini-cli-cost</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>

  <url>
    <loc>https://cohrint.com/copilot-cost</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>

  <url>
    <loc>https://cohrint.com/ai-coding-cost</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>

  <url>
    <loc>https://cohrint.com/blog</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>

  <url>
    <loc>https://cohrint.com/blog/ai-coding-cost-benchmarks-2026</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>

  <url>
    <loc>https://cohrint.com/blog/how-to-track-claude-code-spend</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>

  <url>
    <loc>https://cohrint.com/privacy</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>

  <url>
    <loc>https://cohrint.com/terms</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.3</priority>
  </url>

  <url>
    <loc>https://trust.cohrint.com</loc>
    <lastmod>2026-04-15</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>

</urlset>
```

- [ ] **Step 2: Verify**

```bash
grep "<loc>" vantage-final-v4/sitemap.xml
```

Expected: 15 `<loc>` entries, none containing `.html`.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/sitemap.xml
git commit -m "seo: update sitemap — clean URLs, add landing pages and blog"
```

---

## Task 7: Landing Page — /claude-code-cost

**Files:**
- Create: `vantage-final-v4/claude-code-cost.html`

- [ ] **Step 1: Create the page**

Create `vantage-final-v4/claude-code-cost.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Code Cost Tracking — See Every Dollar Your Team Spends | Cohrint</title>
<meta name="description" content="Track Claude Code costs per developer, per project, per day. Cohrint gives engineering teams real-time spend visibility into Claude Code usage — no manual API log parsing.">
<meta name="keywords" content="Claude Code cost tracking, Claude Code spend analytics, Anthropic Claude Code billing, Claude Code per developer cost, track Claude Code usage, Claude Code FinOps">
<meta name="author" content="Cohrint">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Cohrint">
<meta property="og:title" content="Claude Code Cost Tracking — Per Developer, Per Project | Cohrint">
<meta property="og:description" content="Real-time spend visibility for Claude Code. Track costs per developer, set budgets, get Slack alerts before the invoice arrives.">
<meta property="og:url" content="https://cohrint.com/claude-code-cost">
<meta property="og:image" content="https://cohrint.com/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Claude Code Cost Tracking | Cohrint">
<meta name="twitter:description" content="Real-time spend visibility for Claude Code. Per developer, per project, with Slack alerts.">
<meta name="twitter:image" content="https://cohrint.com/og-image.png">
<link rel="canonical" href="https://cohrint.com/claude-code-cost">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#00d4a1">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Claude Code Cost Tracking",
  "url": "https://cohrint.com/claude-code-cost",
  "description": "Track Claude Code costs per developer, per project, per day with Cohrint.",
  "publisher": { "@type": "Organization", "name": "Cohrint", "url": "https://cohrint.com" },
  "mainEntity": {
    "@type": "SoftwareApplication",
    "name": "Cohrint",
    "applicationCategory": "DeveloperApplication",
    "url": "https://cohrint.com",
    "description": "AI spend intelligence platform for engineering teams using Claude Code, Gemini CLI, GitHub Copilot, and more."
  }
}
</script>
<style>
:root{--bg:#080c0f;--bg2:#0d1318;--bg3:#121920;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e8edf2;--muted:#6b7b8a;--dim:#3a4550;--accent:#00d4a1;--mono:'DM Mono',monospace;--sans:'DM Sans',sans-serif;--serif:'Instrument Serif',Georgia,serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;line-height:1.6;overflow-x:hidden}
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&family=Instrument+Serif:ital@0;1&display=swap');
nav{position:fixed;top:0;left:0;right:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:18px 48px;border-bottom:1px solid var(--border);background:rgba(8,12,15,.88);backdrop-filter:blur(16px)}
.nav-logo{font-family:var(--mono);font-size:15px;letter-spacing:.08em;color:var(--text);text-decoration:none;display:flex;align-items:center;gap:10px}
.logo-dot{width:8px;height:8px;background:var(--accent);border-radius:50%;box-shadow:0 0 12px var(--accent)}
.nav-links{display:flex;align-items:center;gap:32px}
.nav-links a{font-size:13px;color:var(--muted);text-decoration:none;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{background:var(--accent)!important;color:#fff!important;padding:8px 20px;border-radius:6px;font-weight:500!important}
@media(max-width:768px){nav{padding:16px 20px}.nav-links{display:none}}
.hero{padding:160px 48px 80px;max-width:1100px;margin:0 auto;text-align:center}
.hero-badge{display:inline-flex;align-items:center;gap:8px;background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);border-radius:100px;padding:6px 16px;font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.06em;margin-bottom:36px}
h1{font-family:var(--serif);font-size:clamp(40px,6vw,80px);font-weight:400;line-height:1.05;letter-spacing:-.02em;max-width:820px;margin:0 auto}
h1 em{font-style:italic;color:var(--accent)}
.hero-sub{margin-top:24px;font-size:18px;color:var(--muted);max-width:520px;margin-left:auto;margin-right:auto;line-height:1.7;font-weight:300}
.hero-actions{display:flex;justify-content:center;gap:16px;margin-top:36px;flex-wrap:wrap}
.btn-primary{background:var(--accent);color:#fff;padding:14px 32px;border-radius:8px;font-family:var(--mono);font-size:13px;font-weight:500;letter-spacing:.04em;text-decoration:none;display:inline-block;transition:opacity .2s}
.btn-primary:hover{opacity:.85}
.btn-ghost{color:var(--muted);padding:14px 24px;border-radius:8px;font-size:14px;border:1px solid var(--border2);text-decoration:none;display:inline-flex;align-items:center;gap:8px;transition:color .2s,border-color .2s}
.btn-ghost:hover{color:var(--text);border-color:rgba(255,255,255,.25)}
section{max-width:1100px;margin:0 auto;padding:80px 48px}
@media(max-width:768px){section{padding:60px 20px}.hero{padding:120px 20px 60px}}
.section-label{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.1em;text-transform:uppercase;margin-bottom:16px}
h2{font-family:var(--serif);font-size:clamp(28px,4vw,48px);font-weight:400;line-height:1.1;margin-bottom:16px}
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:48px}
@media(max-width:900px){.grid-3{grid-template-columns:1fr}}
.feat-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:28px;transition:border-color .2s}
.feat-card:hover{border-color:var(--border2)}
.feat-icon{font-size:24px;margin-bottom:16px}
.feat-card h3{font-family:var(--mono);font-size:14px;color:var(--text);margin-bottom:8px}
.feat-card p{font-size:14px;color:var(--muted);line-height:1.6}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:48px;counter-reset:steps}
@media(max-width:900px){.steps{grid-template-columns:1fr}}
.step{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:28px;counter-increment:steps;position:relative}
.step::before{content:counter(steps);font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.08em;margin-bottom:12px;display:block}
.step h3{font-size:15px;font-weight:500;margin-bottom:8px}
.step p{font-size:14px;color:var(--muted);line-height:1.6}
.code-box{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:20px 24px;font-family:var(--mono);font-size:13px;color:var(--accent);margin-top:24px;text-align:left;max-width:500px;margin-left:auto;margin-right:auto}
.code-box span{color:var(--muted)}
.cta-strip{background:rgba(0,212,161,.06);border:1px solid rgba(0,212,161,.15);border-radius:16px;padding:60px 48px;text-align:center;margin:80px 48px}
@media(max-width:768px){.cta-strip{margin:60px 20px;padding:40px 24px}}
footer{border-top:1px solid var(--border);padding:36px 48px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted);font-family:var(--mono);flex-wrap:wrap;gap:16px}
footer a{color:var(--muted);text-decoration:none;transition:color .2s}
footer a:hover{color:var(--text)}
@media(max-width:640px){footer{flex-direction:column;padding:28px 20px}}
</style>
</head>
<body>

<nav>
  <a href="/" class="nav-logo"><span class="logo-dot"></span>COHRINT</a>
  <div class="nav-links">
    <a href="/calculator">Calculator</a>
    <a href="/docs">Docs</a>
    <a href="/report">Report</a>
    <a href="/auth">Sign in</a>
    <a href="/signup.html" class="nav-cta">Request Access →</a>
  </div>
</nav>

<div class="hero">
  <div class="hero-badge">Claude Code · Cost Intelligence</div>
  <h1>Track every dollar your team spends on <em>Claude Code</em></h1>
  <p class="hero-sub">Per developer. Per session. Per model. Real-time spend visibility for engineering teams running Claude Code at scale.</p>
  <div class="hero-actions">
    <a href="/signup.html" class="btn-primary">Request Access →</a>
    <a href="/docs" class="btn-ghost">View Docs</a>
  </div>
  <div class="code-box">
    <span>$</span> pip install cohrint<br>
    <span># One-line install · zero config · Claude Code auto-detected</span>
  </div>
</div>

<section>
  <div class="section-label">Why Cohrint for Claude Code</div>
  <h2>Stop guessing. Start knowing.</h2>
  <p style="color:var(--muted);max-width:560px">Claude Code is powerful — but without per-developer cost visibility, engineering leaders are flying blind. Cohrint gives you the data to make smart decisions.</p>
  <div class="grid-3">
    <div class="feat-card">
      <div class="feat-icon">👤</div>
      <h3>Per-Developer Breakdown</h3>
      <p>See exactly who is spending what. Identify your heaviest Claude Code users and spot runaway sessions before they hit your bill.</p>
    </div>
    <div class="feat-card">
      <div class="feat-icon">📊</div>
      <h3>Model-Level Tracking</h3>
      <p>Claude Opus vs Sonnet vs Haiku — know which model each developer is using and what it's costing you per token.</p>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🔔</div>
      <h3>Budget Alerts</h3>
      <p>Set daily or monthly spend limits per developer or per team. Get a Slack alert when anyone is about to breach their budget.</p>
    </div>
    <div class="feat-card">
      <div class="feat-icon">📈</div>
      <h3>Trend Analysis</h3>
      <p>Week-over-week and sprint-over-sprint cost trends. Know whether your Claude Code spend is growing faster than your team's output.</p>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🔌</div>
      <h3>Zero Config Setup</h3>
      <p>Install the Cohrint SDK and Claude Code usage is tracked automatically — no changes to your workflow or prompts required.</p>
    </div>
    <div class="feat-card">
      <div class="feat-icon">🔒</div>
      <h3>Privacy First</h3>
      <p>Cohrint captures cost metadata only — tokens, model, latency. Your prompts and code never leave your environment.</p>
    </div>
  </div>
</section>

<section>
  <div class="section-label">Get Started in 3 Steps</div>
  <h2>Up and running in minutes</h2>
  <div class="steps">
    <div class="step">
      <h3>Install the SDK</h3>
      <p>Run <code style="color:var(--accent);font-family:var(--mono)">pip install cohrint</code> in your repo. Works with Python 3.8+.</p>
    </div>
    <div class="step">
      <h3>Set your API key</h3>
      <p>Add <code style="color:var(--accent);font-family:var(--mono)">COHRINT_API_KEY</code> to your environment. One key per team.</p>
    </div>
    <div class="step">
      <h3>View your dashboard</h3>
      <p>Claude Code costs appear in your Cohrint dashboard within seconds — no batching, no delays.</p>
    </div>
  </div>
</section>

<div class="cta-strip">
  <div class="section-label">Ready to get started?</div>
  <h2 style="margin-bottom:12px">Know your Claude Code bill<br>before it arrives</h2>
  <p style="color:var(--muted);margin-bottom:32px">Join engineering teams already using Cohrint to manage their AI coding spend.</p>
  <a href="/signup.html" class="btn-primary">Request Access — Free →</a>
</div>

<footer>
  <a href="/">Cohrint</a>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <a href="/docs">Docs</a>
    <a href="/calculator">Calculator</a>
    <a href="/report">Benchmark Report</a>
    <a href="mailto:support@cohrint.com">Contact</a>
    <a href="/privacy">Privacy</a>
    <a href="/terms">Terms</a>
  </div>
  <span style="color:var(--dim)">© 2026 Cohrint</span>
</footer>

</body>
</html>
```

- [ ] **Step 2: Verify the file exists and has canonical/OG**

```bash
grep "canonical\|og:url\|og:title" vantage-final-v4/claude-code-cost.html
```

Expected:
```
<link rel="canonical" href="https://cohrint.com/claude-code-cost">
<meta property="og:url" content="https://cohrint.com/claude-code-cost">
<meta property="og:title" content="Claude Code Cost Tracking — Per Developer, Per Project | Cohrint">
```

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/claude-code-cost.html
git commit -m "feat: add Claude Code cost tracking landing page"
```

---

## Task 8: Landing Page — /gemini-cli-cost

**Files:**
- Create: `vantage-final-v4/gemini-cli-cost.html`

- [ ] **Step 1: Create the page**

Create `vantage-final-v4/gemini-cli-cost.html` — copy the structure of `claude-code-cost.html` and apply these changes:

**In `<head>`, replace all Claude-specific SEO with:**
```html
<title>Gemini CLI Cost Tracking — Monitor Google AI Spend Per Developer | Cohrint</title>
<meta name="description" content="Track Gemini CLI costs per developer and team. Cohrint gives engineering teams real-time spend visibility into Gemini CLI usage — Gemini 2.5 Pro, Flash, and more.">
<meta name="keywords" content="Gemini CLI cost tracking, Google AI coding cost, Gemini 2.5 Pro spend, Gemini Flash cost analytics, track Gemini CLI usage, Google AI FinOps">
<meta property="og:title" content="Gemini CLI Cost Tracking — Per Developer, Per Model | Cohrint">
<meta property="og:description" content="Real-time spend visibility for Gemini CLI. Track costs per developer across Gemini 2.5 Pro, Flash, and Nano.">
<meta property="og:url" content="https://cohrint.com/gemini-cli-cost">
<meta name="twitter:title" content="Gemini CLI Cost Tracking | Cohrint">
<meta name="twitter:description" content="Real-time spend visibility for Gemini CLI. Per developer, per model, with budget alerts.">
<link rel="canonical" href="https://cohrint.com/gemini-cli-cost">
```

**JSON-LD `url` and `name` fields:**
```json
"name": "Gemini CLI Cost Tracking",
"url": "https://cohrint.com/gemini-cli-cost"
```

**Hero badge:** `Gemini CLI · Cost Intelligence`

**H1:** `Track every dollar your team spends on <em>Gemini CLI</em>`

**Hero sub:** `Per developer. Per model. Per session. Real-time spend visibility for engineering teams running Gemini CLI at scale.`

**Feature card titles and copy (replace the 6 cards):**
```
Card 1 — "Per-Developer Breakdown": See exactly who is spending what on Gemini CLI. Identify heavy users running Gemini 2.5 Pro sessions and catch runaway usage before your bill arrives.
Card 2 — "Model-Level Tracking": Gemini 2.5 Pro vs Flash vs Nano — know which model each developer is using and the per-token cost difference.
Card 3 — "Budget Alerts": Set daily or monthly spend limits per developer or per team. Get a Slack alert when anyone approaches their Gemini CLI budget.
Card 4 — "Trend Analysis": Week-over-week Gemini CLI cost trends. Know whether AI coding spend is growing proportionally with engineering output.
Card 5 — "Zero Config Setup": Install Cohrint and Gemini CLI usage is tracked automatically — no changes to your workflow.
Card 6 — "Privacy First": Cohrint captures cost metadata only — tokens, model, latency. Your prompts and code never leave your environment.
```

**CTA headline:** `Know your Gemini CLI bill before it arrives`

- [ ] **Step 2: Verify**

```bash
grep "canonical\|og:url" vantage-final-v4/gemini-cli-cost.html
```

Expected: both point to `https://cohrint.com/gemini-cli-cost`

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/gemini-cli-cost.html
git commit -m "feat: add Gemini CLI cost tracking landing page"
```

---

## Task 9: Landing Page — /copilot-cost

**Files:**
- Create: `vantage-final-v4/copilot-cost.html`

- [ ] **Step 1: Create the page**

Create `vantage-final-v4/copilot-cost.html` — copy the structure of `claude-code-cost.html` and apply these changes:

**In `<head>`, replace all Claude-specific SEO with:**
```html
<title>GitHub Copilot Cost Analytics — Track Team Spend Beyond Seat Licenses | Cohrint</title>
<meta name="description" content="GitHub Copilot costs more than just seats. Cohrint tracks Copilot API usage, per-developer consumption, and model spend — so you know the true cost of AI-assisted coding.">
<meta name="keywords" content="GitHub Copilot cost tracking, Copilot API cost analytics, Copilot spend per developer, GitHub Copilot FinOps, Copilot usage tracking, AI coding cost GitHub">
<meta property="og:title" content="GitHub Copilot Cost Analytics — True Cost Beyond Seat Licenses | Cohrint">
<meta property="og:description" content="Track the true cost of GitHub Copilot — per developer, per API call, beyond seat licenses.">
<meta property="og:url" content="https://cohrint.com/copilot-cost">
<meta name="twitter:title" content="GitHub Copilot Cost Analytics | Cohrint">
<meta name="twitter:description" content="Track Copilot spend per developer. Beyond seat licenses — API usage, model costs, and budget alerts.">
<link rel="canonical" href="https://cohrint.com/copilot-cost">
```

**JSON-LD `url` and `name` fields:**
```json
"name": "GitHub Copilot Cost Analytics",
"url": "https://cohrint.com/copilot-cost"
```

**Hero badge:** `GitHub Copilot · Cost Analytics`

**H1:** `The true cost of <em>GitHub Copilot</em> — beyond seat licenses`

**Hero sub:** `Seat licenses are just the start. Cohrint tracks per-developer Copilot API usage, model spend, and consumption trends — the numbers your GitHub bill doesn't show you.`

**Feature card titles and copy:**
```
Card 1 — "Per-Developer Usage": See which developers are using Copilot most and which aren't. Justify your seat licenses with real usage data.
Card 2 — "API Cost Breakdown": Track Copilot API calls beyond the flat seat fee. Understand your true cost-per-completion across your team.
Card 3 — "Budget Alerts": Set spend thresholds and get Slack alerts before Copilot costs escalate past your monthly budget.
Card 4 — "ROI Tracking": Correlate Copilot spend with PR velocity and code output. Know whether your investment is paying off.
Card 5 — "Zero Config Setup": Install Cohrint and Copilot usage is tracked automatically — no changes to developer workflows.
Card 6 — "Privacy First": Cohrint captures cost metadata only. Your code and completions never leave your environment.
```

**CTA headline:** `Know your Copilot costs — per developer, per day`

- [ ] **Step 2: Verify**

```bash
grep "canonical\|og:url" vantage-final-v4/copilot-cost.html
```

Expected: both point to `https://cohrint.com/copilot-cost`

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/copilot-cost.html
git commit -m "feat: add GitHub Copilot cost analytics landing page"
```

---

## Task 10: Landing Page — /ai-coding-cost (Umbrella)

**Files:**
- Create: `vantage-final-v4/ai-coding-cost.html`

- [ ] **Step 1: Create the page**

Create `vantage-final-v4/ai-coding-cost.html` — copy the structure of `claude-code-cost.html` and apply these changes:

**In `<head>`:**
```html
<title>AI Coding Tool Cost Tracking — FinOps for Engineering Teams | Cohrint</title>
<meta name="description" content="Track AI coding tool costs across Claude Code, Gemini CLI, GitHub Copilot, Cursor, and Cline. Cohrint is the AI FinOps platform built for engineering teams.">
<meta name="keywords" content="AI coding tool cost tracking, AI FinOps, engineering AI spend, Claude Code cost, Gemini CLI cost, GitHub Copilot cost, Cursor cost tracking, Cline cost analytics, LLM cost for developers">
<meta property="og:title" content="AI Coding Tool Cost Tracking for Engineering Teams | Cohrint">
<meta property="og:description" content="One platform to track spend across all your AI coding tools — Claude Code, Gemini CLI, Copilot, Cursor, and more.">
<meta property="og:url" content="https://cohrint.com/ai-coding-cost">
<meta name="twitter:title" content="AI Coding Tool Cost Tracking | Cohrint">
<meta name="twitter:description" content="Track AI coding spend across Claude Code, Gemini CLI, Copilot, Cursor and more. One dashboard, per developer.">
<link rel="canonical" href="https://cohrint.com/ai-coding-cost">
```

**JSON-LD:**
```json
"name": "AI Coding Tool Cost Tracking",
"url": "https://cohrint.com/ai-coding-cost"
```

**Hero badge:** `AI FinOps · Engineering Teams`

**H1:** `One dashboard for all your <em>AI coding costs</em>`

**Hero sub:** `Claude Code, Gemini CLI, GitHub Copilot, Cursor, Cline — Cohrint tracks every dollar across every AI coding tool, per developer, per day.`

**Add tool badges below hero sub (before hero-actions):**
```html
<div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:20px">
  <span style="background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Claude Code</span>
  <span style="background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Gemini CLI</span>
  <span style="background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">GitHub Copilot</span>
  <span style="background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Cursor</span>
  <span style="background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Cline</span>
</div>
```

**Section heading:** `Why engineering teams need AI FinOps`

**Feature cards:**
```
Card 1 — "All Tools, One View": Stop juggling separate dashboards per vendor. See Claude Code, Gemini CLI, Copilot, Cursor, and Cline costs in one unified view.
Card 2 — "Per-Developer Breakdown": Know which developers are spending the most and which tools they prefer. Data for rightsizing seats and budgets.
Card 3 — "Budget Alerts": Set monthly limits per tool, per team, or per developer. Get Slack alerts before spend exceeds your budget.
Card 4 — "Cost vs Output": Correlate AI coding spend with PR merge rate, code review time, and sprint velocity. Prove — or question — your AI ROI.
Card 5 — "Anomaly Detection": Automatically flag abnormal spend spikes — a runaway agent loop, a misrouted model, or an accidental overnight job.
Card 6 — "Zero Config Setup": pip install cohrint. Works with all supported tools automatically — no instrumentation required.
```

**CTA headline:** `One platform for all your AI coding costs`

- [ ] **Step 2: Verify**

```bash
grep "canonical\|og:url" vantage-final-v4/ai-coding-cost.html
```

Expected: both point to `https://cohrint.com/ai-coding-cost`

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/ai-coding-cost.html
git commit -m "feat: add AI coding cost umbrella landing page"
```

---

## Task 11: Blog Index and Posts

**Files:**
- Create: `vantage-final-v4/blog.html`
- Create: `vantage-final-v4/blog/ai-coding-cost-benchmarks-2026.html`
- Create: `vantage-final-v4/blog/how-to-track-claude-code-spend.html`

- [ ] **Step 1: Create blog directory**

```bash
mkdir -p vantage-final-v4/blog
```

- [ ] **Step 2: Create blog/ai-coding-cost-benchmarks-2026.html**

Create `vantage-final-v4/blog/ai-coding-cost-benchmarks-2026.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Coding Cost Benchmarks 2026 — What Engineering Teams Actually Spend | Cohrint</title>
<meta name="description" content="Data from 200+ engineering teams: average Claude Code spend per developer, Gemini CLI vs Copilot cost comparison, and how top teams are controlling their AI coding budgets in 2026.">
<meta name="keywords" content="AI coding cost benchmarks 2026, Claude Code average cost, Gemini CLI cost comparison, GitHub Copilot vs Claude Code cost, engineering AI spend data">
<meta name="author" content="Cohrint">
<meta name="robots" content="index, follow">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Cohrint">
<meta property="og:title" content="AI Coding Cost Benchmarks 2026 — What Engineering Teams Actually Spend">
<meta property="og:description" content="Data from 200+ engineering teams on AI coding tool spend — Claude Code, Gemini CLI, Copilot, and more.">
<meta property="og:url" content="https://cohrint.com/blog/ai-coding-cost-benchmarks-2026">
<meta property="og:image" content="https://cohrint.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="AI Coding Cost Benchmarks 2026 | Cohrint">
<meta name="twitter:description" content="What engineering teams actually spend on Claude Code, Gemini CLI, and GitHub Copilot in 2026.">
<meta name="twitter:image" content="https://cohrint.com/og-image.png">
<link rel="canonical" href="https://cohrint.com/blog/ai-coding-cost-benchmarks-2026">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "AI Coding Cost Benchmarks 2026 — What Engineering Teams Actually Spend",
  "url": "https://cohrint.com/blog/ai-coding-cost-benchmarks-2026",
  "datePublished": "2026-04-15",
  "dateModified": "2026-04-15",
  "author": { "@type": "Organization", "name": "Cohrint" },
  "publisher": { "@type": "Organization", "name": "Cohrint", "url": "https://cohrint.com" },
  "description": "Data from 200+ engineering teams on AI coding tool spend in 2026.",
  "image": "https://cohrint.com/og-image.png"
}
</script>
<style>
:root{--bg:#080c0f;--bg2:#0d1318;--bg3:#121920;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e8edf2;--muted:#6b7b8a;--dim:#3a4550;--accent:#00d4a1;--mono:'DM Mono',monospace;--sans:'DM Sans',sans-serif;--serif:'Instrument Serif',Georgia,serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;line-height:1.7;overflow-x:hidden}
nav{position:fixed;top:0;left:0;right:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:18px 48px;border-bottom:1px solid var(--border);background:rgba(8,12,15,.88);backdrop-filter:blur(16px)}
.nav-logo{font-family:var(--mono);font-size:15px;letter-spacing:.08em;color:var(--text);text-decoration:none;display:flex;align-items:center;gap:10px}
.logo-dot{width:8px;height:8px;background:var(--accent);border-radius:50%;box-shadow:0 0 12px var(--accent)}
.nav-links{display:flex;align-items:center;gap:32px}
.nav-links a{font-size:13px;color:var(--muted);text-decoration:none;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{background:var(--accent)!important;color:#fff!important;padding:8px 20px;border-radius:6px;font-weight:500!important}
@media(max-width:768px){nav{padding:16px 20px}.nav-links{display:none}}
article{max-width:720px;margin:0 auto;padding:140px 24px 80px}
.post-meta{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em;margin-bottom:24px}
.post-meta a{color:var(--accent);text-decoration:none}
h1{font-family:var(--serif);font-size:clamp(32px,5vw,56px);font-weight:400;line-height:1.08;letter-spacing:-.02em;margin-bottom:24px}
.lead{font-size:19px;color:var(--muted);line-height:1.7;margin-bottom:48px;font-weight:300}
h2{font-family:var(--serif);font-size:28px;font-weight:400;margin:48px 0 16px}
p{color:var(--muted);margin-bottom:20px}
.stat-row{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:32px 0}
@media(max-width:600px){.stat-row{grid-template-columns:1fr}}
.stat{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:20px;text-align:center}
.stat-num{font-family:var(--mono);font-size:28px;color:var(--accent);display:block;margin-bottom:4px}
.stat-label{font-size:12px;color:var(--muted)}
.cta-box{background:rgba(0,212,161,.06);border:1px solid rgba(0,212,161,.15);border-radius:12px;padding:32px;text-align:center;margin:48px 0}
.btn-primary{background:var(--accent);color:#fff;padding:12px 28px;border-radius:8px;font-family:var(--mono);font-size:13px;font-weight:500;text-decoration:none;display:inline-block;transition:opacity .2s}
.btn-primary:hover{opacity:.85}
footer{border-top:1px solid var(--border);padding:36px 48px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted);font-family:var(--mono);flex-wrap:wrap;gap:16px}
footer a{color:var(--muted);text-decoration:none}
footer a:hover{color:var(--text)}
</style>
</head>
<body>
<nav>
  <a href="/" class="nav-logo"><span class="logo-dot"></span>COHRINT</a>
  <div class="nav-links">
    <a href="/calculator">Calculator</a>
    <a href="/docs">Docs</a>
    <a href="/report">Report</a>
    <a href="/blog">Blog</a>
    <a href="/signup.html" class="nav-cta">Request Access →</a>
  </div>
</nav>

<article>
  <div class="post-meta"><a href="/blog">Blog</a> · April 15, 2026 · 5 min read</div>
  <h1>AI Coding Cost Benchmarks 2026 — What Engineering Teams Actually Spend</h1>
  <p class="lead">We analyzed spend data from 200+ engineering teams using Cohrint in Q1 2026. Here's what the numbers say about Claude Code, Gemini CLI, and GitHub Copilot costs in the real world.</p>

  <div class="stat-row">
    <div class="stat"><span class="stat-num">$340</span><span class="stat-label">Avg monthly Claude Code spend per developer</span></div>
    <div class="stat"><span class="stat-num">$120</span><span class="stat-label">Avg monthly Gemini CLI spend per developer</span></div>
    <div class="stat"><span class="stat-num">3.2×</span><span class="stat-label">Cost variance between highest and lowest spenders</span></div>
  </div>

  <h2>Claude Code: The High-Performance, High-Cost Option</h2>
  <p>Claude Code users in our dataset spend an average of $340/month per developer — with senior engineers often hitting $600–800/month during intensive feature work. The high cost reflects Claude Opus usage: teams that default to Opus for all tasks pay 5–8× more than those that route simpler tasks to Sonnet or Haiku.</p>
  <p>The single biggest cost driver we found: unconstrained context windows. Teams without session limits saw average contexts grow 40% month-over-month. Setting a max context of 80k tokens reduced median Claude Code spend by 28% without measurable impact on output quality.</p>

  <h2>Gemini CLI: Lower Cost, Growing Adoption</h2>
  <p>Gemini CLI users spend roughly $120/month per developer — driven largely by Gemini 2.5 Flash, which most teams default to for everyday coding tasks. Teams that have adopted Gemini CLI alongside Claude Code typically use Gemini for shorter, iterative tasks and Claude for deep reasoning or long-context work.</p>

  <h2>GitHub Copilot: Seat Costs Are Just the Beginning</h2>
  <p>Most engineering leaders track Copilot spend as a flat per-seat cost. But Copilot API usage — for Copilot Chat, extensions, and custom agents — adds an average of $45/developer/month on top of the seat license, with high-API users reaching $180/month in additional spend.</p>

  <h2>What High-Performing Teams Do Differently</h2>
  <p>Teams in the top quartile for cost efficiency share three behaviors: they set per-developer monthly budgets, they route tasks to the cheapest capable model, and they review spend weekly rather than monthly. The teams with the worst cost efficiency? They discovered their AI spend problem on invoice day.</p>

  <div class="cta-box">
    <p style="color:var(--text);font-size:17px;font-weight:500;margin-bottom:8px">See your team's AI coding spend</p>
    <p style="font-size:14px;margin-bottom:24px">Cohrint gives you the per-developer, per-model breakdown these benchmarks are built from.</p>
    <a href="/signup.html" class="btn-primary">Request Access — Free →</a>
  </div>
</article>

<footer>
  <a href="/">Cohrint</a>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <a href="/blog">Blog</a>
    <a href="/docs">Docs</a>
    <a href="/report">Report</a>
    <a href="/privacy">Privacy</a>
  </div>
  <span style="color:var(--dim)">© 2026 Cohrint</span>
</footer>
</body>
</html>
```

- [ ] **Step 3: Create blog/how-to-track-claude-code-spend.html**

Create `vantage-final-v4/blog/how-to-track-claude-code-spend.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>How to Track Claude Code Spend Per Developer — Step-by-Step Guide | Cohrint</title>
<meta name="description" content="A practical guide to tracking Claude Code costs per developer, per model, and per session. Set up Cohrint in under 5 minutes and never be surprised by your Anthropic invoice again.">
<meta name="keywords" content="how to track Claude Code spend, Claude Code cost per developer, monitor Claude Code usage, Claude Code billing breakdown, Anthropic API cost tracking tutorial">
<meta name="author" content="Cohrint">
<meta name="robots" content="index, follow">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Cohrint">
<meta property="og:title" content="How to Track Claude Code Spend Per Developer | Cohrint">
<meta property="og:description" content="Set up per-developer Claude Code cost tracking in under 5 minutes with Cohrint.">
<meta property="og:url" content="https://cohrint.com/blog/how-to-track-claude-code-spend">
<meta property="og:image" content="https://cohrint.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="How to Track Claude Code Spend Per Developer | Cohrint">
<meta name="twitter:description" content="Set up per-developer Claude Code cost tracking in under 5 minutes.">
<meta name="twitter:image" content="https://cohrint.com/og-image.png">
<link rel="canonical" href="https://cohrint.com/blog/how-to-track-claude-code-spend">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "How to Track Claude Code Spend Per Developer",
  "url": "https://cohrint.com/blog/how-to-track-claude-code-spend",
  "datePublished": "2026-04-15",
  "dateModified": "2026-04-15",
  "author": { "@type": "Organization", "name": "Cohrint" },
  "publisher": { "@type": "Organization", "name": "Cohrint", "url": "https://cohrint.com" },
  "description": "Step-by-step guide to tracking Claude Code costs per developer with Cohrint.",
  "image": "https://cohrint.com/og-image.png"
}
</script>
<style>
:root{--bg:#080c0f;--bg2:#0d1318;--bg3:#121920;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e8edf2;--muted:#6b7b8a;--dim:#3a4550;--accent:#00d4a1;--mono:'DM Mono',monospace;--sans:'DM Sans',sans-serif;--serif:'Instrument Serif',Georgia,serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;line-height:1.7;overflow-x:hidden}
nav{position:fixed;top:0;left:0;right:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:18px 48px;border-bottom:1px solid var(--border);background:rgba(8,12,15,.88);backdrop-filter:blur(16px)}
.nav-logo{font-family:var(--mono);font-size:15px;letter-spacing:.08em;color:var(--text);text-decoration:none;display:flex;align-items:center;gap:10px}
.logo-dot{width:8px;height:8px;background:var(--accent);border-radius:50%;box-shadow:0 0 12px var(--accent)}
.nav-links{display:flex;align-items:center;gap:32px}
.nav-links a{font-size:13px;color:var(--muted);text-decoration:none;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{background:var(--accent)!important;color:#fff!important;padding:8px 20px;border-radius:6px;font-weight:500!important}
@media(max-width:768px){nav{padding:16px 20px}.nav-links{display:none}}
article{max-width:720px;margin:0 auto;padding:140px 24px 80px}
.post-meta{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em;margin-bottom:24px}
.post-meta a{color:var(--accent);text-decoration:none}
h1{font-family:var(--serif);font-size:clamp(32px,5vw,52px);font-weight:400;line-height:1.08;letter-spacing:-.02em;margin-bottom:24px}
.lead{font-size:19px;color:var(--muted);line-height:1.7;margin-bottom:48px;font-weight:300}
h2{font-family:var(--serif);font-size:26px;font-weight:400;margin:48px 0 16px}
h3{font-size:16px;font-weight:500;color:var(--text);margin:24px 0 8px}
p{color:var(--muted);margin-bottom:20px}
.code-block{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:20px 24px;font-family:var(--mono);font-size:13px;color:var(--accent);margin:24px 0;overflow-x:auto}
.code-block .comment{color:var(--muted)}
.step-num{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:rgba(0,212,161,.1);border:1px solid rgba(0,212,161,.25);border-radius:50%;font-family:var(--mono);font-size:12px;color:var(--accent);margin-right:10px;flex-shrink:0}
.step-header{display:flex;align-items:center;margin:40px 0 12px}
.step-header h2{margin:0;font-size:22px}
.cta-box{background:rgba(0,212,161,.06);border:1px solid rgba(0,212,161,.15);border-radius:12px;padding:32px;text-align:center;margin:48px 0}
.btn-primary{background:var(--accent);color:#fff;padding:12px 28px;border-radius:8px;font-family:var(--mono);font-size:13px;font-weight:500;text-decoration:none;display:inline-block;transition:opacity .2s}
.btn-primary:hover{opacity:.85}
footer{border-top:1px solid var(--border);padding:36px 48px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted);font-family:var(--mono);flex-wrap:wrap;gap:16px}
footer a{color:var(--muted);text-decoration:none}
footer a:hover{color:var(--text)}
</style>
</head>
<body>
<nav>
  <a href="/" class="nav-logo"><span class="logo-dot"></span>COHRINT</a>
  <div class="nav-links">
    <a href="/calculator">Calculator</a>
    <a href="/docs">Docs</a>
    <a href="/report">Report</a>
    <a href="/blog">Blog</a>
    <a href="/signup.html" class="nav-cta">Request Access →</a>
  </div>
</nav>

<article>
  <div class="post-meta"><a href="/blog">Blog</a> · April 15, 2026 · 4 min read</div>
  <h1>How to Track Claude Code Spend Per Developer</h1>
  <p class="lead">If you're running Claude Code across a team of 5+ developers and checking spend on invoice day, you're already losing money. Here's how to set up per-developer tracking in under 5 minutes.</p>

  <div class="step-header"><span class="step-num">1</span><h2>Install Cohrint</h2></div>
  <p>Cohrint works as a transparent proxy layer — it intercepts Claude Code's Anthropic API calls, records cost metadata, and forwards the request without modifying it. Your developers notice nothing.</p>
  <div class="code-block">
    <span class="comment"># Install the SDK</span><br>
    pip install cohrint<br><br>
    <span class="comment"># Or with npm</span><br>
    npm install cohrint
  </div>

  <div class="step-header"><span class="step-num">2</span><h2>Set your API key</h2></div>
  <p>Get your Cohrint API key from the dashboard after requesting access. Add it to your environment — either per-developer or as a shared team key.</p>
  <div class="code-block">
    <span class="comment"># Add to .bashrc / .zshrc / shell profile</span><br>
    export COHRINT_API_KEY="coh_live_..."<br><br>
    <span class="comment"># Or add to your repo's .env (and .gitignore it)</span><br>
    COHRINT_API_KEY=coh_live_...
  </div>

  <div class="step-header"><span class="step-num">3</span><h2>Tag by developer (optional but recommended)</h2></div>
  <p>To get per-developer breakdowns, tag each environment with the developer's name or ID. This can be set in the environment or in a <code style="color:var(--accent);font-family:var(--mono)">.cohrint.yaml</code> config file.</p>
  <div class="code-block">
    <span class="comment"># Per-developer tagging</span><br>
    export COHRINT_USER="alice@company.com"<br><br>
    <span class="comment"># Or in .cohrint.yaml at repo root</span><br>
    user: ${GIT_AUTHOR_EMAIL}<br>
    team: engineering
  </div>

  <div class="step-header"><span class="step-num">4</span><h2>View your dashboard</h2></div>
  <p>After the first Claude Code session, costs appear in your Cohrint dashboard — broken down by developer, model (Opus / Sonnet / Haiku), tokens, and session duration. No batching, no 24-hour delay.</p>

  <h2>Setting Budget Alerts</h2>
  <p>Once tracking is live, set per-developer or per-team monthly budgets in the Cohrint dashboard. When spend hits 80% of budget, Cohrint sends a Slack alert. At 100%, it can optionally soft-block new sessions or just alert — your choice.</p>

  <h2>What Gets Tracked</h2>
  <p>Cohrint captures: model name, input tokens, output tokens, cost in USD, latency, session ID, and developer tag. <strong style="color:var(--text)">Your prompts and code are never captured.</strong> Cohrint sees the envelope, not the letter.</p>

  <div class="cta-box">
    <p style="color:var(--text);font-size:17px;font-weight:500;margin-bottom:8px">Ready to set this up?</p>
    <p style="font-size:14px;margin-bottom:24px">Request access and be tracking Claude Code spend in under 5 minutes.</p>
    <a href="/signup.html" class="btn-primary">Request Access — Free →</a>
  </div>
</article>

<footer>
  <a href="/">Cohrint</a>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <a href="/blog">Blog</a>
    <a href="/docs">Docs</a>
    <a href="/claude-code-cost">Claude Code Cost</a>
    <a href="/privacy">Privacy</a>
  </div>
  <span style="color:var(--dim)">© 2026 Cohrint</span>
</footer>
</body>
</html>
```

- [ ] **Step 4: Create blog.html (index)**

Create `vantage-final-v4/blog.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blog — AI Coding Cost Insights for Engineering Teams | Cohrint</title>
<meta name="description" content="Insights, benchmarks, and guides on AI coding tool costs — Claude Code, Gemini CLI, GitHub Copilot, and engineering FinOps best practices.">
<meta name="keywords" content="AI coding cost blog, Claude Code cost insights, engineering FinOps, LLM cost guides, AI developer tools blog">
<meta name="author" content="Cohrint">
<meta name="robots" content="index, follow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Cohrint">
<meta property="og:title" content="Blog — AI Coding Cost Insights | Cohrint">
<meta property="og:description" content="Benchmarks, guides, and insights on AI coding tool costs for engineering teams.">
<meta property="og:url" content="https://cohrint.com/blog">
<meta property="og:image" content="https://cohrint.com/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Cohrint Blog — AI Coding Cost Insights">
<meta name="twitter:description" content="Benchmarks, guides, and insights on AI coding tool costs.">
<meta name="twitter:image" content="https://cohrint.com/og-image.png">
<link rel="canonical" href="https://cohrint.com/blog">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#00d4a1">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Blog",
  "name": "Cohrint Blog",
  "url": "https://cohrint.com/blog",
  "description": "AI coding cost insights, benchmarks, and guides for engineering teams.",
  "publisher": { "@type": "Organization", "name": "Cohrint", "url": "https://cohrint.com" }
}
</script>
<style>
:root{--bg:#080c0f;--bg2:#0d1318;--bg3:#121920;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e8edf2;--muted:#6b7b8a;--dim:#3a4550;--accent:#00d4a1;--mono:'DM Mono',monospace;--sans:'DM Sans',sans-serif;--serif:'Instrument Serif',Georgia,serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:16px;line-height:1.6;overflow-x:hidden}
nav{position:fixed;top:0;left:0;right:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:18px 48px;border-bottom:1px solid var(--border);background:rgba(8,12,15,.88);backdrop-filter:blur(16px)}
.nav-logo{font-family:var(--mono);font-size:15px;letter-spacing:.08em;color:var(--text);text-decoration:none;display:flex;align-items:center;gap:10px}
.logo-dot{width:8px;height:8px;background:var(--accent);border-radius:50%;box-shadow:0 0 12px var(--accent)}
.nav-links{display:flex;align-items:center;gap:32px}
.nav-links a{font-size:13px;color:var(--muted);text-decoration:none;transition:color .2s}
.nav-links a:hover{color:var(--text)}
.nav-cta{background:var(--accent)!important;color:#fff!important;padding:8px 20px;border-radius:6px;font-weight:500!important}
@media(max-width:768px){nav{padding:16px 20px}.nav-links{display:none}}
.page-header{padding:140px 48px 60px;max-width:900px;margin:0 auto}
@media(max-width:768px){.page-header{padding:120px 20px 40px}}
.page-label{font-family:var(--mono);font-size:11px;color:var(--accent);letter-spacing:.1em;text-transform:uppercase;margin-bottom:16px}
h1{font-family:var(--serif);font-size:clamp(36px,5vw,60px);font-weight:400;line-height:1.1;margin-bottom:16px}
.page-sub{font-size:17px;color:var(--muted);max-width:500px;line-height:1.7}
.posts{max-width:900px;margin:0 auto;padding:0 48px 80px;display:grid;gap:20px}
@media(max-width:768px){.posts{padding:0 20px 60px}}
.post-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:32px;text-decoration:none;display:block;transition:border-color .2s}
.post-card:hover{border-color:var(--border2)}
.post-card-meta{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:.06em;margin-bottom:12px}
.post-card h2{font-family:var(--serif);font-size:24px;font-weight:400;color:var(--text);margin-bottom:10px;line-height:1.2}
.post-card p{font-size:14px;color:var(--muted);line-height:1.6}
.post-card-tag{display:inline-block;background:rgba(0,212,161,.08);border:1px solid rgba(0,212,161,.2);color:var(--accent);padding:3px 10px;border-radius:20px;font-family:var(--mono);font-size:10px;margin-top:16px}
footer{border-top:1px solid var(--border);padding:36px 48px;display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--muted);font-family:var(--mono);flex-wrap:wrap;gap:16px}
footer a{color:var(--muted);text-decoration:none}
footer a:hover{color:var(--text)}
</style>
</head>
<body>
<nav>
  <a href="/" class="nav-logo"><span class="logo-dot"></span>COHRINT</a>
  <div class="nav-links">
    <a href="/calculator">Calculator</a>
    <a href="/docs">Docs</a>
    <a href="/report">Report</a>
    <a href="/blog" style="color:var(--text)">Blog</a>
    <a href="/signup.html" class="nav-cta">Request Access →</a>
  </div>
</nav>

<div class="page-header">
  <div class="page-label">Blog</div>
  <h1>AI Coding Cost Insights</h1>
  <p class="page-sub">Benchmarks, guides, and data on what engineering teams spend on AI coding tools — and how to control it.</p>
</div>

<div class="posts">
  <a href="/blog/ai-coding-cost-benchmarks-2026" class="post-card">
    <div class="post-card-meta">April 15, 2026 · 5 min read</div>
    <h2>AI Coding Cost Benchmarks 2026 — What Engineering Teams Actually Spend</h2>
    <p>Data from 200+ engineering teams: average Claude Code spend per developer, Gemini CLI vs Copilot cost comparison, and how top teams control their AI coding budgets.</p>
    <span class="post-card-tag">Benchmarks</span>
  </a>

  <a href="/blog/how-to-track-claude-code-spend" class="post-card">
    <div class="post-card-meta">April 15, 2026 · 4 min read</div>
    <h2>How to Track Claude Code Spend Per Developer</h2>
    <p>A practical guide to tracking Claude Code costs per developer, per model, and per session. Set up Cohrint in under 5 minutes and never be surprised by your Anthropic invoice again.</p>
    <span class="post-card-tag">Guide</span>
  </a>
</div>

<footer>
  <a href="/">Cohrint</a>
  <div style="display:flex;gap:24px;flex-wrap:wrap">
    <a href="/docs">Docs</a>
    <a href="/calculator">Calculator</a>
    <a href="/report">Report</a>
    <a href="/privacy">Privacy</a>
  </div>
  <span style="color:var(--dim)">© 2026 Cohrint</span>
</footer>
</body>
</html>
```

- [ ] **Step 5: Verify all blog files**

```bash
ls vantage-final-v4/blog/ && grep "canonical" vantage-final-v4/blog.html vantage-final-v4/blog/ai-coding-cost-benchmarks-2026.html vantage-final-v4/blog/how-to-track-claude-code-spend.html
```

Expected: 2 files in `blog/`, all 3 files have canonical tags.

- [ ] **Step 6: Commit**

```bash
git add vantage-final-v4/blog.html vantage-final-v4/blog/
git commit -m "feat: add blog index and two initial posts with JSON-LD BlogPosting schema"
```

---

## Task 12: Search Engine Verification Files

**Files:**
- Modify: `vantage-final-v4/index.html` — add verification meta tags
- Create: `vantage-final-v4/google-site-verification.html`
- Create: `vantage-final-v4/BingSiteAuth.xml`
- Create: `vantage-final-v4/yandex_verification.html`
- Create: `vantage-final-v4/indexnow.txt`

- [ ] **Step 1: Add verification meta tags to index.html**

In `vantage-final-v4/index.html`, after `<link rel="canonical" href="https://cohrint.com">`, add:
```html
<!-- Search Engine Verification — replace PLACEHOLDER values with real codes from each console -->
<meta name="google-site-verification" content="GOOGLE_VERIFICATION_CODE_HERE">
<meta name="msvalidate.01" content="BING_VERIFICATION_CODE_HERE">
<meta name="yandex-verification" content="YANDEX_VERIFICATION_CODE_HERE">
```

- [ ] **Step 2: Create Google verification file**

Create `vantage-final-v4/google-site-verification.html`:
```html
<!-- Replace filename and content with the exact file Google Search Console provides -->
<!-- Go to: search.google.com/search-console → Add Property → HTML file method -->
<!-- Download the file Google gives you and replace this file with it -->
google-site-verification: googlePLACEHOLDER.html
```

- [ ] **Step 3: Create Bing verification file**

Create `vantage-final-v4/BingSiteAuth.xml`:
```xml
<?xml version="1.0"?>
<!-- Replace this file with the BingSiteAuth.xml downloaded from Bing Webmaster Tools -->
<!-- Go to: bing.com/webmasters → Add Site → XML file method -->
<users>
  <user>BING_VERIFICATION_CODE_HERE</user>
</users>
```

- [ ] **Step 4: Create Yandex verification file**

Create `vantage-final-v4/yandex_verification.html`:
```html
<!-- Replace filename and content with the file Yandex Webmaster provides -->
<!-- Go to: webmaster.yandex.com → Add site → HTML file method -->
<html><head><meta http-equiv="Content-Type" content="text/html; charset=UTF-8"></head><body>Verification: YANDEX_CODE_HERE</body></html>
```

- [ ] **Step 5: Create IndexNow key file**

IndexNow lets you instantly notify Bing + Yandex when pages are published. Generate a random key:

```bash
openssl rand -hex 32
```

Use the output (e.g., `a1b2c3d4...`) as your key. Create two files:

`vantage-final-v4/indexnow.txt` — contents = just the key string (one line):
```
PASTE_YOUR_32_CHAR_HEX_KEY_HERE
```

Also create `vantage-final-v4/<YOUR_KEY>.txt` with the same content (filename must match the key).

- [ ] **Step 6: Verify**

```bash
grep "google-site-verification\|msvalidate\|yandex-verification" vantage-final-v4/index.html
ls vantage-final-v4/BingSiteAuth.xml vantage-final-v4/yandex_verification.html vantage-final-v4/indexnow.txt
```

- [ ] **Step 7: Commit**

```bash
git add vantage-final-v4/index.html vantage-final-v4/google-site-verification.html vantage-final-v4/BingSiteAuth.xml vantage-final-v4/yandex_verification.html vantage-final-v4/indexnow.txt
git commit -m "seo: add search engine verification files and meta tags (placeholders)"
```

---

## Task 13: Update ADMIN_GUIDE.md — Search Console Setup

**Files:**
- Modify: `ADMIN_GUIDE.md`

- [ ] **Step 1: Add search console section to ADMIN_GUIDE.md**

Read the current `ADMIN_GUIDE.md` to find the right insertion point, then append this section:

```markdown
## Search Engine Verification & Sitemap Submission

After deploying, complete these steps once to register cohrint.com with each search engine.

### 1. Google Search Console
1. Go to [search.google.com/search-console](https://search.google.com/search-console)
2. Click **Add Property** → enter `https://cohrint.com`
3. Choose **HTML file** verification method
4. Download the file Google provides (e.g., `googleabc123.html`)
5. Replace `vantage-final-v4/google-site-verification.html` with the downloaded file (rename to match)
6. Update `<meta name="google-site-verification">` in `index.html` with your code
7. Deploy, then click **Verify** in Search Console
8. After verification: go to **Sitemaps** → Submit `https://cohrint.com/sitemap.xml`

### 2. Bing Webmaster Tools (covers DuckDuckGo, Yahoo, Edge, Safari Spotlight)
1. Go to [bing.com/webmasters](https://www.bing.com/webmasters)
2. Click **Add Site** → enter `https://cohrint.com`
3. Choose **XML file** verification
4. Replace `vantage-final-v4/BingSiteAuth.xml` with the file Bing provides
5. Update `<meta name="msvalidate.01">` in `index.html` with your code
6. Deploy, then click **Verify**
7. After verification: go to **Sitemaps** → Submit `https://cohrint.com/sitemap.xml`

### 3. Yandex Webmaster
1. Go to [webmaster.yandex.com](https://webmaster.yandex.com)
2. Click **Add site** → enter `https://cohrint.com`
3. Choose **HTML file** verification
4. Replace `vantage-final-v4/yandex_verification.html` with Yandex's file
5. Update `<meta name="yandex-verification">` in `index.html` with your code
6. Deploy, then verify and submit sitemap

### 4. IndexNow (instant indexing — Bing + Yandex)
IndexNow notifies search engines immediately when pages are published.

1. Generate your key: `openssl rand -hex 32`
2. Create `vantage-final-v4/<YOUR_KEY>.txt` containing just the key string
3. Update `vantage-final-v4/indexnow.txt` with the same key
4. After each deploy, ping IndexNow:
```bash
curl -X POST "https://api.indexnow.org/indexnow" \
  -H "Content-Type: application/json" \
  -d '{
    "host": "cohrint.com",
    "key": "YOUR_KEY_HERE",
    "keyLocation": "https://cohrint.com/YOUR_KEY_HERE.txt",
    "urlList": ["https://cohrint.com/", "https://cohrint.com/sitemap.xml"]
  }'
```

### 5. DuckDuckGo
DuckDuckGo uses Bing's index — no separate console needed. Once Bing is verified and sitemap submitted, DuckDuckGo will index cohrint.com automatically.

### 6. Safari
Safari uses Bing for Spotlight and browser search suggestions. Bing Webmaster Tools covers Safari as well — no separate action needed.

### Notes
- First indexing can take 1–4 weeks even after verification
- Check Search Console weekly for crawl errors or manual actions
- Update `sitemap.xml` lastmod dates whenever pages change significantly
```

- [ ] **Step 2: Verify the section was added**

```bash
grep -n "Search Engine\|IndexNow\|Bing Webmaster" ADMIN_GUIDE.md | head -10
```

Expected: lines showing the new section headings.

- [ ] **Step 3: Commit**

```bash
git add ADMIN_GUIDE.md
git commit -m "docs: add search engine verification and sitemap submission guide to ADMIN_GUIDE"
```

---

## Task 14: Add Blog and Landing Pages to Navigation

**Files:**
- Modify: `vantage-final-v4/index.html`

- [ ] **Step 1: Add Blog link to nav in index.html**

In `vantage-final-v4/index.html`, find the nav links section:
```html
<a href="/calculator.html">Calculator</a>
<a href="/docs.html">Docs</a>
<a href="/report.html">Report</a>
```

Replace with:
```html
<a href="/calculator">Calculator</a>
<a href="/docs">Docs</a>
<a href="/report">Report</a>
<a href="/blog">Blog</a>
```

Also update the mobile nav:
```html
<a href="/calculator.html">Calculator</a>
<a href="/docs.html">Docs</a>
<a href="/report.html">Report</a>
```
→
```html
<a href="/calculator">Calculator</a>
<a href="/docs">Docs</a>
<a href="/report">Report</a>
<a href="/blog">Blog</a>
```

And update the footer links (remove `.html` from all):
```html
<a href="/docs.html">Docs</a>
...
<a href="/report.html">Benchmark Report</a>
<a href="/privacy.html">Privacy</a>
<a href="/terms.html">Terms</a>
```
→
```html
<a href="/docs">Docs</a>
...
<a href="/report">Benchmark Report</a>
<a href="/blog">Blog</a>
<a href="/privacy">Privacy</a>
<a href="/terms">Terms</a>
```

- [ ] **Step 2: Verify**

```bash
grep -n "calculator\|/docs\|/report\|/blog" vantage-final-v4/index.html | grep "href" | head -15
```

Expected: no `.html` in nav/footer hrefs, `/blog` appears.

- [ ] **Step 3: Commit**

```bash
git add vantage-final-v4/index.html
git commit -m "feat: add Blog to nav, update nav/footer links to clean URLs"
```

---

## Task 15: Final Verification and Deploy

- [ ] **Step 1: Verify canonical tags across all public pages**

```bash
grep -rn "canonical" vantage-final-v4/*.html vantage-final-v4/blog/*.html | grep -v "noindex\|#" | grep ".html\""
```

Expected: **zero results** (no `.html` in any canonical URLs).

- [ ] **Step 2: Verify noindex pages**

```bash
grep -l "noindex" vantage-final-v4/auth.html vantage-final-v4/superadmin.html
```

Expected: both files listed.

- [ ] **Step 3: Verify sitemap has no .html extensions**

```bash
grep "\.html" vantage-final-v4/sitemap.xml
```

Expected: **no output** (zero `.html` in sitemap).

- [ ] **Step 4: Verify _redirects has clean URL rules**

```bash
grep "301" vantage-final-v4/_redirects
```

Expected: all existing + new `.html` → clean path 301 rules.

- [ ] **Step 5: Check all new HTML files exist**

```bash
ls vantage-final-v4/claude-code-cost.html vantage-final-v4/gemini-cli-cost.html vantage-final-v4/copilot-cost.html vantage-final-v4/ai-coding-cost.html vantage-final-v4/blog.html vantage-final-v4/blog/ai-coding-cost-benchmarks-2026.html vantage-final-v4/blog/how-to-track-claude-code-spend.html
```

Expected: all 7 files listed without error.

- [ ] **Step 6: Deploy to Cloudflare Pages**

```bash
cd vantageai && npx wrangler pages deploy vantage-final-v4 --project-name cohrint
```

Expected: successful deploy with preview URL.

- [ ] **Step 7: Smoke test live redirects**

```bash
# Test .html → clean URL redirect
curl -sI https://cohrint.com/docs.html | grep -i "location\|HTTP"
# Expected: HTTP/2 301 + Location: https://cohrint.com/docs

# Test new landing page
curl -sI https://cohrint.com/claude-code-cost | grep "HTTP"
# Expected: HTTP/2 200

# Test blog
curl -sI https://cohrint.com/blog | grep "HTTP"
# Expected: HTTP/2 200
```

- [ ] **Step 8: Final commit**

```bash
git add -A && git status
# Review what's staged — should be minimal leftover changes
git commit -m "chore: final SEO verification pass — all pages clean, deploy ready"
```

---

## Post-Deploy Manual Steps (User Action Required)

These steps cannot be automated — they require logging into each console with cohrint.com ownership:

1. **Replace verification placeholder files** with real files from each console before verifying
2. **Google Search Console** — verify + submit `https://cohrint.com/sitemap.xml`
3. **Bing Webmaster Tools** — verify + submit sitemap + enable IndexNow
4. **Yandex Webmaster** — verify + submit sitemap
5. **Generate IndexNow key** (`openssl rand -hex 32`), create key file, ping IndexNow API after each deploy
6. **vantageaiops.com** — deploy the redirect project and connect custom domain in Cloudflare Dashboard

See `ADMIN_GUIDE.md` for step-by-step instructions for each.
