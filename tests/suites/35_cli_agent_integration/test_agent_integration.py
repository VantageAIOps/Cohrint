"""
Test Suite 35 — CLI Agent Integration (P0 + P1)
Covers:
  P0-A: Permission mode & allowedTools passthrough in buildCommand/buildContinueCommand
  P0-B: Session ID persistence to disk (save/load/clear)
  P1-A: ClaudeStreamRenderer handles content_block_delta for real-time streaming
  P1-B: Agent config reading (model, MCP servers, permissions from ~/.claude/settings.json)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, ok, fail, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
RENDERER_HARNESS = CLI_DIR / "test-renderer.ts"
SESSION_HARNESS = CLI_DIR / "test-session-persist.ts"
CONFIG_HARNESS = CLI_DIR / "test-agent-config.ts"


def js_session(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-session-persist.ts via tsx."""
    result = subprocess.run(
        [str(TSX), str(SESSION_HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def js_config(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-agent-config.ts via tsx."""
    result = subprocess.run(
        [str(TSX), str(CONFIG_HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def renderer(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-renderer.ts via tsx."""
    result = subprocess.run(
        [str(TSX), str(RENDERER_HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


# ---------------------------------------------------------------------------
# P0-A: Permission Mode & AllowedTools Passthrough
# ---------------------------------------------------------------------------

class TestPermissionPassthrough:
    """
    Verifies that buildCommand and buildContinueCommand correctly forward
    --permission-mode and --allowedTools flags when configured.
    """

    def test_ai01_build_command_includes_permission_mode(self):
        section("P0-A — Permission Mode Passthrough")
        r = js_config("build-command", json.dumps({"permissionMode": "acceptEdits"}))
        args = r.get("args", [])
        chk(
            "AI.01 buildCommand includes --permission-mode flag",
            "--permission-mode" in args and "acceptEdits" in args,
            f"args={args}",
        )
        assert "--permission-mode" in args

    def test_ai02_build_command_includes_allowed_tools(self):
        r = js_config("build-command", json.dumps({
            "allowedTools": ["Read", "Edit", "Bash(git:*)"],
        }))
        args = r.get("args", [])
        chk(
            "AI.02 buildCommand includes --allowedTools flag",
            "--allowedTools" in args,
            f"args={args}",
        )
        # Verify the tools are joined correctly
        idx = args.index("--allowedTools") if "--allowedTools" in args else -1
        tools_val = args[idx + 1] if idx >= 0 and idx + 1 < len(args) else ""
        chk(
            "AI.02 allowedTools value contains all tools",
            "Read" in tools_val and "Edit" in tools_val and "Bash(git:*)" in tools_val,
            f"tools_val={tools_val}",
        )
        assert "--allowedTools" in args

    def test_ai03_build_command_still_has_verbose_and_stream_json(self):
        """Permission flags must NOT break existing --verbose --output-format flags."""
        r = js_config("build-command", json.dumps({"permissionMode": "auto"}))
        args = r.get("args", [])
        chk("AI.03 --verbose still present", "--verbose" in args, f"args={args}")
        chk("AI.03 --output-format still present", "--output-format" in args)
        chk("AI.03 stream-json still present", "stream-json" in args)
        assert "--verbose" in args and "stream-json" in args

    def test_ai04_build_command_prompt_at_end(self):
        """Prompt must be the last arg after -p flag."""
        r = js_config("build-command", json.dumps({"permissionMode": "acceptEdits"}))
        args = r.get("args", [])
        chk("AI.04 -p is second-to-last", args[-2] == "-p" if len(args) >= 2 else False)
        chk("AI.04 prompt is last arg", args[-1] == "test prompt" if args else False)
        assert args[-1] == "test prompt"

    def test_ai05_build_continue_includes_permission_mode(self):
        r = js_config("build-continue", json.dumps({"permissionMode": "auto"}), "abc-123")
        args = r.get("args", [])
        chk(
            "AI.05 buildContinueCommand includes --permission-mode",
            "--permission-mode" in args and "auto" in args,
            f"args={args}",
        )
        assert "--permission-mode" in args

    def test_ai06_build_continue_includes_resume_session_id(self):
        r = js_config("build-continue", json.dumps({}), "a1b2c3d4-1234-5678-abcd-ef0123456789")
        args = r.get("args", [])
        chk(
            "AI.06 buildContinueCommand includes --resume with session ID",
            "--resume" in args and "a1b2c3d4-1234-5678-abcd-ef0123456789" in args,
            f"args={args}",
        )
        assert "--resume" in args

    def test_ai07_no_overrides_no_extra_flags(self):
        """Without permission config, no extra flags added."""
        r = js_config("build-command", json.dumps({}))
        args = r.get("args", [])
        chk(
            "AI.07 no permission flags when not configured",
            "--permission-mode" not in args and "--allowedTools" not in args,
            f"args={args}",
        )
        assert "--permission-mode" not in args


# ---------------------------------------------------------------------------
# P0-B: Session ID Persistence
# ---------------------------------------------------------------------------

class TestSessionPersistence:
    """
    Verifies that agent session IDs are saved to disk and restored on startup.
    """

    def test_ai10_save_and_load_round_trip(self):
        section("P0-B — Session Persistence")
        data = {"claude": "a1b2c3d4-1234-5678-abcd-ef0123456789", "gemini": "dead-beef-cafe-1234-abcdef012345"}
        r = js_session("save-then-load", json.dumps(data))
        sessions = r.get("sessions", {})
        chk(
            "AI.10 save-then-load preserves claude session ID",
            sessions.get("claude") == data["claude"],
            f"got={sessions.get('claude')}",
        )
        chk(
            "AI.10 save-then-load preserves gemini session ID",
            sessions.get("gemini") == data["gemini"],
            f"got={sessions.get('gemini')}",
        )
        assert sessions.get("claude") == data["claude"]

    def test_ai11_clear_removes_all_sessions(self):
        # Save first, then clear, then load
        js_session("save", json.dumps({"claude": "test-id"}))
        js_session("clear")
        r = js_session("load")
        sessions = r.get("sessions", {})
        chk(
            "AI.11 clear removes all saved session IDs",
            len(sessions) == 0,
            f"got {len(sessions)} sessions after clear",
        )
        assert len(sessions) == 0

    def test_ai12_load_returns_empty_when_no_file(self):
        """Loading when no file exists should return empty dict, not error."""
        js_session("clear")  # ensure clean state
        r = js_session("load")
        sessions = r.get("sessions", {})
        chk("AI.12 load returns empty dict when no file", isinstance(sessions, dict))
        assert "error" not in r

    def test_ai13_overwrite_updates_existing(self):
        """Saving again overwrites previous data entirely."""
        js_session("save", json.dumps({"claude": "old-id"}))
        js_session("save", json.dumps({"claude": "new-id", "codex": "codex-id"}))
        r = js_session("load")
        sessions = r.get("sessions", {})
        chk("AI.13 overwrite updates claude to new ID", sessions.get("claude") == "new-id")
        chk("AI.13 overwrite adds codex ID", sessions.get("codex") == "codex-id")
        assert sessions.get("claude") == "new-id"

    def test_ai14_session_dir_under_vantage_home(self):
        r = js_session("dir")
        d = r.get("dir", "")
        chk("AI.14 session dir is under ~/.vantage/sessions", ".vantage" in d and "sessions" in d)
        assert ".vantage" in d


# ---------------------------------------------------------------------------
# P1-A: Real-time Streaming — content_block_delta Support
# ---------------------------------------------------------------------------

renderer_available = RENDERER_HARNESS.exists()


@pytest.mark.skipif(not renderer_available, reason="test-renderer.ts not present")
class TestStreamingDeltas:
    """
    Verifies that ClaudeStreamRenderer handles content_block_delta events
    for real-time character-by-character output.
    """

    def test_ai20_text_delta_produces_display(self):
        section("P1-A — Real-time Streaming Deltas")
        event = json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        })
        r = renderer("process", event)
        display = r.get("display", "")
        chk(
            "AI.20 content_block_delta with text_delta produces display",
            "Hello" in display,
            f"display={display!r}",
        )
        assert "Hello" in display

    def test_ai21_text_delta_produces_token_text(self):
        event = json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "World"},
        })
        r = renderer("process", event)
        chk(
            "AI.21 text_delta produces tokenText for cost tracking",
            "World" in r.get("tokenText", ""),
        )
        assert "World" in r.get("tokenText", "")

    def test_ai22_input_json_delta_no_display(self):
        """input_json_delta (tool input streaming) should not produce display."""
        event = json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"cmd":'},
        })
        r = renderer("process", event)
        chk(
            "AI.22 input_json_delta produces no display",
            not r.get("display"),
        )

    def test_ai23_message_delta_extracts_tokens(self):
        """message_delta with usage stats should return token counts."""
        event = json.dumps({
            "type": "message_delta",
            "usage": {"output_tokens": 150},
        })
        r = renderer("process", event)
        chk(
            "AI.23 message_delta returns output_tokens",
            r.get("outputTokens") == 150,
            f"got={r.get('outputTokens')}",
        )
        assert r.get("outputTokens") == 150

    def test_ai24_content_block_start_tool_use_announces(self):
        """content_block_start with tool_use should show tool name announcement."""
        event = json.dumps({
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "Bash"},
        })
        r = renderer("process", event)
        display = r.get("display", "")
        chk(
            "AI.24 content_block_start tool_use announces tool",
            "Bash" in display,
            f"display={display!r}",
        )
        assert "Bash" in display

    def test_ai25_content_block_start_text_no_display(self):
        """content_block_start with text type should not produce display."""
        event = json.dumps({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        r = renderer("process", event)
        chk("AI.25 content_block_start text produces no display", not r.get("display"))

    def test_ai26_existing_assistant_events_still_work(self):
        """Ensure existing assistant event parsing is not broken by delta support."""
        event = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Still works"}]},
        })
        r = renderer("process", event)
        chk("AI.26 assistant events still render", "Still works" in r.get("display", ""))
        assert "Still works" in r.get("display", "")


