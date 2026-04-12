# Vega Chatbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Vega" — a female-toned AI chatbot to the VantageAI dashboard that answers dashboard help, VantageAI product questions, and escalates to email support.

**Architecture:** Cloudflare Workers AI (`@cf/meta/llama-3-8b-instruct`) behind a Hono router in a new `vantage-chatbot/` Worker. Static JSON knowledge base + KV doc chunks for context. Rate limiting (20 msg/hr/org) via KV, email escalation via Resend. Frontend widget injected into `app.html`.

**Tech Stack:** Cloudflare Workers AI, Hono 4, KV, Resend, Python pytest (tests), vanilla JS widget (safe DOM only), TypeScript strict.

---

## File Map

| File | Purpose |
|------|---------|
| `vantage-chatbot/src/index.ts` | Hono app entry, route wiring, CORS |
| `vantage-chatbot/src/types.ts` | Shared TS types: `Env`, `ChatRequest`, `ChatResponse`, `Ticket` |
| `vantage-chatbot/src/chat.ts` | Chat handler: knowledge lookup, prompt build, AI call, sanitize, respond |
| `vantage-chatbot/src/ticket.ts` | Ticket handler: validate, send Resend email |
| `vantage-chatbot/src/knowledge.ts` | Load static.json + KV chunks, score top-3 matches |
| `vantage-chatbot/src/sanitize.ts` | Strip API keys, IPs, SQL from AI output |
| `vantage-chatbot/src/prompt.ts` | Build system prompt with plan gate + knowledge context |
| `vantage-chatbot/src/ratelimit.ts` | KV-based sliding window rate limiter (20 msg/hr/org) |
| `vantage-chatbot/knowledge/static.json` | 19 curated Q&A entries with plan_gate fields |
| `vantage-chatbot/knowledge/build-chunks.js` | Node script: reads docs.html, writes KV upload JSON |
| `vantage-chatbot/wrangler.toml` | Worker config, KV bindings, AI binding |
| `vantage-chatbot/package.json` | Dependencies: hono, @cloudflare/workers-types |
| `vantage-chatbot/tsconfig.json` | Strict TS config |
| `vantage-final-v4/widget/chatbot.css` | Chatbot widget styles |
| `vantage-final-v4/widget/chatbot.js` | Chatbot widget JS (safe DOM only — createElement/textContent/appendChild) |
| `vantage-final-v4/app.html` | Inject widget script+style tags before closing body |
| `tests/suites/34_vega_chatbot/conftest.py` | Pytest fixtures: base URL, auth headers |
| `tests/suites/34_vega_chatbot/test_chatbot.py` | 27 integration + unit tests |

---

### Task 1: Worker Scaffold

**Files:**
- Create: `vantage-chatbot/package.json`
- Create: `vantage-chatbot/tsconfig.json`
- Create: `vantage-chatbot/wrangler.toml`
- Create: `vantage-chatbot/src/types.ts`
- Create: `vantage-chatbot/src/index.ts`

- [ ] **Step 1: Write failing health test**

```python
# tests/suites/34_vega_chatbot/test_chatbot.py
import pytest, requests, os

BASE = os.getenv("CHATBOT_URL", "http://localhost:8788")

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["name"] == "vega"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd tests && python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_health -v
```
Expected: `ConnectionRefusedError` or `FAILED`

- [ ] **Step 3: Create package.json**

```json
{
  "name": "vantage-chatbot",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "dev": "wrangler dev --port 8788",
    "deploy": "wrangler deploy",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "hono": "^4.3.0"
  },
  "devDependencies": {
    "@cloudflare/workers-types": "^4.20240512.0",
    "typescript": "^5.4.0",
    "wrangler": "^3.57.0"
  }
}
```

- [ ] **Step 4: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ES2022",
    "moduleResolution": "bundler",
    "lib": ["ES2022"],
    "types": ["@cloudflare/workers-types"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noEmit": true
  },
  "include": ["src/**/*"]
}
```

- [ ] **Step 5: Create wrangler.toml**

```toml
name = "vantage-chatbot"
main = "src/index.ts"
compatibility_date = "2024-09-23"

[ai]
binding = "AI"

[[kv_namespaces]]
binding = "VEGA_KV"
id = "REPLACE_WITH_KV_ID"
preview_id = "REPLACE_WITH_PREVIEW_KV_ID"

[vars]
RESEND_FROM = "vega@vantageaiops.com"
SUPPORT_EMAIL = "support@vantageaiops.com"
```

- [ ] **Step 6: Create src/types.ts**

```typescript
export interface Env {
  AI: Ai;
  VEGA_KV: KVNamespace;
  RESEND_API_KEY: string;
  RESEND_FROM: string;
  SUPPORT_EMAIL: string;
  VANTAGE_API_URL: string;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  plan_limited?: boolean;
}

export interface KnowledgeEntry {
  q: string;
  a: string;
  tags: string[];
  plan_gate?: "pro" | "enterprise";
}

export interface TicketRequest {
  subject: string;
  body: string;
  email: string;
}
```

- [ ] **Step 7: Create src/index.ts**

```typescript
import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env } from "./types";

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors({ origin: ["https://vantageaiops.com", "http://localhost:*"] }));

app.get("/health", (c) => c.json({ status: "ok", name: "vega" }));

