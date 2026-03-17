# Vantage AI — Backend SDK & Server

Enterprise AI observability: token tracking, cost analysis, latency monitoring,
efficiency scoring, and hallucination detection across all AI providers and agents.

**Live dashboard:** https://vantageai.aman-lpucse.workers.dev/app.html

---

## What this does

When your team uses AI (OpenAI, Anthropic, Google, Copilot, Claude Code, Windsurf),
every call goes through the Vantage proxy. We capture:

| Metric | How |
|--------|-----|
| Token usage (prompt/completion/cached) | From provider response |
| Cost per call + monthly total | Live pricing database (23 models) |
| Latency + TTFT | Wall-clock timing |
| Efficiency score (0-100) | Rule-based: system prompt bloat, caching, model fit |
| **Hallucination score (0.0-1.0)** | Claude Opus 4.6 as LLM judge — async |
| Faithfulness, relevancy, toxicity | Ragas-inspired metrics via Opus 4.6 |
| Per-team, per-project breakdown | Tags you set in vantage.init() |
| Per-agent analytics | Copilot vs Claude Code vs Windsurf vs Cursor |

---

## Architecture & design overview

**Core components:**
- **SDK (Python)**: Intercepts OpenAI/Anthropic API calls and emits structured events.
- **Ingest API (FastAPI)**: Receives event batches, auths via `vnt_...` keys, stores them in Supabase/ClickHouse, and exposes analytics endpoints.
- **Analytics engine**: Aggregates raw events into KPIs, timeseries, model/team breakdowns, and hallucination reports.
- **Frontend (static)**: Dashboard UI that visualizes analytics and lets users configure backend connection.
- **Hallucination scoring**: Optional async evaluation using Claude Opus 4.6 (Anthropic API).

**Main data flow:**
1. SDK sends event to `/v1/events` with `Authorization: Bearer vnt_...`.
2. Backend validates API key, stores raw event, and schedules async scoring (if enabled).
3. Analytics endpoints (`/v1/kpis`, `/v1/timeseries`, etc.) query stored events and compute rollups.
4. Frontend fetches these endpoints and renders dashboards.

**Key libraries / tools**
- Backend: `fastapi`, `uvicorn`, `pydantic`, `supabase`, `clickhouse-connect`
- Hallucination: `anthropic` (Claude Opus 4.6)
- Frontend: Vanilla HTML/CSS/JS; Chart.js for charts

---

## Quick start — local development

### 1. Clone and set up

```bash
git clone https://github.com/YOUR_USERNAME/vantage-ai
cd vantage-ai/vantage-backend
```

### 2. Set environment variables

Create `.env` in the `server/` directory:

```bash
# server/.env

# Supabase (from your project settings)
SUPABASE_URL=https://oyljzpvwdfktrkeotmon.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key_here   # NOT the anon key
SUPABASE_ANON_KEY=sb_publishable_ZCgWwpZv5XBR0AjiJ8I9ig_yZ-8XFWN

# ClickHouse (free tier at clickhouse.cloud)
CLICKHOUSE_HOST=your-service.clickhouse.cloud
CLICKHOUSE_PASSWORD=your-password
CLICKHOUSE_DATABASE=vantage

# Claude Opus 4.6 for hallucination scoring
ANTHROPIC_API_KEY=sk-ant-your-key

# Optional
EVAL_ENABLED=true
PORT=8000
```

> **Where is the service role key?**
> Supabase Dashboard → Project Settings → API → service_role key (keep secret!)

### 3. Start the ingest server

```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Server is live at `http://localhost:8000`
Swagger docs at `http://localhost:8000/docs`

### 4. Install the SDK in your project

```bash
pip install -e ../sdk[openai,anthropic,analysis]
```

### 5. Integrate — 3 lines

```python
import vantage
from vantage.proxy.openai_proxy import OpenAI      # drop-in
from vantage.proxy.anthropic_proxy import Anthropic  # drop-in

vantage.init(
    api_key        = "vnt_your_key",      # from Vantage dashboard
    org            = "acme-corp",
    team           = "engineering",
    project        = "chatbot-v2",
    agent          = "cursor",            # what AI tool is being used
    anthropic_key  = "sk-ant-...",        # enables hallucination scoring
    environment    = "development",
    debug          = True,                # prints each captured event
)

# Identical API to the originals
openai_client  = OpenAI(api_key="sk-...")
claude_client  = Anthropic(api_key="sk-ant-...")

# Every call is now tracked
response = openai_client.chat.completions.create(
    model    = "gpt-4o",
    messages = [{"role": "user", "content": "Explain transformers"}],
)
# Captured: 847ms latency | 1,240 prompt + 380 completion tokens
# Cost: $0.00425 | Cheapest alt: gemini-flash at $0.00032 (save 92%)
# Hallucination: 0.04 (scored async by Claude Opus 4.6 in ~3s)
# Efficiency: 78/100 — system prompt is 42% of input
```

