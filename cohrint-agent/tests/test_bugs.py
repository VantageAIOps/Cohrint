"""Regression tests for 5 pre-existing bugs."""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import httpx
import pytest

from cohrint_agent.optimizer import optimize_prompt
from cohrint_agent.tracker import Tracker, TrackerConfig


# ---------------------------------------------------------------------------
# Bug 1: Semantic corruption — "whether or not"
# ---------------------------------------------------------------------------

def test_whether_or_not_preserves_question_intent():
    """'whether or not' must NOT be stripped — changes question to directive."""
    original = "Tell me whether or not to delete the file"
    result = optimize_prompt(original)
    optimized = result.optimized if hasattr(result, "optimized") else str(result)
    assert "whether" in optimized.lower(), (
        f"'whether or not' was incorrectly stripped. Got: {optimized!r}"
    )


# ---------------------------------------------------------------------------
# Bug 2: anonymized privacy mode not implemented
# ---------------------------------------------------------------------------

def _make_tracker(privacy: str) -> Tracker:
    cfg = TrackerConfig(api_key="test-key", privacy=privacy)
    return Tracker(cfg)


def test_anonymized_mode_strips_agent_name_and_hashes_event_id():
    """anonymized mode must strip agent_name/team and hash event_id."""
    tracker = _make_tracker("anonymized")
    tracker.record(
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        latency_ms=200,
        agent_name="my-team-agent",
    )
    with tracker._lock:
        event = tracker._queue[0]

    assert event.agent_name == "", (
        f"agent_name not stripped in anonymized mode: {event.agent_name!r}"
    )
    assert event.team == "", (
        f"team not stripped in anonymized mode: {event.team!r}"
    )
    assert len(event.event_id) == 64 and all(
        c in "0123456789abcdef" for c in event.event_id
    ), f"event_id not hashed in anonymized mode: {event.event_id!r}"


# ---------------------------------------------------------------------------
# Bug 3: Unknown agent defaults to "anthropic" provider
# ---------------------------------------------------------------------------

def test_unknown_agent_provider_defaults_to_unknown_not_anthropic():
    """Unrecognised agent_name must map to 'unknown', not 'anthropic'."""
    tracker = _make_tracker("full")
    tracker.record(
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.002,
        latency_ms=300,
        agent_name="some-random-gpt-tool",
    )
    with tracker._lock:
        event = tracker._queue[0]
    assert event.provider == "unknown", (
        f"Unknown agent mapped to provider {event.provider!r} instead of 'unknown'"
    )


# ---------------------------------------------------------------------------
# Bug 4: Pricing dictionaries inconsistent
# ---------------------------------------------------------------------------

def test_pricing_dictionaries_consistent():
    """cost_tracker.py and pricing.py must use the same model key for claude-haiku-4-5."""
    from cohrint_agent.pricing import MODEL_PRICES
    from cohrint_agent.cost_tracker import MODEL_PRICING

    haiku_key_in_pricing = any("haiku-4-5" in k for k in MODEL_PRICES)
    haiku_key_in_tracker = any("haiku-4-5" in k for k in MODEL_PRICING)
    assert haiku_key_in_pricing, "claude-haiku-4-5 not found in pricing.MODEL_PRICES"
    assert haiku_key_in_tracker, "claude-haiku-4-5 not found in cost_tracker.MODEL_PRICING"

    pricing_key = next(k for k in MODEL_PRICES if "haiku-4-5" in k)
    tracker_key = next(k for k in MODEL_PRICING if "haiku-4-5" in k)
    assert pricing_key == tracker_key, (
        f"Key mismatch: pricing.py uses {pricing_key!r}, cost_tracker.py uses {tracker_key!r}"
    )


# ---------------------------------------------------------------------------
# Bug 5: Flush-before-success loses events
# ---------------------------------------------------------------------------

def test_flush_retains_events_on_network_error(tmp_path, monkeypatch):
    """Events must be preserved (in-queue OR spooled to disk) after HTTP POST fails.

    Current impl: on ConnectError the batch is written to ~/.cohrint/spool.jsonl
    and cleared from memory — persistent spool survives process restart, whereas
    in-memory retention does not. The invariant the user cares about is "no event
    lost", so we verify the sum across queue + spool.
    """
    # Redirect spool to an isolated tmp dir so the test is hermetic.
    import cohrint_agent.tracker as tracker_mod
    monkeypatch.setattr(tracker_mod, "_SPOOL_DIR", tmp_path)
    monkeypatch.setattr(tracker_mod, "_SPOOL_FILE", tmp_path / "spool.jsonl")
    monkeypatch.setattr(tracker_mod, "_SPOOL_LOCK_FILE", tmp_path / "spool.lock")

    tracker = _make_tracker("full")
    tracker.record(
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        latency_ms=100,
        agent_name="cohrint-agent",
    )
    assert len(tracker._queue) == 1

    with patch("httpx.post", side_effect=httpx.ConnectError("timeout")):
        tracker.flush()

    spool_file = tmp_path / "spool.jsonl"
    spooled_lines = (
        [ln for ln in spool_file.read_text().splitlines() if ln.strip()]
        if spool_file.exists() else []
    )
    preserved = len(tracker._queue) + len(spooled_lines)
    assert preserved >= 1, (
        f"Event lost after failed HTTP POST: queue={len(tracker._queue)}, "
        f"spooled={len(spooled_lines)}"
    )
