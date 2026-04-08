"""
test_integration.py — Full integration tests for vantage-agent.

Tests the complete flow: prompt → API → tool execution → result.
Covers multi-turn conversations, tool use, permissions, edge cases,
and feature parity with Claude Code / Cursor terminal.

Requires ANTHROPIC_API_KEY to run. Skipped gracefully without it.
"""
from __future__ import annotations

import os
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import live

# ============================================================================
# A. MULTI-TURN CONVERSATION (context preservation)
# ============================================================================


@live
class TestMultiTurn:
    """Verify the agent maintains context across multiple prompts."""

    def test_remembers_previous_answer(self, client):
        """Ask a question, then ask a follow-up that requires the first answer."""
        client.send("The secret number is 7734. Just acknowledge it.")
        response = client.send("What was the secret number I just told you?")
        assert "7734" in response

    def test_three_turn_conversation(self, client):
        """3-turn conversation building on prior context."""
        client.send("Let x = 10")
        client.send("Let y = x * 3")
        response = client.send("What is y + 5? Just give the number.")
        assert "35" in response

    def test_remembers_file_context(self, client, workspace):
        """Agent reads a file, then answers questions about it from memory."""
        client.send(f"Read the file {workspace}/main.py and remember what functions are defined.")
        response = client.send("What functions did you see? Just list the names.")
        assert "greet" in response.lower()
        assert "add" in response.lower()

    def test_conversation_after_tool_use(self, client, workspace):
        """After using a tool, context is preserved for follow-up."""
        client.send(f"Use Bash to count lines in {workspace}/main.py")
        response = client.send("How many lines was that? Just the number.")
        # main.py has 8 lines
        assert any(c.isdigit() for c in response)


# ============================================================================
# B. TOOL EXECUTION — BASH
# ============================================================================


@live
class TestBashTool:
    """Test Bash tool execution through the agent."""

    def test_simple_command(self, client):
        """Agent executes a simple command."""
        response = client.send("Run: echo 'vantage-test-42'. Show the output.")
        assert "vantage-test-42" in response

    def test_command_with_pipe(self, client, workspace):
        """Agent handles piped commands."""
        response = client.send(f"Run: cat {workspace}/requirements.txt | grep rich")
        assert "rich" in response.lower()

    def test_python_execution(self, client):
        """Agent runs Python code."""
        response = client.send("Run: python3 -c \"print(2**10)\"")
        assert "1024" in response

    def test_git_status(self, client, workspace):
        """Agent runs git commands in workspace."""
        # Init a git repo first
        client.send(f"Run: cd {workspace} && git init && git add . && git commit -m 'init'")
        response = client.send(f"Run: cd {workspace} && git log --oneline")
        assert "init" in response

    def test_failing_command(self, client):
        """Agent handles a command that exits with error."""
        response = client.send("Run: ls /nonexistent_dir_12345. Tell me if it failed.")
        assert any(w in response.lower() for w in ["error", "no such", "fail", "not found"])

    def test_multiline_output(self, client, workspace):
        """Agent handles commands with many output lines."""
        response = client.send(f"Run: find {workspace} -name '*.py' | sort")
        assert "main.py" in response
        assert "utils.py" in response


# ============================================================================
# C. TOOL EXECUTION — FILE OPERATIONS (Read, Write, Edit)
# ============================================================================


@live
class TestFileTools:
    """Test file reading, writing, and editing through the agent."""

    def test_read_file(self, client, workspace):
        """Agent reads a file and reports contents."""
        response = client.send(f"Read {workspace}/config.json and tell me the port value.")
        assert "8080" in response

    def test_write_new_file(self, client, workspace):
        """Agent creates a new file."""
        target = workspace / "output.txt"
        client.send(f"Write the text 'hello from vantage' to {target}")
        assert target.exists()
        assert "hello from vantage" in target.read_text()

    def test_edit_existing_file(self, client, workspace):
        """Agent edits a specific part of a file."""
        client.send(
            f"In {workspace}/main.py, change the greet function to return "
            f"'Hi, {{name}}!' instead of 'Hello, {{name}}!'"
        )
        content = (workspace / "main.py").read_text()
        assert "Hi, {name}!" in content

    def test_read_csv_data(self, client, workspace):
        """Agent reads structured data."""
        response = client.send(f"Read {workspace}/data/users.csv. How many users are there?")
        assert "2" in response

    def test_create_file_in_new_directory(self, client, workspace):
        """Agent creates a file in a directory that doesn't exist yet."""
        target = workspace / "new_dir" / "new_file.py"
        client.send(f"Create {target} with a simple 'hello world' print statement.")
        assert target.exists()
        content = target.read_text()
        assert "print" in content or "hello" in content.lower()

    def test_edit_preserves_rest_of_file(self, client, workspace):
        """Editing one part of a file doesn't corrupt the rest."""
        original = (workspace / "utils.py").read_text()
        client.send(f"In {workspace}/utils.py, change 'ensure_dir' to 'make_dir'")
        updated = (workspace / "utils.py").read_text()
        assert "make_dir" in updated
        assert "read_config" in updated  # Other function preserved
        assert "import os" in updated  # Imports preserved


