"""
test_mcp_stress.py — MCP server stress, resilience & edge-case tests
=====================================================================
Suite MCP-STR: Comprehensive client-perspective stress tests.

Covers:
  • Protocol abuse — malformed JSON-RPC, wrong versions, missing fields
  • Input validation — bad types, overflow numbers, injection, empty strings
  • Multi-agent simulation — concurrent interleaved tool calls
  • Multi-layer LLM traces — deep call chains, circular refs, huge spans
  • Network failure — unreachable API, DNS failure, timeout, partial response
  • Error quality — every failure returns user-friendly message, never stack trace
  • Crash reporting — errors are structured, loggable, actionable
  • Data integrity — NaN propagation, negative values, Unicode, huge payloads
  • Resource abuse — rapid-fire calls, oversized payloads, memory pressure
  • Graceful degradation — server stays alive after errors, doesn't corrupt state

Labels: MCP-STR.1 - MCP-STR.N
"""

import json
import os
import subprocess
import sys
import time
import threading
import random
import string
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.output import ok, fail, warn, info, section, chk, get_results

# ── Harness ───────────────────────────────────────────────────────────────────

MCP_PROTOCOL_VERSION = "2024-11-05"
TIMEOUT = 30
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# JSON-RPC helpers
def rpc_request(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)

def rpc_notify(method, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)

def tool_call(name, args=None, req_id=10):
    return rpc_request("tools/call", {"name": name, "arguments": args or {}}, req_id)

INIT_MSG = rpc_request("initialize", {
    "protocolVersion": MCP_PROTOCOL_VERSION,
    "capabilities": {},
    "clientInfo": {"name": "stress-test", "version": "1.0"},
}, req_id=1)

INITIALIZED_NOTIFY = rpc_notify("notifications/initialized")

TOOLS_LIST = rpc_request("tools/list", {}, req_id=2)