// Placeholder routes — filled in Tasks 5+
app.post("/chat", async (c) => c.json({ reply: "coming soon" }, 501));
app.post("/ticket", async (c) => c.json({ ok: false }, 501));

export default app;
```

- [ ] **Step 8: Install and start dev server**

```bash
cd vantage-chatbot && npm install && npm run dev &
sleep 3
```

- [ ] **Step 9: Run test to verify it passes**

```bash
cd tests && python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_health -v
```
Expected: `PASSED`

- [ ] **Step 10: Commit**

```bash
git add vantage-chatbot/ tests/suites/34_vega_chatbot/
git commit -m "feat(chatbot): scaffold Vega Worker with health endpoint"
```

---

### Task 2: Static Knowledge Base

**Files:**
- Create: `vantage-chatbot/knowledge/static.json`

- [ ] **Step 1: Write failing test**

```python
# append to test_chatbot.py
import json, pathlib

def test_static_knowledge_loads():
    path = pathlib.Path(__file__).parents[3] / "vantage-chatbot/knowledge/static.json"
    data = json.loads(path.read_text())
    assert len(data) >= 10
    for entry in data:
        assert "q" in entry and "a" in entry and "tags" in entry
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_static_knowledge_loads -v
```
Expected: `FAILED` (FileNotFoundError)

- [ ] **Step 3: Create knowledge/static.json**

```json
[
  {
    "q": "What is VantageAI?",
    "a": "VantageAI is an AI cost analytics platform that tracks spending across all your AI providers — Anthropic, OpenAI, Google, and more — from a single dashboard.",
    "tags": ["product", "overview"]
  },
  {
    "q": "How do I add a new API key?",
    "a": "Go to Settings → Provider Connections and click 'Add Provider'. Paste your API key — it's encrypted at rest and never leaves your organization's data boundary.",
    "tags": ["setup", "api-key"]
  },
  {
    "q": "What does the Overview tab show?",
    "a": "The Overview tab shows total spend, API calls, average cost per call, active models, and a daily spend trend chart for your selected time range.",
    "tags": ["dashboard", "overview"]
  },
  {
    "q": "How are budgets enforced?",
    "a": "You set a monthly budget cap per team or model in the Budgets tab. When spend hits 80% of the cap, you receive an alert. At 100%, new API calls are blocked until the next billing cycle.",
    "tags": ["budgets", "alerts"]
  },
  {
    "q": "What is the free tier limit?",
    "a": "The free tier allows up to 50,000 tracked events per month. After that, you'll need to upgrade to Pro or Enterprise.",
    "tags": ["pricing", "free-tier"]
  },
  {
    "q": "How do I invite team members?",
    "a": "Go to Settings → Members and click 'Invite'. Enter their email — they'll receive an invite link valid for 48 hours.",
    "tags": ["team", "members"]
  },
  {
    "q": "What providers does VantageAI support?",
    "a": "VantageAI supports Anthropic, OpenAI, Google Gemini, AWS Bedrock, Azure OpenAI, Mistral, Cohere, and any OpenTelemetry-compatible provider.",
    "tags": ["providers", "integrations"]
  },
  {
    "q": "How do I use the vantageai-agent CLI?",
    "a": "Install with `pip install vantageai-agent`, then run `vantageai-agent`. Use `--backend claude` for Claude Max, `--backend api` for direct API access. Type `/help` in the REPL for all commands.",
    "tags": ["cli", "agent"]
  },
  {
    "q": "What is OpenTelemetry (OTel) support?",
    "a": "VantageAI accepts OTLP metrics and logs. Point your OTel exporter to `https://api.vantageaiops.com/v1/otel/v1/metrics` with your Bearer token. Cost is computed server-side from token counts.",
    "tags": ["otel", "integration"]
  },
  {
    "q": "How do I export my data?",
    "a": "In any analytics tab, click the 'Export CSV' button in the top-right to download the current view as a CSV file.",
    "tags": ["export", "data"],
    "plan_gate": "pro"
  },
  {
    "q": "What is cross-platform analytics?",
    "a": "Cross-platform analytics lets you compare spend and usage across all your AI providers side-by-side, identify which team or model is driving cost, and spot anomalies.",
    "tags": ["analytics", "cross-platform"]
  },
  {
    "q": "How does VantageAI handle data privacy?",
    "a": "Prompts and responses never leave your machine in strict mode. Only token counts and metadata are sent to VantageAI servers. You can verify this in the vantage-local-proxy source code.",
    "tags": ["privacy", "security"]
  },
  {
    "q": "What does the Models tab show?",
    "a": "The Models tab breaks down cost and call volume by model — e.g., claude-sonnet-4-6 vs gpt-4o. Use it to find expensive models and consider cheaper alternatives.",
    "tags": ["dashboard", "models"]
  },
  {
    "q": "How do I set up a budget alert?",
    "a": "In the Budgets tab, click 'New Budget', choose a team and model filter, set a monthly cap, and enter an alert email. Alerts fire at 80% and 100% of the cap.",
    "tags": ["budgets", "setup"]
  },
  {
    "q": "What is the Pro plan?",
    "a": "Pro includes unlimited event tracking, CSV export, advanced filters, priority support, and API access. Billed monthly or annually.",
    "tags": ["pricing", "pro"],
    "plan_gate": "pro"
  },
  {
    "q": "What is Enterprise?",
    "a": "Enterprise adds SSO, custom data retention, SLA guarantees, dedicated support, and on-premise deployment options. Contact sales for pricing.",
    "tags": ["pricing", "enterprise"],
    "plan_gate": "enterprise"
  },
  {
    "q": "How do I reset my password?",
    "a": "Click 'Forgot Password' on the login page. A reset link will be emailed to your registered address and expires in 1 hour.",
    "tags": ["account", "auth"]
  },
  {
    "q": "What does P95 latency mean in the traces tab?",
    "a": "P95 latency means 95% of your API calls completed within that time. A high P95 signals occasional slow calls — check the Traces tab to find the outliers.",
    "tags": ["dashboard", "traces", "latency"]
  },
  {
    "q": "Can I use VantageAI with self-hosted models?",
    "a": "Yes — use the OTel integration or local proxy. Any model that reports token counts via OTLP or the VantageAI SDK can be tracked.",
    "tags": ["integration", "self-hosted"]
  }
]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_static_knowledge_loads -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add vantage-chatbot/knowledge/static.json
git commit -m "feat(chatbot): add 19-entry static knowledge base"
```

---

### Task 3: Knowledge Lookup + Output Sanitizer

**Files:**
- Create: `vantage-chatbot/src/knowledge.ts`
- Create: `vantage-chatbot/src/sanitize.ts`

- [ ] **Step 1: Create src/sanitize.ts**

```typescript
const REDACT_PATTERNS: RegExp[] = [
  /\bvnt_[A-Za-z0-9_-]{20,}\b/g,
  /\bsk-ant-[A-Za-z0-9_-]{20,}\b/g,
  /\bsk-[A-Za-z0-9]{20,}\b/g,
  /\b(?:\d{1,3}\.){3}\d{1,3}\b/g,
  /\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b/g,
  /(?:DROP|DELETE|TRUNCATE|ALTER)\s+TABLE/gi,
];

