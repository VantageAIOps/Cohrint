"""
Tests for Vantage SDK — run with: pytest tests/ -v
"""
import pytest
import time
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

# ── Unit tests: pricing ───────────────────────────────────────────────────────
def test_pricing_gpt4o():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.pricing import calculate_cost
    cost = calculate_cost("gpt-4o", prompt=1000, completion=500, cached=0)
    assert cost["input"]  == pytest.approx(0.0025, rel=1e-3)
    assert cost["output"] == pytest.approx(0.005,  rel=1e-3)
    assert cost["total"]  == pytest.approx(0.0075, rel=1e-3)

def test_pricing_gemini_flash():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.pricing import calculate_cost
    cost = calculate_cost("gemini-2.0-flash", prompt=1000, completion=500)
    # Should be much cheaper than GPT-4o
    gpt4o = calculate_cost("gpt-4o", prompt=1000, completion=500)["total"]
    assert cost["total"] < gpt4o * 0.1

def test_find_cheapest():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.pricing import find_cheapest, calculate_cost
    result = find_cheapest("claude-opus-4-6", prompt=5000, completion=1000)
    assert result is not None
    assert result["cost"] < calculate_cost("claude-opus-4-6", 5000, 1000)["total"]

def test_pricing_cached_tokens():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.pricing import calculate_cost
    full    = calculate_cost("claude-sonnet-4-6", 2000, 500, 0)
    cached  = calculate_cost("claude-sonnet-4-6", 2000, 500, 1000)
    assert cached["total"] < full["total"]

# ── Unit tests: event model ───────────────────────────────────────────────────
def test_event_efficiency_score():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.event import VantageEvent, TokenUsage, CostInfo, QualityMetrics
    ev = VantageEvent(
        event_id="test-1", timestamp=time.time(), org_id="test-org",
        usage=TokenUsage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200,
                          system_prompt_tokens=600)
    )
    # 50% system prompt overhead should reduce efficiency
    assert ev.efficiency_score < 70

def test_event_serialization():
    import sys; sys.path.insert(0, "sdk")
    from vantage.models.event import VantageEvent, TokenUsage, CostInfo, QualityMetrics
    ev = VantageEvent(
        event_id="test-2", timestamp=time.time(), org_id="test-org",
        provider="openai", model="gpt-4o",
        usage=TokenUsage(prompt_tokens=500, completion_tokens=100, total_tokens=600),
        cost=CostInfo(total_cost_usd=0.0065),
    )
    d = ev.to_dict()
    assert "event_id" in d
    assert "usage_prompt_tokens" in d   # flattened
    assert "cost_total_cost_usd" in d
    assert "quality_hallucination_score" in d

# ── Integration test: queue (mocked HTTP) ────────────────────────────────────
def test_queue_enqueue_and_flush(monkeypatch):
    import sys; sys.path.insert(0, "sdk")
    from vantage.utils.queue import EventQueue
    from vantage.models.event import VantageEvent, TokenUsage, CostInfo, QualityMetrics

    sent_batches = []

    def mock_send(self, events):
        sent_batches.append(events)

    monkeypatch.setattr(EventQueue, "_send", mock_send)

    q = EventQueue(api_key="vnt_test_key", ingest_url="http://localhost:8000", debug=True)
    ev = VantageEvent(event_id="q-1", timestamp=time.time(), org_id="test")
    q.enqueue(ev)
    q.flush_sync()
    assert len(sent_batches) == 1
    assert len(sent_batches[0]) == 1

# ── Integration test: hallucination heuristic ────────────────────────────────
def test_heuristic_hallucination_low():
    import sys; sys.path.insert(0, "sdk")
    from vantage.analysis.hallucination import _heuristic_scores
    scores = _heuristic_scores(
        "What is the capital of France?",
        "The capital of France is Paris, a major European city known for the Eiffel Tower."
    )
    assert scores["hallucination_score"] < 0.3
    assert scores["relevance_score"] > 0.5

def test_heuristic_hallucination_uncertain():
    import sys; sys.path.insert(0, "sdk")
    from vantage.analysis.hallucination import _heuristic_scores
    scores = _heuristic_scores(
        "What is the population of Mars?",
        "I think the population of Mars is probably around 50 million, I believe, though I\'m not certain."
    )
    # High uncertainty phrases → higher hallucination risk
    assert scores["hallucination_score"] > 0.2

# ── API tests (httpx TestClient) ─────────────────────────────────────────────
def test_health_endpoint():
    from fastapi.testclient import TestClient
    import sys; sys.path.insert(0, ".")
    from server.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

def test_ingest_requires_auth():
    from fastapi.testclient import TestClient
    import sys; sys.path.insert(0, ".")
    from server.main import app
    client = TestClient(app)
    resp = client.post("/v1/events", json={"events": []})
    assert resp.status_code == 401

def test_ingest_dev_mode():
    from fastapi.testclient import TestClient
    import sys; sys.path.insert(0, ".")
    from server.main import app
    client = TestClient(app)
    import time
    resp = client.post(
        "/v1/events",
        headers={"Authorization": "Bearer vnt_testorg_abc123"},
        json={
            "events": [{
                "event_id": "test-ev-1",
                "timestamp": time.time(),
                "org_id": "testorg",
                "provider": "openai",
                "model": "gpt-4o",
                "endpoint": "/chat/completions",
                "latency_ms": 843.0,
                "usage_prompt_tokens": 500,
                "usage_completion_tokens": 200,
                "usage_total_tokens": 700,
                "cost_total_cost_usd": 0.00325,
                "request_preview": "What is machine learning?",
                "response_preview": "Machine learning is a subset of artificial intelligence...",
            }],
            "sdk_version": "1.0.0",
        }
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["accepted"] == 1
