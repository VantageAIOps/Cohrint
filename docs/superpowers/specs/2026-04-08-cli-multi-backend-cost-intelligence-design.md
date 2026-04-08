# CLI Design: Multi-Backend Cost Intelligence Layer

**Date:** 2026-04-08
**Author:** Aman Jain
**Status:** Approved — ready for implementation planning
**Package:** `vantage-agent` (Python 3.11+)
**Replaces:** `~/.claude/plans/swift-petting-peacock.md`

---

## 1. Problem Statement

Vantage-agent currently requires funded Anthropic API credits to function. Users on Claude Max ($100/mo unlimited), Codex Pro, or Gemini free tier cannot use it without paying extra API costs on top of their existing subscription.

More broadly: **Vantage must work as an agent-agnostic cost intelligence layer** — sitting between the user and any AI agent subscription, providing prompt optimization, cost tracking, anomaly detection, session persistence, and budget enforcement regardless of which backend the user runs.

**Core identity decision:** Vantage = **middleware intelligence layer**, not a wrapper.
**Integration model:** prompt-in → optimize → send → observe output → track. Never intercept tool calls.

**Agents in scope (v1):** `claude` (Claude Code CLI), `codex` (OpenAI CLI), `gemini` (Google CLI).

---

## 2. Design Principles

| Principle | Rationale |
|---|---|
| **Own all business logic** | Optimizer, pricing, recommendations, anomaly detection, budget enforcement — all purely local computation, zero extra tokens to any LLM |
| **Agent-independent** | Any CLI that accepts `echo "prompt" \| agent` or `agent -p "prompt"` works. Maximum compatibility. |
| **Session is the unit** | One serializable `VantageSession` object is the complete state. Crash-safe, resumable, multi-backend. |
| **Degrade gracefully** | Unknown agent output → estimate tokens. Dead process → fall back to context replay. Never crash. |
| **Capability-declared backends** | Backends self-declare what they support. No `if backend == "claude":` scattered across the codebase. |
| **Scale to N agents** | New agent = one file, one class, ~40 lines, declare capabilities. |

---

## 3. Architectural Approaches Considered

Three approaches were evaluated before selecting the final design.

### Approach A — Layered Middleware Pipeline

Vantage as a pure pipeline: `Prompt → [Classify → Optimize → Budget] → Session → Backend → [Track → Anomaly → Recommend] → Output`. Each stage is a pure function. Backend is a swappable adapter at the bottom.

**✅ Pros:** Easy to test each stage independently. Clear linear data flow. Session sits in one place.

**❌ Cons:** Pipeline stages are tightly coupled via a shared `RequestContext` object that grows large. Hard to add cross-cutting concerns (e.g. rate limiting that touches both pre and post stages). No natural place for process lifecycle management.

---

### Approach B — Event-Driven Session Bus

Session emits events (`prompt_received`, `backend_responded`, `tokens_counted`). Optimizer, tracker, anomaly detector are subscribers.

**✅ Pros:** True decoupling. Adding intelligence = adding a subscriber. Session owns process lifecycle cleanly.

**❌ Cons:** Event ordering bugs are hard to debug and reproduce. Overkill for 3 backends. Adds infrastructure complexity without product benefit at this stage.

---

### Approach C — Session-Centric with Capability Registry *(chosen)*

`VantageSession` is the central object. It owns conversation history, the optional persistent process, and a `Backend` adapter. Intelligence runs as pre/post hooks on `session.send()`. Backends self-declare capabilities so Session selects the right execution path without conditionals.

**✅ Pros:** Session is the only stateful object — trivially serializable. Capability flags eliminate scattered `if backend ==` checks. Pre/post hooks are independently testable pure functions. Adding a 4th backend = 1 file + capability declaration. History always present → fallback is automatic and always tested.

**❌ Cons:** `VantageSession` is a moderately large class — must be disciplined about what goes in it vs. in hooks.

