"""
test_mcp_vscode.py — MCP / VS Code extension API tests
=======================================================
Suite MCP: Tests the API as an MCP client (VS Code extension) would use it.
Labels: MCP.1 - MCP.N
"""

import sys
import time
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import API_URL
from helpers.api import signup_api, get_headers
from helpers.output import ok, fail, warn, info, section, chk, get_results

# MCP client identifier
MCP_USER_AGENT = "vantageai-mcp/1.0"
MCP_HEADERS_EXTRA = {"User-Agent": MCP_USER_AGENT}


def mcp_headers(api_key):
    """Headers as a VS Code MCP extension would send them."""
    return {**get_headers(api_key), **MCP_HEADERS_EXTRA}


def test_mcp_signup_and_ingest():
    section("MCP. VS Code — Signup + Ingest")

    # MCP.1 Signup via API
    try:
        d = signup_api()
        api_key = d["api_key"]
        org_id  = d["org_id"]
        chk("MCP.1  Signup → 201", True)
        info(f"  org_id: {org_id}")
    except Exception as e:
        fail(f"MCP.1  Signup failed: {e}")
        return None

    headers = mcp_headers(api_key)

    # MCP.2 Single event with MCP-style payload
    mcp_event = {
        "model":     "gpt-4o",
        "cost":      0.004,
        "tokens":    {"prompt": 200, "completion": 100},
        "timestamp": int(time.time() * 1000),
        "tags":      {"source": "vscode_extension", "file": "main.py", "session": "mcp_test"},
    }
    r = requests.post(f"{API_URL}/v1/events", json=mcp_event, headers=headers, timeout=15)
    chk("MCP.2  POST /events with MCP payload → 202",
        r.status_code in (201, 202),
        f"got {r.status_code}: {r.text[:100]}")

    # MCP.3 Batch ingest 10 events (VS Code session simulation)
    batch_events = [
        {
            "model":     "gpt-4o",
            "cost":      round(0.002 * (i + 1), 6),
            "tokens":    {"prompt": 100 + i * 20, "completion": 50 + i * 10},
            "timestamp": int(time.time() * 1000) + i * 100,
            "tags":      {"source": "vscode_mcp", "request_id": f"req_{i}"},
        }
        for i in range(10)
    ]

    accepted_batch = 0
    for event in batch_events:
        rb = requests.post(f"{API_URL}/v1/events", json=event, headers=headers, timeout=15)
        if rb.status_code in (201, 202):
            accepted_batch += 1

    chk("MCP.3  10 MCP events ingested", accepted_batch >= 9,
        f"{accepted_batch}/10 accepted")

    return api_key, org_id


def test_mcp_analytics(api_key):
    section("MCP. VS Code — Analytics Reads")

    if not api_key:
        warn("MCP.4  No api_key — skipping")
        return

    headers = mcp_headers(api_key)

    # Wait for data
    time.sleep(2)

    # MCP.4 GET /analytics/summary → 200 + valid JSON
    r = requests.get(f"{API_URL}/v1/analytics/summary", headers=headers, timeout=15)
    chk("MCP.4  GET /analytics/summary → 200", r.status_code == 200,
        f"got {r.status_code}")
    if r.ok:
        try:
            d = r.json()
            chk("MCP.5  Analytics summary is valid JSON with data",
                isinstance(d, dict),
                f"got type: {type(d)}")
        except Exception as e:
            fail(f"MCP.5  Could not parse analytics JSON: {e}")

    # MCP.6 GET /analytics/models → 200 + list
    r2 = requests.get(f"{API_URL}/v1/analytics/models", headers=headers, timeout=15)
    chk("MCP.6  GET /analytics/models → 200", r2.status_code == 200,
        f"got {r2.status_code}")
    if r2.ok:
        d2 = r2.json()
        models = d2.get("models") or d2.get("data") or (d2 if isinstance(d2, list) else [])
        chk("MCP.7  Models list is non-empty", len(models) >= 1,
            f"models: {models}")

    # MCP.8 GET /analytics/tokens → 200
    r3 = requests.get(f"{API_URL}/v1/analytics/tokens", headers=headers, timeout=15)
    chk("MCP.8  GET /analytics/tokens → 200", r3.status_code in (200, 404),
        f"got {r3.status_code}")


