"""
Tests for cohrint_agent.tools — local tool execution.

Tests use real filesystem operations in a temp directory.
No mocks — all tools execute against real files and commands.
"""
import os
import tempfile
from pathlib import Path

import pytest

from cohrint_agent.tools import (
    TOOL_DEFINITIONS,
    TOOL_MAP,
    SAFE_TOOLS,
    execute_tool,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temp workspace with sample files."""
    # Create some files
    (tmp_path / "hello.py").write_text("print('hello')\n")
    (tmp_path / "main.py").write_text("def main():\n    return 42\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested content\n")
    (tmp_path / "data.json").write_text('{"key": "value"}\n')
    return tmp_path


# ---- Tool Definitions ----

class TestToolDefinitions:
    def test_six_tools_defined(self):
        assert len(TOOL_DEFINITIONS) == 6

    def test_all_tools_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_tool_map_matches_definitions(self):
        assert set(TOOL_MAP.keys()) == {t["name"] for t in TOOL_DEFINITIONS}

    def test_safe_tools_are_read_only(self):
        assert SAFE_TOOLS == {"Read", "Glob", "Grep"}

    def test_all_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        assert names == {"Bash", "Read", "Write", "Edit", "Glob", "Grep"}


# ---- Bash ----

class TestBash:
    def test_echo(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "echo hello"}, str(tmp_workspace))
        assert "hello" in result

    def test_returns_exit_code_on_failure(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "exit 1"}, str(tmp_workspace))
        assert "exit code 1" in result

    def test_captures_stderr(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "echo err >&2"}, str(tmp_workspace))
        assert "err" in result

    def test_respects_cwd(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "pwd"}, str(tmp_workspace))
        assert str(tmp_workspace) in result

    def test_timeout(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "sleep 10", "timeout": 1}, str(tmp_workspace))
        assert "timed out" in result.lower()

    def test_no_output_returns_marker(self, tmp_workspace):
        result = execute_tool("Bash", {"command": "true"}, str(tmp_workspace))
        assert result == "(no output)"


# ---- Read ----

class TestRead:
    def test_read_file(self, tmp_workspace):
        result = execute_tool("Read", {"file_path": str(tmp_workspace / "hello.py")}, str(tmp_workspace))
        assert "print('hello')" in result

    def test_read_with_line_numbers(self, tmp_workspace):
        result = execute_tool("Read", {"file_path": str(tmp_workspace / "main.py")}, str(tmp_workspace))
        assert "1\t" in result  # line numbers
        assert "def main():" in result

    def test_read_nonexistent(self, tmp_workspace):
        result = execute_tool("Read", {"file_path": str(tmp_workspace / "nope.txt")}, str(tmp_workspace))
        assert "not found" in result.lower()

    def test_read_with_offset_and_limit(self, tmp_workspace):
        result = execute_tool("Read", {
            "file_path": str(tmp_workspace / "main.py"),
            "offset": 1,
            "limit": 1,
        }, str(tmp_workspace))
        assert "return 42" in result
        assert "def main" not in result

    def test_read_empty_file(self, tmp_workspace):
        (tmp_workspace / "empty.txt").write_text("")
        result = execute_tool("Read", {"file_path": str(tmp_workspace / "empty.txt")}, str(tmp_workspace))
        assert "empty" in result.lower()

    def test_read_directory_fails(self, tmp_workspace):
        result = execute_tool("Read", {"file_path": str(tmp_workspace / "sub")}, str(tmp_workspace))
        assert "not a file" in result.lower()


# ---- Write ----

class TestWrite:
    def test_write_new_file(self, tmp_workspace):
        path = str(tmp_workspace / "new.txt")
        result = execute_tool("Write", {"file_path": path, "content": "hello world"}, str(tmp_workspace))
        assert "written" in result.lower()
        assert Path(path).read_text() == "hello world"

    def test_write_creates_parent_dirs(self, tmp_workspace):
        path = str(tmp_workspace / "deep" / "nested" / "file.txt")
        result = execute_tool("Write", {"file_path": path, "content": "deep"}, str(tmp_workspace))
        assert "written" in result.lower()
        assert Path(path).read_text() == "deep"

    def test_write_overwrites_existing(self, tmp_workspace):
        path = str(tmp_workspace / "hello.py")
        execute_tool("Write", {"file_path": path, "content": "new content"}, str(tmp_workspace))
        assert Path(path).read_text() == "new content"

    def test_write_reports_byte_count(self, tmp_workspace):
        path = str(tmp_workspace / "sized.txt")
        result = execute_tool("Write", {"file_path": path, "content": "12345"}, str(tmp_workspace))
        assert "5 bytes" in result


# ---- Edit ----

class TestEdit:
    def test_edit_replaces_unique_string(self, tmp_workspace):
        path = str(tmp_workspace / "main.py")
        result = execute_tool("Edit", {
            "file_path": path,
            "old_string": "return 42",
            "new_string": "return 99",
        }, str(tmp_workspace))
        assert "edited" in result.lower()
        assert "return 99" in Path(path).read_text()

    def test_edit_fails_if_not_found(self, tmp_workspace):
        path = str(tmp_workspace / "main.py")
        result = execute_tool("Edit", {
            "file_path": path,
            "old_string": "does not exist",
            "new_string": "whatever",
        }, str(tmp_workspace))
        assert "not found" in result.lower()

    def test_edit_fails_if_not_unique(self, tmp_workspace):
        # Create file with duplicate content
        path = str(tmp_workspace / "dup.txt")
        Path(path).write_text("line\nline\nline\n")
        result = execute_tool("Edit", {
            "file_path": path,
            "old_string": "line",
            "new_string": "replaced",
        }, str(tmp_workspace))
        assert "3 times" in result

    def test_edit_nonexistent_file(self, tmp_workspace):
        result = execute_tool("Edit", {
            "file_path": str(tmp_workspace / "nope.py"),
            "old_string": "x",
            "new_string": "y",
        }, str(tmp_workspace))
        assert "not found" in result.lower()


# ---- Glob ----

class TestGlob:
    def test_glob_py_files(self, tmp_workspace):
        result = execute_tool("Glob", {"pattern": "*.py"}, str(tmp_workspace))
        assert "hello.py" in result
        assert "main.py" in result

    def test_glob_recursive(self, tmp_workspace):
        result = execute_tool("Glob", {"pattern": "**/*.txt"}, str(tmp_workspace))
        assert "nested.txt" in result

    def test_glob_no_matches(self, tmp_workspace):
        result = execute_tool("Glob", {"pattern": "*.rs"}, str(tmp_workspace))
        assert "no files" in result.lower()

    def test_glob_custom_path(self, tmp_workspace):
        result = execute_tool("Glob", {
            "pattern": "*.txt",
            "path": str(tmp_workspace / "sub"),
        }, str(tmp_workspace))
        assert "nested.txt" in result


# ---- Grep ----

class TestGrep:
    def test_grep_finds_pattern(self, tmp_workspace):
        result = execute_tool("Grep", {"pattern": "def main"}, str(tmp_workspace))
        assert "main.py" in result
        assert "def main" in result

    def test_grep_returns_line_numbers(self, tmp_workspace):
        result = execute_tool("Grep", {"pattern": "return 42"}, str(tmp_workspace))
        assert ":2:" in result  # line 2

    def test_grep_no_matches(self, tmp_workspace):
        result = execute_tool("Grep", {"pattern": "zzz_nonexistent"}, str(tmp_workspace))
        assert "no matches" in result.lower()

    def test_grep_with_include_filter(self, tmp_workspace):
        result = execute_tool("Grep", {
            "pattern": ".*",
            "path": str(tmp_workspace),
            "include": "*.json",
        }, str(tmp_workspace))
        assert "data.json" in result
        assert "hello.py" not in result

    def test_grep_regex(self, tmp_workspace):
        result = execute_tool("Grep", {"pattern": r"return \d+"}, str(tmp_workspace))
        assert "return 42" in result

    def test_grep_invalid_regex(self, tmp_workspace):
        result = execute_tool("Grep", {"pattern": "[invalid"}, str(tmp_workspace))
        assert "invalid" in result.lower()


# ---- Unknown tool ----

class TestUnknownTool:
    def test_unknown_tool(self, tmp_workspace):
        result = execute_tool("DoesNotExist", {}, str(tmp_workspace))
        assert "unknown tool" in result.lower()
