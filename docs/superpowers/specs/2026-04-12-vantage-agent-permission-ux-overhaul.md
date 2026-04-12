# Vantage Agent — Permission Granularity & UX Overhaul

**Date:** 2026-04-12  
**Status:** Implemented — see plan `docs/superpowers/plans/2026-04-12-vantage-agent-permission-ux-overhaul.md`  
**Scope:** vantage-agent CLI — all dimensions: permissions, Claude CLI backend, installation, upgrade, config, sessions, stability

---

## Problem Statement

Users with Claude Max subscriptions cannot use `vantageai-agent` without an Anthropic API key.  
The `ClaudeBackend` exists but is broken for multi-turn tasks.  
The permission system works for the API backend but has no equivalent for the Claude CLI backend.  
Enterprise clients need per-call, auditable tool permissions with consistent UX across all backends.

This document captures every known flaw across all CLI dimensions and defines the design for a unified fix.

---

## Section 1 — Architecture Disconnect (Root Cause)

Two parallel execution paths exist and diverge silently:

```
Path A (working):
  cli.py → _build_client() → AgentClient (api_client.py)
    → hardwired Anthropic API
    → PermissionManager (in-process, per-call)
    → exact token counts, real cost
    → REQUIRES API key with credits

Path B (broken):
  backends/__init__.py → auto_detect_backend()
    → correctly detects: ANTHROPIC_API_KEY → claude CLI → codex → gemini
    → NEVER CALLED by cli.py
    → ClaudeBackend: single-shot subprocess, fake token counts, no tool loop
    → --backend flag parsed but ignored in _build_client()
```

`auto_detect_backend()` is correct logic that goes unused. `ClaudeBackend` is architecturally broken. The fix is not to patch Path B — it's to rebuild it using `claude -p --output-format stream-json`.

---

## Section 2 — Confirmed Flaws by Dimension

### 2.1 — Permission System

| ID | Flaw | Severity | File |
|----|------|----------|------|
| P1 | ClaudeBackend has no permission layer — all tools run without user consent | Critical | backends/claude_backend.py |
| P2 | PermissionManager is in-process only — no equivalent for subprocess backends | Critical | permissions.py |
| P3 | `Bash` treated as single approval unit — `cat README` and `rm -rf /` are identical to the permission system | Critical | permissions.py:112 |
| P4 | `/allow` REPL command works for API backend but cannot update a running Claude subprocess | High | cli.py:129-144 |
| P5 | Two permission stores would diverge on backend switch (permissions.json vs subprocess --allowedTools) | High | permissions.py, cli.py |
| P6 | No org-level policy enforcement — enterprise clients can't set "never allow Bash" centrally | High | — |
| P7 | No audit log of permission decisions — no timestamp, no tool input hash, no "who approved what" | High | — |
| P8 | Safe tools (Read, Glob, Grep) correctly auto-approved, but list hardcoded in tools.py SAFE_TOOLS | Low | tools.py |

### 2.2 — Claude CLI Backend Flaws

| ID | Flaw | Severity | File |
|----|------|----------|------|
| C1 | Single-shot subprocess — no multi-turn tool-use loop | Critical | backends/claude_backend.py:33 |
| C2 | History via string concatenation — loses role structure, inflates token usage | Critical | backends/claude_backend.py:30 |
| C3 | Token counts are `len(text) // 4` — fabricated, shown in dashboard as real | High | backends/claude_backend.py:41-42 |
| C4 | `start_process()` creates zombie subprocess — `send_stdin` reads with 2s timeout heuristic, gets partial output or hangs | High | backends/base.py:50-63 |
| C5 | `--backend` flag parsed in cli.py but never passed to `_build_client()` — dead code | High | cli.py:61-65, 84-92 |
| C6 | First-run message says "Claude.ai subscription does NOT grant API access" — wrong for Claude Max / Claude Code CLI users | High | api_client.py:44-46 |
| C7 | Cost display shows fabricated API-equivalent numbers without labelling them as estimates | Medium | backends/claude_backend.py:43 |
| C8 | `--bare` flag not used when spawning claude subprocess — VantageAI hooks fire twice (once from claude subprocess, once from main process) | Medium | — |

### 2.3 — Installation & First-Run