**Why C over A and B:** A's pipeline couples stages via a growing context object and has no natural session concept. B's event bus is the right architecture at scale but premature for 3 backends. C gives clean separation, a single serializable unit, and a clear extension model without event-ordering complexity.

---

## 4. Chosen Architecture: Session-Centric + Capability Registry

```
User Input
    ↓
┌─────────────────────────────────────────────────────────────┐
│  VantageSession  (single serializable unit)                 │
│                                                             │
│  PRE-SEND HOOKS  (pure functions, zero LLM tokens)          │
│    classifier → optimizer → budget_check                    │
│         ↓            ↓           ↓                         │
│                                                             │
│  ConversationHistory  ←──── always present (primary path)  │
│    • messages: [{role, text}]   normalized, backend-agnostic│
│    • session_id: UUID4                                      │
│    • working_dir: str                                       │
│    • created_at / last_active_at                            │
│         ↓                                                   │
│  Backend  (capability-declared adapter)                     │
│    .name: "claude" | "codex" | "gemini"                     │
│    .capabilities = {                                        │
│      supports_process: bool,     ← keep process alive      │
│      supports_streaming: bool,                              │
│      token_count: "exact" | "estimated" | "free_tier",      │
│      tool_format: "anthropic" | "openai" | "google",        │
│    }                                                        │
│         ↓                                                   │
│  HYBRID SEND PATH                                           │
│    if supports_process and process.alive → stdin/pipe       │
│    else → context-replay (inject history, always works)     │
│         ↓                                                   │
│  POST-SEND HOOKS  (non-blocking where safe)                 │
│    cost_tracker → anomaly → recommendations                 │
│    → telemetry (async, non-blocking)                        │
└─────────────────────────────────────────────────────────────┘
    ↓
Output + Cost Report
```

### Session Lifecycle

```python
# Create
session = VantageSession.create(backend="claude", cwd="/project")

# Send (hybrid path chosen automatically)
response = session.send("refactor this function")

# Persists after every successful turn
# → ~/.vantage/sessions/<session_id>.json

# Resume after crash or new terminal
session = VantageSession.resume(session_id)

# List all sessions
sessions = SessionStore.list()  # sorted by last_active_at
```

### Session File Schema

```json
{
  "id": "uuid4",
  "backend": "claude",
  "cwd": "/project",
  "messages": [
    {"role": "user", "text": "..."},
    {"role": "assistant", "text": "..."}
  ],
  "cost_summary": {
    "total_cost_usd": 0.0234,
    "total_input_tokens": 1200,
    "total_output_tokens": 400,
    "backend": "claude",
    "token_count_confidence": "estimated"
  },
  "created_at": "2026-04-08T10:00:00Z",
  "last_active_at": "2026-04-08T10:45:00Z"
}
```

---

## 5. Backend Interface

```python
# vantage_agent/backends/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

@dataclass
class BackendCapabilities:
    supports_process: bool           # can keep subprocess alive across sends
    supports_streaming: bool         # streams output token by token
    token_count: Literal["exact", "estimated", "free_tier"]
    tool_format: Literal["anthropic", "openai", "google"]

@dataclass
class BackendResult:
    output_text: str
    input_tokens: int
    output_tokens: int
    estimated: bool                  # True if token counts are estimated
    model: str = "unknown"
    exit_code: int = 0               # for subprocess backends

class Backend(ABC):
    name: str
    capabilities: BackendCapabilities

    @abstractmethod
    def send(self, prompt: str, history: list[dict], cwd: str) -> BackendResult:
        """Send prompt with history context. Backend formats history per its tool_format."""
        ...

    def start_process(self) -> "AgentProcess | None":
        """Start persistent subprocess. Returns None if not supported."""
        return None

    def ping_process(self, process: "AgentProcess") -> bool:
        """Check if persistent process is alive and responsive."""
        return False
```

