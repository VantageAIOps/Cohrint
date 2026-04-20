# cohrint-cli — Test Specification (audit harness)

Companion to `SPEC.md`. Every F-item gets at least one concrete test with: exact command, expected output, verification rule, cleanup. Tests are grouped so the audit loop can run them as a batch and score pass/fail.

---

## 0. Environment setup (run once)

### 0.1 Preflight — required tooling
```bash
which claude codex gemini expect script node
node --version        # must be >= 18 (uses AbortSignal.timeout, Array#find via ES2022)
```
**Expected:** all 6 resolve; node ≥ 18.

### 0.2 Build the CLI fresh
```bash
cd cohrint-cli && npm run build
```
**Expected:** `dist/index.js` created, no errors.

### 0.3 Install `cohrint` as a local symlink (so tests use the built binary)
```bash
cd cohrint-cli && npm link
which cohrint        # should point into global npm bin
cohrint --version 2>&1 || head -1 dist/index.js   # verify binary resolves
```

### 0.4 Backup existing user config
```bash
cp -n ~/.vantage/config.json ~/.vantage/config.json.audit-backup 2>/dev/null || true
cp -n ~/.vantage/session.json ~/.vantage/session.json.audit-backup 2>/dev/null || true
```

### 0.5 Install test config (uses cohrint API, tracking on, anonymized)
```bash
cat > ~/.vantage/config.json <<'JSON'
{
  "defaultAgent": "claude",
  "agents": {
    "claude":  { "command": "claude",  "model": "claude-sonnet-4-6" },
    "codex":   { "command": "codex",   "model": "gpt-4o" },
    "gemini":  { "command": "gemini",  "model": "gemini-2.0-flash" }
  },
  "vantageApiKey": "__API_KEY_PLACEHOLDER__",
  "vantageApiBase": "https://api.cohrint.com",
  "privacy": "anonymized",
  "optimization": { "enabled": true },
  "tracking": { "enabled": true, "batchSize": 5, "flushInterval": 3000 }
}
JSON
```
**Note:** `__API_KEY_PLACEHOLDER__` replaced at test time from the user-provided key. Never committed, never echoed.

### 0.6 Reset session state
```bash
rm -f ~/.vantage/session.json
```

### 0.7 Preflight — agent authentication
```bash
claude -p "reply with just the word OK" 2>&1 | head -20
codex  "reply with just the word OK" 2>&1 | head -20
gemini -p "reply with just the word OK" 2>&1 | head -20
```
**Expected:** each prints something containing "OK" or an affirmative short response. No "Not logged in" / "Please run /login" / "authentication" errors.

---

## 1. Test helpers

### 1.1 Bash assertion helper — saved to `/tmp/cohrint-audit/assert.sh`
```bash
mkdir -p /tmp/cohrint-audit
cat > /tmp/cohrint-audit/assert.sh <<'SH'
#!/usr/bin/env bash
PASS=0; FAIL=0
pass() { PASS=$((PASS+1)); printf "  ✓ %s\n" "$1"; }
fail() { FAIL=$((FAIL+1)); printf "  ✗ %s\n" "$1"; printf "    %s\n" "$2"; }
report() { printf "\n=== %d pass, %d fail ===\n" "$PASS" "$FAIL"; [ "$FAIL" -eq 0 ]; }
SH
source /tmp/cohrint-audit/assert.sh
```

### 1.2 Expect helper — REPL interaction template
```tcl
#!/usr/bin/env expect -f
set timeout 30
spawn cohrint
expect "cohrint "
send -- "/help\r"
expect "cohrint "
send -- "/quit\r"
expect eof
```
Saved variants under `/tmp/cohrint-audit/expect/<test-id>.exp`.

---

## 2. Test cases

Convention:
- **T-F1.1** = test for SPEC item F1.1
- **Precond** = state that must hold before running
- **Cmd** = exact command(s)
- **Expect** = expected output or state
- **Verify** = how to measure pass/fail programmatically
- **Cleanup** = restore state for next test

---

### F1 — Invocation modes

