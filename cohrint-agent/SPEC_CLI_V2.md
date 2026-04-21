# cohrint-agent CLI v2 — Feature Spec

Target version: **0.4.0** (breaking: new subcommand grammar; existing prompt-as-args usage preserved).

This spec covers the 8-item request:
1. list/install/uninstall/help for mcp/plugins
2. `init` command
3. add/update hooks/skills/permissions/settings.json
4. `/model` suggests supported backends + models
5. recommendation + hallucination-check toggles
6. Public docs with examples
7. Test until clean slate (pytest zero warnings)
8. Commit + push per phase

---

## Goals

- Unified inventory (A) + delegated install/uninstall (B), as agreed.
- Interactive TUI selectors via `questionary` with non-TTY fallback.
- Complete `/help` catalog in REPL + full `cli-reference` page in public docs.
- 100% test coverage of new surface; zero regressions on existing behaviour.

## Non-goals

- Replace Claude Code's native settings.json editor.
- Own MCP state — we read and delegate, we never shadow upstream storage.
- Implement a marketplace; delegate to upstream (`claude mcp add`, etc.).

---

## Design principles

1. **argv[1] dispatcher runs before argparse** — preserves `cohrint-agent "fix the bug"` prompt-as-args behaviour. Only claimed verbs intercept.
2. **Append-safe, never clobber.** File writes always use tmp + `os.replace`; scoped blocks (`<!-- cohrint:begin/end -->`) so re-runs are idempotent.
3. **Zero deflection.** cohrint never writes `.claude/settings.json` unless the user explicitly ran a `hooks|permissions|settings` subcommand. CLAUDE.md is the only scaffold we touch on `init`.
4. **TTY-aware.** Every interactive flow has a non-TTY fallback (plain list + positional args).
5. **Fail loud, never silent.** Every delegation captures backend stderr and surfaces it; no `2>/dev/null` on install paths.

---

## Command catalog (complete)

### Inventory (A)
```
cohrint-agent models                        List supported models (grouped by backend)
cohrint-agent models --unsupported          Show models we route but don't price
cohrint-agent models info <id>              Single-model detail
cohrint-agent mcp list [--backend X]        Unified MCP server list
cohrint-agent plugins list                  Plugin list (claude-only; "—" elsewhere)
cohrint-agent skills list                   Skills across ~/.claude/skills/ + .claude/skills/
cohrint-agent agents list                   Agents across ~/.claude/agents/ + .claude/agents/
cohrint-agent hooks list                    Parse ~/.claude/settings.json hooks[]
cohrint-agent permissions list              Parse settings.json permissions
cohrint-agent settings show                 Pretty-print merged settings
```

### Install / uninstall (B — delegated)
```
cohrint-agent mcp add <name> [--backend X] [--args ...]    → `<backend> mcp add`
cohrint-agent mcp remove <name>                             → `<backend> mcp remove`
cohrint-agent plugins add <name>                            → `claude plugin` (claude-only)
cohrint-agent plugins remove <name>                         → `claude plugin`
cohrint-agent skills add <path-or-url>                      FS copy or `git clone` into skills dir
cohrint-agent skills remove <name>                          rm -rf under safety check
cohrint-agent agents add <path>                             FS copy
cohrint-agent agents remove <name>                          rm -rf under safety check
```

### Scaffolding
```
cohrint-agent init [--backend claude|gemini|codex] [--all] [--plain] [--force]
  - Writes/appends CLAUDE.md | GEMINI.md | AGENTS.md
  - --all: writes all three
  - --plain: emits vanilla scaffold, no cohrint block
  - --force: overwrite instead of append-in-place
  - Never touches .claude/ subdirs
```

### Config writes (user-invoked)
```
cohrint-agent hooks add <event> <command> [--matcher <glob>] [--scope user|project]
cohrint-agent hooks remove <event> <index>
cohrint-agent permissions allow <pattern>
cohrint-agent permissions deny <pattern>
cohrint-agent permissions set-mode <mode>
cohrint-agent settings set <dotted.key> <json-value>
cohrint-agent settings reset <dotted.key>
```

