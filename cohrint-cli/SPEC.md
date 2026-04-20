# cohrint-cli — Feature Specification (audit success gate)

Version: 2.2.5
Scope: every capability the CLI must support end-to-end. Each item has an **Expected** outcome that is directly verifiable via a shell test. An item is "done" only when the actual outcome matches Expected with zero warnings / crashes / silent failures.

The audit loop terminates when **every F-item below passes two consecutive clean scans**.

---

## F1. Invocation modes

| # | Mode | Invocation | Expected |
|---|------|-----------|---------|
| F1.1 | REPL | `cohrint` (no args) | Banner + `cohrint [claude] >` prompt appears; reads lines until `/quit` or Ctrl+C |
| F1.2 | One-shot arg | `cohrint "what is 2+2"` | Runs once, streams response, prints cost summary, exits 0 |
| F1.3 | Stdin pipe | `echo "hi" \| cohrint` | Reads from stdin, runs once, exits 0 |
| F1.4 | Heredoc | `cohrint <<< "explain X"` | Same as F1.3 |
| F1.5 | Empty stdin | `: \| cohrint` | Exits 0 without calling agent |
| F1.6 | Stdin >1MB | large input piped in | Truncates at 1MB, warns, proceeds |
| F1.7 | First-run setup | no `~/.vantage/config.json`, TTY | Runs `runSetup` wizard, then continues |
| F1.8 | First-run non-TTY | no config, piped | Uses `DEFAULT_CONFIG`, doesn't hang waiting for input |

## F2. Agent support (end-to-end, each must work live)

| # | Agent | Binary | Test |
|---|-------|--------|-----|
| F2.1 | Claude | `claude` | `cohrint --agent claude "say hi"` returns text, session_id captured |
| F2.2 | Codex | `codex` | `cohrint --agent codex "say hi"` returns text |
| F2.3 | Gemini | `gemini` | `cohrint --agent gemini "say hi"` returns text |
| F2.4 | Aider | `aider` | `/agents` marks as ✓ if installed, ✗ if not (non-crashing) |
| F2.5 | ChatGPT | `chatgpt` | Same as F2.4 |
| F2.6 | Agent detection | `/agents` | Lists all 5, ✓/✗ accurate against `which <binary>` |
| F2.7 | Missing agent | `cohrint --agent aider "hi"` when not installed | Clear ENOENT message, exits without crashing |
| F2.8 | Unknown agent | `cohrint --agent foobar "hi"` | Falls back to ALL_AGENTS[0] OR errors clearly |

## F3. Slash commands (REPL)

| # | Command | Expected |
|---|---------|---------|
| F3.1 | `/help` | Lists all slash commands |
| F3.2 | `/cost` | Prints `SessionSummary` (0 if no prompts run) |
| F3.3 | `/agents` | Lists 5 agents with ✓/✗ |
| F3.4 | `/default <agent>` | Switches default in-REPL; persists nothing (in-session only) |
| F3.5 | `/default <bogus>` | Prints "Unknown agent" + available list |
| F3.6 | `/compare <prompt>` | Runs prompt across all detected agents, prints cost-sorted table |
| F3.7 | `/compare` alone | Prints usage hint |
| F3.8 | `/summary` / `/stats` | Dashboard summary (graceful-degrade if no API key) |
| F3.9 | `/budget` | Budget status (graceful-degrade if no API key) |
| F3.10 | `/tips` | Prints recommendations, or "No recommendations yet" |
| F3.11 | `/status` | Current agent + session cost + allowed tools |
| F3.12 | `/reset` | Clears `agentSessionIds`, `allowedTools`, deletes `~/.vantage/session.json` |
| F3.13 | `/setup` | Re-runs setup wizard in-REPL, reloads config, does NOT duplicate signal handlers |
| F3.14 | `/login` | Prints per-agent login instructions |
| F3.15 | `/quit`, `/exit`, `/q` | Flushes tracker, prints session summary, exits 0 |
| F3.16 | `/<agent>` | Switches active agent (REPL-local) |
| F3.17 | `/<agent> <prompt>` | Runs prompt on that agent without switching default |
| F3.18 | `/unknown` | Prints "Unknown command: /unknown" + hint; does NOT silently consume input |
| F3.19 | Empty input | `<enter>` on empty line | Re-prompts, no crash |

## F4. Command-line flags

| # | Flag | Test |
|---|------|-----|
| F4.1 | `--agent <name>` | Routes to that agent |
| F4.2 | `--model <id>` | Forwarded to agent via `--model` |
| F4.3 | `--system <str>` | Forwarded to agent via `--system` |
| F4.4 | `--no-optimize` | Skips prompt optimizer even for long prompts |
| F4.5 | `--timeout <ms>` | Agent process killed after N ms |
| F4.6 | `--debug` | Debug logs from Tracker flushed to stderr |
| F4.7 | `--paste-delay <ms>` | Paste buffer delay tunable (REPL) |
| F4.8 | Unknown flag | Forwarded to agent as-is (not claimed by CLI) |

