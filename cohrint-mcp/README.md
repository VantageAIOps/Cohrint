# cohrint-mcp

MCP server for [Cohrint](https://cohrint.com) — track LLM costs and query analytics directly from your AI coding assistant.

[![npm](https://img.shields.io/npm/v/cohrint-mcp)](https://www.npmjs.com/package/cohrint-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

## Quick start

```bash
# 1. Get your API key (free)
# → https://cohrint.com/signup.html

# 2. Test the server works
COHRINT_API_KEY=crt_your_key npx -y cohrint-mcp

# 3. Add to your editor (see below)
```

## Tools (15 total — 14 read-only + 1 opt-in write)

By default the server exposes only the 14 read-only + offline tools. The single
write tool (`setup_claude_hook`, which modifies `~/.claude/settings.json`) is
hidden unless you opt in — see [Permissions](#permissions--sandboxing) below.

### Analytics tools (require API key)
| Tool | Description |
|------|-------------|
| `track_llm_call` | Log an LLM call — tokens, cost, latency, model, team |
| `get_summary` | MTD spend, today's cost, requests, budget status |
| `get_kpis` | Full KPI table — cost, tokens, latency, efficiency |
| `get_model_breakdown` | Cost + usage per model (customizable period) |
| `get_team_breakdown` | Cost + usage per team for chargeback |
| `check_budget` | Budget % used, remaining, over/under status |
| `get_traces` | Recent multi-step agent traces with cost |
| `get_cost_gate` | CI/CD gate — pass/fail vs budget (today/week/month) |

### Optimizer tools (work offline, no API key needed)
| Tool | Description |
|------|-------------|
| `optimize_prompt` | Compress prompts to reduce token usage, with optimization tips |
| `analyze_tokens` | Count tokens and estimate cost for text |
| `estimate_costs` | Compare costs across 22+ models (OpenAI, Anthropic, Google, Meta, DeepSeek, Mistral) |
| `compress_context` | Compress conversation history within a token budget |
| `find_cheapest_model` | Rank supported models by cost for a given workload |
| `get_recommendations` | Surface top cost-saving suggestions from your usage |

### Setup tool (off by default — filesystem write)
| Tool | Description |
|------|-------------|
| `setup_claude_hook` | Install the Cohrint Stop hook into `~/.claude/settings.json` so Claude Code sessions are auto-tracked. Requires `COHRINT_MCP_ALLOW_SETUP=1`. |

## Editor setup

### Prerequisites
- **Node.js 18+** required (`node --version` to check)
- All editors use `npx -y cohrint-mcp` — no local install needed

---

### Claude Desktop

**Config file:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

```json
{
  "mcpServers": {
    "cohrint": {
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": {
        "COHRINT_API_KEY": "crt_your_key_here"
      }
    }
  }
}
```

**After saving:** Fully quit Claude Desktop (menu bar → Quit, not just close window) and reopen it. Click the hammer icon to see Cohrint tools.

> **macOS tip:** If `npx` is not found, use the full path. Run `which npx` in Terminal and use that (e.g. `/opt/homebrew/bin/npx`).

---

### Claude Code (CLI)

**Project-level** — create `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "cohrint": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": {
        "COHRINT_API_KEY": "crt_your_key_here"
      }
    }
  }
}
```

**Global** — add to `~/.claude/mcp.json` (applies to all projects).

**Verify:** Run `/mcp` inside Claude Code — you should see "cohrint" listed with 15 tools.

---

### Cursor

**Config file:** `~/.cursor/mcp.json` (or Cursor → Settings → MCP Servers)

```json
{
  "mcpServers": {
    "cohrint": {
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": {
        "COHRINT_API_KEY": "crt_your_key_here"
      }
    }
  }
}
```

**After saving:** Restart Cursor. Tools appear automatically in the AI chat.

---

### Windsurf

**Config file:** `~/.codeium/windsurf/mcp_config.json`

```json
{
  "mcpServers": {
    "cohrint": {
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": {
        "COHRINT_API_KEY": "crt_your_key_here"
      }
    }
  }
}
```

**After saving:** Restart Windsurf. Cascade will have access to all Cohrint tools.

---

### VS Code (Copilot Chat)

**Config file:** `.vscode/mcp.json` in your project root (VS Code 1.99+)

```json
{
  "servers": {
    "cohrint": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "cohrint-mcp"],
      "env": {
        "COHRINT_API_KEY": "crt_your_key_here"
      }
    }
  }
}
```

---

### Cline (VS Code extension)

Open Cline → MCP Servers → Add Server → paste:

```json
{
  "cohrint": {
    "command": "npx",
    "args": ["-y", "cohrint-mcp"],
    "env": {
      "COHRINT_API_KEY": "crt_your_key_here"
    }
  }
}
```

---

### Zed

Add to Zed `settings.json` (Zed → Settings → Open Settings):

```json
{
  "context_servers": {
    "cohrint": {
      "command": {
        "path": "npx",
        "args": ["-y", "cohrint-mcp"],
        "env": {
          "COHRINT_API_KEY": "crt_your_key_here"
        }
      }
    }
  }
}
```

---

### JetBrains (IntelliJ, WebStorm, PyCharm)

Settings → Tools → AI Assistant → Model Context Protocol → Add server:
- **Command:** `npx`
- **Arguments:** `-y cohrint-mcp`
- **Environment:** `COHRINT_API_KEY=crt_your_key_here`

---

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COHRINT_API_KEY` | Yes | — | Your `crt_...` API key ([get one free](https://cohrint.com/signup.html)) |
| `COHRINT_ORG` | No | auto-parsed from key | Org ID override |
| `COHRINT_API_BASE` | No | `https://api.cohrint.com` | Custom API base URL |

## Example prompts

Once connected, try these in your AI assistant:

```
# Cost tracking
"How much have we spent on LLMs this month?"          → get_summary
"Which model is costing us the most?"                  → get_model_breakdown
"Show spending by team"                                → get_team_breakdown
"Are we within our AI budget?"                         → check_budget

# Logging
"Track this call: gpt-4o, 500 prompt, 120 completion tokens, $0.003"  → track_llm_call

# Optimization
"Compare costs for this prompt across all models"     → estimate_costs
"How many tokens is this text?"                        → analyze_tokens
"Compress this prompt to save tokens"                  → optimize_prompt

# CI/CD
"Are we safe to merge? Check today's AI spend"         → get_cost_gate
"Show recent agent traces"                             → get_traces
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Server not showing up | 1. Check `node --version` is 18+ <br> 2. Verify JSON syntax (no trailing commas) <br> 3. Fully restart the editor (quit + reopen) |
| "npx not found" on macOS | Use full path: `/opt/homebrew/bin/npx` or `/usr/local/bin/npx` (run `which npx`) |
| "COHRINT_API_KEY is not set" | Add the `env` block with your key to the config |
| Tools fail with 401 | Your API key is invalid or expired — get a new one at [signup](https://cohrint.com/signup.html) |
| Tools return empty data | You haven't sent any events yet — use `track_llm_call` or integrate the SDK |
| Timeout errors | Check internet connection; the API is at `api.cohrint.com` |

## Supported models (for cost estimation)

OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4, gpt-3.5-turbo, o1, o1-mini, o3-mini
Anthropic: claude-sonnet-4, claude-3.5-sonnet, claude-3-opus, claude-3-haiku, claude-haiku-3.5
Google: gemini-2.0-flash, gemini-1.5-pro, gemini-1.5-flash, gemini-pro
Others: llama-3.3-70b, deepseek-v3, deepseek-r1, mistral-large, mistral-small

## Links

- [Dashboard](https://cohrint.com/app.html)
- [Full docs](https://cohrint.com/docs.html)
- [Python SDK](https://pypi.org/project/cohrint/)
- [JavaScript SDK](https://www.npmjs.com/package/cohrint)
- [GitHub](https://github.com/Amanjain98/Cohrint)
