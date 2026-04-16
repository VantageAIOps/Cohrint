"""Tests for tracker.py — dashboard telemetry client."""
import pytest
from unittest.mock import patch, MagicMock
from vantage_agent.tracker import Tracker, TrackerConfig, DashboardEvent, PROVIDER_MAP


class TestTrackerConfig:
    def test_defaults(self):
        cfg = TrackerConfig()
        assert cfg.api_key == ""
        assert cfg.batch_size == 10
        assert cfg.flush_interval == 30.0
        assert cfg.privacy == "full"


class TestProviderMap:
    def test_known_providers(self):
        assert PROVIDER_MAP["claude"] == "anthropic"
        assert PROVIDER_MAP["gemini"] == "google"
        assert PROVIDER_MAP["codex"] == "openai"


class TestTracker:
    def test_start_noop_without_key(self):
        t = Tracker(TrackerConfig(api_key=""))
        t.start()
        assert not t._running

    def test_start_noop_local_only(self):
        t = Tracker(TrackerConfig(api_key="test", privacy="local-only"))
        t.start()
        assert not t._running

    def test_start_with_key(self):
        t = Tracker(TrackerConfig(api_key="test"))
        t.start()
        assert t._running
        t.stop()

    def test_record_queues_event(self):
        t = Tracker(TrackerConfig(api_key="test", batch_size=100))
        t.start()
        t.record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=50,
                 cost_usd=0.01, latency_ms=500)
        assert len(t._queue) == 1
        assert t._queue[0].model == "claude-sonnet-4-6"
        assert t._queue[0].total_tokens == 150
        t.stop()

    @patch("vantage_agent.tracker.httpx.post")
    def test_flush_sends_batch(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        t = Tracker(TrackerConfig(api_key="test-key", batch_size=100))
        t.record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=50,
                 cost_usd=0.01, latency_ms=500)
        t.flush()
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "events" in call_kwargs.kwargs["json"]
        assert len(t._queue) == 0

    @patch("vantage_agent.tracker.httpx.post")
    def test_auto_flush_at_batch_size(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        t = Tracker(TrackerConfig(api_key="test-key", batch_size=2))
        t.record(model="m", input_tokens=1, output_tokens=1, cost_usd=0.001, latency_ms=10)
        assert mock_post.call_count == 0
        t.record(model="m", input_tokens=1, output_tokens=1, cost_usd=0.001, latency_ms=10)
        assert mock_post.call_count == 1

    @patch("vantage_agent.tracker.httpx.post")
    def test_strict_privacy_strips_agent_name(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        t = Tracker(TrackerConfig(api_key="test-key", batch_size=100, privacy="strict"))
        t.record(model="m", input_tokens=1, output_tokens=1, cost_usd=0.001, latency_ms=10)
        t.flush()
        events = mock_post.call_args.kwargs["json"]["events"]
        assert "agent_name" not in events[0]

    def test_flush_noop_empty_queue(self):
        t = Tracker(TrackerConfig(api_key="test"))
        t.flush()  # should not raise

    @patch("vantage_agent.tracker.httpx.post", side_effect=Exception("network error"))
    def test_flush_handles_error(self, mock_post):
        t = Tracker(TrackerConfig(api_key="test-key", batch_size=100))
        t.record(model="m", input_tokens=1, output_tokens=1, cost_usd=0.001, latency_ms=10)
        t.flush()  # should not raise
