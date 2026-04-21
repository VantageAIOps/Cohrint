"""Token-bucket rate limiter with persistent state in ~/.cohrint-agent/rate_state.json."""
from __future__ import annotations

import fcntl
import json
import os
import time
import threading
from pathlib import Path
from dataclasses import dataclass, asdict

from .process_safety import safe_config_dir


# Lazy-resolve _STATE_FILE so import doesn't call Path.home() at module
# load. pwd.getpwuid() can fail in minimal containers (T-SAFETY.lazy_config_dir).
# Tests that patch _STATE_FILE directly still work — monkeypatch.setattr
# creates a real module attribute that shadows this fallback getter.
def __getattr__(name: str):
    if name == "_STATE_FILE":
        return safe_config_dir() / "rate_state.json"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
_LOCK = threading.Lock()  # in-process guard; file lock (below) covers cross-process

# TTL cache for get_global_budget_used
_budget_cache: dict = {"value": None, "ts": 0.0}
_BUDGET_CACHE_TTL = 10.0  # seconds


@dataclass
class RateBucket:
    tokens: float          # current token count
    capacity: float        # max tokens (default: 60 requests/min = 60.0)
    refill_rate: float     # tokens per second (default: 1.0 = 60/min)
    last_refill: float     # unix timestamp of last refill


import math

def _bucket_is_sane(b: RateBucket) -> bool:
    """Reject NaN/inf/negative/absurdly-large persisted bucket state."""
    for v in (b.tokens, b.capacity, b.refill_rate, b.last_refill):
        if not isinstance(v, (int, float)):
            return False
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return False
    if b.tokens < 0 or b.tokens > 1e6:
        return False
    if b.capacity <= 0 or b.capacity > 1e6:
        return False
    if b.refill_rate < 0 or b.refill_rate > 1e4:
        return False
    # last_refill in the future (beyond clock skew) signals a stale or
    # hostile state file; we only accept up to 60 s ahead.
    if b.last_refill <= 0 or b.last_refill > time.time() + 60:
        return False
    return True


def _refill(bucket: RateBucket) -> RateBucket:
    now = time.time()
    # Clamp elapsed to zero so a backward clock step (NTP step-correction
    # after a container wake, DST flip, manual `date` change) can neither
    # drain tokens nor seed a negative last_refill delta into the persisted
    # file (T-SAFETY.clock_rollback).
    elapsed = max(0.0, now - bucket.last_refill)
    new_tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.refill_rate)
    return RateBucket(tokens=new_tokens, capacity=bucket.capacity,
                      refill_rate=bucket.refill_rate, last_refill=now)


def acquire(cost: float = 1.0) -> bool:
    """Try to consume `cost` tokens. Returns True if allowed, False if rate limited.
    Thread-safe via in-process lock + fcntl file lock (cross-process safe).
    Lock file is acquired BEFORE reading/writing state file."""
    # Derive paths from _STATE_FILE so tests can patch just _STATE_FILE
    state_file = _STATE_FILE
    lock_file = state_file.parent / "rate_state.lock"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        # Acquire lock file first, then read/write state file
        with open(lock_file, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                # Now safely read/write state file
                if state_file.exists():
                    raw = state_file.read_text()
                else:
                    raw = ""
                try:
                    bucket = RateBucket(**json.loads(raw)) if raw.strip() else None
                except Exception:
                    bucket = None
                # Field-sanity gate: an attacker with write access to the
                # state file could plant {"tokens": inf, ...} which permanently
                # reports allowed=True (rate-limiter defeat) or inject a NaN
                # which poisons downstream arithmetic. Drop untrusted values
                # and fall through to the default bucket below
                # (T-SAFETY.rate_state_validation).
                if bucket is not None and not _bucket_is_sane(bucket):
                    bucket = None
                if bucket is None:
                    bucket = RateBucket(tokens=60.0, capacity=60.0, refill_rate=1.0, last_refill=time.time())
                bucket = _refill(bucket)
                allowed = bucket.tokens >= cost
                if allowed:
                    bucket.tokens -= cost
                state_file.write_text(json.dumps(asdict(bucket)))
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
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
    """Sum total_cost_usd across all session files in the sessions dir.
    Results are cached for 10 seconds to avoid O(N) scan on every prompt."""
    now = time.time()
    # Derive sessions dir from _STATE_FILE so tests can patch just _STATE_FILE
    sessions_dir = _STATE_FILE.parent / "sessions"
    cache_key = str(sessions_dir)
    if (
        _budget_cache["value"] is not None
        and _budget_cache.get("key") == cache_key
        and (now - _budget_cache["ts"]) < _BUDGET_CACHE_TTL
    ):
        return _budget_cache["value"]

    total = 0.0
    if not sessions_dir.exists():
        _budget_cache.update({"value": total, "ts": now, "key": cache_key})
        return total
    for f in sessions_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            cs = data.get("cost_summary", {})
            total += cs.get("total_cost_usd", 0.0)
        except Exception:
            pass
    _budget_cache.update({"value": total, "ts": now, "key": cache_key})
    return total