### Backend Capability Matrix

| Backend | `supports_process` | `token_count` | `tool_format` | Who pays |
|---|---|---|---|---|
| `api` | False | `exact` | `anthropic` | API credits (per-token) |
| `claude` | True | `estimated` | `anthropic` | Claude Max subscription |
| `codex` | True | `estimated` | `openai` | OpenAI subscription/credits |
| `gemini` | True | `estimated` | `google` | Google free tier / billing |

---

## 6. Backend Selection Logic

```
Priority (first match wins):
1. --backend flag (explicit)
2. VANTAGE_BACKEND env var
3. Auto-detect:
   ANTHROPIC_API_KEY set  → "api"
   `claude` binary found  → "claude"
   `codex` binary found   → "codex"
   `gemini` binary found  → "gemini"
   None                   → error with setup instructions
```

---

## 7. Hybrid Session Strategy

The hybrid approach uses **context ownership as the primary path** and **process persistence as an optimization**. This means the fallback is always exercised and always tested — it is never a last resort written in anger.

```
session.send(prompt):
    1. Run pre-hooks (classify → optimize → budget_check)
    2. if backend.capabilities.supports_process:
           if process is None: process = backend.start_process()
           if process.ping() succeeds:
               return _send_via_process(prompt, process)
           else:
               process = None  # declare dead, fall through
       return _send_via_context_replay(prompt, history)
    3. Run post-hooks (track → anomaly → recommend → telemetry)
    4. session.save()
```

**Context replay (always-available path):**
- Injects `ConversationHistory.messages` as context prefix
- History is trimmed to `MAX_HISTORY_TOKENS = 8000` before injection
- Oldest turns are summarized locally (heuristic, zero API tokens) when limit approached

**Process path (optimization when supported):**
- `AgentProcess` wraps a `subprocess.Popen` with stdin/stdout pipes
- `ping()` sends a sentinel prompt, expects response within `PING_TIMEOUT_S = 5`
- Dead process → fall back to context replay silently
- `PING_TIMEOUT_S` is configurable via `VANTAGE_PING_TIMEOUT` env var

---

## 8. Limitations & Mitigations

### 8.1 Scalability

| Limitation | Impact | Mitigation |
|---|---|---|
| Unbounded history growth | Long sessions silently hit context limits mid-turn | Enforce `MAX_HISTORY_TOKENS=8000`. Summarize oldest N turns locally when limit approached |
| Single-threaded REPL blocks on send | No background work during agent execution | `session.send()` is `async`-first. Post-send hooks (anomaly, telemetry) run concurrently — they do not block output |
| No multi-session cost coordination | Two terminals with same org token have no shared budget awareness | `SessionStore` writes cost to `~/.vantage/sessions/` after every turn. Budget check reads aggregate across all session files atomically |
| Per-process cost isolation | Cumulative daily spend not visible across sessions | `vantage-agent summary` reads all session files and aggregates |

### 8.2 Rate Limiting

| Limitation | Impact | Mitigation |
|---|---|---|
| Zero retry on 429 (api backend) | Turn dropped, history corrupted with orphaned user message | Backend wraps `anthropic.RateLimitError` with `send_with_retry(max_retries=3, backoff=exponential)`. On abort: pop orphaned message |
| No cross-session rate awareness | 3 terminals hitting same API key with no throttle coordination | Per-key token-bucket in `~/.vantage/rate_state.json` (file lock). Each `send()` checks bucket before calling backend |
| Tracker silently discards batches on non-2xx | Events lost on 429 / 500 from dashboard API | Check `response.status_code` in `_do_flush()`. 429/5xx: exponential backoff re-queue. 4xx auth: log and discard |
| CLI backends surface rate errors as unstructured stdout | Vantage can't distinguish a rate error from a real response | Parse `stderr` + exit code on subprocess exit. Exit != 0 or stderr matches rate-limit keywords → structured `BackendError` |