---

## Integrating with AI agents (Copilot, Windsurf, Cursor, Claude Code)

These agents make standard OpenAI/Anthropic API calls internally.
Vantage intercepts them via a local HTTP proxy — zero changes to the agent.

```python
import vantage
from vantage.wrappers.agent_wrapper import AgentProxy

vantage.init(api_key="vnt_...", agent="copilot", team="engineering")

# Start proxy: forwards copilot → api.githubcopilot.com
# while capturing all statistics
proxy = AgentProxy(
    target_host = "https://api.githubcopilot.com",
    local_port  = 8877,
    agent_name  = "copilot",
)
proxy.start()
```

Then set the environment variable that tells Copilot to use your proxy:

```bash
# GitHub Copilot
export OPENAI_API_BASE=http://127.0.0.1:8877

# Cursor
export OPENAI_BASE_URL=http://127.0.0.1:8877

# Claude Code / Windsurf
export ANTHROPIC_BASE_URL=http://127.0.0.1:8878

# Or start proxy for Anthropic agents
proxy_claude = AgentProxy("https://api.anthropic.com", port=8878, agent_name="claude-code")
proxy_claude.start()
```

The dashboard's **"AI Intelligence Layer"** module shows per-agent analytics:
- Which agent generates the most cost
- Which agent has highest hallucination rate
- Which agent is most efficient per token

---

## Multi-tenant: Individual → Team → Enterprise

### Individual (1 user)
```python
vantage.init(api_key="vnt_...", org="my-project")
```
Full cost + hallucination dashboard for one user.

### Team (1-10 users)
```python
# Set per-developer context
vantage.init(api_key="vnt_...", org="startup-inc", team="backend")
vantage.set_user("dev@startup.com")

# Or tag per-call
vantage.tag("user_id", "alice")
vantage.tag("feature", "code-review")
```
Dashboard shows cost/efficiency/hallucination broken down by team member.

### Large organisation (1000+ users)
```python
# In your API gateway / middleware — inject context from auth token
vantage.init(
    api_key     = os.environ["VANTAGE_KEY"],
    org         = "enterprise-corp",
    team        = request.user.department,    # from your auth system
    project     = request.headers["X-Project"],
    environment = "production",
)
vantage.set_user(request.user.id)
```

The dashboard's **Enterprise Reporting** module shows:
- Cost chargeback by department
- Project-level spend vs budget
- Which team has highest hallucination rate
- Cross-team efficiency comparison

---

## Frontend dashboard (vantage-final-v4)