## F5. Live rendering (stream)

| # | Feature | Expected |
|---|---------|---------|
| F5.1 | Token streaming | Text chunks appear character-by-character for Claude `stream-json` |
| F5.2 | Tool-use display | `⏺ ToolName(preview)` printed when Claude invokes a tool |
| F5.3 | Tool-result display | `⎿ <first 10 lines>` + overflow note |
| F5.4 | Spinner | `⢸ Thinking...` on stderr before first chunk, cleared on first output |
| F5.5 | Spinner in non-TTY | No-op (no escape codes) |
| F5.6 | ANSI colors | Enabled only when `isTTY` true |
| F5.7 | Output cap | Truncates at 5MB, single warning printed |
| F5.8 | Backpressure | Pauses child stdout if `process.stdout.write` returns false |
| F5.9 | Stderr passthrough | Non-error stderr from agent forwarded to user's stderr |
| F5.10 | Error suppression | "Not logged in" / "No conversation found" filtered — CLI shows clean message instead |

## F6. Prompt optimization

| # | Feature | Expected |
|---|---------|---------|
| F6.1 | Auto-optimize | Long prose prompt shrinks; `savedTokens > 0` shown |
| F6.2 | Skip structured | JSON / code / yaml detected → no optimization |
| F6.3 | `--no-optimize` | Forces raw prompt through |
| F6.4 | Savings aggregation | Total savings across session shown in `/cost` |

## F7. Cost tracking

| # | Feature | Expected |
|---|---------|---------|
| F7.1 | Per-prompt cost | Printed after each prompt in REPL and one-shot |
| F7.2 | Session aggregates | `/cost` shows running total |
| F7.3 | Uses real `total_cost_usd` from Claude result | Not just an estimate |
| F7.4 | Fallback when missing | Uses `pricing.ts` model+token estimate |
| F7.5 | Cost NOT printed on failed calls | No $0.00 cost summary when `notLoggedIn`, `staleSession` (after retry fail), or timeout |
| F7.6 | No double-count | One prompt = one cost event; `/setup` does not add duplicate listeners |

## F8. Session persistence

| # | Feature | Expected |
|---|---------|---------|
| F8.1 | Persist session IDs | `~/.vantage/session.json` holds `{claude: <uuid>}` after first call |
| F8.2 | Resume on next run | Second REPL prompt uses `--resume <uuid>` for Claude |
| F8.3 | Stale session retry | Claude returns "No conversation found" → clears stale ID, retries fresh, one output |
| F8.4 | `/reset` wipes state | `session.json` deleted, `allowedTools` cleared |
| F8.5 | Migration from old path | `~/.vantage/sessions/active.json` → merged into `session.json`, old file removed |
| F8.6 | Corrupt session.json | Returns empty defaults, CLI continues |

## F9. Permissions flow

| # | Feature | Expected |
|---|---------|---------|
| F9.1 | Tool permission prompt | When Claude returns `permission_denials`, user sees `[y/a/n]` prompt |
| F9.2 | "yes once" | Tool allowed for this retry only |
| F9.3 | "always" | Added to persistent `allowedTools` |
| F9.4 | "no" | Not retried; prompt returns without tool result |
| F9.5 | Retry preserves flags | Extra agent flags + session continuation kept on retry |
| F9.6 | Allowed tools persisted | Stored in `~/.vantage/session.json` across runs |

## F10. Auth / login errors

| # | Feature | Expected |
|---|---------|---------|
| F10.1 | Claude not logged in | Clean `⚠ Claude Code is not logged in. Run 'claude' …` message |
| F10.2 | Codex not logged in | Same pattern for codex (detect + show clean msg) |
| F10.3 | Gemini not logged in | Same pattern for gemini |
| F10.4 | No cost summary on auth fail | Cost summary suppressed |
| F10.5 | Session not persisted on auth fail | `agentSessionIds` unchanged |
| F10.6 | REPL continues | Next prompt works (login failure is not fatal) |
| F10.7 | One-shot exits non-zero | Auth failure in one-shot mode → `exit(1)` |

## F11. Timeouts & process lifecycle

| # | Feature | Expected |
|---|---------|---------|
| F11.1 | Default 300s timeout | Or `VANTAGE_TIMEOUT` env |
| F11.2 | `--timeout` override | Honored |
| F11.3 | Timeout path | SIGTERM sent, grace period, SIGKILL; error shown |
| F11.4 | Ctrl+C in REPL | Calls `shutdown()`: flush tracker, print session summary, exit 0 |
| F11.5 | SIGTERM to parent | Same graceful shutdown |
| F11.6 | SIGHUP | Same graceful shutdown |
| F11.7 | EPIPE on stdout | Readline/stdout error swallowed, does not crash |
| F11.8 | Child ENOENT | "binary not found" error, clean exit (not stack trace) |