### Guardrails
```
cohrint-agent guardrails status
cohrint-agent guardrails hallucination on|off
cohrint-agent guardrails recommendation on|off
```

### Passthrough (from prior design)
```
cohrint-agent exec <backend> <args...>      Raw os.execvp into backend CLI
```

### REPL slash commands (parity + additions)
```
/help                Full command catalog (questionary tree OR rich.tree)
/model               Opens TUI picker grouped by backend
/mcp                 Opens MCP list → Enter = info, D = remove, A = add-dialog
/skills              Same pattern, for skills
/agents              Same pattern, for agents
/init                Runs `cohrint-agent init` with detected backend
/guardrails          Toggle UI
/exec <...>          Same as CLI exec
/ (just slash)       Autocomplete popup (questionary.autocomplete)
```

---

## Phase plan (8 PRs)

Each phase = one branch, one PR, merge-then-proceed. No mega-branch.

### Phase 0 — Foundations (no user-visible change)

Files created:
- `cohrint_agent/subcommands.py` — argv dispatcher, verb table
- `cohrint_agent/inventory/__init__.py` — scanner protocol
- `cohrint_agent/inventory/claude.py` — scans `~/.claude/`, `.claude/`, `~/.claude.json`
- `cohrint_agent/inventory/gemini.py` — scans `~/.gemini/`
- `cohrint_agent/inventory/codex.py` — scans `~/.codex/`
- `cohrint_agent/delegate.py` — `exec_backend()` using `os.execvpe` + `resolve_backend_binary`
- `cohrint_agent/tui.py` — questionary wrappers with `isatty` fallback
- `cohrint_agent/commands/__init__.py`

Files modified:
- `cohrint_agent/cli.py` — call dispatcher in `main()` before argparse
- `pyproject.toml` — add `questionary>=2.0,<3.0`

Tests (new suite `tests/suites/22_cli_v2/`):
- `test_dispatcher.py` — verb routing + prompt passthrough preserved
- `test_inventory_claude.py` — FS fixtures under tmp_path
- `test_delegate.py` — mocked `os.execvpe`
- `test_tui_fallback.py` — non-TTY returns plain result

Ship: version bump to 0.3.1-dev; no PyPI release yet.

### Phase 1 — models + /model suggestions

Implements user point 4.

- `cohrint_agent/commands/models.py` reads `pricing.py` as source of truth
- `/model` (no arg) in REPL: TUI grouped by backend → returns `backend:model` pair
- `/model <id>` preserves current behaviour

Tests:
- All models in pricing.py appear in `models` output
- Unsupported-model list matches hardcoded roadmap
- TUI select returns correct pair; fallback prints flat list

PyPI: 0.3.1.

### Phase 2 — list everywhere

Implements half of user point 1 + part of point 3.

Commands: `mcp list`, `plugins list`, `skills list`, `agents list`, `hooks list`, `permissions list`, `settings show`.

Table format:
```
NAME     SCOPE    BACKEND   ENABLED   PATH
weather  global   claude    yes       ~/.claude/skills/weather/
spotify  local    claude    yes       .claude/skills/spotify/
```

Interactive flag `--interactive` / `-i` on any `list` → questionary select → Enter opens `info` view.

Tests: fixtures for each resource type; interactive path exercised via questionary's test harness.

### Phase 3 — install / uninstall

Implements remainder of user point 1 + rest of point 3.

Delegation matrix:

| Resource | claude | gemini | codex |
|----------|--------|--------|-------|
| mcp add | `claude mcp add` | `gemini mcp add` | `codex mcp add` |
| plugins add | `claude plugin add` | error | error |
| skills add | FS copy | FS copy | FS copy |
| agents add | FS copy | n/a | n/a |

Safety gate (in `delegate.py` + `commands/*.py`):
- refuse writes outside `~/.claude|.gemini|.codex/` or `$PWD/.claude|.gemini|.codex/`
- `remove` requires confirm (`--yes` skips)
- audit log append to `~/.cohrint-agent/install.log` (JSONL)

Tests:
- Each add/remove happy path + confirm flow
- Path-escape attempts rejected
- Audit log written

PyPI: 0.3.2.