### 8.3 Multi-Agent Environment

| Limitation | Impact | Mitigation |
|---|---|---|
| `session_id = ""` always | Events from concurrent sessions indistinguishable in dashboard | `VantageSession` generates `UUID4` session_id at creation, propagated to every `DashboardEvent` |
| No cross-backend cost roll-up | Running claude + codex simultaneously → no single "today's total" | `SessionStore` is backend-agnostic. `vantage-agent summary` aggregates across all backends |
| `/model` switch mid-session blends cost rates | Cumulative total mixes two models' pricing silently | `TurnUsage` records `backend` + `model` per turn. Cost display shows per-backend breakdown, never blended total |
| Keyboard interrupt corrupts message history | Next send causes API role-alternation error | Before each `send()`: validate `messages` ends with assistant turn or is empty. On interrupt: pop orphaned user message |
| No agent handoff protocol | Can't transfer session from claude → codex | `ConversationHistory` normalizes to `[{role, text}]`, stripping tool_use blocks. Backend re-serializes to its own format on import |

### 8.4 Agent Plugin Interaction

| Limitation | Impact | Mitigation |
|---|---|---|
| Classifier bypassed in current code | `api_client.py:99` calls `optimize_prompt()` directly — revert-if-over-compressed safety skipped | Pre-hooks pipeline enforces `classifier → optimizer` ordering. Classifier gates optimization and validates output |
| Tools hardcoded to Anthropic schema | `TOOL_DEFINITIONS` in `tools.py` uses Anthropic format — breaks Codex/Gemini | Backend declares `tool_format`. `ToolRegistry.for_backend(backend)` translates definitions at send time |
| No external plugin/hook point | Can't add custom intelligence without editing source | `VantageSession(extra_pre_hooks=[], extra_post_hooks=[])` accepts callables at construction |
| Recommendations gated by agent name | Tips for `"claude"` never fire on `codex` backend | Recommendations gain `backend_compat: list[str] | "all"`. Tips not referencing agent-internal commands are marked `"all"` |
| MCP tool calls invisible for CLI backends | Tool calls inside `claude -p` subprocess are unobservable | Documented as capability boundary. v1: track prompt-level cost only for CLI backends. Future: parse JSONL logs if available |

### 8.5 Session Fallback

| Limitation | Impact | Mitigation |
|---|---|---|
| No serialization today | Crash = total session loss | `session.save()` writes JSON after every successful turn |
| Fallback path untested | Silent regression risk | `test_fallback_on_process_exit`, `test_fallback_on_timeout`, `test_resume_from_disk` are first-class tests, not edge-case afterthoughts |
| Context replay token bleed | Cost grows O(n) with session length on fallback | History trimmed to `MAX_HISTORY_TOKENS` before injection. Oldest turns summarized |
| No process liveness detection | Stuck process blocks indefinitely | `process.ping()` with `PING_TIMEOUT_S=5` before each send. Timeout → declare dead → fall back |
| Budget can't stop mid-execution subprocess | Can warn before send, never hard-stop inside | Document as capability boundary. API backend: hard stop. CLI backends: warn-only. |
| No detach/reattach across terminals | Closing terminal kills persistent subprocess | v1 limitation: documented. v2: `screen`/`tmux` wrapper for persistent process across disconnects |

---

## 9. Pre/Post Hook Pipeline

All hooks are pure functions. They receive and return a `HookContext` — they do not touch `VantageSession` internals.