| ID | Flaw | Severity | File |
|----|------|----------|------|
| I1 | API key saved as plaintext to `~/.vantage-agent/api_key` with mode 0o600 — no encryption | Critical | api_client.py:54-58 |
| I2 | No first-run wizard — user hits a ValueError error message, not a guided setup | High | api_client.py:89-101 |
| I3 | Config directory split across `~/.vantage` and `~/.vantage-agent` — inconsistent | Medium | session_store.py:11, permissions.py:21 |
| I4 | Config paths hardcoded — no `VANTAGE_CONFIG_DIR` override, fails on read-only home dirs | Medium | session_store.py:11 |
| I5 | No XDG Base Directory support (`$XDG_CONFIG_HOME`, `$XDG_DATA_HOME`) | Low | — |
| I6 | Backend auto-detection (`auto_detect_backend()`) never called — Claude Max users can't get in | Critical | backends/__init__.py:21-45 |

### 2.4 — Versioning & Upgrade

| ID | Flaw | Severity | File |
|----|------|----------|------|
| V1 | Version string duplicated in 4 places — `__init__.py`, `cli.py` BANNER, `telemetry.py`, `tracker.py` | High | all |
| V2 | No upgrade handler — format changes in session JSON or permissions.json will silently break or corrupt | High | — |
| V3 | No schema version field in any persisted JSON file | High | session_store.py, permissions.py |
| V4 | No automatic pricing update — `PRICING_UPDATED` date check will auto-fail tests in ~76 days | Medium | pricing.py:7 |
| V5 | No version check on startup — user running outdated CLI gets no warning | Low | — |

### 2.5 — Session Management

| ID | Flaw | Severity | File |
|----|------|----------|------|
| S1 | Sessions never cleaned up — `~/.vantage/sessions/` grows unbounded | Medium | session_store.py |
| S2 | No file locking in SessionStore — concurrent processes corrupt same session | High | session_store.py:26-28 |
| S3 | `get_global_budget_used()` reads ALL session files on every prompt — O(N) per turn | High | rate_limiter.py:75-84 |
| S4 | Session JSON stores full message text unencrypted — secrets/tokens in plaintext on disk | Critical | session.py:190-198 |
| S5 | Resume does not validate backend availability — resuming a session for an uninstalled backend fails at send() | Medium | cli.py:333 |
| S6 | `last_active_at` not set correctly — session.py save() writes `created_at` on every save (stale for listing) | Low | session.py:196 |
| S7 | History trimming silently drops context — user gets no warning when history is truncated | Medium | session.py:26-31 |

### 2.6 — Rate Limiting

| ID | Flaw | Severity | File |
|----|------|----------|------|
| R1 | Rate limit parameters hardcoded (60 req/min, 60 capacity) — no config override | Low | rate_limiter.py:47 |
| R2 | Race condition on first-run file init — two concurrent processes both see empty file, second write wins | High | rate_limiter.py:38 |
| R3 | `wait_for_token()` busy-loops with fixed 0.5s sleep — no exponential backoff | Low | rate_limiter.py:66 |
| R4 | `get_global_budget_used()` called before every prompt with O(N) session scan | High | cli.py:236, rate_limiter.py:75 |

### 2.7 — Tool Execution

| ID | Flaw | Severity | File |
|----|------|----------|------|
| T1 | No input validation on tool arguments — missing required fields cause KeyError | Critical | tools.py:154-168 |
| T2 | Tool results have no size cap for content — 10MB file response can exceed API message limits | Medium | tools.py:259, 289 |
| T3 | `execute_tool()` does not sanitize `cwd` — path traversal possible if agent crafts `../../../etc` | High | tools.py |
| T4 | Bash command injection possible if agent crafts tool input with shell metacharacters in a non-shell-escaped context | High | tools.py |
| T5 | Tool denial returns string "Tool X was denied" — agent may loop trying same tool or return incoherent response | Medium | api_client.py:257-263 |

### 2.8 — CLI Interface & Stability