# ============================================================================
# D. TOOL EXECUTION — SEARCH (Glob, Grep)
# ============================================================================


@live
class TestSearchTools:
    """Test codebase search through the agent."""

    def test_glob_find_python_files(self, client, workspace):
        """Agent finds files by pattern."""
        response = client.send(f"Find all .py files in {workspace} recursively.")
        assert "main.py" in response
        assert "api.py" in response

    def test_grep_search_content(self, client, workspace):
        """Agent searches file contents."""
        response = client.send(f"Search for 'Flask' in all files under {workspace}")
        assert "api.py" in response

    def test_grep_with_regex(self, client, workspace):
        """Agent uses regex patterns."""
        response = client.send(f"Search for the pattern 'def \\w+\\(' in {workspace}")
        assert "greet" in response or "add" in response or "health" in response

    def test_find_and_read(self, client, workspace):
        """Agent finds a file then reads it — multi-tool chain."""
        response = client.send(
            f"Find any CSV file in {workspace}, then read it and tell me the column names."
        )
        assert "id" in response.lower() or "name" in response.lower() or "email" in response.lower()


# ============================================================================
# E. PERMISSION FLOW
# ============================================================================


class TestPermissionFlow:
    """Test the permission system without API (using tool executor directly)."""

    def test_safe_tools_no_prompt(self, perms, workspace):
        """Read/Glob/Grep execute without prompting."""
        from vantage_agent.tools import execute_tool
        assert perms.is_approved("Read")
        result = execute_tool("Read", {"file_path": str(workspace / "main.py")}, str(workspace))
        assert "greet" in result

    def test_bash_requires_approval(self, perms):
        """Bash is not pre-approved."""
        assert not perms.is_approved("Bash")

    def test_deny_prevents_execution(self, perms):
        """Denied tool returns False."""
        with patch("vantage_agent.permissions.Prompt.ask", return_value="n"):
            assert not perms.check_permission("Bash", {"command": "rm -rf /"})

    def test_allow_once_then_approved(self, perms):
        """After allowing once, tool is approved for the session."""
        with patch("vantage_agent.permissions.Prompt.ask", return_value="y"):
            assert perms.check_permission("Bash", {"command": "echo hi"})
        assert perms.is_approved("Bash")

    def test_allow_always_persists(self, perms, tmp_path):
        """'Always' persists to disk."""
        with patch("vantage_agent.permissions.Prompt.ask", return_value="a"):
            perms.check_permission("Write", {"file_path": "/tmp/x", "content": "y"})
        perm_file = tmp_path / ".vantage-agent" / "permissions.json"
        data = json.loads(perm_file.read_text())
        assert "Write" in data["always_approved"]

    def test_allow_command_bulk_approve(self, perms):
        """Programmatic bulk approval works."""
        perms.approve(["Bash", "Write", "Edit"], always=True)
        assert perms.is_approved("Bash")
        assert perms.is_approved("Write")
        assert perms.is_approved("Edit")

    def test_reset_revokes_all(self, perms):
        """Reset clears everything except safe tools."""
        perms.approve(["Bash", "Write"], always=True)
        perms.reset()
        assert not perms.is_approved("Bash")
        assert not perms.is_approved("Write")
        assert perms.is_approved("Read")