```python
@dataclass
class HookContext:
    prompt: str                      # mutated by optimizer
    history: list[dict]              # read-only for pre-hooks
    backend: Backend                 # read-only
    session_id: str
    result: BackendResult | None     # None for pre-hooks, set for post-hooks
    cost_so_far: CostSummary         # for budget_check and anomaly

# Pre-send hooks (run before backend.send())
PRE_HOOKS = [
    classify_input,       # sets ctx.prompt_type; gates optimizer
    optimize_prompt,      # compresses if type == "prompt"; idempotency-checked
    check_budget,         # raises BudgetExceededError or warns at 80%
]

# Post-send hooks (run after backend.send() returns)
POST_HOOKS = [
    record_cost,          # updates SessionCost from BackendResult
    detect_anomaly,       # fires if current cost > 3x rolling average
    get_recommendations,  # returns list[Recommendation] shown to user
    flush_telemetry,      # async — does not block output
]
```

---

## 10. Cost Display

```
backend: claude (Max subscription — $0/token)
─────────────────────────────────────────────
  turn 3 │ ~1,200 in / ~380 out │ ~$0.02 (estimated)
  total  │ ~3,100 in / ~900 out │ ~$0.05 (estimated, subscription)
─────────────────────────────────────────────
```

- `exact` backends: no `~` prefix, no `(estimated)` label
- `free_tier` backends: `~$0.00 (free tier)`
- `estimated` backends: `~` prefix + `(estimated)` label
- `is_subscription=True`: append `(subscription)` to cost line

---

## 11. File Map

### New Files

| File | Purpose |
|---|---|
| `vantage_agent/session.py` | `VantageSession` — central stateful object, hybrid send logic, serialize/resume |
| `vantage_agent/session_store.py` | `SessionStore` — read/write/list `~/.vantage/sessions/*.json`, global cost aggregation |
| `vantage_agent/hooks.py` | `HookContext` dataclass, `PRE_HOOKS` and `POST_HOOKS` lists |
| `vantage_agent/backends/__init__.py` | Factory: `create_backend(name)` + auto-detect logic |
| `vantage_agent/backends/base.py` | `Backend` ABC, `BackendCapabilities`, `BackendResult`, `AgentProcess` |
| `vantage_agent/backends/api_backend.py` | Direct Anthropic API (extracted from `api_client.py`) |
| `vantage_agent/backends/claude_backend.py` | `claude -p` subprocess, `supports_process=True` |
| `vantage_agent/backends/codex_backend.py` | `codex -p` subprocess, `supports_process=True` |
| `vantage_agent/backends/gemini_backend.py` | `gemini -p` subprocess, `supports_process=True` |
| `vantage_agent/tool_registry.py` | `ToolRegistry.for_backend(backend)` — translates tool definitions to backend format |
| `tests/test_session.py` | Session lifecycle, serialize/resume, hybrid path, fallback |
| `tests/test_backends.py` | Backend unit tests per adapter |
| `tests/test_hooks.py` | Pre/post hook pipeline tests |
| `tests/test_bugs.py` | 5 pre-existing bugs (see Section 12) |

### Modified Files

| File | Change |
|---|---|
| `vantage_agent/api_client.py` | Refactor to use `Backend` interface. Keep as `ApiBackend` thin wrapper. Legacy shim for existing tests. |
| `vantage_agent/optimizer.py` | Remove `"whether or not"` from FILLER_PHRASES. Add idempotency check (skip if output ≈ input). |
| `vantage_agent/pricing.py` | Add `PRICING_UPDATED` date constant. Unify with `cost_tracker.py` — single source of truth. |
| `vantage_agent/cost_tracker.py` | Add `backend` + `model` per `TurnUsage`. Add `is_subscription` flag. Import shared pricing. |
| `vantage_agent/tracker.py` | Fix: check response status. Fix: re-queue on 429/5xx. Fix: anonymized mode. Fix: unknown provider default. Fix: flush-after-success (not before). |
| `vantage_agent/classifier.py` | Wire into `PRE_HOOKS`. Add `backend_compat` to bypass optimization for free-tier backends. |
| `vantage_agent/cli.py` | Add `--backend` flag. Add `--resume <session_id>`. Show backend in banner. Add `vantage-agent summary` subcommand. |
| `vantage_agent/renderer.py` | Show `~` for estimated. Show `(subscription)` for $0 backends. Show `(free tier)` for free tier. |
| `vantage_agent/recommendations.py` | Add `backend_compat` field to `Recommendation`. Filter by backend type. Skip agent-internal commands for CLI backends. |
| `vantage_agent/anomaly.py` | Use `HookContext` input. No direct console side-effect — return structured `AnomalyResult`. |