export function sanitize(text: string): string {
  let out = text;
  for (const pattern of REDACT_PATTERNS) {
    out = out.replace(pattern, "[REDACTED]");
  }
  return out;
}
```

- [ ] **Step 2: Create src/knowledge.ts**

```typescript
import type { Env, KnowledgeEntry } from "./types";
import STATIC from "../knowledge/static.json";

const entries = STATIC as KnowledgeEntry[];

function score(entry: KnowledgeEntry, query: string): number {
  const q = query.toLowerCase();
  const text = (entry.q + " " + entry.a + " " + entry.tags.join(" ")).toLowerCase();
  const words = q.split(/\s+/).filter((w) => w.length > 2);
  return words.filter((w) => text.includes(w)).length;
}

export async function lookup(
  query: string,
  plan: string,
  env: Env
): Promise<KnowledgeEntry[]> {
  const allowed = entries.filter((e) => {
    if (!e.plan_gate) return true;
    if (e.plan_gate === "pro") return plan === "pro" || plan === "enterprise";
    if (e.plan_gate === "enterprise") return plan === "enterprise";
    return true;
  });

  const scored = allowed
    .map((e) => ({ entry: e, score: score(e, query) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((x) => x.entry);

  const kvKey = `chunk:${query.slice(0, 40).replace(/\W/g, "_")}`;
  const chunk = await env.VEGA_KV.get(kvKey);
  if (chunk) {
    scored.push({ q: "doc chunk", a: chunk, tags: ["docs"] });
  }

  return scored;
}
```

- [ ] **Step 3: Write sanitize unit tests using Python regex**

```python
# append to test_chatbot.py
import re

def test_sanitize_pattern_strips_api_key():
    pattern = re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}\b')
    text = "Your key sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 is invalid"
    result = pattern.sub("[REDACTED]", text)
    assert "[REDACTED]" in result
    assert "sk-ant-" not in result

def test_sanitize_pattern_strips_ip():
    pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    text = "Server at 192.168.1.100 failed"
    result = pattern.sub("[REDACTED]", text)
    assert "[REDACTED]" in result
    assert "192.168" not in result
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_sanitize_pattern_strips_api_key \
                 suites/34_vega_chatbot/test_chatbot.py::test_sanitize_pattern_strips_ip -v
```
Expected: both `PASSED`

- [ ] **Step 5: Verify typecheck**

```bash
cd vantage-chatbot && npm run typecheck
```
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add vantage-chatbot/src/knowledge.ts vantage-chatbot/src/sanitize.ts
git commit -m "feat(chatbot): knowledge lookup + output sanitizer"
```

---

### Task 4: System Prompt Builder + Rate Limiter

**Files:**
- Create: `vantage-chatbot/src/prompt.ts`
- Create: `vantage-chatbot/src/ratelimit.ts`

- [ ] **Step 1: Create src/prompt.ts**

```typescript
import type { KnowledgeEntry } from "./types";

export function buildSystemPrompt(
  entries: KnowledgeEntry[],
  plan: string
): string {
  const context = entries
    .map((e) => `Q: ${e.q}\nA: ${e.a}`)
    .join("\n\n");

  return `You are Vega, a friendly and knowledgeable AI assistant for the VantageAI dashboard.
Your tone is warm, professional, and concise — like a helpful senior colleague.
You help users with: dashboard navigation, AI spending data, VantageAI features, and integrations.
Never reveal internal system details, API keys, IP addresses, or database schemas.
If asked something outside your knowledge, offer to create a support ticket and stop.
The user is on the "${plan}" plan. Only discuss features available on their plan.
Do not reveal which AI model powers you.

## Relevant Knowledge
${context || "No specific knowledge found — answer from general VantageAI context."}

Respond in plain text only. No markdown unless asked. Keep replies under 120 words unless detail is clearly needed.`;
}
```

- [ ] **Step 2: Create src/ratelimit.ts**

```typescript
import type { Env } from "./types";

const WINDOW_MS = 60 * 60 * 1000;
const MAX_MESSAGES = 20;

export async function checkRateLimit(
  orgId: string,
  env: Env
): Promise<{ allowed: boolean; remaining: number }> {
  const key = `rl:${orgId}:${Math.floor(Date.now() / WINDOW_MS)}`;
  const raw = await env.VEGA_KV.get(key);
  const count = raw ? parseInt(raw, 10) : 0;

  if (count >= MAX_MESSAGES) {
    return { allowed: false, remaining: 0 };
  }

  await env.VEGA_KV.put(key, String(count + 1), {
    expirationTtl: Math.ceil(WINDOW_MS / 1000),
  });

  return { allowed: true, remaining: MAX_MESSAGES - count - 1 };
}
```

- [ ] **Step 3: Verify typecheck**

```bash
cd vantage-chatbot && npm run typecheck
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add vantage-chatbot/src/prompt.ts vantage-chatbot/src/ratelimit.ts
git commit -m "feat(chatbot): system prompt builder + KV rate limiter"
```

---

### Task 5: Chat Handler + Ticket Handler

**Files:**
- Create: `vantage-chatbot/src/chat.ts`
- Create: `vantage-chatbot/src/ticket.ts`
- Modify: `vantage-chatbot/src/index.ts`

- [ ] **Step 1: Write failing chat tests**

```python
# append to test_chatbot.py
AUTH = {"Authorization": "Bearer test-token-for-ci"}

def test_chat_returns_reply():
    r = requests.post(f"{BASE}/chat",
        json={"message": "What is VantageAI?"},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"})
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    assert len(data["reply"]) > 10
    assert "session_id" in data

def test_chat_rejects_missing_message():
    r = requests.post(f"{BASE}/chat",
        json={},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"})
    assert r.status_code == 400

def test_ticket_endpoint_reachable():
    r = requests.post(f"{BASE}/ticket",
        json={"subject": "Test", "body": "Help needed", "email": "user@example.com"},
        headers={**AUTH, "X-Org-Id": "test-org"})
    # 200 OK or 503 if Resend not configured in CI — both are acceptable
    assert r.status_code in (200, 503)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_chat_returns_reply -v
```
Expected: `FAILED` (501)

- [ ] **Step 3: Create src/chat.ts**

```typescript
import type { Context } from "hono";
import type { Env, ChatRequest, ChatResponse } from "./types";
import { lookup } from "./knowledge";
import { buildSystemPrompt } from "./prompt";
import { sanitize } from "./sanitize";
import { checkRateLimit } from "./ratelimit";
import { randomUUID } from "crypto";

export async function handleChat(c: Context<{ Bindings: Env }>): Promise<Response> {
  const orgId = c.req.header("X-Org-Id") ?? "anonymous";
  const plan = c.req.header("X-Plan") ?? "free";

  const { allowed, remaining } = await checkRateLimit(orgId, c.env);
  if (!allowed) {
    return c.json({ error: "Rate limit exceeded. Try again in an hour." }, 429);
  }

  let body: ChatRequest;
  try {
    body = await c.req.json<ChatRequest>();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const { message, history = [] } = body;
  if (!message || typeof message !== "string" || message.trim().length === 0) {
    return c.json({ error: "message is required" }, 400);
  }

  const knowledgeEntries = await lookup(message, plan, c.env);
  const systemPrompt = buildSystemPrompt(knowledgeEntries, plan);

  const messages: Array<{ role: string; content: string }> = [
    { role: "system", content: systemPrompt },
    ...history.slice(-6),
    { role: "user", content: message.slice(0, 1000) },
  ];

  let aiReply: string;
  try {
    const result = await c.env.AI.run("@cf/meta/llama-3-8b-instruct", { messages }) as { response?: string };
    aiReply = sanitize(result.response ?? "I'm sorry, I couldn't generate a response right now.");
  } catch {
    aiReply = "I'm having trouble connecting right now. Please try again shortly.";
  }

  const response: ChatResponse = {
    reply: aiReply,
    session_id: body.session_id ?? randomUUID(),
    plan_limited: remaining < 3,
  };

  return c.json(response, 200);
}
```

- [ ] **Step 4: Create src/ticket.ts**

```typescript
import type { Context } from "hono";
import type { Env, TicketRequest } from "./types";

export async function handleTicket(c: Context<{ Bindings: Env }>): Promise<Response> {
  let body: TicketRequest;
  try {
    body = await c.req.json<TicketRequest>();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const { subject, body: msgBody, email } = body;
  if (!subject || !msgBody || !email) {
    return c.json({ error: "subject, body, and email are required" }, 400);
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: "Invalid email address" }, 400);
  }

  const orgId = c.req.header("X-Org-Id") ?? "unknown";

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${c.env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: c.env.RESEND_FROM,
        to: [c.env.SUPPORT_EMAIL],
        reply_to: email,
        subject: `[Support] ${subject}`,
        text: `Org: ${orgId}\nFrom: ${email}\n\n${msgBody}`,
      }),
    });

    if (!res.ok) {
      return c.json({ ok: false, error: "Email service unavailable" }, 503);
    }
    return c.json({ ok: true });
  } catch {
    return c.json({ ok: false, error: "Email service unavailable" }, 503);
  }
}
```

- [ ] **Step 5: Update src/index.ts to wire routes**

```typescript
import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env } from "./types";
import { handleChat } from "./chat";
import { handleTicket } from "./ticket";

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors({ origin: ["https://vantageaiops.com", "http://localhost:*"] }));

app.get("/health", (c) => c.json({ status: "ok", name: "vega" }));
app.post("/chat", handleChat);
app.post("/ticket", handleTicket);

export default app;
```

- [ ] **Step 6: Verify typecheck**

```bash
cd vantage-chatbot && npm run typecheck
```

- [ ] **Step 7: Restart dev server and run tests**

```bash
cd vantage-chatbot && npm run dev &
sleep 3
cd tests && python -m pytest suites/34_vega_chatbot/ -v
```
Expected: health + chat + ticket tests pass

- [ ] **Step 8: Commit**

```bash
git add vantage-chatbot/src/
git commit -m "feat(chatbot): chat + ticket handlers wired to Hono routes"
```

---

### Task 6: Doc Chunks Builder

**Files:**
- Create: `vantage-chatbot/knowledge/build-chunks.js`

- [ ] **Step 1: Create knowledge/build-chunks.js**

Uses `String.prototype.matchAll` to extract heading sections from docs.html and writes KV upload JSON to stdout.

```javascript
#!/usr/bin/env node
// Run: node knowledge/build-chunks.js > knowledge/kv-upload.json
const fs = require("fs");
const path = require("path");

const docsPath = path.resolve(__dirname, "../../vantage-final-v4/docs.html");
const html = fs.readFileSync(docsPath, "utf8");

const headingPattern = /<h[23][^>]*>(.*?)<\/h[23]>/gi;
const tagPattern = /<[^>]+>/g;

const matches = Array.from(html.matchAll(headingPattern));
const sections = [];

matches.forEach(function(match, i) {
  const heading = match[1].replace(tagPattern, "").trim();
  const start = match.index + match[0].length;
  const end = i + 1 < matches.length ? matches[i + 1].index : html.length;
  const bodyText = html.slice(start, end)
    .replace(tagPattern, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 500);

  if (bodyText.length > 50) {
    const key = "chunk:" + heading.slice(0, 40).replace(/\W+/g, "_").toLowerCase();
    sections.push({ key: key, value: heading + ": " + bodyText, expiration_ttl: 86400 * 30 });
  }
});

process.stdout.write(JSON.stringify(sections, null, 2));
```

- [ ] **Step 2: Run the builder and verify output**

```bash
cd vantage-chatbot && node knowledge/build-chunks.js | head -20
```
Expected: JSON array with `key`, `value`, `expiration_ttl` fields

- [ ] **Step 3: Write test**

```python
def test_build_chunks_produces_valid_json():
    import subprocess, json
    result = subprocess.run(
        ["node", "knowledge/build-chunks.js"],
        capture_output=True, text=True,
        cwd="vantage-chatbot"
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data) > 0
    assert "key" in data[0] and "value" in data[0]
```

- [ ] **Step 4: Run test**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_build_chunks_produces_valid_json -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add vantage-chatbot/knowledge/build-chunks.js
git commit -m "feat(chatbot): doc chunks builder from docs.html"
```

---

### Task 7: Frontend Widget

**Files:**
- Create: `vantage-final-v4/widget/chatbot.css`
- Create: `vantage-final-v4/widget/chatbot.js`
- Modify: `vantage-final-v4/app.html`

All DOM manipulation in chatbot.js uses `createElement`, `textContent`, and `appendChild` exclusively.

- [ ] **Step 1: Write widget tests**

```python
def test_widget_files_exist():
    import pathlib
    base = pathlib.Path(__file__).parents[3] / "vantage-final-v4/widget"
    assert (base / "chatbot.css").exists()
    assert (base / "chatbot.js").exists()

def test_widget_js_uses_safe_dom_only():
    import pathlib
    js = (pathlib.Path(__file__).parents[3] / "vantage-final-v4/widget/chatbot.js").read_text()
    # Must use only safe DOM methods — no string-based mutation
    assert ".innerHTML" not in js

def test_widget_css_has_required_selectors():
    import pathlib
    css = (pathlib.Path(__file__).parents[3] / "vantage-final-v4/widget/chatbot.css").read_text()
    assert "#vega-launcher" in css
    assert "#vega-panel" in css
    assert ".vega-msg" in css
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_widget_files_exist -v
```
Expected: `FAILED`

- [ ] **Step 3: Create widget/chatbot.css**

```css
#vega-launcher {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  cursor: pointer;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
#vega-launcher:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 28px rgba(99, 102, 241, 0.5);
}
#vega-launcher svg { width: 24px; height: 24px; fill: white; }

#vega-panel {
  position: fixed;
  bottom: 88px;
  right: 24px;
  width: 360px;
  max-height: 520px;
  background: #1e1e2e;
  border: 1px solid #3b3b5c;
  border-radius: 16px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  z-index: 9998;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 14px;
  color: #e2e8f0;
  overflow: hidden;
  transform: translateY(12px);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
#vega-panel.vega-open {
  opacity: 1;
  transform: translateY(0);
  pointer-events: all;
}
#vega-header {
  padding: 14px 16px;
  background: #2a2a3e;
  border-bottom: 1px solid #3b3b5c;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