### Phase 4 — init + hooks/permissions/settings

Implements user point 2 + remaining of point 3.

`init`:
- Append-safe block between `<!-- cohrint:begin --> ... <!-- cohrint:end -->`
- `--plain` emits only the vanilla scaffold (matches upstream)
- `--force` replaces file contents entirely (only applied to missing or `--plain` origin files)

`hooks|permissions|settings`:
- Writer uses atomic tmp + `os.replace`
- Holds `open_lockfile()` from `process_safety.py` during RMW
- Schema-validates settings.json before write; refuses unknown top-level keys

Tests:
- `init` idempotent (runs twice = same result)
- `init --plain` produces byte-identical upstream template
- Hooks/permissions writes don't corrupt existing keys
- Concurrent write test (two processes, lock serialises)

### Phase 5 — guardrails toggle

Implements user point 5.

State: `~/.cohrint-agent/config.json` adds `{"guardrails": {"hallucination": bool, "recommendation": bool}}`.

When `hallucination: true`:
- Every assistant response routed through a cheap claim-validator (haiku-tier)
- Cached by response hash → zero overhead on repeats

When `recommendation: true`:
- After each turn, print "consider using <model>" hint if `pricing.py` shows a cheaper model that covers the prompt's token class

`/guardrails` in REPL opens a 2-toggle checkbox via questionary.

Tests:
- Toggles persist across runs
- Zero overhead when both off (perf budget: <1ms added per turn)

### Phase 6 — /help catalog + autocomplete

Implements user point 4's "suggestions" clause.

REPL `/help` renders the full catalog grouped by verb (rich.tree if questionary lacks tree widget).
Typing `/` in REPL pops questionary.autocomplete with all commands + one-line descriptions.

`cohrint-agent <verb> --help` prints verb-specific help generated from the same catalog source — no duplication.

Tests: catalog single source of truth; /help output matches argparse help for each verb.

### Phase 7 — docs + final test pass + ship

Implements user points 6, 7, 8.

Docs (`cohrint-frontend/docs.html`):
- New DOCS entry `'cli-reference'`
- Nav group "CLI" with sub-items per verb
- Each command: signature, description, example, example output
- Cross-link from `getting-started` entry

Final test pass:
- Run full `pytest -q -W error tests/suites/` — zero warnings, zero failures
- Run `mypy cohrint_agent/` — zero errors
- Run `ruff check cohrint_agent/` — zero errors
- Manual smoke: install fresh venv, `pip install -e .`, run every command at least once

Ship:
- Version bump to 0.4.0 in `pyproject.toml`
- Update `cohrint-worker/src/routes/cli.ts` Python release row (`version: '0.4.0'`, raise `minSupported` to `'0.3.0'`)
- PyPI upload
- `wrangler deploy` for worker (after user approval — per feedback_deploy_workflow memory)
- `wrangler pages deploy` for docs (after user approval)
- Release notes in GitHub Releases

---

## Test strategy

- **Suite location**: `tests/suites/22_cli_v2/` (new)
- **Style**: pytest, no mocking of filesystem (use `tmp_path`); mocks only for `subprocess`/`os.execvpe` where actually spawning would break CI
- **Coverage target**: 90%+ on `cohrint_agent/commands/` and `cohrint_agent/inventory/`
- **Regression gate**: Phases 1-7 all run existing suite as-is; if any pre-existing test fails, stop and fix before continuing
- **"Clean slate" definition**: `pytest -q -W error` exits 0 with no warnings on full suite

---

## Risks + mitigations

| Risk | Mitigation |
|------|------------|
| questionary breaks under non-TTY (CI, piped) | `tui.py` checks `sys.stdin.isatty()`; falls back to flat list + positional args |
| Claude Code settings.json schema changes upstream | Schema validation at write time; unknown top-level keys rejected with error |
| `claude mcp add` flag syntax drifts | Capture stderr; surface verbatim; `--raw-args` escape hatch |
| exec passthrough drops signals | Use `os.execvpe` (process replacement) not `subprocess` |
| FS scan hangs REPL on slow mount | 500ms per-scanner timeout; results cached 60s |
| Auto-append to CLAUDE.md surprises users | Show diff preview before write when run interactively; `--yes` skips |
| PyPI 0.4.0 breaks `minSupported` bump for existing users | Raise `minSupported` to `'0.3.0'` only; 0.2.x users get upgrade notice, not force |