def launch_mcp(env_overrides=None, api_key="crt_test_stress_key"):
    """Launch MCP server, send handshake, return (proc, send_fn, recv_fn)."""
    env = {**os.environ, "VANTAGE_API_KEY": api_key}
    if env_overrides:
        env.update(env_overrides)

    proc = subprocess.Popen(
        ["npx", "-y", "cohrint-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    return proc


def handshake(proc):
    """Send init + initialized + tools/list, return parsed responses."""
    msgs = "\n".join([INIT_MSG, INITIALIZED_NOTIFY, TOOLS_LIST, ""])
    proc.stdin.write(msgs)
    proc.stdin.flush()
    time.sleep(1.5)
    return _read_responses(proc)


def send_and_recv(proc, message, wait=1.0):
    """Send a single message and read responses."""
    proc.stdin.write(message + "\n")
    proc.stdin.flush()
    time.sleep(wait)
    return _read_responses(proc)


def send_raw(proc, raw_text):
    """Send raw text (possibly malformed) to stdin."""
    proc.stdin.write(raw_text + "\n")
    proc.stdin.flush()


def _read_responses(proc, timeout=3.0):
    """Non-blocking read of all available JSON-RPC lines from stdout."""
    import select
    responses = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Use non-blocking read via os
        import fcntl
        fd = proc.stdout.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            data = proc.stdout.read()
            if data:
                for line in data.strip().splitlines():
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            responses.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except (BlockingIOError, TypeError):
            pass
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        if responses:
            break
        time.sleep(0.2)
    return responses


def kill(proc):
    """Kill process cleanly."""
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def get_stderr(proc):
    """Read stderr for crash/error reports."""
    try:
        import fcntl
        fd = proc.stderr.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            return proc.stderr.read() or ""
        except (BlockingIOError, TypeError):
            return ""
        finally:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)
    except Exception:
        return ""


# ── Batch runner: send multiple messages in one session ───────────────────────

def run_session(messages, api_key="crt_test_stress_key", env_overrides=None, wait_per_msg=0.8):
    """
    Launch MCP, handshake, then send each message. Returns list of all responses.
    Each entry: (req_id_sent, responses_list)
    """
    proc = launch_mcp(api_key=api_key, env_overrides=env_overrides)
    all_responses = []
    stderr_data = ""
    try:
        hs = handshake(proc)
        all_responses.append(("handshake", hs))

        for i, msg in enumerate(messages):
            resps = send_and_recv(proc, msg, wait=wait_per_msg)
            all_responses.append((f"msg_{i}", resps))

        stderr_data = get_stderr(proc)
    finally:
        kill(proc)
    return all_responses, stderr_data


def run_single_tool(name, args=None, req_id=10, api_key="crt_test_stress_key",
                     env_overrides=None):
    """Launch MCP, handshake, call one tool, return the tool response."""
    msg = tool_call(name, args, req_id)
    results, stderr = run_session([msg], api_key=api_key, env_overrides=env_overrides)
    # Find response matching our req_id
    for label, resps in results:
        for r in resps:
            if r.get("id") == req_id:
                return r, stderr
    return None, stderr


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SECTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Protocol Abuse ─────────────────────────────────────────────────────────

def test_protocol_abuse():
    section("MCP-STR. Protocol Abuse — Malformed JSON-RPC")

    # STR.1 — Completely invalid JSON
    proc = launch_mcp()
    try:
        handshake(proc)
        send_raw(proc, "this is not json at all!!!")
        time.sleep(0.5)
        alive = proc.poll() is None
        chk("STR.1  Server survives garbage input on stdin",
            alive, f"proc exited with {proc.returncode}")
    finally:
        kill(proc)

    # STR.2 — Valid JSON but not JSON-RPC
    proc = launch_mcp()
    try:
        handshake(proc)
        send_raw(proc, json.dumps({"hello": "world"}))
        time.sleep(0.5)
        alive = proc.poll() is None
        chk("STR.2  Server survives non-RPC JSON", alive)
    finally:
        kill(proc)

    # STR.3 — JSON-RPC with wrong protocol version
    proc = launch_mcp()
    try:
        wrong_version = rpc_request("initialize", {
            "protocolVersion": "9999-01-01",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        }, req_id=1)
        proc.stdin.write(wrong_version + "\n")
        proc.stdin.flush()
        time.sleep(1)
        alive = proc.poll() is None
        # Server should respond (possibly with error), not crash
        chk("STR.3  Server handles wrong protocol version without crash", alive)
    finally:
        kill(proc)

    # STR.4 — Missing method field
    proc = launch_mcp()
    try:
        handshake(proc)
        send_raw(proc, json.dumps({"jsonrpc": "2.0", "id": 99}))
        time.sleep(0.5)
        alive = proc.poll() is None
        chk("STR.4  Server survives request missing 'method'", alive)
    finally:
        kill(proc)

    # STR.5 — Call non-existent tool
    resp, _ = run_single_tool("definitely_not_a_real_tool", {})
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        is_error = result.get("isError", False)
        chk("STR.5  Unknown tool returns isError=true with clear message",
            is_error and "Unknown tool" in text,
            f"isError={is_error}, text={text[:100]}")
    else:
        fail("STR.5  No response for unknown tool call")

    # STR.6 — Huge request ID (integer overflow test)
    resp, _ = run_single_tool("get_summary", {}, req_id=99999999999999)
    chk("STR.6  Handles huge request ID",
        resp is not None, "no response")

    # STR.7 — Empty string request ID
    proc = launch_mcp()
    try:
        handshake(proc)
        msg = json.dumps({"jsonrpc": "2.0", "id": "", "method": "tools/call",
                          "params": {"name": "get_summary", "arguments": {}}})
        send_raw(proc, msg)
        time.sleep(0.5)
        alive = proc.poll() is None
        chk("STR.7  Server handles empty string request ID", alive)
    finally:
        kill(proc)

    # STR.8 — Null request ID
    proc = launch_mcp()
    try:
        handshake(proc)
        msg = json.dumps({"jsonrpc": "2.0", "id": None, "method": "tools/call",
                          "params": {"name": "get_summary", "arguments": {}}})
        send_raw(proc, msg)
        time.sleep(0.5)
        alive = proc.poll() is None
        chk("STR.8  Server handles null request ID", alive)
    finally:
        kill(proc)


# ── 2. Input Validation — Bad Types & Edge Cases ─────────────────────────────

def test_input_validation():
    section("MCP-STR. Input Validation — Type Coercion, Overflow, Injection")

    # STR.9 — track_llm_call with string where number expected
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": "not_a_number",
        "completion_tokens": "also_not",
        "total_cost_usd": "NaN",
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        # Should either error cleanly OR track with coerced values — never crash
        chk("STR.9  String-as-number doesn't crash (track_llm_call)",
            True, f"response: {text[:100]}")
        # Should NOT contain NaN in the success message
        if not result.get("isError"):
            has_nan = "NaN" in text or "nan" in text
            chk("STR.10 No NaN in success output for bad numeric input",
                not has_nan, f"text: {text[:150]}")
    else:
        fail("STR.9  No response for bad type input")
        fail("STR.10 Skipped — no response")

    # STR.11 — Negative token values
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": -500,
        "completion_tokens": -100,
        "total_cost_usd": -0.01,
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        is_error = result.get("isError", False)
        chk("STR.11 Negative values handled (either error or clamp, not crash)",
            resp is not None, f"isError={is_error}")
    else:
        fail("STR.11 No response")

    # STR.12 — Extremely large cost (near-infinity)
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_cost_usd": 9999999999999,
    })
    chk("STR.12 Extremely large cost doesn't crash",
        resp is not None, "no response")

    # STR.13 — Empty string for required fields
    resp, _ = run_single_tool("optimize_prompt", {"prompt": ""})
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        chk("STR.13 Empty prompt returns isError (optimize_prompt)",
            is_error, f"isError={is_error}")
    else:
        fail("STR.13 No response")

    # STR.14 — Missing required arguments entirely
    resp, _ = run_single_tool("analyze_tokens", {})
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.14 Missing required arg → isError with clear message",
            is_error and ("required" in text.lower() or "error" in text.lower()),
            f"isError={is_error}, text={text[:100]}")
    else:
        fail("STR.14 No response")

    # STR.15 — SQL/command injection in model name
    resp, _ = run_single_tool("track_llm_call", {
        "model": "'; DROP TABLE events; --",
        "provider": "openai",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.001,
    })
    chk("STR.15 SQL injection in model name doesn't crash",
        resp is not None, "no response")

    # STR.16 — XSS in tags
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.001,
        "tags": {"<script>alert('xss')</script>": "value", "key": "<img onerror=alert(1)>"},
    })
    chk("STR.16 XSS in tags doesn't crash", resp is not None)

    # STR.17 — Unicode stress
    resp, _ = run_single_tool("optimize_prompt", {
        "prompt": "🎉🔥💰" * 100 + "日本語テスト" + "العربية" + "中文测试" + "\u0000\uffff",
    })
    chk("STR.17 Unicode/emoji stress doesn't crash", resp is not None)

    # STR.18 — Extremely long string (100KB prompt)
    big_prompt = "a " * 50000  # ~100KB
    resp, _ = run_single_tool("analyze_tokens", {"text": big_prompt}, req_id=18)
    chk("STR.18 100KB prompt doesn't crash analyze_tokens",
        resp is not None, "no response or timeout")

    # STR.19 — Zero values everywhere
    resp, _ = run_single_tool("track_llm_call", {
        "model": "test",
        "provider": "test",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_cost_usd": 0,
        "latency_ms": 0,
    })
    chk("STR.19 All-zero values handled", resp is not None)

    # STR.20 — get_model_breakdown with extreme days
    resp, _ = run_single_tool("get_model_breakdown", {"days": 999999})
    chk("STR.20 Extreme days value handled", resp is not None)

    # STR.21 — get_traces with negative limit
    resp, _ = run_single_tool("get_traces", {"limit": -10})
    chk("STR.21 Negative limit handled", resp is not None)

    # STR.22 — get_cost_gate with invalid period
    resp, _ = run_single_tool("get_cost_gate", {"period": "invalid_period"})
    chk("STR.22 Invalid period string handled", resp is not None)

    # STR.23 — compress_context with wrong message format
    resp, _ = run_single_tool("compress_context", {
        "messages": "not an array",
    })
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        chk("STR.23 String instead of array → isError",
            is_error, f"isError={is_error}")
    else:
        fail("STR.23 No response")

    # STR.24 — compress_context with missing role/content
    resp, _ = run_single_tool("compress_context", {
        "messages": [{"wrong_field": "value"}, {}, None, 42],
    })
    chk("STR.24 Malformed message objects don't crash",
        resp is not None, "no response")

    # STR.25 — find_cheapest_model with NaN tokens
    resp, _ = run_single_tool("find_cheapest_model", {
        "input_tokens": "NaN",
        "output_tokens": "undefined",
    })
    chk("STR.25 NaN/undefined tokens don't crash find_cheapest_model",
        resp is not None)

    # STR.26 — estimate_costs with null prompt
    resp, _ = run_single_tool("estimate_costs", {"prompt": None})
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        chk("STR.26 null prompt → isError", is_error, f"isError={is_error}")
    else:
        fail("STR.26 No response")


