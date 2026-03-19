# vantageaiops-mcp

MCP server for [VantageAI](https://vantageaiops.com) — track LLM costs and query analytics directly from your AI coding assistant.

[![npm](https://img.shields.io/npm/v/vantageaiops-mcp)](https://www.npmjs.com/package/vantageaiops-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Tools

| Tool | Description |
|------|-------------|
| `track_llm_call` | Log an LLM call (tokens, cost, latency, model, team) |
| `get_summary` | MTD spend, requests, top model, budget status |
| `get_kpis` | Full KPI table with deltas |
| `get_model_breakdown` | Cost + usage per model |
| `get_team_breakdown` | Cost + usage per team (chargeback) |
| `check_budget` | Budget % used, remaining, status |
| `get_traces` | Recent multi-step agent traces |
| `get_cost_gate` | CI/CD gate — pass/fail vs budget |

## Setup

### 1. Get your API key

Sign up free at [vantageaiops.com/signup.html](https://vantageaiops.com/signup.html) — your `vnt_...` key is generated instantly.

### 2. Add to your coding assistant

Pick your platform. All configs use `npx vantageaiops-mcp` — no local install needed.

---

## Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vantage": {
      "command": "npx",
      "args": ["-y", "vantageaiops-mcp"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here"
      }
    }
  }
}
```

Restart Claude Desktop. VantageAI tools appear in the tool picker automatically.

---

## Cursor

Edit `~/.cursor/mcp.json` (or Cursor → Settings → MCP):

```json
{
  "mcpServers": {
    "vantage": {
      "command": "npx",
      "args": ["-y", "vantageaiops-mcp"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here"
      }
    }
  }
}
```

---

## Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "vantage": {
      "command": "npx",
      "args": ["-y", "vantageaiops-mcp"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here"
      }
    }
  }
}
```

---

## VS Code (Copilot / GitHub Copilot Chat)

Add to `.vscode/mcp.json` in your project root (VS Code 1.99+):

```json
{
  "servers": {
    "vantage": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "vantageaiops-mcp"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here"
      }
    }
  }
}
```

---

## Cline (VS Code extension)

Open Cline → MCP Servers → Add Server → paste:

```json
{
  "vantage": {
    "command": "npx",
    "args": ["-y", "vantageaiops-mcp"],
    "env": {
      "VANTAGE_API_KEY": "vnt_your_key_here"
    }
  }
}
```

---

## Zed

Add to your Zed `settings.json`:

```json
{
  "context_servers": {
    "vantage": {
      "command": {
        "path": "npx",
        "args": ["-y", "vantageaiops-mcp"],
        "env": {
          "VANTAGE_API_KEY": "vnt_your_key_here"
        }
      }
    }
  }
}
```

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VANTAGE_API_KEY` | ✅ | — | Your `vnt_...` API key from [signup](https://vantageaiops.com/signup.html) |
| `VANTAGE_ORG` | No | parsed from key | Org ID override |
| `VANTAGE_API_BASE` | No | `https://api.vantageaiops.com` | Custom API base URL |

---

## Example usage in chat

Once connected, ask your assistant:

- *"How much have we spent on LLMs this month?"* → `get_summary`
- *"Which model is costing us the most?"* → `get_model_breakdown`
- *"Are we within our AI budget?"* → `check_budget`
- *"Show me recent agent traces"* → `get_traces`
- *"Track this call: gpt-4o, 500 prompt tokens, 120 completion tokens, $0.003"* → `track_llm_call`

---

## Links

- [Dashboard](https://vantageaiops.com/app.html)
- [Docs](https://vantageaiops.com/docs.html)
- [Python SDK](https://pypi.org/project/vantageaiops/)
- [JavaScript SDK](https://www.npmjs.com/package/vantageaiops)