## F12. Dashboard integration

| # | Feature | Expected |
|---|---------|---------|
| F12.1 | Tracker batching | Sends after `batchSize` events OR `flushInterval` ms |
| F12.2 | Tracker HTTPS only | `apiBase` must start with `https://` else skipped |
| F12.3 | Tracker retry | 5xx / 429 / 408 → retry up to 5 times, drop after |
| F12.4 | Tracker 4xx | Dropped (not retried) |
| F12.5 | Privacy: local-only | Zero network calls |
| F12.6 | Privacy: anonymized | `agent_name` stripped, prompt text NOT sent |
| F12.7 | Privacy: strict | Same as anonymized + no tracking at all |
| F12.8 | Privacy: full | All fields sent |
| F12.9 | Graceful degrade | No API key → `/summary` prints "No API key" hint |
| F12.10 | 401 from API | Error shown, CLI continues |
| F12.11 | Network failure | Event queued for retry, CLI continues |
| F12.12 | Final flush on exit | `beforeExit` hook runs one last flush |

## F13. Configuration & setup

| # | Feature | Expected |
|---|---------|---------|
| F13.1 | `~/.vantage/config.json` | Created on first run |
| F13.2 | Atomic write | Uses tmp + rename |
| F13.3 | Corrupt config | Warns, falls back to defaults |
| F13.4 | Setup wizard — no agents | Warns but still writes default config |
| F13.5 | Setup wizard — privacy choice | Validated, defaults to "anonymized" |
| F13.6 | Setup wizard — readline closed | Always closed in finally (no hang on error) |
| F13.7 | `/setup` in-REPL | Reloads config, replaces Tracker, no listener leak |

## F14. Safety

| # | Feature | Expected |
|---|---------|---------|
| F14.1 | Block `LD_PRELOAD` etc. | Stripped from env passed to child |
| F14.2 | `VANTAGE_PASS_ENV` | Allows named vars, still blocks dangerous ones |
| F14.3 | API key not logged | Never printed to stdout/stderr (even in debug mode) |
| F14.4 | Session IDs validated | UUIDv4 regex before persisting — no injection |
| F14.5 | Prompt size cap | 1MB stdin, output cap 5MB |

## F15. Observability & diagnostics

| # | Feature | Expected |
|---|---------|---------|
| F15.1 | `--debug` | Tracker logs flush errors, unknown agents, drops |
| F15.2 | Anomaly detection | `checkCostAnomaly` prints warning on cost spike |
| F15.3 | Tip display | Post-prompt inline tip if relevant |
| F15.4 | `/tips` command | Explicit recommendations |
| F15.5 | Version command | `cohrint --version` (if supported) — gap: verify |

## F16. Multi-prompt / multi-turn correctness

| # | Scenario | Expected |
|---|----------|---------|
| F16.1 | 5 prompts in a row | Cost monotonically increases, session continues |
| F16.2 | Agent switch mid-session | `/gemini` then prompt → uses gemini, keeps claude's session for later |
| F16.3 | Long prompt (5kb) | Optimizer runs, no truncation of optimized prompt |
| F16.4 | Multi-line paste | Lines within `PASTE_DELAY_MS` grouped into single input |
| F16.5 | `/reset` then prompt | Fresh session (no `--resume`) |
| F16.6 | `/quit` after prompts | Session summary shown, tracker flushed |

---

## Test prompts (multi-level)

Used in the audit's live-run phase (F2, F5, F16):

- **Simple**: `"what is 2+2"` — numeric answer, ~10 tokens out
- **Code**: `"write a haiku about recursion"` — short creative
- **Tool-heavy** (Claude only): `"list files in /tmp"` — exercises `⏺ Bash` rendering
- **Long**: `"explain CAP theorem in 500 words"` — streaming + anomaly check
- **Structured** (optimizer skip): `'{"key":"value","num":42}'` — should NOT optimize
- **Multi-turn**: `"remember the number 47"` then `"what number did I tell you"` — session continuation
- **Heredoc**: `cohrint <<< "multi\nline\nprompt"` — stdin path

---

## Audit loop exit criteria

For each F-item:
- ✅ **Pass** = behavior matches Expected, verified by shell test OR direct code reading
- ❌ **Fail** = bug found → fix → rerun that item
- ⚠️ **Skip** = not testable in this env (e.g. aider not installed) — note it, don't block

Loop terminates when **two consecutive full sweeps report zero failures**.
