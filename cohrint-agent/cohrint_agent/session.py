"""
session.py — CohrintSession: the single serializable stateful unit.

Hybrid send: process-persistence path first (when supported), context-replay fallback always.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console

from .hooks import HookContext, CostSummary, run_pre_hooks, run_post_hooks
from .session_store import SessionStore, DEFAULT_SESSIONS_DIR

_console = Console()

if TYPE_CHECKING:
    from .backends.base import Backend, BackendResult, AgentProcess

MAX_HISTORY_TOKENS = 8000
_CHARS_PER_TOKEN = 4  # conservative estimate

# Per-message ceiling. A single LLM response that dumps a 50 MiB file would
# otherwise sit in self.history unbounded and be paid-for on every replay.
# 256 KiB ~= 64 k tokens — already far past the per-turn context budget
# but small enough that 10 such messages don't OOM the process
# (T-BOUNDS.per_message_cap).
MAX_MESSAGE_CHARS = 256 * 1024


def _cap_message_text(text: str) -> str:
    """Cap individual message text to prevent history memory blow-up."""
    if not isinstance(text, str):
        return ""
    if len(text) > MAX_MESSAGE_CHARS:
        return text[:MAX_MESSAGE_CHARS] + "\n[...truncated by cohrint-agent]"
    return text


def _estimate_tokens(messages: list[dict]) -> int:
    return sum(len(m.get("text", "")) for m in messages) // _CHARS_PER_TOKEN


def _trim_history(messages: list[dict]) -> list[dict]:
    """Remove oldest pairs until history fits within MAX_HISTORY_TOKENS.

    Truncates any oversized individual message FIRST so a 50 MiB turn
    can't force the pair-drop loop to evict the entire history just to
    meet the token ceiling (T-BOUNDS.per_message_cap).
    """
    msgs = list(messages)
    trimmed = False
    # Per-message truncation first — bounds per-turn memory and keeps the
    # token estimate meaningful for the pair-drop loop below.
    for m in msgs:
        t = m.get("text", "")
        if isinstance(t, str) and len(t) > MAX_MESSAGE_CHARS:
            m["text"] = t[:MAX_MESSAGE_CHARS] + "\n[...truncated]"
            trimmed = True
    # Keep at least the last pair — wiping history to empty gives worse
    # replays than sending a slightly-too-big last pair.
    while _estimate_tokens(msgs) > MAX_HISTORY_TOKENS and len(msgs) > 2:
        msgs = msgs[2:]  # drop oldest user+assistant pair
        trimmed = True
    if trimmed:
        _console.print("  [dim]Note: old context trimmed to fit token limit[/dim]")
    return msgs


class CohrintSession:
    def __init__(
        self,
        session_id: str,
        backend: "Backend",
        cwd: str,
        history: list[dict],
        cost_summary: dict,
        store: SessionStore,
        tracker=None,
        budget_usd: float = 0.0,
        created_at: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.backend = backend
        self.cwd = cwd
        self.history: list[dict] = history
        self._cost_summary = cost_summary
        self._store = store
        self._tracker = tracker
        self._budget_usd = budget_usd
        # Cache created_at in memory so save() doesn't re-read the file
        # on every turn — the extra load() was both a perf cost and a
        # load/save TOCTOU window on concurrent resume
        # (T-CONCUR.save_no_reload).
        self._created_at = created_at or datetime.now(timezone.utc).isoformat()
        self._process: "AgentProcess | None" = None

    @classmethod
    def create(
        cls,
        backend: "Backend",
        cwd: str,
        store: SessionStore | None = None,
        tracker=None,
        budget_usd: float = 0.0,
    ) -> "CohrintSession":
        return cls(
            session_id=str(uuid.uuid4()),
            backend=backend,
            cwd=cwd,
            history=[],
            cost_summary={"total_cost_usd": 0.0, "total_input_tokens": 0, "total_output_tokens": 0},
            store=store or SessionStore(),
            tracker=tracker,
            budget_usd=budget_usd,
        )

    @classmethod
    def resume(
        cls,
        session_id: str,
        backend: "Backend",
        store: SessionStore | None = None,
        tracker=None,
    ) -> "CohrintSession":
        _store = store or SessionStore()
        data = _store.load(session_id)
        # Validate + clamp the cost-tracking fields on the untrusted-data
        # boundary. A file tampered to set total_cost_usd=-9e20 would
        # otherwise defeat the budget gate (fraction goes very negative,
        # never crosses 0.80) (T-COST.resume_bounds).
        raw_cs = data.get("cost_summary") or {}
        if not isinstance(raw_cs, dict):
            raw_cs = {}
        safe_cs = {
            "total_cost_usd": max(0.0, min(1e9, float(raw_cs.get("total_cost_usd") or 0.0))),
            "total_input_tokens": max(0, int(raw_cs.get("total_input_tokens") or 0)),
            "total_output_tokens": max(0, int(raw_cs.get("total_output_tokens") or 0)),
        }
        raw_budget = data.get("budget_usd", 0.0)
        import math as _math
        try:
            budget = float(raw_budget)
        except (TypeError, ValueError):
            budget = 0.0
        # Check NaN/inf BEFORE clamping — min()/max() silently turn NaN
        # into the non-NaN bound under Python's comparison rules, which
        # would sneak an uninitialised budget past the gate.
        if _math.isnan(budget) or _math.isinf(budget):
            budget = 0.0
        budget = max(0.0, min(1e9, budget))
        raw_created = data.get("created_at")
        created = raw_created if isinstance(raw_created, str) else None
        # Validate cwd from an untrusted source — an embedded null byte
        # would reach subprocess.run() and yield an opaque exit-1 failure
        # on older CPython builds where the null check happens after fork
        # (T-SAFETY.cwd_nul).
        raw_cwd = data.get("cwd", ".")
        cwd = raw_cwd if (isinstance(raw_cwd, str) and "\x00" not in raw_cwd) else "."
        return cls(
            session_id=session_id,
            backend=backend,
            cwd=cwd,
            history=data.get("messages", []) if isinstance(data.get("messages"), list) else [],
            cost_summary=safe_cs,
            store=_store,
            tracker=tracker,
            budget_usd=budget,
            created_at=created,
        )

    def send(self, prompt: str) -> str:
        """Send prompt through pre-hooks → backend → post-hooks → save."""
        cost_so_far = CostSummary(
            total_cost_usd=self._cost_summary.get("total_cost_usd", 0.0),
            prompt_count=len([m for m in self.history if m["role"] == "user"]),
            budget_usd=self._budget_usd,
        )
        ctx = HookContext(
            prompt=prompt,
            history=list(self.history),
            backend_name=self.backend.name,
            backend_token_count=self.backend.capabilities.token_count,
            session_id=self.session_id,
            result=None,
            cost_so_far=cost_so_far,
        )

        # Pre-hooks: classify → optimize → budget check
        ctx = run_pre_hooks(ctx)

        # Append user message (after optimization). Cap size to prevent
        # a single oversized turn from pinning memory forever.
        user_msg = {"role": "user", "text": _cap_message_text(ctx.prompt)}
        self.history.append(user_msg)

        try:
            result = self._send_to_backend(ctx.prompt)
        except KeyboardInterrupt:
            # Pop orphaned user message to keep history valid
            if self.history and self.history[-1] == user_msg:
                self.history.pop()
            raise

        # Append assistant response, capped to prevent single-turn OOM.
        self.history.append({
            "role": "assistant",
            "text": _cap_message_text(result.output_text),
        })

        # Update cost summary. Clamp to non-negative so a buggy backend
        # can't silently reduce the accumulated spend (T-COST.nonneg).
        cost_usd = max(0.0, float(getattr(result, "cost_usd", 0.0) or 0.0))
        in_tok = max(0, int(result.input_tokens or 0))
        out_tok = max(0, int(result.output_tokens or 0))
        self._cost_summary["total_cost_usd"] = self._cost_summary.get("total_cost_usd", 0.0) + cost_usd
        self._cost_summary["total_input_tokens"] = self._cost_summary.get("total_input_tokens", 0) + in_tok
        self._cost_summary["total_output_tokens"] = self._cost_summary.get("total_output_tokens", 0) + out_tok

        # Persist immediately after the cost is accumulated so a crash in
        # post-hooks or telemetry cannot lose billed spend (T-COST.save_first).
        # Best-effort — save failure should not mask the turn's output, but
        # we surface it once per session to stderr so silent loss of spend
        # accounting is detectable (T-SAFETY.save_failure_visible).
        try:
            self.save()
        except Exception as e:
            if not getattr(self, "_save_warned", False):
                import sys
                print(
                    f"[cohrint-agent] warning: session save failed "
                    f"(spend accounting may be incomplete): {e}",
                    file=sys.stderr,
                )
                self._save_warned = True

        # Post-hooks (anomaly, recommendations)
        ctx.result = result
        ctx.cost_so_far.total_cost_usd = self._cost_summary["total_cost_usd"]
        run_post_hooks(ctx)

        # Telemetry
        if self._tracker:
            self._tracker.record(
                model=result.model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost_usd,
                latency_ms=0,
                session_id=self.session_id,
            )

        return result.output_text

    def _send_to_backend(self, prompt: str) -> "BackendResult":
        """Try process path first; fall back to context-replay."""
        # Process persistence path (optimization)
        if self.backend.capabilities.supports_process:
            if self._process is None:
                self._process = self.backend.start_process()
            if self._process is not None and self._process.ping():
                try:
                    from .backends.base import BackendResult
                    raw = self._process.send_stdin(prompt)
                    inp = len(prompt) // _CHARS_PER_TOKEN
                    out = len(raw) // _CHARS_PER_TOKEN
                    return BackendResult(
                        output_text=raw,
                        input_tokens=inp,
                        output_tokens=out,
                        estimated=True,
                        model="unknown",
                        cost_usd=0.0,
                    )
                except Exception:
                    self._process = None  # declare dead, fall through

        # Context-replay path (always available)
        trimmed = _trim_history(list(self.history[:-1]))  # exclude current user msg (already appended)
        return self.backend.send(
            prompt=prompt,
            history=trimmed,
            cwd=self.cwd,
        )

    def save(self) -> None:
        self._store.save({
            "id": self.session_id,
            "backend": self.backend.name,
            "cwd": self.cwd,
            "messages": self.history,
            "cost_summary": {**self._cost_summary, "backend": self.backend.name},
            "budget_usd": self._budget_usd,
            "created_at": self._created_at,
        })