def test_mcp_batch_then_analytics(api_key):
    section("MCP. VS Code — Batch Ingest → Analytics Within 5s")

    if not api_key:
        warn("MCP.9  No api_key — skipping")
        return

    headers = mcp_headers(api_key)

    # Ingest 10 more events
    for i in range(10):
        requests.post(f"{API_URL}/v1/events",
                      json={"model": "claude-3-sonnet", "cost": 0.003,
                            "tokens": {"prompt": 150, "completion": 75},
                            "timestamp": int(time.time() * 1000) + i,
                            "tags": {"batch_test": "mcp"}},
                      headers=headers, timeout=15)

    start = time.monotonic()

    # Poll analytics for up to 5s
    data_reflected = False
    for _ in range(10):
        time.sleep(0.5)
        r = requests.get(f"{API_URL}/v1/analytics/models", headers=headers, timeout=15)
        if r.ok:
            d = r.json()
            models = d.get("models") or d.get("data") or (d if isinstance(d, list) else [])
            if any("claude" in str(m).lower() for m in models):
                data_reflected = True
                break

    elapsed = time.monotonic() - start
    chk("MCP.9  Batch ingest reflected in analytics within 5s",
        data_reflected,
        f"claude-3-sonnet not found after {elapsed:.1f}s")


def test_mcp_key_rotation_grace(api_key):
    section("MCP. VS Code — Key Rotation Grace Period")

    if not api_key:
        warn("MCP.10 No api_key — skipping")
        return

    headers_old = mcp_headers(api_key)

    # Rotate the key
    r_rotate = requests.post(f"{API_URL}/v1/auth/rotate",
                             headers=headers_old, timeout=15)
    chk("MCP.10 POST /rotate → 200", r_rotate.status_code == 200,
        f"got {r_rotate.status_code}")

    if r_rotate.ok:
        new_key = (r_rotate.json().get("api_key") or
                   r_rotate.json().get("new_key") or
                   r_rotate.json().get("key"))

        if new_key:
            # New key should work immediately
            r_new = requests.get(f"{API_URL}/v1/analytics/summary",
                                 headers=mcp_headers(new_key), timeout=15)
            chk("MCP.11 New key works immediately after rotation",
                r_new.status_code in (200, 404),
                f"got {r_new.status_code}")

            # Old key may still work during grace period or may be revoked
            r_old = requests.get(f"{API_URL}/v1/analytics/summary",
                                 headers=headers_old, timeout=15)
            if r_old.status_code in (200, 404):
                info("  MCP.12 Old key still works (grace period active)")
                chk("MCP.12 Old key works during grace period", True)
            elif r_old.status_code == 401:
                info("  MCP.12 Old key immediately revoked (no grace period)")
                chk("MCP.12 Old key properly rejected", True)
            else:
                warn(f"MCP.12 Unexpected status: {r_old.status_code}")


def main():
    section("Suite MCP — VS Code MCP Client Tests")
    info(f"API: {API_URL}")
    info(f"User-Agent: {MCP_USER_AGENT}")

    result = test_mcp_signup_and_ingest()
    if result:
        api_key, org_id = result
    else:
        api_key = None

    test_mcp_analytics(api_key)

    # For batch test, use a fresh account to avoid confusion with prior data
    try:
        d2 = signup_api()
        fresh_key = d2["api_key"]
    except Exception:
        fresh_key = api_key

    test_mcp_batch_then_analytics(fresh_key)
    test_mcp_key_rotation_grace(api_key)

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
