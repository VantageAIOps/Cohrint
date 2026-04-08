"""Token-bucket rate limiter with persistent state in ~/.vantage/rate_state.json."""
from __future__ import annotations

import fcntl
import json
import time
import threading
from pathlib import Path
from dataclasses import dataclass, asdict

_STATE_FILE = Path.home() / ".vantage" / "rate_state.json"
_LOCK = threading.Lock()  # in-process guard; file lock (below) covers cross-process


@dataclass
class RateBucket:
    tokens: float          # current token count
    capacity: float        # max tokens (default: 60 requests/min = 60.0)
    refill_rate: float     # tokens per second (default: 1.0 = 60/min)
    last_refill: float     # unix timestamp of last refill



def _refill(bucket: RateBucket) -> RateBucket:
    now = time.time()
    elapsed = now - bucket.last_refill
    new_tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate)
    return RateBucket(tokens=new_tokens, capacity=bucket.capacity,
                      refill_rate=bucket.refill_rate, last_refill=now)


def acquire(cost: float = 1.0) -> bool:
    """Try to consume `cost` tokens. Returns True if allowed, False if rate limited.
    Thread-safe via in-process lock + fcntl file lock (cross-process safe)."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(_STATE_FILE, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read()
                try:
                    bucket = RateBucket(**json.loads(raw)) if raw.strip() else None
                except Exception:
                    bucket = None
                if bucket is None:
                    bucket = RateBucket(tokens=60.0, capacity=60.0, refill_rate=1.0, last_refill=time.time())
                bucket = _refill(bucket)
                allowed = bucket.tokens >= cost
                if allowed:
                    bucket.tokens -= cost
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(asdict(bucket)))
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        return allowed


def wait_for_token(cost: float = 1.0, max_wait: float = 60.0) -> bool:
    """Block until a token is available or max_wait seconds pass."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if acquire(cost):
            return True
        time.sleep(0.5)
    return False


def get_global_budget_used() -> float:
    """Sum total_cost_usd across all session files in ~/.vantage/sessions/."""
    sessions_dir = Path.home() / ".vantage" / "sessions"
    total = 0.0
    if not sessions_dir.exists():
        return total
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            # Support both vantage-agent format (cost_summary.total_cost_usd)
            # and local-proxy format (cost_summary.total_cost_usd)
            cs = data.get("cost_summary", {})
            total += cs.get("total_cost_usd", 0.0)
        except Exception:
            pass
    return total