| ID | Flaw | Severity | File |
|----|------|----------|------|
| CL1 | `summary` subcommand detected via `sys.argv[1]` string check before argparse — breaks `vantageai-agent summary --help` | Medium | cli.py:324 |
| CL2 | `--debug` flag parsed but only passed to Tracker, not used for broader debug output | Low | cli.py:59 |
| CL3 | BANNER version hardcoded as `v0.1.0` — won't update when package is upgraded | High | cli.py:30 |
| CL4 | No `--version` flag | Medium | — |
| CL5 | No `--config` flag to point at alternate config directory | Medium | — |
| CL6 | No `--dry-run` mode to preview actions without executing | Low | — |
| CL7 | Pipe mode and REPL mode both fall through to same code path — edge cases in detection (sys.stdin.isatty()) | Low | cli.py:346-352 |
| CL8 | No shell completion support (bash/zsh/fish) | Low | — |
| CL9 | REPL has no history/readline support — can't use up-arrow to recall previous prompts | Low | cli.py:200 |
| CL10 | `/model` command switches model mid-session but doesn't recalculate cost tracker — cost attribution wrong after switch | Medium | cli.py:176-185 |

### 2.9 — Pricing & Cost Accuracy

| ID | Flaw | Severity | File |
|----|------|----------|------|
| PR1 | Unknown models silently fall back to claude-sonnet-4-6 rates — user sees wrong cost, no warning | High | pricing.py:36-44 |
| PR2 | Token estimation uses 4 chars/token for all backends — off by up to 30% for code-heavy prompts | Medium | backends/claude_backend.py:10 |
| PR3 | Pricing data is static — requires manual update every time Anthropic changes pricing | Medium | pricing.py |
| PR4 | No label distinguishing "API-equivalent cost" vs "actual API cost" for Claude CLI backend | High | — |

### 2.10 — Testing Gaps

| ID | Gap | Impact |
|----|-----|--------|
| TE1 | No test for `VantageSession.resume()` | Session corruption goes undetected |
| TE2 | No test for concurrent `SessionStore` access | Data corruption in multi-process scenarios |
| TE3 | No test for subprocess backend (ClaudeBackend, CodexBackend) | Broken backends ship silently |
| TE4 | No test for Tracker flush retry on HTTP failure | Telemetry loss undetected |
| TE5 | No test for `BudgetExceededError` in hooks | Budget enforcement untested |
| TE6 | No test for `permissions.json` corruption recovery | Bad JSON crashes CLI silently |
| TE7 | No test for pipe mode | Regression risk |
| TE8 | No test for full session lifecycle (create → send → save → resume → send) | Lifecycle regression risk |
| TE9 | No test for history trimming at exact boundary | Off-by-one in trim logic |
| TE10 | No test for rate limiter concurrent access | Race condition undetected |

---

## Section 3 — Proposed Design: Approach 1 + 4 Combined

### 3.1 — Overview

The solution has two layers:

- **Layer A (Approach 4 — Tiered Startup):** On first run or `--backend claude`, show a structured permission selection. User picks a tier. Safe tools are pre-approved. This sets session defaults.
- **Layer B (Approach 1 — PreToolUse Hook + Socket):** For every tool call not covered by the tier defaults, a hook fires. The hook communicates with the running vantage-agent via Unix socket. The user sees a per-call prompt with full input preview. Consistent across backends.

Both layers read/write the same shared permission store.

### 3.2 — Shared Permission Store

Single source of truth at `~/.vantage-agent/permissions.json`:

```json
{
  "schema_version": 1,
  "always_approved": ["Read", "Glob", "Grep"],
  "always_denied": [],
  "session_approved": [],
  "audit_log": [
    {
      "ts": "2026-04-12T10:00:00Z",
      "tool": "Bash",
      "input_hash": "sha256:...",
      "input_preview": "git status",
      "decision": "allow_session",
      "backend": "claude"
    }
  ]
}
```

**Rules:**
- `always_approved` = tools that never prompt (persists across sessions)
- `always_denied` = tools that always block (enterprise policy override)
- `session_approved` = approved for current session only (cleared on exit)
- `audit_log` = append-only, written on every permission decision
- `Bash` is NEVER in `always_approved` by default — always triggers a hook

Both `PermissionManager` (API backend) and the hook script (Claude CLI backend) read/write this file. `fcntl.flock()` for concurrent access safety.

### 3.3 — Tiered Startup (Approach 4)

Shown on first run with `--backend claude` (or when `auto_detect_backend()` returns `claude`):

```
  Vantage Agent — Tool Permissions

  Select what Claude is allowed to do:

  [1] Read-only    Read, Glob, Grep                        (safe, no prompt)
  [2] Standard     + Edit, Write                           (file changes, ask once)
  [3] Full         + Bash (shell)                          (Bash always asks per-call)
  [4] Custom       Choose tools individually

  > _
```

