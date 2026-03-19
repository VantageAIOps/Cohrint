# vantage-ai

**LLM cost tracking and AI API monitoring SDK.**

Track token usage, cost, latency and quality for OpenAI, Anthropic, Google and Mistral — with one line of code.

[![PyPI](https://img.shields.io/pypi/v/vantageaiops)](https://pypi.org/project/vantageaiops/)
[![Python](https://img.shields.io/pypi/pyversions/vantageaiops)](https://pypi.org/project/vantageaiops/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Install

```bash
pip install vantageaiops            # core only
pip install vantageaiops[openai]    # + OpenAI proxy
pip install vantageaiops[anthropic] # + Anthropic proxy
pip install vantageaiops[google]    # + Gemini proxy
pip install vantageaiops[all]       # everything
```

## Quickstart

```python
import vantage
from vantage.wrappers import create_openai_proxy
import openai

# 1. Init once (e.g. in app startup)
vantage.init(api_key="vnt_your_key")

# 2. Wrap your OpenAI client — zero other changes
client = create_openai_proxy(openai.OpenAI())

# 3. Use normally — every call is automatically tracked
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

Every call is logged to your [VantageAI dashboard](https://vantageaiops.com/app.html) with:
- Token counts (prompt + completion)
- Cost in USD
- Latency (ms)
- Model and provider
- Team / environment tags

## Anthropic

```python
import vantage
from vantage.wrappers import create_anthropic_proxy
import anthropic

vantage.init(api_key="vnt_your_key")
client = create_anthropic_proxy(anthropic.Anthropic())

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}]
)
```

## Manual tracking

```python
import vantage

vantage.init(api_key="vnt_your_key")

vantage.track(
    model="gpt-4o",
    provider="openai",
    prompt_tokens=500,
    completion_tokens=120,
    total_cost_usd=0.0035,
    latency_ms=842,
    team="search",
    environment="production",
)
```

## Agent / multi-step traces

```python
import uuid, vantage

vantage.init(api_key="vnt_your_key")

trace_id = str(uuid.uuid4())

# Step 1 — root call
vantage.track(model="gpt-4o", ..., trace_id=trace_id, span_depth=0)

# Step 2 — sub-call
vantage.track(model="claude-3-5-sonnet-20241022", ..., trace_id=trace_id, span_depth=1)
```

Traces appear in the **Agent Traces** tab of your dashboard with per-span cost breakdown.

## Configuration

```python
vantage.init(
    api_key="vnt_your_key",
    org="acme",                  # auto-parsed from key if omitted
    team="platform",             # default team tag
    environment="production",    # default: "production"
    ingest_url="https://api.vantageaiops.com",
    flush_interval=2.0,          # seconds between auto-flush
    batch_size=50,               # events per HTTP request
    debug=False,
)
```

## Links

- [Dashboard](https://vantageaiops.com/app.html)
- [Full docs](https://vantageaiops.com/docs.html)
- [REST API reference](https://vantageaiops.com/docs.html#api)
- [GitHub](https://github.com/amanjain/vantageai)