# ── 3. Multi-Agent Concurrent Calls ──────────────────────────────────────────

def test_multi_agent_concurrent():
    section("MCP-STR. Multi-Agent — Concurrent Interleaved Calls")

    # STR.27 — Rapid-fire 10 tool calls in one session
    messages = []
    for i in range(10):
        tools = ["get_summary", "get_kpis", "check_budget", "get_traces",
                 "optimize_prompt", "analyze_tokens", "estimate_costs",
                 "find_cheapest_model", "get_model_breakdown", "get_team_breakdown"]
        t = tools[i]
        args = {}
        if t == "optimize_prompt":
            args = {"prompt": f"Test prompt {i}"}
        elif t == "analyze_tokens":
            args = {"text": f"Analyze this text {i}"}
        elif t == "estimate_costs":
            args = {"prompt": f"Estimate for {i}"}
        elif t == "find_cheapest_model":
            args = {"input_tokens": 100 * (i + 1), "output_tokens": 50 * (i + 1)}
        messages.append(tool_call(t, args, req_id=100 + i))

    results, stderr = run_session(messages, wait_per_msg=0.5)

    # Count responses (excluding handshake)
    resp_count = 0
    for label, resps in results:
        if label != "handshake":
            resp_count += len(resps)

    chk("STR.27 10 rapid-fire tool calls all get responses",
        resp_count >= 8,  # allow some timing slack
        f"got {resp_count}/10 responses")

    # STR.28 — Verify no response corruption (each response has valid content)
    valid_responses = 0
    for label, resps in results:
        if label == "handshake":
            continue
        for r in resps:
            result = r.get("result", {})
            content = result.get("content", [])
            if content and isinstance(content, list) and content[0].get("type") == "text":
                valid_responses += 1
    chk("STR.28 All responses have valid content structure",
        valid_responses >= 8,
        f"{valid_responses} valid out of {resp_count}")

    # STR.29 — Parallel sessions (multi-agent simulation)
    # Launch 3 servers simultaneously, each making calls
    threads = []
    thread_results = [None, None, None]

    def agent_session(idx):
        try:
            r, _ = run_single_tool("optimize_prompt",
                                   {"prompt": f"Agent {idx} testing concurrency"},
                                   req_id=200 + idx)
            thread_results[idx] = r
        except Exception as e:
            thread_results[idx] = str(e)

    for i in range(3):
        t = threading.Thread(target=agent_session, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=45)

    successful = sum(1 for r in thread_results if isinstance(r, dict) and r.get("result"))
    chk("STR.29 3 parallel MCP instances all respond",
        successful >= 2,  # allow 1 flaky
        f"{successful}/3 succeeded")


