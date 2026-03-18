"""
Async event queue — batches events and flushes to ingest server.
Zero latency impact on the application.
"""
from __future__ import annotations
import json, logging, queue, threading, time, urllib.error, urllib.request
from vantage.models.event import VantageEvent

logger = logging.getLogger("vantage.queue")
SDK_VERSION = "1.0.0"


class EventQueue:
    def __init__(self, api_key: str, ingest_url: str, flush_interval: float = 2.0,
                 batch_size: int = 50, debug: bool = False):
        self.api_key        = api_key
        self.ingest_url     = ingest_url.rstrip("/")
        self.flush_interval = flush_interval
        self.batch_size     = batch_size
        self.debug          = debug
        self._q: queue.Queue[VantageEvent] = queue.Queue(maxsize=10_000)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="vantage-flush")
        self._thread.start()

    def enqueue(self, event: VantageEvent) -> None:
        try:
            self._q.put_nowait(event)
            qsize = self._q.qsize()
            if self.debug:
                logger.debug("[vantage] %s | %s | %d tok | $%.6f",
                             event.provider, event.model,
                             event.usage.total_tokens, event.cost.total_cost_usd)
            # Warn at 80% capacity before silent drops occur
            if qsize >= 8_000 and qsize % 500 == 0:
                logger.warning(
                    "Vantage queue at %d/10000 — events will be dropped at capacity. "
                    "Consider reducing flush_interval or batch_size.",
                    qsize,
                )
        except queue.Full:
            logger.warning("Vantage queue full (10000) — event dropped")

    def flush_sync(self) -> None:
        batch: list[VantageEvent] = []
        try:
            while len(batch) < self.batch_size:
                batch.append(self._q.get_nowait())
        except queue.Empty:
            pass
        if batch:
            self._send(batch)

    def _run(self) -> None:
        while True:
            time.sleep(self.flush_interval)
            try:
                self.flush_sync()
            except Exception as e:
                logger.warning("Flush error: %s", e)

    def _send(self, events: list[VantageEvent]) -> None:
        payload = json.dumps({
            "events": [e.to_dict() for e in events],
            "sdk_version": SDK_VERSION,
        }).encode()
        req = urllib.request.Request(
            f"{self.ingest_url}/v1/events", data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                if self.debug:
                    logger.debug("Flushed %d events → %s", len(events), r.status)
        except Exception as e:
            logger.warning("Ingest failed: %s", e)
