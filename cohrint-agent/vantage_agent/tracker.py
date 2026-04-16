"""
tracker.py — Dashboard telemetry client.

Batches cost/usage events and sends them to the Cohrint backend API.
Respects privacy modes: full, strict, anonymized, local-only.
Cost tracking module for cohrint-agent.
"""
from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import __version__
from .cost_tracker import SessionCost
from .telemetry import OTelExporter


@dataclass
class TrackerConfig:
    api_key: str = ""
    api_base: str = "https://api.cohrint.com"
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
    agent_name: str = "cohrint-agent"
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
    """Batched telemetry sender for the Cohrint dashboard."""

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
        agent_name: str = "cohrint-agent",
        session_id: str = "",
    ) -> None:
        """Queue a usage event."""
        raw_event_id = str(uuid.uuid4())

        if self.config.privacy == "anonymized":
            hashed_id = hashlib.sha256(raw_event_id.encode()).hexdigest()
            event = DashboardEvent(
                event_id=hashed_id,
                provider=PROVIDER_MAP.get(agent_name, "unknown"),
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                total_cost_usd=cost_usd,
                latency_ms=latency_ms,
                agent_name="",
                team="",
                session_id=session_id,
            )
        else:
            event = DashboardEvent(
                event_id=raw_event_id,
                provider=PROVIDER_MAP.get(agent_name, "unknown"),
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                total_cost_usd=cost_usd,
                latency_ms=latency_ms,
                agent_name=agent_name,
                session_id=session_id,
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
        batch = self._queue[:]  # snapshot — do NOT clear yet

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
            resp = httpx.post(
                url,
                json={"events": events},
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": f"cohrint-agent/{__version__}",
                },
                timeout=10,
            )
            if resp.status_code < 400:
                # Only clear on success (2xx/3xx)
                self._queue = [e for e in self._queue if e not in batch]
                if self.config.debug:
                    print(f"  [tracker] flushed {len(events)} events")
                # Fire-and-forget OTel export for each event in the batch
                _otel = OTelExporter()
                for e in batch:
                    _otel.export_async({
                        "model": e.model,
                        "prompt_tokens": e.prompt_tokens,
                        "completion_tokens": e.completion_tokens,
                        "total_cost_usd": e.total_cost_usd,
                        "cost_usd": e.total_cost_usd,
                        "latency_ms": e.latency_ms,
                        "session_id": e.session_id,
                    })
            else:
                if self.config.debug:
                    print(f"  [tracker] flush failed: HTTP {resp.status_code} — events retained")
        except Exception as exc:
            if self.config.debug:
                print(f"  [tracker] flush error: {exc} — events retained")
            # Do NOT clear queue — events will retry on next flush

    def _schedule_flush(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self.config.flush_interval, self._flush_and_reschedule)
        self._timer.daemon = True
        self._timer.start()

    def _flush_and_reschedule(self) -> None:
        self.flush()
        self._schedule_flush()