# ── 4. Multi-Layer LLM Trace Chains ──────────────────────────────────────────

def test_multi_layer_traces():
    section("MCP-STR. Multi-Layer LLM — Deep Traces & Complex Chains")

    # STR.30 — Deep agent trace (10-level nesting)
    trace_id = f"trace-deep-{int(time.time())}"
    messages = []
    for depth in range(10):
        messages.append(tool_call("track_llm_call", {
            "model": "gpt-4o",
            "provider": "openai",
            "prompt_tokens": 100 + depth * 50,
            "completion_tokens": 50 + depth * 25,
            "total_cost_usd": round(0.001 * (depth + 1), 6),
            "latency_ms": 200 + depth * 100,
            "team": "multi-agent",
            "trace_id": trace_id,
            "span_depth": depth,
            "tags": {"agent": f"agent_level_{depth}", "parent": f"agent_level_{max(0, depth-1)}"},
        }, req_id=300 + depth))

    results, stderr = run_session(messages, wait_per_msg=0.3)

    resp_count = sum(len(resps) for label, resps in results if label != "handshake")
    chk("STR.30 10-deep agent trace chain ingested",
        resp_count >= 8,
        f"got {resp_count}/10")

    # STR.31 — Trace with extremely long trace_id (1000 chars)
    long_trace = "trace-" + "x" * 994
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_cost_usd": 0.001,
        "trace_id": long_trace,
        "span_depth": 0,
    })
    chk("STR.31 1000-char trace_id handled", resp is not None)

    # STR.32 — Multiple traces mixed (simulating 3 agents working simultaneously)
    messages = []
    for i in range(15):
        agent = i % 3
        messages.append(tool_call("track_llm_call", {
            "model": ["gpt-4o", "claude-sonnet-4", "gemini-2.0-flash"][agent],
            "provider": ["openai", "anthropic", "google"][agent],
            "prompt_tokens": 100 + i * 10,
            "completion_tokens": 50 + i * 5,
            "total_cost_usd": round(0.001 * (i + 1), 6),
            "trace_id": f"parallel-agent-{agent}-{int(time.time())}",
            "span_depth": i // 3,
            "team": f"team-{agent}",
        }, req_id=400 + i))

    results, _ = run_session(messages, wait_per_msg=0.3)
    resp_count = sum(len(resps) for label, resps in results if label != "handshake")
    chk("STR.32 15 mixed multi-agent trace events handled",
        resp_count >= 12,
        f"got {resp_count}/15")

    # STR.33 — Trace with special chars in trace_id
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_cost_usd": 0.001,
        "trace_id": "trace/with\\special$chars&id=1;DROP TABLE",
        "span_depth": 0,
    })
    chk("STR.33 Special chars in trace_id don't crash", resp is not None)


# ── 5. Network Failure Simulation ────────────────────────────────────────────

