"""
vantage-ai SDK — init
"""
from __future__ import annotations
import logging
from typing import Optional
from vantage.utils.queue import EventQueue

logger = logging.getLogger("vantage")
_queue: Optional[EventQueue] = None
_config: dict = {}


def init(api_key: str, *, org: str = "", team: str = "", environment: str = "production",
         ingest_url: str = "https://ingest.vantage.ai", flush_interval: float = 2.0,
         batch_size: int = 50, debug: bool = False) -> None:
    global _queue, _config
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    if not org:
        parts = api_key.split("_")
        org = parts[1] if len(parts) >= 3 else "default"
    _config = {"api_key": api_key, "org_id": org, "team": team,
               "environment": environment, "ingest_url": ingest_url, "debug": debug}
    _queue = EventQueue(api_key=api_key, ingest_url=ingest_url,
                        flush_interval=flush_interval, batch_size=batch_size, debug=debug)
    _queue.start()
    logger.info("Vantage initialised — org=%s env=%s", org, environment)


def _get_queue() -> EventQueue:
    if _queue is None:
        raise RuntimeError("Call vantage.init(api_key=...) first.")
    return _queue


def _get_config() -> dict:
    return _config


def tag(key: str, value: str) -> None:
    from vantage.proxy.universal import _CTX_TAGS
    _CTX_TAGS.set({**_CTX_TAGS.get({}), key: value})


def flush() -> None:
    if _queue:
        _queue.flush_sync()


from vantage.proxy.universal import trace
__version__ = "1.0.0"
__all__ = ["init", "trace", "tag", "flush", "__version__"]