#### T-F1.1 — REPL starts and exits cleanly
**Precond:** fresh session.json absent.
**Cmd (expect script):**
```expect
spawn cohrint
expect { "cohrint " { } timeout { exit 1 } }
send -- "/quit\r"
expect eof
```
**Expect:** banner containing "Cohrint CLI", prompt `cohrint [claude] >`, session summary on quit.
**Verify:** `exit 0` from expect.

#### T-F1.2 — One-shot prompt via arg
**Cmd:** `cohrint --agent claude "reply with just: FOURTY-TWO"`
**Expect:** stdout contains `FOURTY-TWO` (or similar literal answer); exit 0; cost summary printed.
**Verify:** `grep -i 'FOURTY-TWO'` returns 0.

#### T-F1.3 — One-shot via stdin pipe
**Cmd:** `echo "reply with just: OK" | cohrint --agent claude`
**Expect:** stdout contains `OK`; exit 0.

#### T-F1.4 — One-shot via heredoc
**Cmd:** `cohrint --agent claude <<< "reply: PING"`
**Expect:** stdout contains `PING`.

#### T-F1.5 — Empty stdin
**Cmd:** `: | cohrint`
**Expect:** exit 0, no agent spawned (`ps` check inside a wrapper: no `claude` child created).
**Verify:** output ends without any model response.

#### T-F1.6 — Large stdin (>1MB)
**Cmd:** `head -c 1500000 /dev/urandom | base64 | cohrint --agent claude --no-optimize 2>&1 | head -50`
**Expect:** stderr contains `prompt truncated at 1MB`; exit 0.

#### T-F1.7 — First-run setup wizard (TTY)
**Precond:** move config aside (`mv ~/.vantage/config.json ~/.vantage/config.json.stash`)
**Cmd (expect):** `spawn cohrint; expect "Welcome to Cohrint CLI"; send "\r\r\r"` (accept defaults)
**Expect:** writes `~/.vantage/config.json` with `defaultAgent` set.
**Cleanup:** `mv ~/.vantage/config.json.stash ~/.vantage/config.json`.

#### T-F1.8 — First-run non-TTY
**Precond:** config absent.
**Cmd:** `echo "" | cohrint`
**Expect:** does NOT prompt, uses DEFAULT_CONFIG, exits 0 without blocking.

---

### F2 — Agent support

#### T-F2.1 — Claude live
**Cmd:** `cohrint --agent claude "what is 2+2? reply with one number only"`
**Expect:** stdout contains `4`; session.json gains claude uuid.
**Verify:** `jq -r '.sessionIds.claude' ~/.vantage/session.json` matches UUID regex.

#### T-F2.2 — Codex live
**Cmd:** `cohrint --agent codex "what is 2+2? reply with one number only"`
**Expect:** stdout contains `4`.

#### T-F2.3 — Gemini live
**Cmd:** `cohrint --agent gemini "what is 2+2? reply with one number only"`
**Expect:** stdout contains `4`.

#### T-F2.4 / T-F2.5 — Aider / ChatGPT detection (not installed locally)
**Cmd (expect REPL):** `send "/agents\r"`
**Expect:** aider and chatgpt shown with `✗`, not `✓`. No crash.

#### T-F2.6 — Agent detection accurate
**Cmd (expect REPL):** `send "/agents\r"`
**Expect:** claude/codex/gemini all `✓`; aider/chatgpt `✗`.

#### T-F2.7 — Missing agent one-shot
**Cmd:** `cohrint --agent aider "hi" 2>&1 | head -5`
**Expect:** message starts with `Error running Aider:` or `'aider' not found`; exit non-zero OR 0 (document which). No stack trace.

#### T-F2.8 — Unknown agent name
**Cmd:** `cohrint --agent foobar "hi" 2>&1 | head -5`
**Expect:** falls back to claude (ALL_AGENTS[0]) and runs, OR shows clear "Unknown agent". Document actual behavior.

---

### F3 — Slash commands (REPL — expect-driven)

Each below is an expect script skeleton. Test ID shown before the `send` line.