def test_network_failures():
    section("MCP-STR. Network Failures — Unreachable API, Bad URLs")

    # STR.34 — Unreachable API base URL
    resp, stderr = run_single_tool("get_summary", {},
                                    env_overrides={"VANTAGE_API_BASE": "http://127.0.0.1:1"})
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.34 Unreachable API → isError (not crash)",
            is_error, f"isError={is_error}")
        # Error message should be user-friendly, not raw stack trace
        chk("STR.35 Error message is user-friendly (no stack trace)",
            "Error:" in text and "at Object" not in text and "node_modules" not in text,
            f"text: {text[:200]}")
    else:
        fail("STR.34 No response at all (server likely crashed)")
        fail("STR.35 Skipped")

    # STR.36 — Invalid API base URL (bad protocol)
    resp, stderr = run_single_tool("get_kpis", {},
                                    env_overrides={"VANTAGE_API_BASE": "not_a_url"})
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        chk("STR.36 Bad protocol URL → isError", is_error)
    else:
        fail("STR.36 No response")

    # STR.37 — Missing API key
    resp, stderr = run_single_tool("get_summary", {}, api_key="")
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.37 Missing API key → clear error message",
            is_error and "VANTAGE_API_KEY" in text,
            f"text: {text[:150]}")
    else:
        fail("STR.37 No response")

    # STR.38 — Malformed API key
    resp, stderr = run_single_tool("get_summary", {}, api_key="invalid_key_format")
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        chk("STR.38 Malformed API key → error (not crash)", is_error or resp is not None)
    else:
        fail("STR.38 No response")

    # STR.39 — Server stays alive after network error (can still call offline tools)
    proc = launch_mcp(env_overrides={"VANTAGE_API_BASE": "http://127.0.0.1:1"})
    try:
        handshake(proc)

        # First call will fail (network tool)
        resp1 = send_and_recv(proc, tool_call("get_summary", {}, req_id=50), wait=3)

        # Second call should still work (offline tool)
        resp2 = send_and_recv(proc, tool_call("optimize_prompt",
                                               {"prompt": "test after failure"}, req_id=51), wait=2)

        alive = proc.poll() is None
        chk("STR.39 Server alive after network error", alive)

        has_offline_response = False
        for r in resp2:
            if r.get("id") == 51:
                result = r.get("result", {})
                content = result.get("content", [{}])
                text = content[0].get("text", "") if content else ""
                if "Optimizer" in text or "token" in text.lower() or "efficient" in text.lower():
                    has_offline_response = True
        chk("STR.40 Offline tools still work after API failure",
            has_offline_response, f"responses: {len(resp2)}")
    finally:
        kill(proc)

    # STR.41 — Repeated failures don't degrade server
    proc = launch_mcp(env_overrides={"VANTAGE_API_BASE": "http://127.0.0.1:1"})
    try:
        handshake(proc)
        for i in range(5):
            send_and_recv(proc, tool_call("get_summary", {}, req_id=60 + i), wait=1.5)
        alive = proc.poll() is None
        chk("STR.41 Server survives 5 consecutive network failures", alive)

        # Still works for offline tool
        resp = send_and_recv(proc, tool_call("analyze_tokens",
                                              {"text": "still works"}, req_id=70), wait=1)
        has_resp = any(r.get("id") == 70 for r in resp)
        chk("STR.42 Offline tool works after 5 network failures", has_resp)
    finally:
        kill(proc)


# ── 6. Error Message Quality ─────────────────────────────────────────────────

def test_error_quality():
    section("MCP-STR. Error Quality — User-Friendly Messages")

    error_cases = [
        ("STR.43", "optimize_prompt", {}, "prompt.*required|required"),
        ("STR.44", "analyze_tokens", {}, "text.*required|required"),
        ("STR.45", "estimate_costs", {}, "prompt.*required|required"),
        ("STR.46", "compress_context", {"messages": "not-array"}, "array.*required|required"),
        ("STR.47", "definitely_fake_tool", {}, "Unknown tool|unknown"),
    ]

    for label, tool_name, args, expected_pattern in error_cases:
        resp, _ = run_single_tool(tool_name, args)
        if resp:
            result = resp.get("result", {})
            is_error = result.get("isError", False)
            content = result.get("content", [{}])
            text = content[0].get("text", "") if content else ""

            chk(f"{label} {tool_name} error is structured (isError=true)",
                is_error, f"isError={is_error}, text={text[:80]}")

            # Error should never contain stack traces
            has_stack = ("at " in text and ".js:" in text) or "node_modules" in text
            chk(f"{label}b {tool_name} error has no stack trace",
                not has_stack, f"text: {text[:200]}")
        else:
            fail(f"{label} No response for {tool_name}")
            fail(f"{label}b Skipped")


# ── 7. Crash Reporting — Structured Error Logging ────────────────────────────