**Critical constraint:** Bash is NEVER in any auto-approve tier. Even "Full" still requires per-call hook approval for each Bash command. The tier only determines which file tools auto-approve.

Selection is written to `~/.vantage-agent/config.json` under `default_tier` and can be changed any time with `/tier` REPL command.

### 3.4 — PreToolUse Hook Architecture (Approach 1)

```
vantage-agent process
├── Main thread: REPL input loop
├── Thread A: subprocess stdout reader (stream-json parser)
│     └── stdout_pause_event: threading.Event
├── Thread B: Unix socket server at /tmp/vantage-perm-<pid>.sock
│     └── On connection: sets stdout_pause_event, shows permission prompt,
│           collects user input, writes to shared permission store,
│           sends decision back to hook, clears stdout_pause_event
└── Subprocess: claude -p <prompt>
      --output-format stream-json
      --verbose
      --permission-mode bypassPermissions   ← Claude Code's own UI bypassed; hooks still fire (verified)
      --resume <session_id>                 ← native conversation history
      --no-session-persistence              ← prevents CC from writing its own session file (avoids double-storage); hooks still fire (unlike --bare which kills hooks)
      --model <model>
      --settings /tmp/vantage-<pid>-settings.json  ← REPLACES user settings (verified); must merge existing hooks
            └── PreToolUse hook → ~/.vantage-agent/perm-hook.sh
                      ├── Read always_approved from permissions.json → fast-path exit 0
                      ├── Read always_denied → fast-path exit 2
                      ├── Connect to /tmp/vantage-perm-<pid>.sock
                      │     └── Send: {tool, input, session_id}
                      │     └── Recv: {decision: "allow"|"deny"|"allow_always"|"deny_always"}
                      └── Exit 0 (allow) or exit 2 (deny with reason)
```

### 3.5 — Terminal I/O Ownership

The stdout reader thread must yield the terminal when a permission prompt is needed:

```
stdout_reader thread:
  for each line in subprocess.stdout:
    if stdout_pause_event.is_set():
      buffer.append(line)          ← buffer while paused
    else:
      render(line)                 ← normal output

socket_server thread on permission request:
  stdout_pause_event.set()
  show_permission_prompt(tool, input)  ← owns terminal
  get user input
  write decision to permissions.json
  send decision to hook
  stdout_pause_event.clear()
  flush(buffer)                   ← dump buffered lines
```

No interleaving. The socket server thread owns the terminal exclusively during the prompt. Buffered lines flush after the prompt resolves, appearing as a natural continuation of output.

### 3.6 — Hook Fail Policy

The hook script must handle socket unavailability:

```bash
# Retry with backoff (covers race condition at startup)
for i in 1 2 3 4 5; do
  nc -U /tmp/vantage-perm-$PPID.sock < payload > response && break
  sleep 0.1
done

# On timeout: apply fail policy from config
if [ -z "$response" ]; then
  POLICY=$(jq -r '.hook_fail_policy // "allow"' ~/.vantage-agent/config.json)
  [ "$POLICY" = "deny" ] && exit 2 || exit 0
fi
```

Default policy: `allow` (developer mode). Enterprise default: `deny`. Set via `~/.vantage-agent/config.json` or `VANTAGE_HOOK_FAIL_POLICY` env var.

### 3.7 — Settings File Merge

Before spawning the subprocess, vantage-agent merges existing user Claude Code settings with the vantage hook:

```python
def build_session_settings(pid: int) -> dict:
    user_settings = load_user_claude_settings()  # ~/.claude/settings.json
    existing_pre_hooks = user_settings.get("hooks", {}).get("PreToolUse", [])
    vantage_hook = {
        "matcher": ".*",
        "hooks": [{"type": "command",
                   "command": f"~/.vantage-agent/perm-hook.sh",
                   "env": {"VANTAGE_SOCKET": f"/tmp/vantage-perm-{pid}.sock"}}]
    }
    merged = {**user_settings}
    merged["hooks"] = {
        **user_settings.get("hooks", {}),
        "PreToolUse": existing_pre_hooks + [vantage_hook]
    }
    return merged
```

User's existing hooks run first. Vantage hook appended last.