```expect
spawn cohrint
expect "cohrint "
# T-F3.1
send "/help\r"
expect { "Cohrint Commands" { } timeout { puts FAIL_HELP; exit 1 } }
expect "cohrint "
# T-F3.2
send "/cost\r"
expect { "Session Summary" { } timeout { puts FAIL_COST; exit 1 } }
expect "cohrint "
# T-F3.3
send "/agents\r"
expect { "Claude Code" { } timeout { puts FAIL_AGENTS; exit 1 } }
expect "cohrint "
# T-F3.4
send "/default gemini\r"
expect { "Default agent set to Gemini" { } timeout { puts FAIL_DEF; exit 1 } }
expect "cohrint "
# T-F3.5
send "/default zzz\r"
expect { "Unknown agent" { } timeout { puts FAIL_DEFBAD; exit 1 } }
expect "cohrint "
# T-F3.10
send "/tips\r"
expect { "cohrint " { } timeout { puts FAIL_TIPS; exit 1 } }
# T-F3.11
send "/status\r"
expect { "Agent:" { } timeout { puts FAIL_STATUS; exit 1 } }
expect "cohrint "
# T-F3.14
send "/login\r"
expect { "not logged in" { } timeout { puts FAIL_LOGIN; exit 1 } }
expect "cohrint "
# T-F3.18
send "/zzz-nope\r"
expect { "Unknown command" { } timeout { puts FAIL_UNKNOWN; exit 1 } }
expect "cohrint "
# T-F3.19
send "\r"
expect "cohrint "
# T-F3.15
send "/quit\r"
expect eof
```

#### T-F3.6 — /compare live
**Cmd (expect):** `send "/compare reply with just: X\r"` — requires ≥2 agents authenticated
**Expect:** table rendered, sorted by cost, with at least 2 rows.

#### T-F3.7 — /compare no prompt
**Cmd (expect):** `send "/compare\r"`
**Expect:** Since empty suffix doesn't match `/compare <prompt>` regex, falls through. Must not crash. Document actual behavior.

#### T-F3.8 — /summary live (needs API key)
**Precond:** `config.vantageApiKey` set.
**Cmd (expect):** `send "/summary\r"`
**Expect:** `Dashboard Summary` header; numeric fields (today spend, mtd spend, 30d spend).

#### T-F3.9 — /budget live (needs API key)
**Cmd (expect):** `send "/budget\r"`
**Expect:** either `Budget Status` block OR `No budget set` message. No crash.

#### T-F3.12 — /reset
**Cmd (expect):** `send "/reset\r"` then in new shell: `ls ~/.vantage/session.json`
**Expect:** "Session reset" message; session.json absent OR empty.

#### T-F3.13 — /setup in REPL
**Cmd (expect):** `send "/setup\r"` + answer prompts
**Expect:** "Configuration saved" message; REPL continues (not crashed); subsequent `/cost` works.

#### T-F3.16 — /<agent> switch
**Cmd (expect):** `send "/codex\r"` → expect `Switched to Codex CLI`. Prompt prefix changes.

#### T-F3.17 — /<agent> <prompt> routing
**Cmd (expect):** `send "/gemini reply with: GEM\r"`
**Expect:** output contains `GEM`; default agent unchanged (prompt prefix still shows prior agent).

---

### F4 — Command-line flags

#### T-F4.1 — `--agent`
Covered by T-F2.1/2.2/2.3.

#### T-F4.2 — `--model`
**Cmd:** `cohrint --agent claude --model claude-haiku-4-5 "reply: MDL" 2>&1 | head -50`
**Expect:** exit 0; output has `MDL`. Model forwarded (verify by process tree? or trust pass-through — code-read verify).
**Verify (code):** grep in index.ts: `if (flags.model) extraAgentFlags.push("--model", flags.model)` — confirmed.

#### T-F4.3 — `--system`
**Cmd:** `cohrint --agent claude --system "always reply in CAPS" "say hello"`
**Expect:** output all caps (or majority caps).

