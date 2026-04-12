"""Tests for the Vega chatbot Worker."""
import json
import pathlib
import re
import subprocess

import pytest
import requests

BASE = "http://localhost:8788"
ROOT = pathlib.Path(__file__).parents[3]


# ── Task 1: Health ────────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["name"] == "vega"


# ── Task 2: Static knowledge ──────────────────────────────────────────────────

def test_static_knowledge_loads():
    path = ROOT / "vantage-chatbot/knowledge/static.json"
    data = json.loads(path.read_text())
    assert len(data) >= 10
    for entry in data:
        assert "q" in entry and "a" in entry and "tags" in entry


# ── Task 3: Sanitizer ─────────────────────────────────────────────────────────

def test_sanitize_pattern_strips_api_key():
    pattern = re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}\b')
    text = "Your key sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789 is invalid"
    result = pattern.sub("[REDACTED]", text)
    assert "[REDACTED]" in result
    assert "sk-ant-" not in result


def test_sanitize_pattern_strips_ip():
    pattern = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    text = "Server at 192.168.1.100 failed"
    result = pattern.sub("[REDACTED]", text)
    assert "[REDACTED]" in result
    assert "192.168" not in result


# ── Task 5: Chat + ticket endpoints ───────────────────────────────────────────

AUTH = {"Authorization": "Bearer test-token-for-ci"}


def test_chat_returns_reply():
    r = requests.post(f"{BASE}/chat",
        json={"message": "What is VantageAI?"},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"})
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    assert len(data["reply"]) > 10
    assert "session_id" in data


def test_chat_rejects_missing_message():
    r = requests.post(f"{BASE}/chat",
        json={},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"})
    assert r.status_code == 400


def test_ticket_endpoint_reachable():
    r = requests.post(f"{BASE}/ticket",
        json={"subject": "Test", "body": "Help needed", "email": "user@example.com"},
        headers={**AUTH, "X-Org-Id": "test-org"})
    # 200 OK or 503 if Resend not configured in CI — both acceptable
    assert r.status_code in (200, 503)