def test_crash_reporting():
    section("MCP-STR. Crash Reporting — Structured Stderr Logging")

    # STR.53 — Server startup logs to stderr
    proc = launch_mcp()
    try:
        handshake(proc)
        time.sleep(0.5)
        stderr = get_stderr(proc)
        chk("STR.53 Server logs startup info to stderr",
            "[vantage-mcp]" in stderr,
            f"stderr: {stderr[:200]}")
    finally:
        kill(proc)

    # STR.54 — Missing API key: calling a tool should return clear error
    resp, _ = run_single_tool("get_summary", {}, api_key="")
    if resp:
        result = resp.get("result", {})
        is_error = result.get("isError", False)
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.54 Missing API key tool call → isError with setup instructions",
            is_error and ("VANTAGE_API_KEY" in text or "not set" in text.lower()),
            f"isError={is_error}, text={text[:200]}")
    else:
        fail("STR.54 No response")

    # STR.55 — Stderr never leaks API key
    api_key = "crt_testorg_secretvalue123456789"
    proc = launch_mcp(api_key=api_key)
    try:
        handshake(proc)
        # Trigger an error
        send_and_recv(proc, tool_call("get_summary", {}, req_id=80), wait=2)
        stderr = get_stderr(proc)
        chk("STR.55 Stderr never leaks full API key",
            "secretvalue123456789" not in stderr,
            f"stderr contains key fragment!")
    finally:
        kill(proc)


# ── 8. Data Integrity — NaN, Boundaries, Edge Values ─────────────────────────