#### T-F4.4 — `--no-optimize`
**Cmd:** `cohrint --agent claude --no-optimize "please kindly explain what 2+2 is in great detail"`
**Expect:** NO line starting with `Optimized:` in output (optimizer skipped).

#### T-F4.5 — `--timeout`
**Cmd:** `cohrint --agent claude --timeout 1 "write a 2000 word essay on AI" 2>&1 | head -20`
**Expect:** stderr contains `timed out after 1s`; process exits within 2s wall time.
**Verify:** `time` the command; assert < 3s.

#### T-F4.6 — `--debug`
**Cmd:** `cohrint --agent claude --debug "hi" 2>&1 | grep -i '\[vantage\]'`
**Expect:** at least one `[vantage]` debug line in stderr.

#### T-F4.7 — `--paste-delay`
**Cmd (expect with short delay):** set `VANTAGE_PASTE_DELAY=20`, paste 2 lines within 15ms
**Expect:** treated as 2 separate prompts (not bundled).

#### T-F4.8 — Unknown flag passthrough
**Cmd:** `cohrint --agent claude --some-future-claude-flag val "hi" 2>&1`
**Expect:** agent receives `--some-future-claude-flag val`; agent may error but CLI wrapper doesn't reject unknown flag itself.

---

### F5 — Live rendering

#### T-F5.1 — Token streaming visible
**Cmd:** `cohrint --agent claude "count from 1 to 5, one number per line, slowly"`
**Expect:** output appears incrementally (not all at once at end). **Verify:** write a wrapper that captures timestamps per stdout chunk; assert time delta > 200ms between first and last chunk for a 5-token-minimum prompt.

#### T-F5.2 — Tool-use display (Claude only)
**Cmd:** `cohrint --agent claude "run 'ls /tmp' using the Bash tool and tell me what you see"`
**Expect:** stdout contains `⏺ Bash(` prefix from renderer (if Claude CLI allows it — depends on login).

#### T-F5.3 — Tool-result rendering
Paired with T-F5.2: `⎿` prefix present.

#### T-F5.4 — Spinner visible
**Cmd:** `cohrint --agent claude "reply slowly" 2>&1 | cat`
**Expect:** stderr contains `Thinking...` frame at least once. Note: `cat` keeps stderr separate, so use `2>&1` to merge.

#### T-F5.5 — Spinner suppressed non-TTY
**Cmd:** `cohrint --agent claude "hi" </dev/null 2>/tmp/cohrint-audit/stderr.txt`
**Expect:** `/tmp/cohrint-audit/stderr.txt` has NO spinner frames (`⢋⢙⢹` chars absent).

#### T-F5.6 — ANSI colors only on TTY
**Cmd:** `cohrint --agent claude "hi" 2>&1 | cat > /tmp/cohrint-audit/out.txt`
**Expect:** output file has NO ANSI escapes (`\x1b[` absent). Re-run with `script -q /dev/null cohrint ...`; expect escapes present.

#### T-F5.7 — 5MB output cap
**Cmd:** `cohrint --agent claude "print the letter A 10 million times" 2>&1 | head -100`
**Expect:** stderr contains `Output truncated at 5MB`.

#### T-F5.8 — Backpressure (code-read only)
**Verify:** `runner.ts` contains `if (!ok) { child.stdout?.pause(); process.stdout.once("drain", () => child.stdout?.resume()); }` at flush — present at runner.ts:~356-359. **Pass by code-read.**

#### T-F5.9 — Stderr passthrough
**Cmd (with a fake agent):** harder to test live. Substitute via `VANTAGE_PASS_ENV` + a shell script agent.
**Alternative code-read:** stderr handler in runAgent forwards `process.stderr.write(chunk)` unless it matches suppression pattern.

#### T-F5.10 — Error message suppression
**Precond:** set a stale session ID: `echo '{"sessionIds":{"claude":"00000000-0000-0000-0000-000000000000"},"allowedTools":[]}' > ~/.vantage/session.json`
**Cmd (expect REPL):** send a prompt that uses `--resume`
**Expect:** user sees `Session expired — starting fresh` + answer. Does NOT see `No conversation found with session ID`.

