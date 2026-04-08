"""Tests for vantage_agent.rate_limiter — 8 unit tests using tmp_path fixtures."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# We patch Path.home() globally inside each test so all _STATE_FILE / sessions_dir
# references resolve under tmp_path instead of ~/.vantage/
import vantage_agent.rate_limiter as rl


def _home_patcher(tmp_path: Path):
    """Return a context manager that redirects Path.home() to tmp_path AND
    re-points the module-level _STATE_FILE constant."""
    from unittest.mock import patch as _patch
    import contextlib

    @contextlib.contextmanager
    def _cm():
        new_state = tmp_path / ".vantage" / "rate_state.json"
        with _patch.object(Path, "home", return_value=tmp_path), \
             _patch.object(rl, "_STATE_FILE", new_state):
            yield

    return _cm()


# ---------------------------------------------------------------------------
# 1. acquire() succeeds when tokens available
# ---------------------------------------------------------------------------
def test_acquire_succeeds_with_tokens(tmp_path):
    with _home_patcher(tmp_path):
        # Fresh bucket has 60 tokens
        result = rl.acquire(1.0)
    assert result is True


# ---------------------------------------------------------------------------
# 2. acquire() fails when bucket empty
# ---------------------------------------------------------------------------
def test_acquire_fails_when_empty(tmp_path):
    state_file = tmp_path / ".vantage" / "rate_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Write a bucket with 0 tokens and last_refill = now (no time to refill)
    bucket = rl.RateBucket(tokens=0.0, capacity=60.0, refill_rate=0.0, last_refill=time.time())
    state_file.write_text(json.dumps(rl.asdict(bucket)))

    with _home_patcher(tmp_path):
        result = rl.acquire(1.0)
    assert result is False


# ---------------------------------------------------------------------------
# 3. _refill() adds tokens based on elapsed time
# ---------------------------------------------------------------------------
def test_refill_adds_tokens():
    past = time.time() - 10.0  # 10 seconds ago
    bucket = rl.RateBucket(tokens=0.0, capacity=60.0, refill_rate=1.0, last_refill=past)
    refilled = rl._refill(bucket)
    # Should have gained ~10 tokens (1.0/sec × 10s)
    assert refilled.tokens >= 9.9
    assert refilled.tokens <= 10.1


# ---------------------------------------------------------------------------
# 4. Bucket doesn't exceed capacity
# ---------------------------------------------------------------------------
def test_refill_does_not_exceed_capacity():
    past = time.time() - 1000.0  # very old
    bucket = rl.RateBucket(tokens=50.0, capacity=60.0, refill_rate=1.0, last_refill=past)
    refilled = rl._refill(bucket)
    assert refilled.tokens == 60.0


# ---------------------------------------------------------------------------
# 5. get_global_budget_used() returns 0 when no sessions dir
# ---------------------------------------------------------------------------
def test_global_budget_zero_no_sessions(tmp_path):
    # No sessions directory created
    with _home_patcher(tmp_path):
        total = rl.get_global_budget_used()
    assert total == 0.0


# ---------------------------------------------------------------------------
# 6. get_global_budget_used() sums across multiple session files
# ---------------------------------------------------------------------------
def test_global_budget_sums_sessions(tmp_path):
    sessions_dir = tmp_path / ".vantage" / "sessions"
    sessions_dir.mkdir(parents=True)

    for i, cost in enumerate([0.50, 1.25, 0.10]):
        (sessions_dir / f"session_{i}.json").write_text(
            json.dumps({"cost_summary": {"total_cost_usd": cost}})
        )
    # One malformed file — should be skipped silently
    (sessions_dir / "bad.json").write_text("not-json")

    with _home_patcher(tmp_path):
        total = rl.get_global_budget_used()
    assert abs(total - 1.85) < 1e-9


# ---------------------------------------------------------------------------
# 7. wait_for_token() returns True when token available immediately
# ---------------------------------------------------------------------------
def test_wait_for_token_returns_true_immediately(tmp_path):
    with _home_patcher(tmp_path):
        result = rl.wait_for_token(cost=1.0, max_wait=5.0)
    assert result is True


# ---------------------------------------------------------------------------
# 8. wait_for_token() returns False when max_wait exceeded
# ---------------------------------------------------------------------------
def test_wait_for_token_returns_false_on_timeout(tmp_path):
    state_file = tmp_path / ".vantage" / "rate_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Zero tokens, zero refill rate — will never get a token
    bucket = rl.RateBucket(tokens=0.0, capacity=60.0, refill_rate=0.0, last_refill=time.time())
    state_file.write_text(json.dumps(rl.asdict(bucket)))

    with _home_patcher(tmp_path):
        result = rl.wait_for_token(cost=1.0, max_wait=0.6)  # 0.6s → ~1 retry loop
    assert result is False
