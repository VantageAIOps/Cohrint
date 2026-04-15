"""
test_security_hardening.py — Security Hardening Tests
======================================================
Suite SH: Validates brute-force protection on /v1/auth/session and
prompt_hash format validation on /v1/events.

Checks:
  SH.1  POST /v1/auth/session with wrong key → 401 (not locked out initially)
  SH.2  POST /v1/events with valid 32-char hex prompt_hash → accepted
  SH.3  POST /v1/events with 16-char hex prompt_hash → 400 (below minimum)
  SH.4  POST /v1/events with non-hex prompt_hash → 400
  SH.5  POST /v1/events with 128-char hex prompt_hash → accepted (upper bound)
  SH.6  POST /v1/events with 129-char hex prompt_hash → 400 (above maximum)
  SH.7  POST /v1/events with null prompt_hash → accepted (field is optional)
  SH.8  POST /v1/events/batch with invalid prompt_hash in one item → 400
"""

import sys
import uuid
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.output import section, chk, get_results

SESSION_URL = f"{API_URL}/v1/auth/session"
EVENTS_URL  = f"{API_URL}/v1/events"


def make_event(prompt_hash=None):
    ev = {
        "event_id":          f"sh-{uuid.uuid4()}",
        "provider":          "anthropic",
        "model":             "claude-sonnet-4-6",
        "prompt_tokens":     100,
        "completion_tokens": 50,
        "total_tokens":      150,
        "cost_usd":          0.001,
        "latency_ms":        500,
    }
    if prompt_hash is not None:
        ev["prompt_hash"] = prompt_hash
    return ev


def test_session_invalid_key_returns_401():
    section("SH — /v1/auth/session brute-force protection")

    r = requests.post(SESSION_URL, json={"api_key": "crt_thiskeyisinvalid"}, timeout=15)
    chk("SH.1  Invalid key → 401 (not locked out on first attempt)",
        r.status_code == 401, f"got {r.status_code}")


def test_prompt_hash_validation(headers):
    section("SH — prompt_hash format validation")

    # SH.2: Valid 32-char hex — should be accepted
    r = requests.post(EVENTS_URL, json=make_event("a" * 32), headers=headers, timeout=15)
    chk("SH.2  32-char hex prompt_hash → 201",
        r.status_code in (200, 201), f"got {r.status_code}: {r.text[:200]}")

    # SH.3: 16-char hex — below minimum, should be rejected
    r = requests.post(EVENTS_URL, json=make_event("b" * 16), headers=headers, timeout=15)
    chk("SH.3  16-char hex prompt_hash → 400",
        r.status_code == 400, f"got {r.status_code}")

    # SH.4: Non-hex string — should be rejected
    r = requests.post(EVENTS_URL, json=make_event("sha256:notvalidhex" + "x" * 20), headers=headers, timeout=15)
    chk("SH.4  Non-hex prompt_hash → 400",
        r.status_code == 400, f"got {r.status_code}")

    # SH.5: 128-char hex — upper bound, should be accepted
    r = requests.post(EVENTS_URL, json=make_event("c" * 128), headers=headers, timeout=15)
    chk("SH.5  128-char hex prompt_hash → 201",
        r.status_code in (200, 201), f"got {r.status_code}: {r.text[:200]}")

    # SH.6: 129-char hex — above maximum, should be rejected
    r = requests.post(EVENTS_URL, json=make_event("d" * 129), headers=headers, timeout=15)
    chk("SH.6  129-char hex prompt_hash → 400",
        r.status_code == 400, f"got {r.status_code}")

    # SH.7: null/missing prompt_hash — field is optional, should be accepted
    r = requests.post(EVENTS_URL, json=make_event(None), headers=headers, timeout=15)
    chk("SH.7  Missing prompt_hash → 201 (field optional)",
        r.status_code in (200, 201), f"got {r.status_code}: {r.text[:200]}")


def test_batch_prompt_hash_validation(headers):
    section("SH — batch endpoint prompt_hash validation")

    valid_ev   = make_event("e" * 32)
    invalid_ev = make_event("f" * 16)  # below minimum

    r = requests.post(f"{EVENTS_URL}/batch", json={"events": [valid_ev, invalid_ev]},
                      headers=headers, timeout=15)
    chk("SH.8  Batch with one invalid prompt_hash → 400",
        r.status_code == 400, f"got {r.status_code}")


def test_results():
    results = get_results()
    passed  = sum(1 for v in results.values() if v)
    total   = len(results)
    assert passed == total, f"{total - passed}/{total} SH checks failed"
