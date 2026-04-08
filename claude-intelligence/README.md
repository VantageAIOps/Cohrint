# claude-intelligence

Plug-and-play Claude Code setup: hooks, agents, and settings templates that make Claude Code smarter in any repo.

## What this installs

| Component | Location | Purpose |
|-----------|----------|---------|
| `CLAUDE.md` | `.claude/CLAUDE.md` | Global brain — coding conventions, response style, workflow rules |
| `settings.json` | `.claude/settings.json` | Permissions, model config, hook wiring |
| `.claudeignore` | `.claudeignore` | Keeps Claude from reading node_modules, build artifacts, secrets |
| `pre-commit.sh` | `.claude/hooks/pre-commit.sh` | Blocks commits if TS check / lint / tests fail |
| `lint-on-save.sh` | `.claude/hooks/lint-on-save.sh` | Auto-formats files after every Edit/Write |
| `claude-md-enforcer.sh` | `.claude/hooks/claude-md-enforcer.sh` | Warns when CLAUDE.md exceeds 100 lines |
| `vantage-track.js` | `.claude/hooks/vantage-track.js` | Posts Claude Code token costs to VantageAI (optional) |
| `agents/code-reviewer.md` | `.claude/agents/code-reviewer.md` | Reviews code for bugs, security, performance |
| `agents/test-writer.md` | `.claude/agents/test-writer.md` | Writes comprehensive test suites |
| `agents/debugger.md` | `.claude/agents/debugger.md` | Systematic root-cause bug diagnosis |

## Prerequisites

- [Claude Code CLI](https://claude.ai/code) installed (`~/.claude/` must exist)
- Node.js 18+ (for `vantage-track.js`)
- bash

## One-command install

```bash
bash <(curl -s https://raw.githubusercontent.com/Amanjain98/VantageAI/main/claude-intelligence/install.sh)
```

Run from your project root. The script is interactive — it will ask before overwriting existing files.

## Manual install

1. Copy `templates/CLAUDE.md` → `.claude/CLAUDE.md`
2. Copy `templates/.claudeignore` → `.claudeignore`
3. Copy `templates/settings.json` → `.claude/settings.json`
4. Copy `agents/*.md` → `.claude/agents/`
5. Copy `hooks/*` → `.claude/hooks/` and `chmod +x .claude/hooks/*.sh`
6. Edit `.claude/CLAUDE.md` — replace `{{YOUR_NAME}}` and fill in `## Project Context`

## Components

### Hooks

**`pre-commit.sh`** — Runs before every `git commit`. Blocks if:
- TypeScript type check fails (`npx tsc --noEmit`)
- ESLint fails on staged `.ts/.tsx/.js/.jsx` files
- `npm test` fails
- ruff or pytest fails (Python projects)

**`lint-on-save.sh`** — Runs after every `Edit` or `Write`. Auto-formats:
- JS/TS: Prettier + ESLint `--fix`
- Python: ruff format + ruff check `--fix` (or black)
- Go: gofmt
- Rust: rustfmt

**`claude-md-enforcer.sh`** — Monitors CLAUDE.md length. Emits a system message if it exceeds 100 lines, prompting Claude to compress it.

**`vantage-track.js`** — Reads Claude Code session `.jsonl` files from `~/.claude/projects/` and posts token usage + cost data to [VantageAI](https://vantageaiops.com). Requires a free API key. Silent on errors — never breaks Claude Code.

### Agents

**`code-reviewer`** — Invoke with `/agent code-reviewer`. Reviews the last commit for security issues, performance problems, type safety, and code quality. Reports as CRITICAL / WARNING / SUGGESTION.

**`test-writer`** — Invoke with `/agent test-writer`. Reads source code, identifies all code paths, and writes tests following the project's framework and patterns.

**`debugger`** — Invoke with `/agent debugger`. Traces bugs systematically: reproduce → isolate → root cause → fix → verify.

### Settings

`settings.json` configures:
- **Model**: `claude-sonnet-4-6`
- **Permissions**: broad allow list for common dev tools, deny list for destructive commands
- **Hooks**: wires pre-commit, lint-on-save, and vantage-track to the right events

### CLAUDE.md

A generalized "global brain" with:
- Stack preferences (Next.js, Tailwind, PostgreSQL, etc.)
- Code conventions (TypeScript strict, functional components, etc.)
- Workflow rules (branch → PR → CI → merge)
- Response style rules (concise, no filler)

Edit the `## Project Context` and `## Who I Am` sections to match your project.

## Optional: Vantage API key

Get a free key at [vantageaiops.com](https://vantageaiops.com) to track Claude Code token costs across all your projects.

The install script will prompt for it. Or set it in your shell profile:

```bash
export VANTAGE_API_KEY=vnt_your_key_here
```

## License

MIT