---

## 12. Pre-Existing Bugs (Fix in Phase 1)

### Bug 1: Semantic corruption in optimizer
- **File:** `optimizer.py:38` — `"whether or not"` in `FILLER_PHRASES`
- **Impact:** "Tell me whether or not to delete the file" → "Tell me to delete the file"
- **Fix:** Remove `"whether or not"` from FILLER_PHRASES

### Bug 2: `anonymized` privacy mode not implemented
- **File:** `tracker.py` — `anonymized` falls through to `full` behavior
- **Fix:** Strip `agent_name`, `team`, hash `event_id`

### Bug 3: Unknown agent defaults to `"anthropic"` provider
- **File:** `tracker.py:99` — `PROVIDER_MAP.get(agent_name, "anthropic")`
- **Fix:** Default to `"unknown"`, not `"anthropic"`

### Bug 4: Pricing dictionaries inconsistent
- **Files:** `cost_tracker.py` uses `"claude-haiku-4-5-20251001"`, `pricing.py` uses `"claude-haiku-4-5"`
- **Fix:** Single pricing source imported by both

### Bug 5: Flush-before-success loses events
- **File:** `tracker.py::_do_flush()` — clears queue before HTTP POST completes
- **Fix:** Only clear queue after successful POST (2xx)

---

## 13. Test Plan (40+ new tests)

### Bug Fixes (`tests/test_bugs.py`)
- [ ] `test_whether_or_not_preserves_question_intent`
- [ ] `test_anonymized_mode_differs_from_full_and_strict`
- [ ] `test_unknown_agent_provider_not_anthropic`
- [ ] `test_pricing_dictionaries_consistent`
- [ ] `test_flush_retains_events_on_network_error`

### Session (`tests/test_session.py`)
- [ ] `test_session_creates_with_uuid`
- [ ] `test_session_saves_after_successful_turn`
- [ ] `test_session_resume_restores_history`
- [ ] `test_session_resume_restores_cost_summary`
- [ ] `test_fallback_on_process_exit`
- [ ] `test_fallback_on_process_timeout`
- [ ] `test_fallback_to_context_replay_when_no_process_support`
- [ ] `test_history_trimmed_at_max_tokens`
- [ ] `test_interrupt_pops_orphaned_user_message`
- [ ] `test_session_id_propagated_to_dashboard_events`

### Backends (`tests/test_backends.py`)
- [ ] `test_auto_detect_api_key_returns_api`
- [ ] `test_auto_detect_claude_binary_returns_claude`
- [ ] `test_auto_detect_no_binaries_raises_error`
- [ ] `test_explicit_flag_overrides_autodetect`
- [ ] `test_api_backend_returns_exact_tokens`
- [ ] `test_claude_backend_returns_estimated_tokens`
- [ ] `test_backend_handles_unknown_output_gracefully`
- [ ] `test_subscription_backend_shows_zero_cost`
- [ ] `test_backend_rate_limit_retry_exponential`
- [ ] `test_subprocess_rate_error_returns_structured_error`
- [ ] `test_tool_registry_translates_anthropic_to_openai`
- [ ] `test_tool_registry_translates_anthropic_to_google`

### Hooks (`tests/test_hooks.py`)
- [ ] `test_classifier_gates_optimizer`
- [ ] `test_already_optimized_not_re_optimized`
- [ ] `test_budget_blocks_api_send_when_exceeded`
- [ ] `test_budget_warns_at_80_percent`
- [ ] `test_budget_cannot_hard_stop_cli_backend`
- [ ] `test_anomaly_returns_structured_result_not_side_effect`
- [ ] `test_recommendations_backend_compat_all`
- [ ] `test_recommendations_skip_agent_internal_for_cli`
- [ ] `test_telemetry_hook_is_nonblocking`

