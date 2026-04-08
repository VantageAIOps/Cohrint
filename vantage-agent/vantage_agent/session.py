"""
session.py — VantageSession: the single serializable stateful unit.

Hybrid send: process-persistence path first (when supported), context-replay fallback always.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .hooks import HookContext, CostSummary, run_pre_hooks, run_post_hooks
from .session_store import SessionStore, DEFAULT_SESSIONS_DIR

if TYPE_CHECKING:
    from .backends.base import Backend, BackendResult, AgentProcess

MAX_HISTORY_TOKENS = 8000
_CHARS_PER_TOKEN = 4  # conservative estimate


def _estimate_tokens(messages: list[dict]) -> int:
    return sum(len(m.get("text", "")) for m in messages) // _CHARS_PER_TOKEN


def _trim_history(messages: list[dict]) -> list[dict]:
    """Remove oldest pairs until history fits within MAX_HISTORY_TOKENS."""
    msgs = list(messages)
    while _estimate_tokens(msgs) > MAX_HISTORY_TOKENS and len(msgs) >= 2:
        msgs = msgs[2:]  # drop oldest user+assistant pair
    return msgs


class VantageSession:
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
    ) -> None:
        self.session_id = session_id
        self.backend = backend
        self.cwd = cwd
        self.history: list[dict] = history
        self._cost_summary = cost_summary
        self._store = store
        self._tracker = tracker
        self._budget_usd = budget_usd
        self._process: "AgentProcess | None" = None

    @classmethod
    def create(
        cls,
        backend: "Backend",
        cwd: str,
        store: SessionStore | None = None,
        tracker=None,
        budget_usd: float = 0.0,
    ) -> "VantageSession":
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
    ) -> "VantageSession":
        _store = store or SessionStore()
        data = _store.load(session_id)
        return cls(
            session_id=session_id,
            backend=backend,
            cwd=data.get("cwd", "."),
            history=data.get("messages", []),
            cost_summary=data.get("cost_summary", {"total_cost_usd": 0.0}),
            store=_store,
            tracker=tracker,
            budget_usd=data.get("budget_usd", 0.0),
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

        # Append user message (after optimization)
        user_msg = {"role": "user", "text": ctx.prompt}
        self.history.append(user_msg)

        try:
            result = self._send_to_backend(ctx.prompt)
        except KeyboardInterrupt:
            # Pop orphaned user message to keep history valid
            if self.history and self.history[-1] == user_msg:
                self.history.pop()
            raise

        # Append assistant response
        self.history.append({"role": "assistant", "text": result.output_text})

        # Update cost summary
        cost_usd = getattr(result, "cost_usd", 0.0)
        self._cost_summary["total_cost_usd"] = self._cost_summary.get("total_cost_usd", 0.0) + cost_usd
        self._cost_summary["total_input_tokens"] = self._cost_summary.get("total_input_tokens", 0) + result.input_tokens
        self._cost_summary["total_output_tokens"] = self._cost_summary.get("total_output_tokens", 0) + result.output_tokens

        # Post-hooks (anomaly, recommendations)
        ctx.result = result
        ctx.cost_so_far.total_cost_usd = self._cost_summary["total_cost_usd"]
        run_post_hooks(ctx)

        # Telemetry
        if self._tracker:
            self._tracker.record(
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=cost_usd,
                latency_ms=0,
                session_id=self.session_id,
            )

        # Save session after every successful turn
        self.save()
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
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
