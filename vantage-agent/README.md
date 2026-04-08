# Vantage Agent

AI coding agent with per-tool permissions, cost tracking, prompt optimization, and anomaly detection. Works across Claude (API), Claude Code, Codex CLI, and Gemini CLI.

## Install

```bash
pip install vantage-agent
```

Requires Python 3.9+.

## Quick Start

### Interactive REPL

```bash
# Set your API key, then launch
export ANTHROPIC_API_KEY=sk-...
vantage-agent
```

### One-shot prompt

```bash
vantage-agent "explain the main function in cli.py"
```

### Pipe mode

```bash
echo "summarize this file" | vantage-agent
```

## Backends

Vantage auto-detects the best backend. You can override with `--backend`:

| Backend | Description | Requires |
|---------|-------------|---------|
| `api` | Direct Anthropic API (exact token counts) | `ANTHROPIC_API_KEY` |
| `claude` | Claude Code subprocess (free tier / subscription) | `claude` binary |
| `codex` | OpenAI Codex CLI subprocess | `codex` binary |
| `gemini` | Gemini CLI subprocess | `gemini` binary |

```bash
vantage-agent --backend claude "refactor this function"
vantage-agent --backend codex "write unit tests for auth.py"
```

Auto-detect priority: `VANTAGE_BACKEND` env → `ANTHROPIC_API_KEY` → `claude` binary → `codex` binary → `gemini` binary.

## Session Management

Sessions are persisted to `~/.vantage/sessions/`. Resume any previous session:

```bash
# List sessions and costs
vantage-agent summary

# Resume by session ID
vantage-agent --resume abc12345
```

## REPL Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/tools` | Show tool approval status |
| `/allow Bash,Write` | Approve specific tools |
| `/allow all` | Approve all tools for this session |
| `/cost` | Show current session cost |
| `/optimize on\|off` | Toggle prompt optimization |
| `/model claude-opus-4-6` | Switch model mid-session |
| `/reset` | Clear history, permissions, cost |
| `/quit` | Exit (shows final cost summary) |

## Cost Tracking

Every turn shows token usage and cost. Exit shows a full session summary:

```
  +----- Cost Summary -----+
  Model:             claude-sonnet-4-6
  Input tokens:      1,234
  Output tokens:     456
  Cost:              $0.0123
  Session total:     $0.0456
  Prompts:           3
  +-------------------------+
```

For Claude Code / Codex / Gemini (subscription or free tier), costs are labeled `~$0.00 (free tier)` or `~$0.0123 (estimated)`.

## VantageAI Dashboard

Send telemetry to your VantageAI dashboard for cross-session cost analysis:

```bash
export VANTAGE_API_KEY=vnt_...
vantage-agent
```

Or pass inline: `vantage-agent --vantage-key vnt_...`

## All Flags

```
vantage-agent [OPTIONS] [PROMPT]

  PROMPT              One-shot prompt (omit for interactive REPL)

  --backend           api | claude | codex | gemini (auto-detected)
  --model             Model ID (default: claude-sonnet-4-6)
  --max-tokens        Max output tokens (default: 16384)
  --resume SESSION_ID Resume a previous session
  --api-key           Anthropic API key (or ANTHROPIC_API_KEY env)
  --vantage-key       VantageAI dashboard API key (or VANTAGE_API_KEY env)
  --system            Custom system prompt
  --no-optimize       Disable prompt optimization
  --cwd               Set working directory
  --debug             Enable debug output
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `VANTAGE_API_KEY` | VantageAI dashboard key |
| `VANTAGE_BACKEND` | Force backend (api/claude/codex/gemini) |
| `VANTAGE_MODEL` | Default model override |

## License

MIT
