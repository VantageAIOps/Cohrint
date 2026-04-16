"""
vantage/client.py
Core engine: async event queue, background flush, hallucination scoring.
Thread-safe. Zero latency impact on the calling application.
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from cohrint.models.event import CohrintEvent

logger = logging.getLogger("cohrint")


class CohrintClient:
    def __init__(
        self,
        api_key:              str,
        org:                  str   = "",
        team:                 str   = "",
        project:              str   = "",
        environment:          str   = "production",
        agent:                str   = "",
        ingest_url:           str   = "https://vantage-api.aman-lpucse.workers.dev/v1/events",
        anthropic_key:        str   = "",
        enable_hallucination: bool  = True,
        flush_interval:       float = 2.0,
        batch_size:           int   = 50,
        debug:                bool  = False,
    ):
        self.api_key              = api_key
        self.org                  = org
        self.team                 = team
        self.project              = project
        self.environment          = environment
        self.agent                = agent
        self.ingest_url           = ingest_url
        self.anthropic_key        = anthropic_key
        self.enable_hallucination = enable_hallucination
        self.flush_interval       = flush_interval
        self.batch_size           = batch_size
        self.debug                = debug

        # Thread-local tags (user_id, team overrides, etc.)
        self._local = threading.local()

        # Event queue — bounded to prevent OOM
        self._queue: queue.Queue[CohrintEvent] = queue.Queue(maxsize=10_000)

        # Async event loop for hallucination scoring (runs in background thread)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_thread: Optional[threading.Thread] = None

        self._start_background_flusher()
        if self.enable_hallucination and self.anthropic_key:
            self._start_async_loop()

        if debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.debug("CohrintClient ready — org=%s env=%s", org, environment)

    # ── Tag management ────────────────────────────────────────────────────────

    def set_tag(self, key: str, value: str) -> None:
        if not hasattr(self._local, "tags"):
            self._local.tags = {}
        self._local.tags[key] = value

    def clear_tags(self) -> None:
        self._local.tags = {}

    def get_tags(self) -> dict[str, str]:
        return dict(getattr(self._local, "tags", {}))

    # ── Capture ───────────────────────────────────────────────────────────────

    def capture(self, event: CohrintEvent) -> None:
        """
        Enqueue event for async ingest. Never blocks the caller.
        Merges org/team/project context + thread-local tags.
        """
        # Inject global context
        if not event.org_id:     event.org_id     = self.org
        if not event.team:       event.team        = self.team
        if not event.project:    event.project     = self.project
        if not event.environment: event.environment = self.environment
        if not event.agent:      event.agent       = self.agent

        # Merge thread-local tags
        merged = {**self.get_tags(), **event.tags}
        # Promote well-known tag keys
        if "team"    in merged and not event.team:    event.team    = merged.pop("team")
        if "project" in merged and not event.project: event.project = merged.pop("project")
        if "user_id" in merged and not event.user_id: event.user_id = merged.pop("user_id")
        event.tags = merged

        if self.debug:
            logger.debug(
                "[vantage] %s/%s | %d tok | $%.6f | lat=%.0fms | hall=%.2f",
                event.provider, event.model,
                event.total_tokens, event.total_cost_usd,
                event.latency_ms,
                event.hallucination_score or -1,
            )

        try:
            self._queue.put_nowait(event)
            # Warn early at 80% capacity (8000/10000) to give time to react
            qsize = self._queue.qsize()
            if qsize >= 8_000 and qsize % 500 == 0:
                logger.warning(
                    "[vantage] Queue at %d/10000 — flush_interval may be too slow; "
                    "events will be dropped at capacity",
                    qsize,
                )
        except queue.Full:
            logger.warning("[vantage] Queue full (10000) — dropping event silently")

        # Trigger async hallucination scoring if we have content
        if (
            self.enable_hallucination
            and self.anthropic_key
            and self._loop
            and event.request_preview
            and event.response_preview
            and event.hallucination_score is None
        ):
            asyncio.run_coroutine_threadsafe(
                self._score_hallucination(event), self._loop
            )

    # ── Async hallucination scoring ───────────────────────────────────────────

    async def _score_hallucination(self, event: CohrintEvent) -> None:
        """
        Calls Claude Opus 4.6 to score hallucination + quality.
        Runs concurrently — never blocks the main event loop.
        Updates the event in-place then re-queues it for patch upload.
        """
        try:
            from cohrint.analysis.hallucination import evaluate_response
            scores = await evaluate_response(
                user_query    = event.request_preview,
                ai_response   = event.response_preview,
                model         = event.model,
                system_prompt = event.system_preview,
                anthropic_key = self.anthropic_key,
            )
            event.hallucination_score  = scores.get("hallucination_score")
            event.faithfulness_score   = scores.get("relevance_score")
            event.relevancy_score      = scores.get("relevance_score")
            event.consistency_score    = scores.get("coherence_score")
            event.toxicity_score       = scores.get("toxicity_score")
            event.efficiency_score     = int(scores.get("overall_quality", 5.0) * 10)
            event.analysis_done        = True

            # Send a patch event to update the scores on the server
            await self._patch_event_async(event)

        except Exception as e:
            logger.debug("[vantage] Hallucination scoring error: %s", e)

    async def _patch_event_async(self, event: CohrintEvent) -> None:
        """PATCH /v1/events/{id}/scores with quality metrics."""
        patch_url = self.ingest_url.replace("/events", f"/events/{event.event_id}/scores")
        payload = json.dumps({
            "hallucination_score": event.hallucination_score,
            "faithfulness_score":  event.faithfulness_score,
            "relevancy_score":     event.relevancy_score,
            "consistency_score":   event.consistency_score,
            "toxicity_score":      event.toxicity_score,
            "efficiency_score":    event.efficiency_score,
        }).encode()
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    patch_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if self.debug:
                        logger.debug("[vantage] Scores patched → %s", resp.status)
        except Exception as e:
            logger.debug("[vantage] Score patch failed: %s", e)

    def _start_async_loop(self) -> None:
        """Dedicated event loop for async hallucination scoring."""
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_forever()

        self._async_thread = threading.Thread(
            target=_run, daemon=True, name="vantage-async"
        )
        self._async_thread.start()
        # Give loop time to start
        for _ in range(10):
            if self._loop:
                break
            time.sleep(0.05)

    # ── Sync flush ────────────────────────────────────────────────────────────

    def flush(self) -> None:
        batch: list[CohrintEvent] = []
        try:
            while len(batch) < self.batch_size:
                batch.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if batch:
            self._send_batch(batch)

    def _send_batch(self, events: list[CohrintEvent]) -> None:
        payload = json.dumps({
            "events": [e.to_dict() for e in events],
            "sdk_version": "0.2.0",
        }).encode()
        req = urllib.request.Request(
            self.ingest_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "X-Vantage-Org": self.org,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if self.debug:
                    logger.debug("[vantage] Flushed %d events → %s", len(events), resp.status)
        except urllib.error.URLError as e:
            logger.warning("[vantage] Ingest failed: %s", e)
        except Exception as e:
            logger.warning("[vantage] Unexpected error: %s", e)

    def _start_background_flusher(self) -> None:
        def _run():
            while True:
                time.sleep(self.flush_interval)
                try:
                    self.flush()
                except Exception as e:
                    logger.debug("[vantage] Flush error: %s", e)

        t = threading.Thread(target=_run, daemon=True, name="vantage-flusher")
        t.start()

    def __repr__(self) -> str:
        return (
            f"CohrintClient(org={self.org!r}, env={self.environment!r}, "
            f"queue={self._queue.qsize()}, hall={self.enable_hallucination})"
        )