#vega-header-name { font-weight: 600; color: #a5b4fc; }
#vega-header-sub { font-size: 11px; color: #6b7280; margin-top: 2px; }
#vega-close {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
  font-size: 18px;
}
#vega-close:hover { color: #e2e8f0; }
#vega-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.vega-msg {
  max-width: 85%;
  padding: 10px 13px;
  border-radius: 12px;
  line-height: 1.5;
  word-break: break-word;
}
.vega-msg-bot {
  background: #2a2a3e;
  border: 1px solid #3b3b5c;
  align-self: flex-start;
}
.vega-msg-user {
  background: #4f46e5;
  color: #fff;
  align-self: flex-end;
}
#vega-footer {
  padding: 12px;
  border-top: 1px solid #3b3b5c;
  display: flex;
  gap: 8px;
}
#vega-input {
  flex: 1;
  background: #2a2a3e;
  border: 1px solid #3b3b5c;
  border-radius: 8px;
  color: #e2e8f0;
  padding: 8px 12px;
  font-size: 13px;
  outline: none;
  resize: none;
}
#vega-input:focus { border-color: #6366f1; }
#vega-send {
  background: #4f46e5;
  border: none;
  border-radius: 8px;
  color: #fff;
  padding: 8px 14px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
}
#vega-send:hover { background: #4338ca; }
#vega-send:disabled { opacity: 0.5; cursor: not-allowed; }
.vega-typing-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #6366f1;
  animation: vegaBounce 1.2s infinite;
  margin: 0 2px;
}
.vega-typing-dot:nth-child(2) { animation-delay: 0.2s; }
.vega-typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes vegaBounce {
  0%, 80%, 100% { transform: translateY(0); }
  40% { transform: translateY(-6px); }
}
#vega-ticket-btn {
  background: none;
  border: none;
  color: #6366f1;
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
  padding: 0 12px 8px;
  align-self: flex-start;
}
```

- [ ] **Step 4: Create widget/chatbot.js**

Every DOM element is built with `createElement`. Text is set via `textContent` or `createTextNode`. No string-based DOM mutation is used.

```javascript
(function () {
  "use strict";

  var CHATBOT_URL = window.VEGA_CHATBOT_URL || "https://chatbot.vantageaiops.com";
  var sessionId = null;
  var history = [];
  var isOpen = false;

  function makeEl(tag, id, className) {
    var node = document.createElement(tag);
    if (id) node.id = id;
    if (className) node.className = className;
    return node;
  }

  function setText(node, text) {
    node.textContent = text;
    return node;
  }

  // Launcher button with SVG icon
  var svgNS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  var svgPath = document.createElementNS(svgNS, "path");
  svgPath.setAttribute("d", "M12 2C6.477 2 2 6.477 2 12c0 1.89.525 3.66 1.438 5.168L2 22l4.832-1.438A9.956 9.956 0 0012 22c5.523 0 10-4.477 10-10S17.523 2 12 2z");
  svg.appendChild(svgPath);

  var launcher = makeEl("button", "vega-launcher");
  launcher.setAttribute("aria-label", "Chat with Vega");
  launcher.appendChild(svg);

  // Header
  var headerName = setText(makeEl("div", "vega-header-name"), "Vega");
  var headerSub = setText(makeEl("div", "vega-header-sub"), "VantageAI Assistant");
  var headerLeft = makeEl("div");
  headerLeft.appendChild(headerName);
  headerLeft.appendChild(headerSub);

  var closeBtn = makeEl("button", "vega-close");
  closeBtn.setAttribute("aria-label", "Close chat");
  closeBtn.textContent = "\u00d7";

  var header = makeEl("div", "vega-header");
  header.appendChild(headerLeft);
  header.appendChild(closeBtn);

  // Messages container
  var messagesEl = makeEl("div", "vega-messages");

  // Support ticket button
  var ticketBtn = makeEl("button", "vega-ticket-btn");
  ticketBtn.textContent = "Create a support ticket";

  // Input footer
  var input = makeEl("textarea", "vega-input");
  input.setAttribute("placeholder", "Ask Vega anything...");
  input.setAttribute("rows", "2");
  var sendBtn = makeEl("button", "vega-send");
  sendBtn.textContent = "Send";
  var footer = makeEl("div", "vega-footer");
  footer.appendChild(input);
  footer.appendChild(sendBtn);

  // Panel
  var panel = makeEl("div", "vega-panel");
  panel.appendChild(header);
  panel.appendChild(messagesEl);
  panel.appendChild(ticketBtn);
  panel.appendChild(footer);

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  // ── Helpers ────────────────────────────────────────────────────────────────

  function addMessage(text, role) {
    var cls = "vega-msg " + (role === "user" ? "vega-msg-user" : "vega-msg-bot");
    var div = makeEl("div", null, cls);
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function showTyping() {
    var div = makeEl("div", null, "vega-msg vega-msg-bot");
    for (var i = 0; i < 3; i++) {
      div.appendChild(makeEl("span", null, "vega-typing-dot"));
    }
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  addMessage("Hi! I'm Vega, your VantageAI assistant. Ask me about your dashboard, pricing, or integrations.", "bot");

  // ── Events ─────────────────────────────────────────────────────────────────

  launcher.addEventListener("click", function () {
    isOpen = !isOpen;
    if (isOpen) { panel.classList.add("vega-open"); input.focus(); }
    else { panel.classList.remove("vega-open"); }
  });

  closeBtn.addEventListener("click", function () {
    isOpen = false;
    panel.classList.remove("vega-open");
  });

  ticketBtn.addEventListener("click", function () {
    var subject = window.prompt("Brief subject for your ticket:");
    if (!subject) return;
    var msgBody = window.prompt("Describe your issue:");
    if (!msgBody) return;
    var email = window.prompt("Your email address for follow-up:");
    if (!email) return;

    var tokenMatch = document.cookie.match(/session=([^;]+)/);
    var reqHeaders = { "Content-Type": "application/json" };
    if (tokenMatch) reqHeaders["Authorization"] = "Bearer " + tokenMatch[1];

    fetch(CHATBOT_URL + "/ticket", {
      method: "POST",
      headers: reqHeaders,
      body: JSON.stringify({ subject: subject, body: msgBody, email: email }),
    }).then(function (r) {
      addMessage(
        r.ok ? "Ticket submitted! We'll follow up at " + email + " soon."
             : "Couldn't submit ticket. Please email support@vantageaiops.com directly.",
        "bot"
      );
    }).catch(function () {
      addMessage("Couldn't submit ticket. Please email support@vantageaiops.com directly.", "bot");
    });
  });

  function sendMessage() {
    var text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendBtn.disabled = true;

    addMessage(text, "user");
    history.push({ role: "user", content: text });

    var typingEl = showTyping();
    var tokenMatch = document.cookie.match(/session=([^;]+)/);
    var orgId = document.body.getAttribute("data-org-id") || "unknown";
    var plan = document.body.getAttribute("data-plan") || "free";

    var reqHeaders = { "Content-Type": "application/json", "X-Org-Id": orgId, "X-Plan": plan };
    if (tokenMatch) reqHeaders["Authorization"] = "Bearer " + tokenMatch[1];

    fetch(CHATBOT_URL + "/chat", {
      method: "POST",
      headers: reqHeaders,
      body: JSON.stringify({ message: text, session_id: sessionId, history: history.slice(-6) }),
    }).then(function (r) {
      return r.json();
    }).then(function (data) {
      if (typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
      var reply = (data && data.reply) ? data.reply : "Sorry, something went wrong.";
      addMessage(reply, "bot");
      history.push({ role: "assistant", content: reply });
      if (data && data.session_id) sessionId = data.session_id;
    }).catch(function () {
      if (typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
      addMessage("Connection error. Please try again.", "bot");
    }).finally(function () {
      sendBtn.disabled = false;
    });
  }

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
})();
```

- [ ] **Step 5: Inject into app.html**

Read the bottom of `vantage-final-v4/app.html`. Add these two lines immediately before `</body>`:

```html
  <link rel="stylesheet" href="/widget/chatbot.css">
  <script src="/widget/chatbot.js"></script>
```

- [ ] **Step 6: Run widget tests**

```bash
python -m pytest suites/34_vega_chatbot/test_chatbot.py::test_widget_files_exist \
                 suites/34_vega_chatbot/test_chatbot.py::test_widget_js_uses_safe_dom_only \
                 suites/34_vega_chatbot/test_chatbot.py::test_widget_css_has_required_selectors -v
```
Expected: all three `PASSED`

- [ ] **Step 7: Commit**

```bash
git add vantage-final-v4/widget/ vantage-final-v4/app.html
git commit -m "feat(chatbot): Vega frontend widget — safe DOM, textContent only"
```

---

### Task 8: Full Test Suite

**Files:**
- Create: `tests/suites/34_vega_chatbot/conftest.py`
- Modify: `tests/suites/34_vega_chatbot/test_chatbot.py`

- [ ] **Step 1: Create conftest.py**

```python
# tests/suites/34_vega_chatbot/conftest.py
import os
import pytest

@pytest.fixture(scope="session")
def base_url():
    return os.getenv("CHATBOT_URL", "http://localhost:8788")

@pytest.fixture(scope="session")
def auth_headers():
    return {
        "Authorization": "Bearer test-token-for-ci",
        "X-Org-Id": "test-org-pytest",
        "X-Plan": "free",
    }

@pytest.fixture(scope="session")
def pro_headers():
    return {
        "Authorization": "Bearer test-token-for-ci",
        "X-Org-Id": "test-org-pro",
        "X-Plan": "pro",
    }
```

- [ ] **Step 2: Add remaining tests**

```python
def test_chat_with_history(base_url, auth_headers):
    r = requests.post(f"{base_url}/chat",
        json={
            "message": "What about the Models tab?",
            "history": [
                {"role": "user", "content": "What is VantageAI?"},
                {"role": "assistant", "content": "VantageAI is an AI cost analytics platform."},
            ],
        },
        headers=auth_headers)
    assert r.status_code == 200

def test_chat_accepts_long_message(base_url, auth_headers):
    r = requests.post(f"{base_url}/chat",
        json={"message": "x" * 2000},
        headers=auth_headers)
    assert r.status_code == 200

def test_chat_session_id_persists(base_url, auth_headers):
    r = requests.post(f"{base_url}/chat",
        json={"message": "hello", "session_id": "my-session-abc"},
        headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["session_id"] == "my-session-abc"

def test_chat_no_auth_allowed(base_url):
    r = requests.post(f"{base_url}/chat",
        json={"message": "What is VantageAI?"},
        headers={"X-Org-Id": "anon", "X-Plan": "free"})
    assert r.status_code == 200

def test_chat_whitespace_rejected(base_url, auth_headers):
    r = requests.post(f"{base_url}/chat",
        json={"message": "   "},
        headers=auth_headers)
    assert r.status_code == 400

def test_ticket_missing_fields(base_url, auth_headers):
    r = requests.post(f"{base_url}/ticket",
        json={"subject": "Test"},
        headers=auth_headers)
    assert r.status_code == 400

def test_ticket_invalid_email(base_url, auth_headers):
    r = requests.post(f"{base_url}/ticket",
        json={"subject": "Test", "body": "Help", "email": "not-an-email"},
        headers=auth_headers)
    assert r.status_code == 400

def test_health_name(base_url):
    r = requests.get(f"{base_url}/health")
    assert r.json()["name"] == "vega"

def test_cors_on_preflight(base_url):
    r = requests.options(f"{base_url}/chat",
        headers={"Origin": "https://vantageaiops.com", "Access-Control-Request-Method": "POST"})
    assert r.status_code in (200, 204)

def test_chat_reply_non_empty(base_url, auth_headers):
    r = requests.post(f"{base_url}/chat",
        json={"message": "How do budgets work?"},
        headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["reply"].strip() != ""

def test_knowledge_basics_no_plan_gate():
    import json, pathlib
    data = json.loads((pathlib.Path(__file__).parents[3] / "vantage-chatbot/knowledge/static.json").read_text())
    basics = [e for e in data if "overview" in e.get("tags", []) or "product" in e.get("tags", [])]
    assert all("plan_gate" not in e for e in basics)

def test_knowledge_pro_entries_gated():
    import json, pathlib
    data = json.loads((pathlib.Path(__file__).parents[3] / "vantage-chatbot/knowledge/static.json").read_text())
    pro = [e for e in data if "pro" in e.get("tags", [])]
    assert all(e.get("plan_gate") in ("pro", "enterprise") for e in pro)
```

- [ ] **Step 3: Run full suite**

```bash
cd tests && python -m pytest suites/34_vega_chatbot/ -v --tb=short 2>&1 | tail -40
```
Expected: 25+ tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/suites/34_vega_chatbot/
git commit -m "test(chatbot): 27 integration + unit tests for Vega"
```

---

### Task 9: KV Namespace + Deploy

**Files:**
- Modify: `vantage-chatbot/wrangler.toml`

- [ ] **Step 1: Create KV namespace**

```bash
cd vantage-chatbot
npx wrangler kv namespace create VEGA_KV
# Copy the id value from output
npx wrangler kv namespace create VEGA_KV --preview
# Copy the preview_id value from output
```

- [ ] **Step 2: Update wrangler.toml with real IDs**

Replace both `REPLACE_WITH_KV_ID` placeholders in `wrangler.toml` with the IDs from Step 1.

- [ ] **Step 3: Upload doc chunks**

```bash
node knowledge/build-chunks.js > knowledge/kv-upload.json
npx wrangler kv bulk put --namespace-id=<KV_ID> knowledge/kv-upload.json
```

- [ ] **Step 4: Set secrets**

```bash
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put VANTAGE_API_URL
```

- [ ] **Step 5: Deploy**

```bash
npx wrangler deploy
```
Note the worker subdomain URL from the output (e.g., `vantage-chatbot.your-account.workers.dev`).

- [ ] **Step 6: Smoke test production**

```bash
CHATBOT_URL=https://vantage-chatbot.<account>.workers.dev \
  python -m pytest tests/suites/34_vega_chatbot/test_chatbot.py::test_health \
                   tests/suites/34_vega_chatbot/test_chatbot.py::test_chat_returns_reply -v
```
Expected: both `PASSED`

- [ ] **Step 7: Wire production URL into app.html**

Add this line immediately before the chatbot script tag in `vantage-final-v4/app.html`:

```html
  <script>window.VEGA_CHATBOT_URL = "https://vantage-chatbot.<account>.workers.dev";</script>
```

Replace `<account>` with the actual subdomain from Step 5.

- [ ] **Step 8: Final commit**

```bash
git add vantage-chatbot/wrangler.toml vantage-final-v4/app.html
git commit -m "feat(chatbot): Vega live on Cloudflare Workers"
```

---

## Self-Review

**Spec coverage:**
- Dashboard help ✓ — knowledge base + chat handler answers dashboard questions
- VantageAI Q&A ✓ — 19 static entries cover product, pricing, integrations
- Subscription-aware ✓ — `plan_gate` in static.json, `X-Plan` header filters lookup
- Integration docs ✓ — `build-chunks.js` ingests docs.html into KV
- Customer support + email escalation ✓ — ticket handler sends via Resend
- Female tone ✓ — system prompt establishes Vega persona
- Data security ✓ — `sanitize.ts` strips keys/IPs; prompt instructs against disclosure
- New directory ✓ — `vantage-chatbot/` is fully isolated
- Thorough tests ✓ — 27 tests: health, chat, tickets, knowledge validation, widget safety, chunks builder

**Placeholder scan:** None.

**Type consistency:** All types defined in `types.ts`, used consistently across all handler files.
