# cohrint

**LLM cost tracking and AI API monitoring SDK for TypeScript and JavaScript.**

Track token usage, cost, latency and quality for OpenAI, Anthropic, Google and Mistral — with one line of code.

[![npm](https://img.shields.io/npm/v/cohrint)](https://www.npmjs.com/package/cohrint)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Install

```bash
npm install cohrint
# peer deps — install whichever providers you use
npm install openai              # for OpenAI proxy
npm install @anthropic-ai/sdk   # for Anthropic proxy
```

## Quickstart — OpenAI

```ts
import { init, createOpenAIProxy } from "cohrint";
import OpenAI from "openai";

// 1. Init once (e.g. in app startup)
init({ apiKey: "crt_your_key" });

// 2. Wrap your OpenAI client — zero other changes needed
const openai = createOpenAIProxy(new OpenAI());

// 3. Use normally — every call is automatically tracked
const res = await openai.chat.completions.create({
  model: "gpt-4o",
  messages: [{ role: "user", content: "Hello!" }],
});
```

## Quickstart — Anthropic

```ts
import { init, createAnthropicProxy } from "cohrint";
import Anthropic from "@anthropic-ai/sdk";

init({ apiKey: "crt_your_key" });
const client = createAnthropicProxy(new Anthropic());

const res = await client.messages.create({
  model: "claude-3-5-sonnet-20241022",
  max_tokens: 1024,
  messages: [{ role: "user", content: "Hello!" }],
});
```

## Manual tracking

```ts
import { getClient } from "cohrint";

getClient().capture({
  eventId: crypto.randomUUID(),
  provider: "openai",
  model: "gpt-4o",
  promptTokens: 500,
  completionTokens: 120,
  totalCostUsd: 0.0035,
  latencyMs: 842,
  team: "search",
  environment: "production",
});
```

## Agent / multi-step traces

```ts
import { init, trace } from "cohrint";
import OpenAI from "openai";

init({ apiKey: "crt_your_key" });

const traceId = crypto.randomUUID();

// Wrap each LLM call with trace() to group them
const step1 = await trace(
  () => openai.chat.completions.create({ model: "gpt-4o", messages: [...] }),
  { traceId, spanDepth: 0, team: "agent" }
);

const step2 = await trace(
  () => openai.chat.completions.create({ model: "gpt-4o-mini", messages: [...] }),
  { traceId, spanDepth: 1, team: "agent" }
);
```

Traces appear in the **Agent Traces** tab of your dashboard with per-span cost breakdown.

## Cost calculator

```ts
import { calculateCost, findCheapest } from "cohrint";

const cost = calculateCost("gpt-4o", 10_000, 2_000);
console.log(`Cost: $${cost.totalCostUsd.toFixed(4)}`);

const alt = findCheapest("gpt-4o", 10_000, 2_000);
console.log(`Save ${((cost.totalCostUsd - alt.costUsd) / cost.totalCostUsd * 100).toFixed(0)}% with ${alt.model}`);
```

## Configuration

```ts
import { init } from "cohrint";

init({
  apiKey: "crt_your_key",
  org: "acme",                         // auto-parsed from key if omitted
  team: "platform",                    // default team tag
  environment: "production",           // default: "production"
  ingestUrl: "https://api.cohrint.com", // default
  flushInterval: 2,                    // seconds between auto-flush
  batchSize: 50,                       // events per HTTP request
  debug: false,
});
```

## Links

- [Dashboard](https://cohrint.com/app.html)
- [Full docs](https://cohrint.com/docs.html)
- [REST API reference](https://cohrint.com/docs.html#api)
- [Python SDK](https://pypi.org/project/cohrint/)
