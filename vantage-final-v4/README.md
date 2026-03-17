# Vantage AI — Enterprise Documentation

> AI cost intelligence platform — token tracking, model pricing comparison,
> efficiency scoring and budget governance for developers and organisations.

**Live:** https://vantageai.aman-lpucse.workers.dev

---

## Table of contents

1. [Quick start — run locally](#1-quick-start--run-locally)
2. [Supabase database setup](#2-supabase-database-setup)
3. [Google OAuth setup](#3-google-oauth-setup)
4. [Custom domain setup](#4-custom-domain-setup)
5. [Repository structure](#5-repository-structure)
6. [Architecture](#6-architecture)
7. [Design system](#7-design-system)
8. [User flows](#8-user-flows)
9. [All 9 product modules](#9-all-9-product-modules)
10. [Deploying to Cloudflare](#10-deploying-to-cloudflare)
11. [Environment variables](#11-environment-variables)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Quick start — run locally

### Prerequisites
- Any modern browser (Chrome, Firefox, Safari, Edge)
- Python 3 or Node.js (just for the local server)
- No build step, no npm install, no framework

### Option A — Python (simplest)
```bash
# Clone your repo
git clone https://github.com/YOUR_USERNAME/vantage-ai
cd vantage-ai

# Start local server on port 3000
python3 -m http.server 3000

# Open in browser
open http://localhost:3000
```

### Option B — Node.js
```bash
npm install -g serve
cd vantage-ai
serve . -p 3000
open http://localhost:3000
```

### Option C — VS Code Live Server
1. Install the **Live Server** extension in VS Code
2. Right-click `index.html` → Open with Live Server
3. Browser opens automatically at `http://127.0.0.1:5500`

### Pages you can access locally
| URL | Page |
|-----|------|
| `http://localhost:3000/` | Landing page |
| `http://localhost:3000/app.html` | Enterprise dashboard |
| `http://localhost:3000/auth.html` | Login / Sign up |
| `http://localhost:3000/calculator.html` | Pricing calculator |
| `http://localhost:3000/docs.html` | Documentation |
| `http://localhost:3000/check.html` | Deployment health check |

### Test data (no backend needed)
1. Open `http://localhost:3000/app.html`
2. A **"Seed data"** panel appears automatically
3. Click **"Generate test data"**
4. 52,000 events generate in ~5 seconds and store in browser IndexedDB
5. All 9 dashboard modules populate with realistic data

---

## 2. Supabase database setup

### Credentials (already configured in the code)
```
Project URL : https://oyljzpvwdfktrkeotmon.supabase.co
Anon Key    : sb_publishable_ZCgWwpZv5XBR0AjiJ8I9ig_yZ-8XFWN
```

### Run the schema
1. Go to https://supabase.com/dashboard/project/oyljzpvwdfktrkeotmon
2. Click **SQL Editor** → **New query**
3. Open `supabase-schema.sql` from this repo
4. Paste the entire contents → click **Run**
5. You should see: `Schema created successfully | table_count: 6`

### Configure Auth redirect URLs
1. Supabase Dashboard → **Authentication → URL Configuration**
2. Set these exactly:

```
Site URL:
  https://vantageai.aman-lpucse.workers.dev

Additional redirect URLs:
  https://vantageai.aman-lpucse.workers.dev/app.html
  http://localhost:3000/app.html
  http://127.0.0.1:5500/app.html
```

3. Click **Save**

### What the database stores
| Table | Purpose |
|-------|---------|
| `auth.users` | Managed by Supabase — email, password hash, OAuth tokens |
| `organisations` | Auto-created on signup — one per user |
| `profiles` | Links user to org, stores name/role/avatar |
| `api_keys` | SHA-256 hashed SDK keys |
| `usage_daily` | Daily aggregated AI usage per model |
| `budget_rules` | Spend limits and alert thresholds |
| `waitlist` | Emails from the landing page form |

---

## 3. Google OAuth setup

### Step 1 — Google Cloud Console
1. Go to https://console.cloud.google.com
2. Create project → **Vantage AI**
3. APIs & Services → **OAuth consent screen**
   - User type: **External**
   - App name: Vantage AI
   - Save and continue (skip scopes and test users)
4. APIs & Services → **Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized JavaScript origins:
     ```
     https://vantageai.aman-lpucse.workers.dev
     http://localhost:3000
     http://127.0.0.1:5500
     ```
   - Authorized redirect URIs:
     ```
     https://oyljzpvwdfktrkeotmon.supabase.co/auth/v1/callback
     ```
5. Copy **Client ID** and **Client Secret**

### Step 2 — Enable in Supabase
1. Supabase Dashboard → **Authentication → Providers → Google**
2. Toggle **Enable**
3. Paste Client ID and Client Secret
4. Click **Save**

### Step 3 — Test
Open `https://vantageai.aman-lpucse.workers.dev/auth.html` → click **Continue with Google**

---

## 4. Custom domain setup

### Option A — Get a free `.dev` domain via Cloudflare Registrar
1. Cloudflare Dashboard → **Domain Registration → Register Domains**
2. Search `vantageai.dev` or `vantage-ai.dev`
3. Register (~$10-12/year)

### Option B — Connect an existing domain
If you own `vantageai.com`:
1. Your DNS provider (or move DNS to Cloudflare, which is free)
2. Add a CNAME record:
   ```
   Type:  CNAME
   Name:  @  (or www)
   Value: vantageai.aman-lpucse.workers.dev
   ```

### Option C — Custom subdomain on workers.dev (rename your project)
Your current URL is `vantageai.aman-lpucse.workers.dev`.
To change the subdomain part (`vantageai`):
1. Cloudflare Dashboard → **Workers & Pages → your project**
2. **Settings → Custom Domains → Add custom domain**
3. Or go to **Settings → General → Project name** to rename

### Option D — Free subdomain options
| Domain | Cost | How |
|--------|------|-----|
| `vantageai.pages.dev` | Free | Rename Cloudflare Pages project |
| `vantageai.vercel.app` | Free | Deploy to Vercel |
| `vantageai.netlify.app` | Free | Deploy to Netlify |
| `vantageai.dev` | ~$12/yr | Buy via Cloudflare Registrar |
| `vantage-ai.com` | ~$10/yr | Buy via Cloudflare Registrar |

### To get `vantageai.pages.dev` (cleanest free option)
1. Cloudflare Dashboard → **Workers & Pages → Create application → Pages**
2. Connect to your GitHub repo
3. Project name: `vantageai` → creates `vantageai.pages.dev`
4. Build settings: Framework = None, build command = blank, output = `/`

---

## 5. Repository structure

```
vantage-ai/
│
├── index.html            Landing page with hero, features, pricing
├── auth.html             Login, signup, Google OAuth, magic link
├── app.html              Enterprise dashboard — all 9 modules
├── calculator.html       Live AI pricing calculator (23 models)
├── docs.html             Integration documentation
├── signup.html           Waitlist / join page
├── check.html            Deployment health checker
│
├── vantage-models.js     Pricing database — 23 models, 7 providers
├── seed-data.js          Test data generator — 52k events, IndexedDB
│
├── _headers              Cloudflare Pages security headers (CSP)
├── _redirects            Cloudflare Pages URL routing
│
├── supabase-schema.sql   Database schema — run once in Supabase SQL editor
└── README.md             This file
```

---

## 6. Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Browser (Client)                   │
│                                                       │
│  index.html ──► auth.html ──► app.html               │
│                    │              │                   │
│              Supabase JS    IndexedDB                 │
│              Auth SDK       (test data)               │
│              (50k MAU free)                           │
└──────────────────────┬──────────────────────────────-┘
                       │ HTTPS
          ┌────────────▼────────────┐
          │   Supabase (free tier)  │
          │                         │
          │  auth.users             │
          │  organisations          │
          │  profiles               │
          │  api_keys               │
          │  usage_daily            │
          │  budget_rules           │
          │  waitlist               │
          └─────────────────────────┘

Hosting:  Cloudflare Workers/Pages (unlimited free)
CDN:      Cloudflare global edge (200+ locations)
Auth:     Supabase (50,000 MAU free)
Database: Supabase Postgres (500MB free)
Charts:   Chart.js (loaded from cdnjs.cloudflare.com)
```

### Data flow — user signs up
```
1. User fills form in auth.html
2. supabase.auth.signUp() called
3. Supabase creates auth.users row
4. DB trigger fires → creates organisations + profiles row automatically
5. User redirected to app.html
6. app.html loads user's org data from Supabase
7. Seed data panel appears (first visit)
8. User generates 52k test events → stored in IndexedDB locally
```

### Data flow — SDK captures an AI call
```
1. Developer wraps OpenAI/Anthropic client with Vantage proxy
2. vantage.init("vnt_your_key") called once at startup
3. Every API call intercepted → tokens, cost, latency captured
4. Event queued in memory (async, zero latency impact)
5. Background thread flushes batch every 2 seconds
6. POST /v1/events to ingest server
7. Ingest server validates API key (hash lookup in Supabase)
8. Events written to ClickHouse (time-series) + usage_daily (Supabase)
9. Dashboard queries aggregate in real time
```

---

## 7. Design system

### Colours
```css
--bg:    #080c0f   /* Page background */
--bg2:   #0d1318   /* Card background */
--bg3:   #121920   /* Input / code background */
--tx:    #e8edf2   /* Primary text */
--mu:    #6b7b8a   /* Muted text */
--ac:    #00d4a1   /* Accent (teal-green) */
--bl:    #0098ff   /* Blue */
--am:    #f59e0b   /* Amber / warning */
--re:    #f87171   /* Red / error */
--pu:    #a78bfa   /* Purple */
```

### Typography
- **Headings:** Instrument Serif (Google Fonts) — editorial feel
- **UI:** DM Sans — clean, readable
- **Code / numbers:** DM Mono — technical precision

### Component patterns
```
Cards:      bg2 background, 1px border, 12px border-radius
KPI cards:  24px mono font for values, 9px mono uppercase labels
Tables:     1px bottom borders, hover background 2% white
Tags:       10px mono, pill shape, colour-coded by status
Charts:     Chart.js 4, transparent bg, no gridlines by default
```

### Spacing
- Container padding: `24px 28px`
- Card padding: `18px 20px`
- Grid gap: `12-14px`
- Section margin: `20px bottom`

---

## 8. User flows

### New user — email signup
```
Landing page (index.html)
  → Click "Start free →"
  → auth.html loads (signup tab active)
  → Enter name, email, password
  → supabase.auth.signUp() called
  → Email confirmation sent by Supabase
  → User clicks link in email
  → Redirected to app.html
  → First visit: seed data panel auto-opens
  → Click "Generate test data" → 52k events loaded
  → Full dashboard available
```

### Returning user — Google OAuth
```
auth.html
  → Click "Continue with Google"
  → Google account picker opens
  → User selects account
  → Google sends code to Supabase callback URL
  → Supabase exchanges for session
  → Redirected to app.html (logged in)
```

### Developer — SDK integration
```
1. Sign up at /auth.html
2. Open app.html → Security & Governance module
3. Generate API key (shows once, store safely)
4. pip install vantage-ai[openai]
5. Add 2 lines to existing code:
     import vantage
     from vantage.proxy.openai_proxy import OpenAI
     vantage.init("vnt_your_key")
6. All API calls tracked automatically
7. Dashboard populates with real data
```

### Manager / CFO — reporting flow
```
app.html → Enterprise Reporting module
  → View YTD spend by department
  → Click "Export CSV" → download chargeback report
  → Click "Export PDF" → executive summary
  → Schedule: configure weekly email reports
```

---

## 9. All 9 product modules

### Module 1 — Cost Intelligence (9 features)
The core product. Answers "how much are we spending and where?"
- Real-time spend dashboard with 30/90-day trends
- Cost breakdown by model, team, feature, endpoint
- Budget gauge with MTD vs limit comparison
- Active alert feed (budget breaches, anomaly spikes)
- Top-10 most expensive requests table
- Provider cost comparison chart
- Team cost attribution donut chart
- Daily spend bar chart (current day highlighted)
- Savings opportunity callout box

### Module 2 — Token Analytics (7 features)
The efficiency layer. Surfaces waste in system prompts and context.
- Total token count with prompt / completion / cached split
- Efficiency score (0-100) per endpoint
- System prompt size analysis per endpoint
- Cache hit rate tracking (target: 40%+)
- Daily token usage stacked bar chart
- Optimisation recommendations with estimated savings
- Wasted token quantification

### Module 3 — Model Comparison (8 features)
The viral hook. Used for sharing in Slack and engineering blogs.
- Live pricing for all 23 models across 7 providers
- Usage profile sliders (prompt tokens, completion tokens, requests/month)
- Monthly cost calculator for every model
- "vs cheapest" delta column
- Quality vs cost scatter chart
- Provider breakdown donut chart
- Tier filter (Frontier / Mid / Fast)
- Savings recommendation box

### Module 4 — Performance & Latency (7 features)
Rounds out observability. Cost without latency is half the picture.
- p50 / p95 / p99 latency trend charts
- Time-to-first-token (TTFT) tracking
- Error rate over time
- TTFT distribution histogram
- Per-model latency comparison bar chart
- SLA compliance table (all models)
- Alert when p99 exceeds threshold

### Module 5 — Quality & Evaluation (8 features)
What separates observability platforms in 2026.
- A/B experiment tracker with winner detection
- Side-by-side output comparison (current vs candidate model)
- Quality score over time per model
- Eval dataset results table (accuracy, coherence, factuality)
- Regression detection with alerts
- Cost vs quality trade-off analysis
- Prompt versioning linkage
- Winner recommendation with monthly saving

### Module 6 — AI Intelligence Layer (5 features)
The moat. Features nobody else owns clearly yet.
- **Auto model router** — rule-based routing to cheapest model per endpoint
- **Prompt optimizer agent** — compresses system prompts 20-35%
- **Smart cache recommendations** — identifies high-repetition prompts
- Router decision trend chart
- Routing rule CRUD interface

### Module 7 — Enterprise Reporting (6 features)
What gets you into the CFO meeting.
- YTD spend chart by month
- ROI metrics (cost per request, hours saved, ROI multiple)
- Departmental chargeback table with efficiency scores
- CSV and PDF export buttons
- Scheduled report configuration
- Budget vs actual comparison

### Module 8 — Security & Governance (8 features)
The enterprise gate. Required for regulated industries.
- API key management (create, list, revoke)
- Role-based access control matrix (Owner / Admin / Developer / Viewer)
- Full audit log with IP addresses
- Data retention policy by plan tier
- Compliance status (SOC2, GDPR, HIPAA, CCPA)
- Per-key usage tracking
- Key rotation reminders
- Single sign-on readiness (Enterprise plan)

### Module 9 — Developer Experience (7 features)
The bottom-up growth engine.
- Quickstart code (Python / TypeScript / cURL tabs)
- Integration health monitoring (SDK version, last call time)
- Webhook configuration (Slack, PagerDuty, custom)
- Live event stream (real-time incoming calls)
- Seed data generator (52k events for testing)
- API explorer
- SDK installation instructions per language

---

## 10. Deploying to Cloudflare

### Method A — GitHub auto-deploy (recommended)

```bash
# 1. Push files to GitHub
git init
git add .
git commit -m "Initial Vantage AI deployment"
git remote add origin https://github.com/YOUR_USERNAME/vantage-ai
git push -u origin main

# 2. Connect in Cloudflare
# dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git
# Select repo → Framework: None → Build command: blank → Output: /
# Click Save and Deploy
```

Every `git push` auto-redeploys. No build step needed.

### Method B — Direct upload (no GitHub)
```bash
# Unzip vantage-fixed-v3.zip
# Drag all 12 files to:
# Cloudflare Dashboard → Workers & Pages → your project
# → Deployments → Upload assets → drag files → Deploy
```

### Verify deployment
Open: `https://your-site.pages.dev/check.html`
All 8 critical files should show green "200 OK".

---

## 11. Environment variables

All credentials live directly in `auth.html` and `app.html`.
For a production backend, move these to Cloudflare Pages environment variables:

| Variable | Value | Where used |
|----------|-------|------------|
| `SUPABASE_URL` | `https://oyljzpvwdfktrkeotmon.supabase.co` | auth.html, app.html |
| `SUPABASE_ANON` | `sb_publishable_ZCgW...` | auth.html, app.html |

To add in Cloudflare Pages:
1. Workers & Pages → your project → **Settings → Environment Variables**
2. Add both variables
3. Redeploy

Note: The anon key is safe to expose in client-side code — Supabase Row Level
Security prevents any user from accessing another user's data.

---

## 12. Troubleshooting

### "Only index.html loads"
Files were uploaded as a zip. Cloudflare wraps zip contents in a subdirectory.
**Fix:** Unzip, then drag the individual files into Cloudflare's upload area.

### "Redirect loop on auth.html"
Supabase credentials are wrong or not configured.
**Fix:** Verify `SUPABASE_URL` and `SUPABASE_ANON` in auth.html line ~198.

### "Google OAuth redirect_uri_mismatch"
**Fix:** Add `https://oyljzpvwdfktrkeotmon.supabase.co/auth/v1/callback`
to Google Console → Credentials → Authorized redirect URIs.

### "Charts don't load"
Chart.js CDN blocked.
**Fix:** Check browser console for CSP errors. The `_headers` file already
allows `cdnjs.cloudflare.com`. If still blocked, try a different browser.

### "Seed data button doesn't appear"
Only shows on first visit. To re-seed:
**Fix:** Open browser DevTools (F12) → Application → IndexedDB → delete
`vantage_seed` database → reload the page.

### "Email confirmation not arriving"
**Fix:** Supabase Dashboard → Authentication → Settings → disable
"Enable email confirmations" for development/testing.

### Local CORS errors with Supabase
**Fix:** Use a local HTTP server (python3 -m http.server) not file:// protocol.
Supabase blocks requests from `file://` origins.

---

## Contributing

This is a monorepo of static files — no build system required.
Edit any `.html` file, save, and refresh to see changes locally.

The shared pricing database (`vantage-models.js`) is imported by both
`app.html` and `calculator.html` via `<script src="vantage-models.js">`.
Update model prices there and both pages update automatically.

---

*Built with Supabase · Cloudflare Pages · Chart.js · Vanilla JS*
*Zero build step · Zero npm dependencies · Zero monthly cost*