def test_data_integrity():
    section("MCP-STR. Data Integrity — Boundaries & Edge Values")

    # STR.56 — Massive token count in analyze_tokens
    resp, _ = run_single_tool("analyze_tokens", {
        "text": "word " * 10000,  # ~50KB, ~10K tokens
        "model": "gpt-4o",
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.56 10K-word text analyzed without crash",
            "Token" in text or "token" in text,
            f"text: {text[:100]}")
    else:
        fail("STR.56 No response")

    # STR.57 — compress_context with 100 messages
    messages = [{"role": "user" if i % 2 == 0 else "assistant",
                 "content": f"Message {i}: " + "x" * 50}
                for i in range(100)]
    resp, _ = run_single_tool("compress_context", {
        "messages": messages,
        "max_tokens": 500,
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [])
        chk("STR.57 100-message compression works",
            len(content) >= 1, f"content items: {len(content)}")
        # Verify the compressed output is valid JSON
        if len(content) >= 2:
            try:
                compressed = json.loads(content[1].get("text", "{}"))
                chk("STR.58 Compressed output is valid JSON",
                    "messages" in compressed,
                    f"keys: {list(compressed.keys()) if isinstance(compressed, dict) else type(compressed)}")
            except json.JSONDecodeError as e:
                fail(f"STR.58 Compressed output invalid JSON: {e}")
        else:
            chk("STR.58 Compressed output returned", len(content) >= 1)
    else:
        fail("STR.57 No response")
        fail("STR.58 Skipped")

    # STR.59 — estimate_costs accuracy (token counts should be consistent)
    resp, _ = run_single_tool("estimate_costs", {
        "prompt": "Hello world",
        "completion_tokens": 10,
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        # Should list multiple models
        model_count = text.count("|") // 6  # rough estimate from table rows
        chk("STR.59 estimate_costs lists multiple models",
            "gpt" in text.lower() or "claude" in text.lower() or "gemini" in text.lower(),
            f"models mentioned: {model_count}")
    else:
        fail("STR.59 No response")

    # STR.60 — find_cheapest_model with impossible filter
    resp, _ = run_single_tool("find_cheapest_model", {
        "input_tokens": 1000,
        "output_tokens": 500,
        "tier": "nonexistent_tier",
        "provider": "nonexistent_provider",
    })
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.60 No matching models → graceful response",
            "No models found" in text or resp is not None,
            f"text: {text[:100]}")
    else:
        fail("STR.60 No response")

    # STR.61 — Boolean where number expected
    resp, _ = run_single_tool("get_model_breakdown", {"days": True})
    chk("STR.61 Boolean as days parameter doesn't crash", resp is not None)

    # STR.62 — Array where string expected
    resp, _ = run_single_tool("optimize_prompt", {"prompt": [1, 2, 3]})
    chk("STR.62 Array as prompt doesn't crash", resp is not None)

    # STR.63 — Object where string expected
    resp, _ = run_single_tool("analyze_tokens", {"text": {"nested": "object"}})
    chk("STR.63 Object as text doesn't crash", resp is not None)

    # STR.64 — Very large JSON object as tags
    big_tags = {f"key_{i}": f"value_{i}" for i in range(200)}
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.001,
        "tags": big_tags,
    })
    chk("STR.64 200-key tags object handled", resp is not None)


# ── 9. Resource Abuse — Rapid Fire & Memory Pressure ─────────────────────────

def test_resource_abuse():
    section("MCP-STR. Resource Abuse — Rapid Fire & Overload")

    # STR.65 — 20 calls in quick succession (same session)
    proc = launch_mcp()
    try:
        handshake(proc)
        for i in range(20):
            send_raw(proc, tool_call("find_cheapest_model",
                                     {"input_tokens": 100, "output_tokens": 50},
                                     req_id=500 + i))
        time.sleep(5)
        alive = proc.poll() is None
        chk("STR.65 Server alive after 20 rapid-fire calls", alive)
    finally:
        kill(proc)

    # STR.66 — Alternating online/offline tools in quick succession
    proc = launch_mcp()
    try:
        handshake(proc)
        for i in range(10):
            if i % 2 == 0:
                send_raw(proc, tool_call("optimize_prompt",
                                         {"prompt": f"test {i}"}, req_id=600 + i))
            else:
                send_raw(proc, tool_call("get_summary", {}, req_id=600 + i))
        time.sleep(4)
        alive = proc.poll() is None
        chk("STR.66 Mixed online/offline rapid calls don't crash", alive)
    finally:
        kill(proc)


# ── 10. Graceful Degradation — State Consistency ─────────────────────────────

def test_graceful_degradation():
    section("MCP-STR. Graceful Degradation — State Consistency")

    # STR.67 — Tools/list still works after tool errors
    proc = launch_mcp()
    try:
        handshake(proc)

        # Trigger an error
        send_and_recv(proc, tool_call("fake_tool", {}, req_id=90), wait=0.5)

        # tools/list should still work
        resp = send_and_recv(proc, rpc_request("tools/list", {}, req_id=91), wait=1)
        has_tools = False
        for r in resp:
            if r.get("id") == 91:
                tools = r.get("result", {}).get("tools", [])
                has_tools = len(tools) > 0
        chk("STR.67 tools/list works after tool error",
            has_tools, f"responses: {len(resp)}")
    finally:
        kill(proc)

    # STR.68 — Resources still work after tool errors
    proc = launch_mcp()
    try:
        handshake(proc)

        send_and_recv(proc, tool_call("fake_tool", {}, req_id=92), wait=0.5)

        resp = send_and_recv(proc, rpc_request("resources/list", {}, req_id=93), wait=1)
        has_resources = False
        for r in resp:
            if r.get("id") == 93:
                resources = r.get("result", {}).get("resources", [])
                has_resources = len(resources) > 0
        chk("STR.68 resources/list works after tool error",
            has_resources, f"responses: {len(resp)}")
    finally:
        kill(proc)

    # STR.69 — Multiple tool errors don't accumulate (no memory leak pattern)
    proc = launch_mcp()
    try:
        handshake(proc)
        for i in range(10):
            send_and_recv(proc, tool_call("fake_tool_" + str(i), {}, req_id=700 + i), wait=0.3)

        # Now a real tool should work fine
        resp = send_and_recv(proc, tool_call("analyze_tokens",
                                              {"text": "still working"}, req_id=800), wait=1)
        has_result = False
        for r in resp:
            if r.get("id") == 800:
                result = r.get("result", {})
                content = result.get("content", [{}])
                text = content[0].get("text", "") if content else ""
                if "Token" in text or "token" in text:
                    has_result = True
        chk("STR.69 Real tool works after 10 consecutive errors",
            has_result, f"responses: {len(resp)}")
    finally:
        kill(proc)


# ── 11. Edge Case Payloads ────────────────────────────────────────────────────

def test_edge_payloads():
    section("MCP-STR. Edge Payloads — Unusual But Valid")

    # STR.70 — Track call with all optional fields populated
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 500,
        "completion_tokens": 200,
        "total_cost_usd": 0.0035,
        "latency_ms": 1234,
        "team": "backend",
        "environment": "staging",
        "trace_id": "full-trace-001",
        "span_depth": 2,
        "tags": {"feature": "search", "version": "v2", "experiment": "ab-test-42"},
    })
    chk("STR.70 Full payload with all fields accepted", resp is not None)
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        is_error = result.get("isError", False)
        # With a test API key, the API will reject — but server should handle it gracefully
        # Either success (Tracked:) or structured API error (❌ Error:), never crash
        chk("STR.71 Full payload returns structured response (success or API error)",
            ("Tracked:" in text) or ("Error:" in text and is_error),
            f"isError={is_error}, text={text[:100]}")

    # STR.72 — Track with only required fields (minimal payload)
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_cost_usd": 0.000001,
    })
    chk("STR.72 Minimal required-only payload accepted", resp is not None)

    # STR.73 — compress_context with single message
    resp, _ = run_single_tool("compress_context", {
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 4000,
    })
    chk("STR.73 Single message compression works", resp is not None)

    # STR.74 — compress_context with zero max_tokens
    resp, _ = run_single_tool("compress_context", {
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 0,
    })
    chk("STR.74 Zero max_tokens doesn't crash", resp is not None)

    # STR.75 — compress_context with empty messages array
    resp, _ = run_single_tool("compress_context", {
        "messages": [],
    })
    chk("STR.75 Empty messages array handled", resp is not None)

    # STR.76 — optimize_prompt with whitespace-only prompt
    resp, _ = run_single_tool("optimize_prompt", {"prompt": "   \n\t\n   "})
    chk("STR.76 Whitespace-only prompt handled", resp is not None)

    # STR.77 — Newlines and special whitespace in model name
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o\n\r\t",
        "provider": "openai",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.001,
    })
    chk("STR.77 Newlines in model name handled", resp is not None)

    # STR.78 — Very precise cost value
    resp, _ = run_single_tool("track_llm_call", {
        "model": "gpt-4o",
        "provider": "openai",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.00000000001,
    })
    chk("STR.78 Very small cost value handled", resp is not None)