### Multi-Session / Scalability
- [ ] `test_session_store_aggregates_across_backends`
- [ ] `test_rate_state_token_bucket_across_sessions`
- [ ] `test_concurrent_sessions_independent_cost`
- [ ] `test_tracker_thread_safety_concurrent_records`

### Renderer
- [ ] `test_estimated_cost_shows_tilde_prefix`
- [ ] `test_subscription_shows_zero_cost_label`
- [ ] `test_free_tier_shows_free_tier_label`
- [ ] `test_exact_cost_no_tilde`

---

## 14. Implementation Phases

### Phase 1: Fix Bugs (no architecture changes)
- [ ] Fix 5 bugs in Section 12
- [ ] Write `tests/test_bugs.py` — all must pass
- [ ] All existing tests still pass
- [ ] Commit + push

### Phase 2: Hook Pipeline + Session Object
- [ ] Create `HookContext`, `PRE_HOOKS`, `POST_HOOKS` in `hooks.py`
- [ ] Wire `classifier → optimizer` correctly
- [ ] Create `VantageSession` with in-memory history
- [ ] `session.save()` / `VantageSession.resume()` with `SessionStore`
- [ ] Session ID propagated to tracker events
- [ ] Tests: `test_session.py`, `test_hooks.py`

### Phase 3: Backend Abstraction
- [ ] Create `backends/` package — `base.py`, `api_backend.py`
- [ ] Extract API logic from `api_client.py` into `ApiBackend`
- [ ] `api_client.py` becomes a thin shim (no regression)
- [ ] All existing tests still pass

### Phase 4: CLI Backends + Auto-Detection
- [ ] Auto-detect logic in `backends/__init__.py`
- [ ] `claude_backend.py`, `codex_backend.py`, `gemini_backend.py`
- [ ] `AgentProcess` with `ping()` + timeout fallback
- [ ] `--backend` flag in `cli.py`
- [ ] `tool_registry.py` for format translation
- [ ] Tests: `test_backends.py`

### Phase 5: Cost Display + Renderer Updates
- [ ] `~` prefix for estimated, `(subscription)`, `(free tier)` labels
- [ ] Per-backend breakdown in cost summary
- [ ] `vantage-agent summary` subcommand (reads all session files)
- [ ] Tests: renderer tests

### Phase 6: Multi-Session + Rate Limiting
- [ ] Token-bucket rate state in `~/.vantage/rate_state.json`
- [ ] Retry with exponential backoff in API backend
- [ ] Tracker re-queue on 429/5xx
- [ ] Global budget check across session files
- [ ] Tests: multi-session + scalability tests

---

## 15. Verification

```bash
# 1. Zero regression
python -m pytest tests/ -q

# 2. Bug fixes
python -m pytest tests/test_bugs.py -v

# 3. Session resume
vantage-agent --backend claude "hello"
# CTRL+C, note session_id from banner
vantage-agent --resume <session_id> "continue"

# 4. Auto-detection (no API key, claude installed)
unset ANTHROPIC_API_KEY
vantage-agent "list files"
# → auto-detects claude backend

# 5. Explicit backend
vantage-agent --backend codex "explain this function"

# 6. Summary across sessions
vantage-agent summary
# → aggregated cost across all backends and sessions today
```

---

## 16. Out of Scope (v1)

- Llama / local model backends
- Fetch pricing from VantageAI API (static dict is fine for v1)
- `screen`/`tmux` process detach/reattach across terminals
- MCP tool call observation for CLI backends
- Agent-internal command passthrough (`/compact` forwarding)
- Real-time token extraction from Claude JSONL logs
- Browser extension backend