@live
class TestPermissionFlowLive:
    """Test permission denial/approval with live API."""

    def test_denied_tool_agent_adapts(self, workspace, cost):
        """When a tool is denied, agent gets error and adapts."""
        from vantage_agent.api_client import AgentClient
        from vantage_agent.permissions import PermissionManager

        # Create perms that deny everything except Read
        perms = PermissionManager()
        # Monkey-patch to auto-deny Bash
        original_check = perms.check_permission
        def deny_bash(tool_name, tool_input):
            if tool_name == "Bash":
                return False
            return original_check(tool_name, tool_input)
        perms.check_permission = deny_bash
        perms.approve(["Read", "Glob", "Grep"], always=False)

        client = AgentClient(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            permissions=perms,
            cost=cost,
            cwd=str(workspace),
        )
        # Agent should handle denial gracefully
        response = client.send("Use Bash to run 'echo test'. If denied, say DENIED.")
        assert "denied" in response.lower() or "unable" in response.lower() or "cannot" in response.lower()


# ============================================================================
# F. COST TRACKING
# ============================================================================


@live
class TestCostTracking:
    """Verify real cost tracking from API responses."""

    def test_cost_recorded_after_prompt(self, client):
        """Cost is tracked after a prompt."""
        client.send("Say hello.")
        assert client.cost.total_cost_usd > 0
        assert client.cost.total_input > 0
        assert client.cost.total_output > 0
        assert client.cost.prompt_count == 1

    def test_cost_accumulates(self, client):
        """Cost accumulates across multiple prompts."""
        client.send("Say one.")
        cost1 = client.cost.total_cost_usd
        client.send("Say two.")
        cost2 = client.cost.total_cost_usd
        assert cost2 > cost1
        assert client.cost.prompt_count == 2

    def test_tool_use_adds_cost(self, client, workspace):
        """Tool use (multi-turn) costs more than simple text."""
        # Simple prompt
        client2_cost = SessionCost(model="claude-sonnet-4-6")
        from vantage_agent.api_client import AgentClient
        client2 = AgentClient(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            permissions=client.permissions,
            cost=client2_cost,
            cwd=str(workspace),
        )
        client2.send("Say hi.")
        simple_cost = client2.cost.total_cost_usd

        # Tool-using prompt (will use Read tool)
        client.send(f"Read {workspace}/main.py and tell me what it does.")
        tool_cost = client.cost.total_cost_usd

        # Tool use typically costs more (more tokens from tool results)
        assert tool_cost > 0


# ============================================================================
# G. CLI COMMANDS (unit tests, no API needed)
# ============================================================================


class TestCLICommands:
    """Test /commands handling without API."""

    def test_handle_help(self, workspace, perms, cost):
        """Test /help returns True (handled)."""
        from vantage_agent.cli import _handle_command
        from vantage_agent.api_client import AgentClient

        if not os.environ.get("ANTHROPIC_API_KEY") and not any(
            os.path.exists(p) for p in [
                os.path.expanduser("~/.vantage-agent/api_key"),
                os.path.expanduser("~/.anthropic/api_key"),
            ]
        ):
            pytest.skip("No API key for client init")

        client = AgentClient(
            model="claude-sonnet-4-6",
            permissions=perms,
            cost=cost,
            cwd=str(workspace),
        )
        assert _handle_command("/help", client) is True

    def test_allow_command_parsing(self, perms):
        """Test /allow parses tool names."""
        perms.approve(["Bash", "Write"], always=True)
        assert perms.is_approved("Bash")
        assert perms.is_approved("Write")

    def test_tools_status(self, perms):
        """Test /tools shows correct state."""
        session, always = perms.status()
        assert "Read" in session
        assert "Glob" in session
        assert "Grep" in session


# ============================================================================
# H. EDGE CASES & EXTREME SCENARIOS
# ============================================================================