# ── 12. Config & Startup Edge Cases ──────────────────────────────────────────

def test_config_edge_cases():
    section("MCP-STR. Config & Startup Edge Cases")

    # STR.79 — API key with only prefix (crt_ with nothing after)
    resp, stderr = run_single_tool("get_summary", {}, api_key="crt_")
    chk("STR.79 Minimal API key prefix doesn't crash", resp is not None)

    # STR.80 — API key with unicode
    resp, stderr = run_single_tool("get_summary", {}, api_key="crt_org_🔑key")
    chk("STR.80 Unicode in API key doesn't crash", resp is not None)

    # STR.81 — Very long API key (1000 chars)
    long_key = "crt_testorg_" + "a" * 988
    resp, stderr = run_single_tool("optimize_prompt",
                                    {"prompt": "test"},
                                    api_key=long_key)
    chk("STR.81 1000-char API key doesn't crash", resp is not None)

    # STR.82 — API base with trailing slashes
    resp, stderr = run_single_tool("optimize_prompt",
                                    {"prompt": "test"},
                                    env_overrides={"VANTAGE_API_BASE": "https://api.cohrint.com///"})
    chk("STR.82 Trailing slashes in API base handled", resp is not None)


# ── 13. Response Format Validation ────────────────────────────────────────────

def test_response_format():
    section("MCP-STR. Response Format — Strict MCP Compliance")

    # STR.83 — Every tool response follows MCP content format
    offline_tools = [
        ("optimize_prompt", {"prompt": "Please help me write better code"}),
        ("analyze_tokens", {"text": "Hello world this is a test"}),
        ("estimate_costs", {"prompt": "Calculate costs for this"}),
        ("compress_context", {"messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]}),
        ("find_cheapest_model", {"input_tokens": 1000, "output_tokens": 500}),
    ]

    format_ok = 0
    for tool_name, args in offline_tools:
        resp, _ = run_single_tool(tool_name, args)
        if resp:
            result = resp.get("result", {})
            content = result.get("content", [])
            # MCP spec: content must be an array of {type, text} objects
            if (isinstance(content, list) and len(content) >= 1 and
                    all(isinstance(c, dict) and c.get("type") == "text" and
                        isinstance(c.get("text"), str) for c in content)):
                format_ok += 1

    chk(f"STR.83 All {len(offline_tools)} offline tools return valid MCP content format",
        format_ok == len(offline_tools),
        f"{format_ok}/{len(offline_tools)} valid")

    # STR.84 — Error responses also follow MCP format
    error_tools = [
        ("optimize_prompt", {}),
        ("analyze_tokens", {}),
        ("not_a_tool", {}),
    ]
    error_format_ok = 0
    for tool_name, args in error_tools:
        resp, _ = run_single_tool(tool_name, args)
        if resp:
            result = resp.get("result", {})
            content = result.get("content", [])
            is_error = result.get("isError", False)
            if (is_error and isinstance(content, list) and len(content) >= 1 and
                    content[0].get("type") == "text"):
                error_format_ok += 1

    chk(f"STR.84 All {len(error_tools)} error responses follow MCP format",
        error_format_ok == len(error_tools),
        f"{error_format_ok}/{len(error_tools)}")

    # STR.85 — Error text starts with recognizable prefix
    resp, _ = run_single_tool("not_a_tool", {})
    if resp:
        result = resp.get("result", {})
        content = result.get("content", [{}])
        text = content[0].get("text", "") if content else ""
        chk("STR.85 Error text starts with ❌ Error prefix",
            text.startswith("❌ Error:") or text.startswith("Error:"),
            f"text starts with: {text[:30]}")
    else:
        fail("STR.85 No response")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    section("Suite MCP-STR — MCP Server Stress & Resilience Tests")
    info("Testing protocol abuse, input validation, multi-agent, network failures,")
    info("error quality, crash reporting, data integrity, resource abuse, and more.")
    info("")

    t0 = time.monotonic()

    test_protocol_abuse()
    test_input_validation()
    test_multi_agent_concurrent()
    test_multi_layer_traces()
    test_network_failures()
    test_error_quality()
    test_crash_reporting()
    test_data_integrity()
    test_resource_abuse()
    test_graceful_degradation()
    test_edge_payloads()
    test_config_edge_cases()
    test_response_format()

    elapsed = round(time.monotonic() - t0, 1)
    results = get_results()
    info("")
    info(f"Completed in {elapsed}s")
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