---

### F6 — Prompt optimization

#### T-F6.1 — Auto-optimize prose
**Cmd:** `cohrint --agent claude "could you please kindly just explain what 2+2 equals in the most simple and direct way possible?" 2>&1 | grep -E "Optimized|saved"`
**Expect:** line like `Optimized: N -> M tokens (saved X, -Y%)` printed.

#### T-F6.2 — Skip structured data
**Cmd:** `cohrint --agent claude '{"question": "what is 2+2"}' 2>&1 | grep -E "Optimized"`
**Expect:** NO optimization line (heuristic detected JSON).

#### T-F6.3 — --no-optimize override (covered by T-F4.4)

#### T-F6.4 — Savings aggregate
**Cmd (expect REPL):** run 2 prose prompts, then `/cost`.
**Expect:** `Tokens saved: N` line where N > 0.

---

### F7 — Cost tracking

#### T-F7.1 — Per-prompt cost printed
**Cmd:** `cohrint --agent claude "hi" 2>&1 | grep -E "Cost:|Session total"`
**Expect:** 2 lines.

#### T-F7.2 — Session aggregates
**Cmd (expect):** 2 prompts + `/cost`. **Expect:** `Total cost: $X` where X > 0.

#### T-F7.3 — Real total_cost_usd used
**Verify (code):** runner.ts `flushLine` parses `obj["total_cost_usd"]` from Claude's result line → `capturedCostUsd`. **Check:** grep confirms.