# ---------------------------------------------------------------------------
# P1-B: Agent Config Reading
# ---------------------------------------------------------------------------

class TestAgentConfigReading:
    """
    Verifies that vantage can read agent native config files.
    These tests read real files on the system — they skip gracefully
    if the agent is not installed.
    """

    def test_ai30_read_claude_model_returns_string(self):
        section("P1-B — Agent Config Reading")
        r = js_config("read-claude-model")
        model = r.get("model")
        chk(
            "AI.30 readClaudeConfig returns model (or null if not installed)",
            model is None or isinstance(model, str),
            f"model={model!r}",
        )
        # Don't assert non-null — claude might not be installed on CI

    def test_ai31_read_claude_mcp_returns_list(self):
        r = js_config("read-claude-mcp")
        servers = r.get("mcpServers")
        chk(
            "AI.31 readClaudeConfig returns MCP server list",
            isinstance(servers, list),
            f"servers={servers!r}",
        )
        assert isinstance(servers, list)

    def test_ai32_read_claude_permissions_returns_object_or_null(self):
        r = js_config("read-claude-permissions")
        perms = r.get("permissions")
        chk(
            "AI.32 readClaudeConfig returns permissions (object or null)",
            perms is None or isinstance(perms, dict),
            f"permissions type={type(perms).__name__}",
        )

    def test_ai33_config_read_does_not_crash_on_missing_file(self):
        """readClaudeConfig must return null gracefully if ~/.claude doesn't exist."""
        # This test passes as long as no exception propagates
        r = js_config("read-claude-model")
        chk("AI.33 no crash on config read", "error" not in r)
        assert "error" not in r