### 3.8 — Cost Display for Claude CLI Backend

```
  ↳ 1,204 tokens · API-equivalent: $0.0097  [Max subscription: $0.00 actual]
```

- Always label cost as "API-equivalent" for claude backend
- Show actual charge as $0.00 for Max users
- Session summary shows both: "API-equivalent total: $0.42 | Actual paid: $0.00"
- Positions it as a value metric for VantageAI: "Your Max subscription saved you $X this session"

### 3.9 — `--permission-mode bypassPermissions` Rationale

Using `bypassPermissions` instead of `--allowedTools` means:
- Our hook is the only permission gate — no duplication with Claude Code's own UI
- `/allow` REPL command writes to `permissions.json`, hook reads it on next call — immediate effect
- No subprocess restart needed when permissions change
- If `bypassPermissions` suppresses PreToolUse hooks (needs verification), fallback: use `--permission-mode default` with hook returning early and Claude Code's UI never shown (hook intercepts before CC's UI fires)

**Verification required before implementation:** Confirm PreToolUse hook fires in `bypassPermissions` mode. Test with: `claude -p "run ls" --permission-mode bypassPermissions --settings <hook-settings> --output-format json`

### 3.10 — Session ID as Conversation Anchor

Replace string-concatenated history with native `--resume`:

```python
class ClaudeCliSession:
    def __init__(self):
        self._claude_session_id: str | None = None  # from result event

    def send(self, prompt: str) -> BackendResult:
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "bypassPermissions",
               "--model", self._model, "--bare"]
        if self._claude_session_id:
            cmd += ["--resume", self._claude_session_id]
        # parse stream, extract session_id from result event
        result = self._run_and_parse(cmd)
        self._claude_session_id = result.session_id  # store for next turn
        return result
```

Conversation history is native to Claude Code's session store. No token inflation from string concatenation. History trimming handled by Claude Code internally.

---

## Section 4 — Flaws to Fix Before Implementation

These flaws must be resolved first, as they affect the foundation:

### Priority 1 — Blockers

| ID | Fix Required |
|----|-------------|
| C5 | Wire `--backend` flag through `_build_client()` to actually select backend |
| I6 | Call `auto_detect_backend()` in `_build_client()` when no API key present |
| C6 | Replace misleading first-run error message with detection of Claude Code CLI |
| P2 | Unify permission gate — both backends use same `permissions.json` |
| S2 | Add `fcntl.flock()` to `SessionStore.save()` and `load()` |
| T1 | Add input validation to `execute_tool()` — check required fields per tool |
| V3 | Add `schema_version` field to all persisted JSON files |

### Priority 2 — Required for Claude CLI Backend

| ID | Fix Required |
|----|-------------|
| C1 | Replace `ClaudeBackend.send()` with stream-json subprocess parser |
| C2 | Replace history concatenation with `--resume session_id` |
| C3 | Replace `len//4` token count with values from stream-json `usage` field |
| C4 | Remove `start_process()` / `AgentProcess` from ClaudeBackend — it's broken |
| C7 | Label all Claude CLI backend costs as "API-equivalent" |
| C8 | Pass `--bare` to subprocess (or verify hook behavior, then decide) |

### Priority 3 — Permission System

| ID | Fix Required |
|----|-------------|
| P1 | Implement PreToolUse hook script at `~/.vantage-agent/perm-hook.sh` |
| P3 | Bash never in auto-approve — always shows command preview |
| P4 | `/allow` writes to `permissions.json`, hook reads on next call |
| P6 | Org policy: check VantageAI API if `VANTAGE_API_KEY` set |
| P7 | Audit log appended on every permission decision |

### Priority 4 — Stability & Config

