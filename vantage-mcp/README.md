# vantage-mcp

MCP server for [VantageAI](https://vantageaiops.com) — track LLM costs and query analytics directly from your AI coding assistant.

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

Go to [vantageaiops.com/app.html](https://vantageaiops.com/app.html) → Settings → copy your `vnt_...` key.

### 2. Add to your coding assistant

Pick your platform below and paste the config.

---

## Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vantage": {
      "command": "node",
      "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here",
        "VANTAGE_ORG": "your_org"
      }
    }
  }
}
```

Restart Claude Desktop. You'll see VantageAI tools available in the tool picker.

---

## Cursor

Edit `~/.cursor/mcp.json` (or open Cursor → Settings → MCP):

```json
{
  "mcpServers": {
    "vantage": {
      "command": "node",
      "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here",
        "VANTAGE_ORG": "your_org"
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
      "command": "node",
      "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here",
        "VANTAGE_ORG": "your_org"
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
      "command": "node",
      "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
      "env": {
        "VANTAGE_API_KEY": "vnt_your_key_here",
        "VANTAGE_ORG": "your_org"
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
    "command": "node",
    "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
    "env": {
      "VANTAGE_API_KEY": "vnt_your_key_here",
      "VANTAGE_ORG": "your_org"
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
        "path": "node",
        "args": ["/absolute/path/to/vantage-mcp/dist/index.js"],
        "env": {
          "VANTAGE_API_KEY": "vnt_your_key_here",
          "VANTAGE_ORG": "your_org"
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
| `VANTAGE_API_KEY` | ✅ | — | Your `vnt_...` API key |
| `VANTAGE_ORG` | No | parsed from key | Org ID override |
| `VANTAGE_API_BASE` | No | `https://api.vantageaiops.com` | Custom API base URL |

---

## Example usage in chat

Once connected, you can ask your assistant:

- *"How much have we spent on LLMs this month?"* → `get_summary`
- *"Which model is costing us the most?"* → `get_model_breakdown`
- *"Are we within our AI budget?"* → `check_budget`
- *"Show me recent agent traces"* → `get_traces`
- *"Track this call: gpt-4o, 500 prompt tokens, 120 completion tokens, $0.003"* → `track_llm_call`

## Local development

```bash
cd vantage-mcp
npm install
npm run build        # compile TypeScript
npm start            # run server (stdin/stdout MCP protocol)
```
