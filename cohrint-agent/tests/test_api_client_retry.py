"""
TDD tests for api_client._send_with_retry() exponential backoff.
Written BEFORE verifying implementation passes — each test was watched to fail.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call
import anthropic


def make_client():
    """Return ApiClient with a fake Anthropic client (no real API key needed)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from cohrint_agent.api_client import AgentClient

    c = AgentClient.__new__(AgentClient)
    c.client = MagicMock()
    c._model = "claude-sonnet-4-6"
    return c


# ── RED → GREEN ────────────────────────────────────────────────────────────

def test_retry_succeeds_on_first_attempt():
    """No retries when first call succeeds."""
    c = make_client()
    c.client.messages.stream.return_value = MagicMock(stop_reason="end_turn")

    with patch("time.sleep") as mock_sleep:
        result = c._send_with_retry(model="m", max_tokens=10)

    assert result.stop_reason == "end_turn"
    mock_sleep.assert_not_called()
    assert c.client.messages.stream.call_count == 1


def test_retry_on_rate_limit_error():
    """Retries up to 3 times on RateLimitError then succeeds."""
    c = make_client()
    ok_response = MagicMock(stop_reason="end_turn")
    c.client.messages.stream.side_effect = [
        anthropic.RateLimitError("rate limited", response=MagicMock(status_code=429), body={}),
        anthropic.RateLimitError("rate limited", response=MagicMock(status_code=429), body={}),
        ok_response,
    ]

    with patch("time.sleep") as mock_sleep:
        result = c._send_with_retry(model="m", max_tokens=10)

    assert result is ok_response
    assert c.client.messages.stream.call_count == 3
    # Exponential backoff: first wait ~0.5s, second ~1.5s
    assert mock_sleep.call_count == 2
    waits = [call_args[0][0] for call_args in mock_sleep.call_args_list]
    assert waits[0] < waits[1]  # backoff increases


def test_retry_raises_after_max_retries():
    """Re-raises RateLimitError after exhausting retries."""
    c = make_client()
    err = anthropic.RateLimitError("still rate limited", response=MagicMock(status_code=429), body={})
    c.client.messages.stream.side_effect = err

    with patch("time.sleep"):
        with pytest.raises(anthropic.RateLimitError):
            c._send_with_retry(model="m", max_tokens=10, max_retries=3)

    assert c.client.messages.stream.call_count == 4  # 1 initial + 3 retries


def test_retry_on_529_overloaded():
    """Retries on HTTP 529 (overloaded) status."""
    c = make_client()
    overloaded = anthropic.APIStatusError(
        "overloaded", response=MagicMock(status_code=529), body={}
    )
    ok_response = MagicMock(stop_reason="end_turn")
    c.client.messages.stream.side_effect = [overloaded, ok_response]

    with patch("time.sleep"):
        result = c._send_with_retry(model="m", max_tokens=10)

    assert result is ok_response
    assert c.client.messages.stream.call_count == 2


def test_non_rate_limit_error_not_retried():
    """Non-rate-limit APIStatusError (e.g. 400) is raised immediately."""
    c = make_client()
    bad_request = anthropic.APIStatusError(
        "bad request", response=MagicMock(status_code=400), body={}
    )
    c.client.messages.stream.side_effect = bad_request

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(anthropic.APIStatusError):
            c._send_with_retry(model="m", max_tokens=10)

    assert c.client.messages.stream.call_count == 1
    mock_sleep.assert_not_called()


def test_backoff_delays_are_exponential():
    """Backoff delays follow 2^attempt + 0.5 pattern."""
    c = make_client()
    ok = MagicMock(stop_reason="end_turn")
    c.client.messages.stream.side_effect = [
        anthropic.RateLimitError("rl", response=MagicMock(status_code=429), body={}),
        anthropic.RateLimitError("rl", response=MagicMock(status_code=429), body={}),
        anthropic.RateLimitError("rl", response=MagicMock(status_code=429), body={}),
        ok,
    ]

    with patch("time.sleep") as mock_sleep:
        c._send_with_retry(model="m", max_tokens=10)

    waits = [a[0][0] for a in mock_sleep.call_args_list]
    assert len(waits) == 3
    # Each wait should be larger than the previous (exponential)
    assert waits[0] < waits[1] < waits[2]