---

## Dependency additions

- `questionary>=2.0,<3.0` (adds `prompt_toolkit>=3.0` transitive)
- No other new deps. No new npm deps.

Install-size delta: ~1.5 MB (questionary + prompt_toolkit + wcwidth).

---

## Ship checklist

- [ ] Phase 0 — dispatcher + inventory stubs + questionary dep
- [ ] Phase 1 — models + /model — PyPI 0.3.1
- [ ] Phase 2 — list for mcp/plugins/skills/agents/hooks/permissions/settings
- [ ] Phase 3 — install/uninstall — PyPI 0.3.2
- [ ] Phase 4 — init + hooks/permissions/settings writers
- [ ] Phase 5 — guardrails toggle
- [ ] Phase 6 — /help catalog + autocomplete
- [ ] Phase 7 — docs.html + final test pass + PyPI 0.4.0

Estimated calendar: 7 PRs × ~1–3 days each. 2–3 weeks end-to-end with review cycles.

---

## Open questions (answer before Phase 0)

1. **questionary or textual?** Defaulting to questionary (lighter, ~600KB). Upgrade to textual only if a single command needs full-screen modal (none currently do).
2. **Plugin semantics on gemini/codex**: Default is `list` → "—", `add/remove` → error "no plugin concept for <backend>". OK?
3. **Scope split**: Phase-by-phase merge as listed, or group Phases 0-2 into one opening PR? My default is phase-by-phase for cleaner review.
4. **Gemini + Codex inventory paths**: Gemini uses `~/.gemini/` — confirmed. Codex audit **done** — see below.

---

## Codex audit findings

Root: `~/.codex/` (override via `CODEX_HOME`). Project-scoped: `.codex/config.toml`.

| Resource | Claude | Gemini | Codex |
|----------|--------|--------|-------|
| Root | `~/.claude/` + `.claude/` | `~/.gemini/` | `~/.codex/` + `.codex/` |
| Config format | JSON (`settings.json`) | JSON | **TOML** (`config.toml`) |
| Scaffold file | `CLAUDE.md` | `GEMINI.md` | `AGENTS.md` |
| Skills/rules | `skills/` dir with per-skill subdirs | — | `rules/` dir (different semantics) |
| Agents | `agents/*.md` (multi-file) | — | **single `AGENTS.md` file** |
| MCP | `~/.claude.json` mcpServers | gemini mcp CLI | not documented yet; confirm in Phase 2 |
| Sessions | — | — | `~/.codex/sessions/` |
| Logs | — | — | `~/.codex/logs/` |

**Inventory implications:**
- `cohrint_agent/inventory/codex.py` must parse TOML (stdlib `tomllib` on Python 3.11+; `tomli` fallback for 3.9/3.10)
- Codex "agents" concept ≠ Claude agents concept: for Codex, `agents list` shows the single AGENTS.md's declared agents section (if present) or returns a single-entry list
- Codex "rules" appear to map closest to Claude skills — list them under `skills list --backend codex` with a footnote; `--backend codex rules list` is a future alias if users want parity
- For `plugins` on Codex: same behaviour as Gemini — "—" on list, error on add/remove

**Scaffold writer implications for `init`:**
- Claude: append-safe block in `CLAUDE.md`
- Gemini: append-safe block in `GEMINI.md`
- Codex: append-safe block in `AGENTS.md` — but this file is ALSO where Codex stores agent definitions, so the append block must be distinct section (proposed header `## Cohrint CLI` with the markers, never touching agent declarations)

Sources:
- [Configuration Reference – Codex | OpenAI Developers](https://developers.openai.com/codex/config-reference)
- [codex/docs/config.md at main · openai/codex](https://github.com/openai/codex/blob/main/docs/config.md)
- [Where OpenAI Codex CLI Stores Configuration Files | Inventive HQ](https://inventivehq.com/knowledge-base/openai/where-configuration-files-are-stored)