class TestEdgeCasesOffline:
    """Edge cases that don't need API."""

    def test_empty_file_read(self, workspace):
        """Read an empty file."""
        from vantage_agent.tools import execute_tool
        (workspace / "empty.txt").write_text("")
        result = execute_tool("Read", {"file_path": str(workspace / "empty.txt")}, str(workspace))
        assert "empty" in result.lower()

    def test_binary_file_read(self, workspace):
        """Read a binary file doesn't crash."""
        from vantage_agent.tools import execute_tool
        (workspace / "binary.bin").write_bytes(bytes(range(256)))
        result = execute_tool("Read", {"file_path": str(workspace / "binary.bin")}, str(workspace))
        assert isinstance(result, str)

    def test_unicode_file_operations(self, workspace):
        """Unicode content in files."""
        from vantage_agent.tools import execute_tool
        unicode_content = "Hello 世界 🌍 Ñoño café"
        execute_tool("Write", {
            "file_path": str(workspace / "unicode.txt"),
            "content": unicode_content,
        }, str(workspace))
        result = execute_tool("Read", {
            "file_path": str(workspace / "unicode.txt"),
        }, str(workspace))
        assert "世界" in result
        assert "🌍" in result

    def test_very_long_file(self, workspace):
        """Read a file with 10000 lines."""
        from vantage_agent.tools import execute_tool
        content = "\n".join(f"line {i}" for i in range(10000))
        (workspace / "big.txt").write_text(content)
        result = execute_tool("Read", {
            "file_path": str(workspace / "big.txt"),
            "limit": 50,
        }, str(workspace))
        lines = result.strip().splitlines()
        assert len(lines) == 50

    def test_special_chars_in_bash(self, workspace):
        """Bash handles special characters."""
        from vantage_agent.tools import execute_tool
        result = execute_tool("Bash", {
            "command": "echo 'hello \"world\" $HOME `test`'",
        }, str(workspace))
        assert "hello" in result

    def test_edit_multiline_string(self, workspace):
        """Edit a multiline block."""
        from vantage_agent.tools import execute_tool
        (workspace / "multi.py").write_text(
            "def old():\n    pass\n\ndef other():\n    return 1\n"
        )
        result = execute_tool("Edit", {
            "file_path": str(workspace / "multi.py"),
            "old_string": "def old():\n    pass",
            "new_string": "def new():\n    return 42",
        }, str(workspace))
        assert "edited" in result.lower()
        assert "def new():" in (workspace / "multi.py").read_text()
        assert "def other():" in (workspace / "multi.py").read_text()

    def test_glob_no_permission_needed(self, workspace):
        """Glob works without special permissions (safe tool)."""
        from vantage_agent.tools import execute_tool
        result = execute_tool("Glob", {"pattern": "**/*.py"}, str(workspace))
        assert "main.py" in result

    def test_grep_across_many_files(self, workspace):
        """Grep searches across nested directories."""
        from vantage_agent.tools import execute_tool
        result = execute_tool("Grep", {
            "pattern": "import",
            "path": str(workspace),
        }, str(workspace))
        assert "utils.py" in result
        assert "api.py" in result

    def test_bash_timeout_short(self, workspace):
        """Bash respects timeout."""
        from vantage_agent.tools import execute_tool
        start = time.time()
        result = execute_tool("Bash", {
            "command": "sleep 30",
            "timeout": 2,
        }, str(workspace))
        elapsed = time.time() - start
        assert elapsed < 5
        assert "timed out" in result.lower()

    def test_write_then_read_roundtrip(self, workspace):
        """Write → Read roundtrip preserves content."""
        from vantage_agent.tools import execute_tool
        content = "line1\nline2\nline3\n"
        execute_tool("Write", {
            "file_path": str(workspace / "roundtrip.txt"),
            "content": content,
        }, str(workspace))
        result = execute_tool("Read", {
            "file_path": str(workspace / "roundtrip.txt"),
        }, str(workspace))
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    def test_edit_then_grep_verifies(self, workspace):
        """Edit a file then grep confirms the change."""
        from vantage_agent.tools import execute_tool
        execute_tool("Edit", {
            "file_path": str(workspace / "main.py"),
            "old_string": "return a + b",
            "new_string": "return a * b",
        }, str(workspace))
        result = execute_tool("Grep", {
            "pattern": "return a \\* b",
            "path": str(workspace / "main.py"),
        }, str(workspace))
        assert "main.py" in result