The static UI in `vantage-final-v4/` can be hosted on Cloudflare Pages (https://vantageai.aman-lpucse.workers.dev/).
It calls the backend REST APIs (`/v1/kpis`, `/v1/timeseries`, etc.) using an API key.

### Connect the UI to your backend

1. Deploy the backend (e.g., Render, Railway) and note its base URL (e.g. `https://vantage-ingest.onrender.com`).
2. Open `vantage-final-v4/app.html` in a browser and click **Settings**.
3. Enter:
   - **Backend API base URL**: your backend URL (no trailing slash).
   - **Vantage API key**: a `vnt_...` key (e.g., `vnt_acme_...`).
   - **Org ID**: the org from your API key (auto-derived from a key formatted as `vnt_{org}_{id}`).

If you want to bypass the prompt, you can also set query params in the URL:
`?api_base=...&api_key=...&org=...`

---

## How hallucination scoring works

Every AI call that has both a user query and a response gets scored
asynchronously by Claude Opus 4.6 (usually within 3-10 seconds):

```
Your app calls GPT-4o
         ↓
Vantage proxy captures request + response (0ms overhead)
         ↓
Your app gets the response immediately (no delay)
         ↓ (async, background)
Claude Opus 4.6 evaluates:
  - hallucination_score: 0.0–1.0 (is the response factually grounded?)
  - coherence_score: 0.0–1.0
  - relevancy_score: 0.0–1.0
  - completeness_score: 0.0–1.0
  - toxicity_score: 0.0–1.0
  - overall_quality: 0.0–10.0
         ↓
Scores patched to the event in ClickHouse
         ↓
Dashboard shows hallucination trends, worst offenders, type breakdown
```

**Hallucination types detected:**
- `factual` — incorrect stated facts
- `entity` — wrong names, dates, numbers
- `attribution` — wrong source/author claims
- `citation` — fabricated references
- `intrinsic` — contradicts the given context
- `none` — response appears grounded

---

## API reference

### POST /v1/events
```bash
curl -X POST http://localhost:8000/v1/events \
  -H "Authorization: Bearer vnt_your_key" \
  -H "Content-Type: application/json" \
  -d '{"events": [...], "sdk_version": "0.2.0"}'
```

### GET /v1/stats/{org_id}?days=30
Returns KPIs: total spend, tokens, efficiency score, hallucination rate.

### GET /v1/stats/{org_id}/models
Cost breakdown by model, sorted by spend.

### GET /v1/stats/{org_id}/teams
Cost, efficiency, hallucination rate per team.

### GET /v1/stats/{org_id}/agents
Per-agent analytics — Copilot vs Claude Code vs Windsurf vs Cursor.

### GET /v1/stats/{org_id}/hallucination
Hallucination trends, type distribution, worst-offending models.

### GET /v1/stats/{org_id}/efficiency
Efficiency scores, system prompt analysis, top savings opportunities.

Full Swagger UI: `http://localhost:8000/docs`

---

## Open source tools used

| Tool | Purpose | License |
|------|---------|---------|
| **Claude Opus 4.6** | LLM-as-judge hallucination + quality scoring | Anthropic API |
| **FastAPI** | Ingest and analytics API server | MIT |
| **ClickHouse** | Time-series event storage (free tier at clickhouse.cloud) | Apache 2.0 |
| **Supabase** | User auth, org management, API keys | Apache 2.0 |
| **OpenTelemetry** (planned) | Standard distributed tracing spans | Apache 2.0 |
| **Ragas** (planned) | RAG evaluation — faithfulness, relevancy | MIT |
| **DeepEval** (planned) | Additional LLM eval metrics | Apache 2.0 |

---

## Domain name guidance (finding the best available domain)

Choosing a good domain for the company is important. Here are steps and tips to find an available name:

### Step 1: Pick a short, brandable base
- Prefer **one or two words** (e.g., `vantage`, `vantageai`, `vantageanalytics`).
- Avoid hyphens if possible (makes spoken spelling harder).
- Keep it < 15 characters if you can.

### Step 2: Check availability quickly
Use one of these tools:
- Cloudflare Registrar / Cloudflare Pages (search for nice `*.workers.dev` or `*.pages.dev` names)
- Namecheap, GoDaddy, Google Domains, or Domain.com
- `whois` / `dig` on the command line:
  ```bash
  whois vantageai.dev
  ```

### Step 3: Pick a TLD strategy
- **.dev** is great for developer tooling and integrates with Cloudflare (HTTPS enforced).
- **.ai** is widely used for AI startups (usually more expensive).
- **.com** is fine if you can get a short & clean one.

### Suggestion list (check availability)
1. `vantageai.dev` (recommended, used in this project)
2. `vantageanalytics.dev`
3. `vantage-cost.ai`
4. `vantageintel.ai`
5. `vantagehq.dev`

> Tip: use the domain registrar search tool to see instant availability; pick the shortest available name you like.

---

---

## DB schema changes (Supabase migrations)

Yes — you can change the Supabase schema remotely, including from VS Code, by using Supabase migrations or the SQL editor.

### Option 1 — Supabase CLI + migrations (recommended)
1. Install:
   ```bash
   npm install -g supabase
   ```
2. Login:
   ```bash
   supabase login
   ```
3. Initialize (if not already):
   ```bash
   supabase init
   ```
4. Create a migration:
   ```bash
   supabase migration new add_some_column
   ```
5. Edit the generated SQL under `supabase/migrations/` in VS Code (example file included: `supabase/migrations/0001_initial_schema.sql`).
6. Commit the migration SQL file to Git so teammates and CI can reproduce the schema.
7. Apply changes:
   ```bash
   supabase db push
   ```

This approach keeps schema changes versioned, reviewable, and consistent across environments.

> **VS Code + Git workflow**
> 1. Create a migration with the Supabase CLI.
> 2. Edit the SQL in VS Code, run `git diff` to confirm changes.
> 3. Open a PR with the migration file, then merge.
> 4. In CI, run `supabase db push` to apply migrations automatically.

### Option 2 — Supabase dashboard (quick edits)
- In the Supabase web UI, use **SQL Editor → New query**.
- Run DDL statements (`ALTER TABLE`, `CREATE TABLE`, etc.).
- If you do this, commit an equivalent migration SQL to your repo so other environments stay in sync.

### Option 3 — Direct Postgres access (advanced)
- Use `psql` / TablePlus / DBeaver with the Supabase Postgres connection string.
- Use with caution: direct changes can drift from migrations.

---

## Project structure

```
vantage-backend/
│
├── sdk/                          pip install vantage-ai
│   ├── pyproject.toml
│   └── vantage/
│       ├── __init__.py           vantage.init(), vantage.tag()
│       ├── client.py             VantageClient — queue + flush + async scoring
│       ├── models/
│       │   ├── event.py          VantageEvent dataclass
│       │   └── pricing.py        Live pricing for 23 models
│       ├── proxy/
│       │   ├── openai_proxy.py   drop-in OpenAI wrapper
│       │   ├── anthropic_proxy.py drop-in Anthropic wrapper
│       │   ├── litellm_proxy.py  any model via LiteLLM
│       │   └── universal.py      unified interface
│       ├── wrappers/
│       │   └── agent_wrapper.py  HTTP proxy for Copilot/Windsurf/Cursor
│       └── analysis/
│           ├── hallucination.py  Claude Opus 4.6 scoring
│           └── efficiency.py     Rule-based efficiency scorer
│
└── server/                       FastAPI ingest + analytics backend
    ├── main.py                   Routes, auth, request models
    ├── requirements.txt
    └── .env                      Your credentials (never commit this)
```

---

## Environment variables reference

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | `https://oyljzpvwdfktrkeotmon.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Yes | service_role key (Supabase → Settings → API) |
| `ANTHROPIC_API_KEY` | For hallucination | Your Anthropic key for Opus 4.6 scoring |
| `CLICKHOUSE_HOST` | Yes | Your ClickHouse Cloud hostname |
| `CLICKHOUSE_PASSWORD` | Yes | ClickHouse password |
| `CLICKHOUSE_DATABASE` | No | Default: `vantage` |
| `EVAL_ENABLED` | No | Default: `true` — set to `false` to disable scoring |
| `PORT` | No | Default: `8000` |

---

## Getting a Vantage API key

1. Open https://vantageai.aman-lpucse.workers.dev/app.html
2. Go to **Security & Governance** in the sidebar
3. Click **"+ Generate key"**
4. Copy it — shown once only (starts with `vnt_`)

---

## Deploy the server (free)

```bash
# Railway (recommended — free tier, 1-click)
railway login
railway up

# OR Render
# Connect GitHub repo → select server/ → add env vars → deploy

# OR Docker anywhere
docker build -t vantage-server .
docker run -p 8000:8000 --env-file .env vantage-server
```

---

## Troubleshooting

**"vantage not initialised"**
Call `vantage.init(api_key="...")` before any proxy imports.

**Hallucination scores are -1 or null**
Set `anthropic_key` in `vantage.init()` or `ANTHROPIC_API_KEY` env var.

**No data in dashboard after integrating**
- Check `debug=True` output — it prints every captured event
- Verify `ingest_url` points to your running server
- Check server logs for auth errors

**Agent proxy not capturing**
Verify the env var is set: `echo $OPENAI_API_BASE` should be `http://127.0.0.1:8877`

**ClickHouse connection refused**
Free tier requires SSL. Make sure `secure=True` in ClickHouseStore (it is by default).

---

## End-to-end setup checklist (all components)

This project has three main layers:

1. **Data ingestion + analytics backend** (`vantage-backend/server`) — FastAPI service that accepts `/v1/events` and exposes `/v1/*` analytics endpoints.
2. **Frontend dashboard + landing pages** (`vantage-final-v4/`) — static UI hosted on Cloudflare Pages.
3. **Persistent storage + auth** (Supabase; optionally ClickHouse) — stores users, orgs, API keys, events, and rollups.

### Step 1 — Supabase (required)
- Create a project and run `supabase-schema.sql` from this repo.
- Configure Auth redirect URLs for the UI (Cloudflare Pages + local dev).
- Copy `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` into `server/.env`.
- Supabase stores:
  - `auth.users` (password hashes managed by Supabase)
  - `api_keys` (sha256 hashes of `vnt_...` keys)
  - `ai_events` and `usage_daily` (captured usage data)

### Step 2 — Optional: ClickHouse (for high-volume analytics)
- Provision cloud ClickHouse and set `CLICKHOUSE_HOST`, `CLICKHOUSE_PASSWORD`, `CLICKHOUSE_DATABASE` in `.env`.
- The backend will store events in ClickHouse (if configured) and also rollup tables in Supabase.

### Step 3 — Backend deployment
- Run locally: `uvicorn server.main:app --reload --port 8000`.
- Deploy to Render/Railway/Heroku using `render.yaml` or existing deployment config.
- Ensure your deployment has the same env vars as `.env` and can reach Supabase.

### Step 4 — Frontend deployment (Cloudflare Pages)
- Deploy `vantage-final-v4/` as a static site.
- Connect it to your repo and deploy.
- The UI will call the backend via the Settings flow (or URL query params).

### Step 5 — Configure the dashboard to talk to the backend
- In the dashboard UI (app.html) click **Settings**.
- Enter:
  - Backend base URL (no trailing `/`)
  - Vantage API key (`vnt_...`)
  - Org ID (auto-derives from key format `vnt_{org}_{id}`)

> Tip: Use query params if you want to bypass prompts:
> `app.html?api_base=https://your-backend&api_key=vnt_acme_...&org=acme`

---

## Testing & edge cases

### Backend test cases
- **Auth validation**: call `/v1/kpis/{org}` with missing/invalid `Authorization: Bearer` header.
- **Throttling**: send a large batch (>500 events) to `/v1/events` and verify it returns 400.
- **Event persistence**: post a valid event, then query `/v1/kpis/{org}` to confirm it appears.
- **Hallucination scoring**:
  - With `ANTHROPIC_API_KEY` set, ensure `quality_hallucination_score` is populated.
  - With `EVAL_ENABLED=false` (or missing key), ensure the heuristic fallback runs and score is not -1.
- **ClickHouse down**: stop ClickHouse and verify the service still runs (should log warnings, not crash).

### Frontend test cases
- **No backend configured**: open dashboard with no settings and confirm it falls back to demo data.
- **Invalid API key**: configure key that fails auth, verify dashboard shows errors and does not crash.
- **Missing org**: set `org` to a nonexistent org; dashboard should show empty/zero state.
- **Period selector**: change 7/30/90 days and validate charts update.
- **Settings persistence**: refresh page and confirm settings survive (stored in `localStorage`).

### Edge cases to validate
- **Large payloads**: send events with huge `request_preview`/`response_preview` and ensure backend accepts them (DB field limits).
- **Special characters**: ensure JSON and CSV exports (if any) handle unicode and newlines.
- **Partial failure**: send a mixed batch where half the events are invalid; backend should reject whole batch (currently it does).

---

## Hallucination scoring (master model & switching)

By default the backend uses **Claude Opus 4.6** for hallucination/quality scoring (via the Anthropic API).

### Change the model without editing code
A new environment variable lets you switch the evaluation model at runtime:

- `EVAL_MODEL` (default: `claude-opus-4-6`)

Example:
```bash
EVAL_MODEL=claude-opus-5-1 \
ANTHROPIC_API_KEY=sk-ant-... \
uvicorn server.main:app --reload
```

### If you want to hardcode a model (not recommended)
You can still change it in code (but this is no longer required):
- `vantage/analysis/hallucination.py` uses `EVAL_MODEL` as the model name.

### Disable hallucination scoring
- Set `EVAL_ENABLED=false` (the backend will skip Anthropic calls and use heuristics instead).

---

## Security & authentication notes

### Password storage
- User passwords are **not stored in this repo**.
- Authentication is handled by Supabase Auth, which stores passwords hashed (bcrypt/argon2) and never exposes the plaintext.

### API keys
- API keys (`vnt_...`) are stored in Supabase as **SHA-256 hashes** (see `server/main.py`).
- The backend validates keys by hashing the presented key and comparing to stored hash.
- **Do not commit** service role keys or API keys to source control.

### Frontend secrets
- The dashboard stores the `vnt_...` API key in `localStorage` to keep the UI working.
- Treat that key as sensitive the same way you would treat a session token.

---

## Next improvements (optional)

- Add a UI toggle to switch the hallucination evaluator model (Opus 4.6 → newer version).
- Add a formal test suite (pytest) covering key backend endpoints.
- Add RBAC to the dashboard (admin vs viewer).
- Add caching/in-memory rate limiting for `/v1/events` ingestion.