| ID | Fix Required |
|----|-------------|
| V1 | Single version source in `__init__.py`, read dynamically in BANNER and telemetry |
| I3 | Consolidate config to single `~/.vantage-agent/` directory |
| I4 | Add `VANTAGE_CONFIG_DIR` env var override |
| R2 | Fix rate limiter file init race — acquire lock before opening file |
| R4 | Cache `get_global_budget_used()` result with 10s TTL instead of per-prompt scan |
| S3 | Cache budget total, invalidate on session save |
| CL4 | Add `--version` flag |
| PR1 | Warn (don't silently misbill) for unknown model names |
| PR4 | Label API-equivalent costs in UI |

### Priority 5 — Post-implementation

| ID | Fix Required |
|----|-------------|
| I1 | API key encryption (keychain integration or symmetric encryption) |
| S4 | Session JSON message encryption (optional, off by default) |
| S1 | Session retention policy — auto-delete sessions older than N days |
| V4 | Pricing auto-refresh from VantageAI API |
| CL9 | readline/history support in REPL |
| TE1-TE10 | Test coverage for all identified gaps |

---

## Section 5 — What is NOT Changing

- The API backend (`AgentClient`) and its `PermissionManager` remain unchanged
- All existing CLI flags remain (backward compatible additions only)
- Session file format gains `schema_version` field but existing fields unchanged
- `VANTAGE_API_KEY` telemetry path unchanged
- All existing tests must continue to pass

---

## Section 6 — Open Questions: RESOLVED (2026-04-12)

1. **Does `PreToolUse` hook fire in `--permission-mode bypassPermissions`?**  
   ✅ **YES — confirmed by live test.**  
   Hook fires. Tool data arrives via **stdin as JSON** (not env vars):  
   `{"session_id":"...","tool_name":"Bash","tool_input":{"command":"echo hello"},"permission_mode":"bypassPermissions",...}`  
   Exit 0 = allow. Exit 2 = block. The reason string we print to stdout becomes the tool_result the model sees.  
   **Implication:** Design proceeds as written. `bypassPermissions` is the right flag.

2. **Does `--bare` suppress PreToolUse hooks?**  
   ✅ **YES — `--bare` completely suppresses all hooks.**  
   Hook log was empty when `--bare` was passed. Also: `--bare` requires `ANTHROPIC_API_KEY` strictly (no keychain/OAuth).  
   **Implication:** Do NOT use `--bare`. Use `--no-session-persistence` to prevent Claude Code from writing its own session file (avoids double-session-storage), while keeping hooks active.

3. **Does `--settings` merge or replace `~/.claude/settings.json`?**  
   ✅ **REPLACES — confirmed by live test.**  
   User has a `PreToolUse` hook for `Bash(git commit*)` in their settings. When `--settings /tmp/vantage-only.json` was passed, only the vantage hook fired — user's hook was silent.  
   **Implication:** The merge logic in §3.7 is required. At subprocess spawn, vantage-agent must read `~/.claude/settings.json`, merge existing PreToolUse hooks, write combined settings to temp file.

4. **What does the model see when hook exits 2?**  
   ✅ **Tested — the reason string is delivered as tool_result content.**  
   Hook printing `{"decision":"block","reason":"Vantage: user approval required for Bash"}` and exiting 2 caused the model to receive exactly that reason string as the tool_result. Model responded: *"A pre-tool hook is blocking Bash execution with: 'Vantage: user approval required for Bash'"* and adapted gracefully.  
   **Implication:** Denial message should be actionable: `"[Vantage] Bash denied by user. Suggest /allow Bash or try a read-only approach."` Model will pivot without looping.

5. **Rate limit events in stream-json — can we extract `resetsAt`?**  
   ✅ **Confirmed from live stream:** `{"type":"rate_limit_event","rate_limit_info":{"resetsAt":1775998800,...}}`  
   Parse and display: `"Rate limited. Resets in 4m 32s."` using `datetime.fromtimestamp(resetsAt) - datetime.now()`.

---

## Section 7 — Granularity Summary

The combined design achieves:

| Dimension | API Backend | Claude CLI Backend (new) |
|-----------|-------------|--------------------------|
| Per-tool-name approval | ✅ | ✅ (hook) |
| Per-call content preview | ✅ | ✅ (hook shows full input) |
| Bash command visibility before execution | ✅ | ✅ (hook shows command) |
| y/once/always/never choices | ✅ | ✅ |
| Safe tools fast-path (no prompt) | ✅ | ✅ (hook reads always_approved) |
| `/allow` takes effect immediately | ✅ | ✅ (via permissions.json) |
| Consistent store across backends | after fix | after fix |
| Org-level policy enforcement | ❌ | ✅ (if VANTAGE_API_KEY) |
| Audit log | ❌ | ✅ |
| Works without API key | ❌ | ✅ |
| API-equivalent cost display | n/a | ✅ (labelled) |

---

*Next step: invoke writing-plans skill to create implementation plan from this spec.*