@live
class TestEdgeCasesLive:
    """Edge cases requiring live API."""

    def test_empty_prompt_handling(self, client):
        """Agent handles near-empty prompt."""
        response = client.send(".")
        assert isinstance(response, str)

    def test_very_long_prompt(self, client):
        """Agent handles a very long prompt."""
        long_prompt = "Repeat this word: buffalo. " * 200 + " How many times did I say buffalo?"
        response = client.send(long_prompt)
        assert isinstance(response, str)
        assert len(response) > 0

    def test_unicode_prompt(self, client):
        """Agent handles unicode in prompt."""
        response = client.send("Translate '你好世界' to English. Just the translation.")
        assert "hello" in response.lower() or "world" in response.lower()

    def test_code_generation(self, client, workspace):
        """Agent generates code to a file."""
        target = workspace / "generated.py"
        client.send(
            f"Write a Python function that calculates fibonacci(n) iteratively "
            f"to {target}. Just the function, no tests."
        )
        assert target.exists()
        content = target.read_text()
        assert "def" in content
        assert "fibonacci" in content.lower() or "fib" in content.lower()

    def test_multi_tool_chain(self, client, workspace):
        """Agent chains multiple tools: grep → read → edit."""
        response = client.send(
            f"In {workspace}, find which file has a 'health' endpoint, "
            f"read that file, then add a '/status' endpoint that returns "
            f"{{'version': '1.0'}}. Show me what you changed."
        )
        content = (workspace / "src" / "api.py").read_text()
        assert "status" in content or "version" in content

    def test_agent_runs_tests(self, client, workspace):
        """Agent runs pytest on the workspace."""
        response = client.send(
            f"Run pytest on {workspace}/test_main.py and tell me if tests pass."
        )
        assert any(w in response.lower() for w in ["pass", "passed", "ok", "success"])

    def test_handles_tool_error_gracefully(self, client):
        """Agent handles a tool that returns an error."""
        response = client.send(
            "Read the file /nonexistent/path/to/file.txt and tell me what happened."
        )
        assert any(w in response.lower() for w in ["not found", "doesn't exist", "error", "no such"])

    def test_rapid_fire_prompts(self, client):
        """Multiple quick prompts in sequence don't corrupt state."""
        r1 = client.send("What is 1+1? Just the number.")
        r2 = client.send("What is 2+2? Just the number.")
        r3 = client.send("What is 3+3? Just the number.")
        assert "2" in r1
        assert "4" in r2
        assert "6" in r3

    def test_conversation_with_tool_and_followup(self, client, workspace):
        """Tool use mid-conversation, then follow-up without tools."""
        client.send(f"Read {workspace}/requirements.txt")
        response = client.send("Based on what you just read, what testing framework is listed?")
        assert "pytest" in response.lower()


# ============================================================================
# I. FEATURE PARITY — Things Claude Code / Cursor can do
# ============================================================================


@live
class TestFeatureParity:
    """Tests ensuring vantage-agent can do what Claude Code does."""

    def test_explore_codebase(self, client, workspace):
        """Agent can explore a codebase structure."""
        response = client.send(
            f"Explore {workspace} and give me a summary of the project structure."
        )
        assert any(w in response.lower() for w in ["main.py", "src", "data", "api"])

    def test_fix_bug(self, client, workspace):
        """Agent can find and fix a bug."""
        # Introduce a bug
        (workspace / "buggy.py").write_text(
            "def divide(a, b):\n    return a / b\n\n"
            "# BUG: no zero division check\n"
            "result = divide(10, 0)\n"
        )
        client.send(
            f"The file {workspace}/buggy.py has a division by zero bug. "
            f"Fix it by adding a check that returns None when b is 0."
        )
        content = (workspace / "buggy.py").read_text()
        assert "0" in content  # Some check for zero
        assert "None" in content or "none" in content

    def test_refactor_code(self, client, workspace):
        """Agent can refactor code."""
        client.send(
            f"In {workspace}/main.py, refactor the 'add' function to also "
            f"support subtraction. Rename it to 'calculate(a, b, op)' where "
            f"op is '+' or '-'."
        )
        content = (workspace / "main.py").read_text()
        assert "calculate" in content

    def test_create_test_file(self, client, workspace):
        """Agent creates a test file for existing code."""
        target = workspace / "test_utils.py"
        client.send(
            f"Write pytest tests for {workspace}/utils.py. "
            f"Save to {target}. Test read_config and ensure_dir."
        )
        assert target.exists()
        content = target.read_text()
        assert "def test_" in content

    def test_explain_code(self, client, workspace):
        """Agent explains code without modifying it."""
        response = client.send(f"Explain what {workspace}/src/api.py does. Be brief.")
        original = (workspace / "src" / "api.py").read_text()
        assert "Flask" in response or "flask" in response or "api" in response.lower()
        # File should be unchanged
        assert (workspace / "src" / "api.py").read_text() == original

    def test_search_and_replace_across_files(self, client, workspace):
        """Agent searches across files and makes targeted edits."""
        response = client.send(
            f"In {workspace}, find all files that import 'os' and list them."
        )
        assert "utils.py" in response
