"""
tracker.py — Dashboard telemetry client.

Batches cost/usage events and sends them to the VantageAI backend API.
Respects privacy modes: full, strict, anonymized, local-only.
Ported from vantage-cli/src/tracker.ts.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .cost_tracker import SessionCost

__version__ = "0.1.0"


@dataclass
class TrackerConfig:
    api_key: str = ""
    api_base: str = "https://api.vantageaiops.com"
    batch_size: int = 10
    flush_interval: float = 30.0  # seconds
    privacy: str = "full"  # full | strict | anonymized | local-only
    debug: bool = False


@dataclass
class DashboardEvent:
    event_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    latency_ms: int
    environment: str = "cli"
    agent_name: str = "vantage-agent"
    team: str = "default"
    session_id: str = ""


PROVIDER_MAP = {
    "claude": "anthropic",
    "codex": "openai",
    "gemini": "google",
    "aider": "anthropic",
    "chatgpt": "openai",
}


class Tracker:
    """Batched telemetry sender for the VantageAI dashboard."""

    def __init__(self, config: TrackerConfig) -> None:
        self.config = config
        self._queue: list[DashboardEvent] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False

    def start(self) -> None:
        if self.config.privacy == "local-only" or not self.config.api_key:
            return
        self._running = True
        self._schedule_flush()

    def stop(self) -> None:
        self._running = False
        if self._timer:
            self._timer.cancel()
        self.flush()

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        agent_name: str = "vantage-agent",
    ) -> None:
        """Queue a usage event."""
        event = DashboardEvent(
            event_id=str(uuid.uuid4()),
            provider=PROVIDER_MAP.get(agent_name, "anthropic"),
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            total_cost_usd=cost_usd,
            latency_ms=latency_ms,
            agent_name=agent_name,
        )
        with self._lock:
            self._queue.append(event)
            if len(self._queue) >= self.config.batch_size:
                self._do_flush()

    def flush(self) -> None:
        with self._lock:
            self._do_flush()

    def _do_flush(self) -> None:
        if not self._queue or not self.config.api_key:
            return
        batch = self._queue[:]
        self._queue.clear()

        events = []
        for e in batch:
            data: dict[str, Any] = {
                "event_id": e.event_id,
                "provider": e.provider,
                "model": e.model,
                "prompt_tokens": e.prompt_tokens,
                "completion_tokens": e.completion_tokens,
                "total_tokens": e.total_tokens,
                "total_cost_usd": e.total_cost_usd,
                "latency_ms": e.latency_ms,
                "environment": e.environment,
                "agent_name": e.agent_name,
                "team": e.team,
            }
            if self.config.privacy == "strict":
                data.pop("agent_name", None)
            events.append(data)

        try:
            url = f"{self.config.api_base}/v1/events/batch"
            httpx.post(
                url,
                json={"events": events},
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": f"vantage-agent/{__version__}",
                },
                timeout=10,
            )
            if self.config.debug:
                print(f"  [tracker] flushed {len(events)} events")
        except Exception as exc:
            if self.config.debug:
                print(f"  [tracker] flush error: {exc}")

    def _schedule_flush(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self.config.flush_interval, self._flush_and_reschedule)
        self._timer.daemon = True
        self._timer.start()

    def _flush_and_reschedule(self) -> None:
        self.flush()
        self._schedule_flush()