#### T-F7.4 — Fallback pricing
**Cmd:** `cohrint --agent codex "hi"` (codex likely doesn't emit `total_cost_usd`). **Expect:** cost printed via `pricing.ts` estimate, non-zero.

#### T-F7.5 — No cost summary on failed call
**Precond:** logout of claude (or mock by pointing `agents.claude.command` to `/bin/false`).
**Alternative:** Set a stale session and check first call with auth failure suppressed — skip cost. **Expect:** no "+----- Cost Summary -----+" block printed.

#### T-F7.6 — No double-count
**Cmd (expect REPL):** `/setup` (accept all defaults), then prompt "hi", then `/cost`. **Expect:** promptCount == 1 (not 2). **Verify:** grep `Prompts: 1` in output.

---

### F8 — Session persistence

#### T-F8.1 — Session ID persisted
**Cmd:** `rm -f ~/.vantage/session.json && cohrint --agent claude "hi"` then `cat ~/.vantage/session.json`
**Expect:** file has `{"sessionIds":{"claude":"<uuid>"},"allowedTools":[]}`. (Note: one-shot mode does NOT persist — this test actually runs in REPL.)
**Run in REPL instead (expect):** `/quit` after one prompt; then inspect file.

#### T-F8.2 — Resume next run
**Cmd (expect 2 sessions):** first REPL prompt "remember X=42", `/quit`. Second REPL prompt "what was X", `/quit`. **Expect:** response contains `42` (session continuation).

#### T-F8.3 — Stale session retry
**Precond:** `echo '{"sessionIds":{"claude":"00000000-0000-0000-0000-000000000000"},"allowedTools":[]}' > ~/.vantage/session.json`
**Cmd (expect REPL):** send prompt.
**Expect:** output contains `Session expired — starting fresh`; prompt answered normally; session.json now has a real uuid.

#### T-F8.4 — /reset wipes state (expect REPL):
Send `/reset`. Check `ls ~/.vantage/session.json` afterwards (file must be gone).

#### T-F8.5 — Old sessions migration
**Precond:** `mkdir -p ~/.vantage/sessions && echo '{"claude":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}' > ~/.vantage/sessions/active.json && rm -f ~/.vantage/session.json`
**Cmd:** start REPL (it runs `migrateOldSessions` on startup).
**Expect:** new session.json contains the old claude UUID; old file deleted.

#### T-F8.6 — Corrupt session.json tolerated
**Precond:** `echo 'not json' > ~/.vantage/session.json`
**Cmd:** start REPL.
**Expect:** no crash; `loadState` returns empty defaults.

---

### F9 — Permissions flow

#### T-F9.1 — Permission prompt shown on denial
Difficult to force without Claude's actual permission denial. Skip unless we can mock. **Code-read:** `executeWithPermissions` handles `permission_denials` array from runner. **Pass by inspection.**

#### T-F9.2/3/4 — yes/always/no flows
Interactive; cover via expect if possible by asking Claude to use a tool without prior approval. Document whether mock-able; else mark `code-read only`.

#### T-F9.5 — Retry preserves flags
**Code-read:** retry in `executeWithPermissions` uses same `currentFlags` + `retryTools`.

#### T-F9.6 — Allowed tools persisted
**Cmd:** After a successful "always" approval (expect), `/quit`, inspect `~/.vantage/session.json` — `allowedTools` contains tool name.

---

### F10 — Auth / login errors

Since all agents are authenticated, we SIMULATE failure by pointing at a non-authed stub.

#### T-F10.1 — Claude simulated logout
**Precond:** create stub `/tmp/cohrint-audit/fake-claude` that prints `Not logged in · Please run /login` to stdout and exits 1. Then update config `agents.claude.command` to `/tmp/cohrint-audit/fake-claude`.
**Cmd:** `cohrint --agent claude "hi" 2>&1`
**Expect:** user sees only `⚠ Claude Code is not logged in.` (clean message). Does NOT see raw "Not logged in" OR cost summary.
**Cleanup:** restore config.

#### T-F10.2/3 — Repeat with fake codex, fake gemini. **Expect:** same clean handling.

#### T-F10.4 — No cost summary
**Verify:** output of T-F10.1 does not contain `+----- Cost Summary -----+`.

#### T-F10.5 — Session not persisted
**Verify:** after T-F10.1, `jq -r '.sessionIds.claude' ~/.vantage/session.json` returns null / unchanged.

#### T-F10.6 — REPL continues
**Cmd (expect):** send prompt → auth fail → send another prompt. **Expect:** second prompt is accepted (REPL not terminated).

#### T-F10.7 — One-shot exits 1
**Cmd:** `cohrint --agent claude "hi"; echo "EXIT=$?"` with fake claude.
**Expect:** `EXIT=1`.

---

### F11 — Timeouts & process lifecycle

#### T-F11.1 — Default timeout honored
**Cmd:** set `VANTAGE_TIMEOUT=2000` and run a long prompt.
**Expect:** `timed out after 2s`.

#### T-F11.2 — --timeout CLI flag
Covered by T-F4.5.

#### T-F11.3 — SIGTERM then SIGKILL
**Cmd:** start a long-running claude prompt; observe child pid; verify SIGTERM first then SIGKILL after grace (10% of timeout, capped 10s). **Verify:** `ps` after timeout — no zombie.

#### T-F11.4 — Ctrl+C in REPL
**Cmd (expect):** send `\x03` (SIGINT). **Expect:** session summary printed; process exits 0.

#### T-F11.5 — SIGTERM to parent
**Cmd:** `cohrint & pid=$!; sleep 1; kill -TERM $pid; wait $pid`
**Expect:** exit 0; session summary printed.

#### T-F11.6 — SIGHUP
Same as T-F11.5 with SIGHUP.

#### T-F11.7 — EPIPE on stdout
**Cmd:** `cohrint --agent claude "print 1 to 1000" | head -1`
**Expect:** no crash, no "EPIPE" in stderr.

#### T-F11.8 — Child ENOENT
**Cmd:** update config so `agents.claude.command = "/nonexistent-bin"`. Run `cohrint --agent claude "hi"`.
**Expect:** clean "not found" message, no stack trace.
**Cleanup:** restore config.

---

### F12 — Dashboard integration (live — sends real events)

#### T-F12.1 — Event batching
**Precond:** `batchSize: 5, flushInterval: 3000`. Set `--debug`.
**Cmd:** run 5 prompts rapidly in REPL.
**Expect:** debug logs show 1 flush (not 5).

#### T-F12.2 — HTTPS gate
**Precond:** set `vantageApiBase` to `http://api.cohrint.com`.
**Cmd:** `cohrint --debug "hi"`.
**Expect:** stderr contains `Skipping tracking: API base is not HTTPS`.

#### T-F12.3 — 5xx retry
Hard to test without a mock server. **Code-read:** tracker.ts retry path verified.

#### T-F12.4 — 4xx drop
Same — **code-read**.

#### T-F12.5 — Privacy local-only
**Precond:** set `privacy: "local-only"`.
**Cmd:** `cohrint --agent claude --debug "hi" 2>&1 | grep -E "POST|fetch|events"`
**Expect:** NO network call attempt visible.

#### T-F12.6 — Privacy anonymized
**Precond:** `privacy: "anonymized"`.
**Verify (code):** tracker.ts enqueue sets `event.agent_name = "anonymous"`.

#### T-F12.7 — Privacy strict
Same as anonymized per current code. **Note as ambiguous** — SPEC says "no tracking at all" but tracker.ts only strips fields. **Potential bug.**

#### T-F12.8 — Privacy full
**Precond:** `privacy: "full"`.
**Verify (code):** tracker does NOT strip `agent_name`.

#### T-F12.9 — Graceful degrade no key
**Precond:** `vantageApiKey: ""`.
**Cmd (expect):** `/summary`. **Expect:** `No API key configured` message.

#### T-F12.10 — 401 handled
**Precond:** `vantageApiKey: "crt_invalidkey"`.
**Cmd (expect):** `/summary`. **Expect:** `Failed to fetch dashboard` message; no crash.

#### T-F12.11 — Network failure queued
Harder to test live. **Code-read:** `catch (err)` in flush unshifts back to queue.

#### T-F12.12 — Final flush on exit
**Cmd:** run 2 prompts, `/quit`. **Verify:** events visible on dashboard for this session.

---

### F13 — Config & setup

#### T-F13.1 — Config created on first run
Covered by T-F1.7.

#### T-F13.2 — Atomic write
**Verify (code):** config.ts saves to `path + ".tmp"` then renames. **Pass by code-read.**

#### T-F13.3 — Corrupt config tolerated
**Precond:** `echo 'broken json' > ~/.vantage/config.json`
**Cmd:** `cohrint --agent claude "hi" 2>&1 | head -5`
**Expect:** stderr contains `Config corrupted, using defaults`; CLI continues.

#### T-F13.4 — Setup wizard with no agents installed
**Precond:** temporarily rename `claude codex gemini` binaries (or use PATH manipulation).
**Cmd (expect):** run `runSetup`. **Expect:** warning shown; config still written.

#### T-F13.5 — Privacy choice validated
**Cmd (expect setup):** answer `banana` for privacy. **Expect:** falls back to `anonymized`.

#### T-F13.6 — Readline closed on error
**Verify (code):** setup.ts uses try/finally around `rl.close()`. **Pass by code-read.**

#### T-F13.7 — /setup in REPL no listener leak
**Cmd (expect):** run `/setup` twice, then one prompt. **Verify:** cost summary printed ONCE (not twice), via T-F7.6 pattern.

---

### F14 — Safety

#### T-F14.1 — Block LD_PRELOAD
**Cmd:** `LD_PRELOAD=/tmp/evil.so cohrint --agent claude "hi"` (even if /tmp/evil.so absent) — observe child env.
**Verify (code):** runner.ts `buildSafeEnv` strips `LD_PRELOAD`. **Pass by code-read.**

#### T-F14.2 — VANTAGE_PASS_ENV allows named vars
**Cmd:** `VANTAGE_PASS_ENV=MY_VAR MY_VAR=xx cohrint "print MY_VAR from env"` — indirect.
**Verify (code):** buildSafeEnv logic.

#### T-F14.3 — API key not logged
**Precond:** set API key to `crt_test_secret_abc123`.
**Cmd:** `cohrint --debug "hi" 2>&1 | grep -c "crt_test_secret_abc123"`.
**Expect:** count == 0.

#### T-F14.4 — Session ID regex validated
**Verify (code):** `isValidSessionId` in runner.ts uses `/^[0-9a-f]{8}-.../i`.
**Cmd (inject invalid):** `echo '{"sessionIds":{"claude":"not a uuid"},"allowedTools":[]}' > ~/.vantage/session.json && cohrint` — expect it to ignore the invalid id.
**Expect:** claude prompt works (no `--resume not a uuid` passed). **Verify:** `ps -ef | grep claude` during run.

#### T-F14.5 — Size caps
1MB stdin tested by T-F1.6; 5MB stdout by T-F5.7.

---

### F15 — Observability

#### T-F15.1 — --debug emits logs
Covered by T-F4.6.

#### T-F15.2 — Anomaly detection
**Cmd (expect):** run a tiny prompt ($0.0001), then a huge one ($0.05+). **Expect:** anomaly warning on the 2nd.
**Alternative:** mock `checkCostAnomaly` threshold — code-read.

#### T-F15.3 — Inline tip
**Verify (code):** `showInlineTip()` called after each prompt.

#### T-F15.4 — /tips command
Covered by T-F3.10.

#### T-F15.5 — --version flag
**Cmd:** `cohrint --version` — **likely gap.**
**Expect:** prints `2.2.5`. If not implemented → **bug**.

---

### F16 — Multi-prompt correctness

#### T-F16.1 — 5 prompts in a row
**Cmd (expect):** send 5 "hi N" prompts. **Expect:** after each, session total cost increases monotonically; promptCount reaches 5.

#### T-F16.2 — Agent switch mid-session
**Cmd (expect):** prompt claude "remember X=1"; `/gemini`; prompt gemini "say HI_GEM"; `/claude`; prompt "what was X". **Expect:** claude recalls X=1 (session preserved per-agent).

#### T-F16.3 — Long prompt
**Cmd:** generate 5KB prose, send. **Expect:** response arrives; optimizer either optimized or skipped based on heuristic.

#### T-F16.4 — Multi-line paste
**Cmd (expect):** send 3 lines within 50ms. **Expect:** treated as single prompt (bundle).

#### T-F16.5 — /reset then fresh prompt
**Cmd (expect):** prompt, `/reset`, prompt. **Expect:** second uses no `--resume` (fresh session_id in session.json).

#### T-F16.6 — /quit flushes tracker
**Cmd (expect):** 2 prompts, `/quit`. **Verify:** dashboard shows the 2 events.

---

## 3. Scoreboard

For each F-item the audit script outputs one of:
- `PASS` — test ran and matched Expected
- `FAIL: <short reason>`
- `SKIP: <why>` (e.g. "codex not installed")
- `CODE-READ: <file:line>` (verified by inspection only)

A sweep is **clean** when FAIL count == 0. Loop stops after **2 consecutive clean sweeps**.

## 4. Cleanup (run at end of entire audit)

```bash
mv ~/.vantage/config.json.audit-backup ~/.vantage/config.json 2>/dev/null || true
mv ~/.vantage/session.json.audit-backup ~/.vantage/session.json 2>/dev/null || true
rm -rf /tmp/cohrint-audit
```

## 5. Known limitations of this test harness

- F9 (tool permission flow) — partially code-read only; hard to force Claude into a real denial scenario
- F11.3 (SIGKILL escalation) — requires process observation; may be flaky on slow systems
- F12.11 (network failure retry) — requires proxy/mock
- F15.2 (anomaly) — threshold-dependent; may not fire on small test spend

These get marked `CODE-READ` rather than `FAIL`.

## 6. Proceed checklist (what I need from you)

- [ ] Confirm all 3 agents (claude/codex/gemini) respond to `-p "hi"` (per 0.7) → if not, say which fails
- [ ] Paste the cohrint API key for §0.5 replacement
- [ ] Confirm `api.cohrint.com` is the production endpoint (vs the current `api.vantageaiops.com`)
- [ ] OK to proceed sending ~20 live events to the dashboard during this audit

Once all four ticked, I start the audit loop.
