"""
test_mcp_server.py — MCP server stdio transport tests
=====================================================
Suite MCP-SRV: Tests the MCP server starts, completes handshake, and lists tools.
Labels: MCP-SRV.1 - MCP-SRV.N
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.output import ok, fail, warn, info, section, chk, get_results

# Expected tools the MCP server should expose
EXPECTED_TOOLS = [
    "track_llm_call",
    "get_summary",
    "get_kpis",
    "get_model_breakdown",
    "get_team_breakdown",
    "check_budget",
    "get_traces",
    "get_cost_gate",
    "optimize_prompt",
    "analyze_tokens",
    "estimate_costs",
    "compress_context",
]

# find_cheapest_model exists in local source but may not be in published npm yet

MCP_PROTOCOL_VERSION = "2024-11-05"

# JSON-RPC messages for the MCP handshake
INITIALIZE_MSG = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "vantage-test", "version": "1.0"},
    },
})

INITIALIZED_NOTIFICATION = json.dumps({
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
})

TOOLS_LIST_MSG = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
})


def run_mcp_handshake():
    """Start the MCP server via npx and perform a full handshake."""
    stdin_data = "\n".join([INITIALIZE_MSG, INITIALIZED_NOTIFICATION, TOOLS_LIST_MSG, ""])

    try:
        proc = subprocess.run(
            ["npx", "-y", "cohrint-mcp"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **__import__("os").environ,
                "VANTAGE_API_KEY": "crt_test_mcp_server_check",
            },
        )
    except FileNotFoundError:
        return None, "npx not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "MCP server timed out after 30s"

    return proc, None


def parse_jsonrpc_lines(stdout):
    """Parse JSON-RPC response lines from stdout, skipping non-JSON lines."""
    responses = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return responses


def test_mcp_server_starts():
    section("MCP-SRV. Server Startup + Handshake")

    proc, err = run_mcp_handshake()

    if err:
        fail(f"MCP-SRV.1  Server start failed: {err}")
        return None

    chk("MCP-SRV.1  Server process exited cleanly",
        proc.returncode == 0,
        f"exit code {proc.returncode}, stderr: {proc.stderr[:200]}")

    # Verify no non-JSON output on stdout (would break MCP protocol)
    stdout_lines = proc.stdout.strip().splitlines()
    non_json_lines = [
        line for line in stdout_lines
        if line.strip() and not line.strip().startswith("{")
    ]
    chk("MCP-SRV.2  No non-JSON output on stdout (protocol clean)",
        len(non_json_lines) == 0,
        f"found {len(non_json_lines)} non-JSON lines: {non_json_lines[:3]}")

    responses = parse_jsonrpc_lines(proc.stdout)
    chk("MCP-SRV.3  Got JSON-RPC responses",
        len(responses) >= 2,
        f"got {len(responses)} responses")

    if len(responses) < 2:
        return None

    return responses


def test_mcp_initialize(responses):
    section("MCP-SRV. Initialize Response")

    if not responses:
        warn("MCP-SRV.4  No responses — skipping")
        return

    init_resp = responses[0]

    chk("MCP-SRV.4  Initialize response has result",
        "result" in init_resp,
        f"keys: {list(init_resp.keys())}")

    if "result" not in init_resp:
        return

    result = init_resp["result"]

    chk("MCP-SRV.5  Protocol version matches",
        result.get("protocolVersion") == MCP_PROTOCOL_VERSION,
        f"got {result.get('protocolVersion')}")

    server_info = result.get("serverInfo", {})
    chk("MCP-SRV.6  Server identifies as vantage-mcp",
        "vantage" in server_info.get("name", "").lower(),
        f"got name: {server_info.get('name')}")

    capabilities = result.get("capabilities", {})
    chk("MCP-SRV.7  Capabilities include tools",
        "tools" in capabilities,
        f"capabilities: {list(capabilities.keys())}")


def test_mcp_tools_list(responses):
    section("MCP-SRV. Tools List")

    if not responses or len(responses) < 2:
        warn("MCP-SRV.8  No tools/list response — skipping")
        return

    tools_resp = responses[1]

    chk("MCP-SRV.8  tools/list response has result",
        "result" in tools_resp,
        f"keys: {list(tools_resp.keys())}")

    if "result" not in tools_resp:
        return

    tools = tools_resp["result"].get("tools", [])
    tool_names = [t["name"] for t in tools]

    chk(f"MCP-SRV.9  Server exposes {len(EXPECTED_TOOLS)} tools",
        len(tools) == len(EXPECTED_TOOLS),
        f"got {len(tools)}: {tool_names}")

    # Check each expected tool is present
    missing = [t for t in EXPECTED_TOOLS if t not in tool_names]
    chk("MCP-SRV.10 All expected tools present",
        len(missing) == 0,
        f"missing: {missing}")

    # Validate each tool has a valid inputSchema
    schema_ok = 0
    for tool in tools:
        schema = tool.get("inputSchema", {})
        if schema.get("type") == "object" and "properties" in schema:
            schema_ok += 1
    chk("MCP-SRV.11 All tools have valid inputSchema",
        schema_ok == len(tools),
        f"{schema_ok}/{len(tools)} have valid schemas")


def test_mcp_config_location():
    """Verify .mcp.json exists at project root (not just .claude/mcp.json)."""
    section("MCP-SRV. Config File Location")

    project_root = Path(__file__).parent.parent.parent.parent
    mcp_json = project_root / ".mcp.json"
    claude_mcp_json = project_root / ".claude" / "mcp.json"

    chk("MCP-SRV.12 .mcp.json exists at project root",
        mcp_json.exists(),
        f"not found at {mcp_json}")

    if mcp_json.exists():
        try:
            data = json.loads(mcp_json.read_text())
            servers = data.get("mcpServers", {})
            chk("MCP-SRV.13 .mcp.json has vantage server configured",
                "vantage" in servers,
                f"servers: {list(servers.keys())}")
        except (json.JSONDecodeError, Exception) as e:
            fail(f"MCP-SRV.13 .mcp.json is invalid JSON: {e}")

    # Warn if stale .claude/mcp.json exists (can confuse users)
    if claude_mcp_json.exists():
        warn("MCP-SRV.14 .claude/mcp.json still exists — "
             "Claude Code uses .mcp.json at project root, not .claude/mcp.json. "
             "Consider removing .claude/mcp.json to avoid confusion.")
    else:
        chk("MCP-SRV.14 No stale .claude/mcp.json", True)


def main():
    section("Suite MCP-SRV — MCP Server Transport Tests")

    responses = test_mcp_server_starts()
    test_mcp_initialize(responses)
    test_mcp_tools_list(responses)
    test_mcp_config_location()

    results = get_results()
    info(f"Results: {results['passed']} passed, {results['failed']} failed, "
         f"{results['warned']} warned")
    sys.exit(0 if results["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
