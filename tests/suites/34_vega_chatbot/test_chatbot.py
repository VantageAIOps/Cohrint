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


# ── Task 6: Doc chunks builder ────────────────────────────────────────────────

def test_build_chunks_produces_valid_json():
    result = subprocess.run(
        ["node", "knowledge/build-chunks.js"],
        capture_output=True, text=True,
        cwd=str(ROOT / "vantage-chatbot"),
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data) > 0
    assert "key" in data[0] and "value" in data[0]


# ── Task 7: Frontend widget ───────────────────────────────────────────────────

def test_widget_files_exist():
    base = ROOT / "vantage-final-v4/widget"
    assert (base / "chatbot.css").exists()
    assert (base / "chatbot.js").exists()


def test_widget_js_uses_safe_dom_only():
    js = (ROOT / "vantage-final-v4/widget/chatbot.js").read_text()
    assert ".innerHTML" not in js


def test_widget_css_has_required_selectors():
    css = (ROOT / "vantage-final-v4/widget/chatbot.css").read_text()
    assert "#vega-launcher" in css
    assert "#vega-panel" in css
    assert ".vega-msg" in css


# ── Task 8: Full coverage ─────────────────────────────────────────────────────

def test_chat_with_history():
    r = requests.post(
        f"{BASE}/chat",
        json={
            "message": "What about the Models tab?",
            "history": [
                {"role": "user", "content": "What is VantageAI?"},
                {"role": "assistant", "content": "VantageAI is an AI cost analytics platform."},
            ],
        },
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"},
    )
    assert r.status_code == 200
    assert "reply" in r.json()


def test_chat_accepts_long_message():
    r = requests.post(
        f"{BASE}/chat",
        json={"message": "x" * 2000},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"},
    )
    assert r.status_code == 200


def test_chat_session_id_persists():
    r = requests.post(
        f"{BASE}/chat",
        json={"message": "hello", "session_id": "my-session-abc"},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"},
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == "my-session-abc"


def test_chat_no_auth_allowed():
    r = requests.post(
        f"{BASE}/chat",
        json={"message": "What is VantageAI?"},
        headers={"X-Org-Id": "anon", "X-Plan": "free"},
    )
    assert r.status_code == 200


def test_chat_whitespace_rejected():
    r = requests.post(
        f"{BASE}/chat",
        json={"message": "   "},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"},
    )
    assert r.status_code == 400


def test_ticket_missing_fields():
    r = requests.post(
        f"{BASE}/ticket",
        json={"subject": "Test"},
        headers={**AUTH, "X-Org-Id": "test-org"},
    )
    assert r.status_code == 400


def test_ticket_invalid_email():
    r = requests.post(
        f"{BASE}/ticket",
        json={"subject": "Test", "body": "Help", "email": "not-an-email"},
        headers={**AUTH, "X-Org-Id": "test-org"},
    )
    assert r.status_code == 400


def test_health_name_is_vega():
    r = requests.get(f"{BASE}/health")
    assert r.json()["name"] == "vega"


def test_cors_on_preflight():
    r = requests.options(
        f"{BASE}/chat",
        headers={
            "Origin": "https://vantageaiops.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code in (200, 204)


def test_chat_reply_non_empty():
    r = requests.post(
        f"{BASE}/chat",
        json={"message": "How do budgets work?"},
        headers={**AUTH, "X-Org-Id": "test-org", "X-Plan": "free"},
    )
    assert r.status_code == 200
    assert r.json()["reply"].strip() != ""


def test_knowledge_basics_no_plan_gate():
    data = json.loads((ROOT / "vantage-chatbot/knowledge/static.json").read_text())
    basics = [e for e in data if "overview" in e.get("tags", []) or "product" in e.get("tags", [])]
    assert all("plan_gate" not in e for e in basics)


def test_knowledge_pro_entries_gated():
    data = json.loads((ROOT / "vantage-chatbot/knowledge/static.json").read_text())
    pro = [e for e in data if "pro" in e.get("tags", [])]
    assert all(e.get("plan_gate") in ("pro", "enterprise") for e in pro)


def test_app_html_injects_widget():
    html = (ROOT / "vantage-final-v4/app.html").read_text()
    assert 'href="/widget/chatbot.css"' in html
    assert 'src="/widget/chatbot.js"' in html
