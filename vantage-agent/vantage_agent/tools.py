"""
tools.py — Local tool definitions and executor.

Each tool mirrors Claude Code's built-in tools. Vantage executes them locally
and sends results back to the Anthropic API.
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tool JSON schemas (sent to the Anthropic API as available tools)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "Bash",
        "description": "Execute a shell command and return stdout/stderr. Use for system commands, git, package managers, builds, tests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "Read",
        "description": "Read a file from the filesystem. Returns contents with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read (default 2000)",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Write",
        "description": "Write content to a file. Creates parent directories if needed. Overwrites existing files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "Edit",
        "description": "Replace an exact string in a file. old_string must be unique in the file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "Glob",
        "description": "Find files matching a glob pattern. Returns sorted file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts')",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: cwd)",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "Grep",
        "description": "Search file contents with regex. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (default: cwd)",
                },
                "include": {
                    "type": "string",
                    "description": "Glob to filter files (e.g. '*.py')",
                },
            },
            "required": ["pattern"],
        },
    },
]

# Map for quick lookup
TOOL_MAP: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOL_DEFINITIONS}

# Default safe tools (read-only, no side effects)
SAFE_TOOLS = {"Read", "Glob", "Grep"}


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_tool(name: str, tool_input: dict[str, Any], cwd: str) -> str:
    """Execute a tool locally and return the result as a string."""
    if name == "Bash":
        return _exec_bash(tool_input, cwd)
    if name == "Read":
        return _exec_read(tool_input)
    if name == "Write":
        return _exec_write(tool_input)
    if name == "Edit":
        return _exec_edit(tool_input)
    if name == "Glob":
        return _exec_glob(tool_input, cwd)
    if name == "Grep":
        return _exec_grep(tool_input, cwd)
    return f"Unknown tool: {name}"


def _exec_bash(inp: dict[str, Any], cwd: str) -> str:
    cmd = inp["command"]
    timeout = inp.get("timeout", 120)
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        out = ""
        if result.stdout:
            out += result.stdout
        if result.stderr:
            out += ("\n" if out else "") + result.stderr
        if result.returncode != 0:
            out += f"\n(exit code {result.returncode})"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def _exec_read(inp: dict[str, Any]) -> str:
    file_path = inp["file_path"]
    offset = inp.get("offset", 0)
    limit = inp.get("limit", 2000)
    try:
        p = Path(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        if not p.is_file():
            return f"Not a file: {file_path}"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = lines[offset : offset + limit]
        numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
        return "\n".join(numbered) or "(empty file)"
    except Exception as e:
        return f"Error reading {file_path}: {e}"


def _exec_write(inp: dict[str, Any]) -> str:
    file_path = inp["file_path"]
    content = inp["content"]
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing {file_path}: {e}"


def _exec_edit(inp: dict[str, Any]) -> str:
    file_path = inp["file_path"]
    old_string = inp["old_string"]
    new_string = inp["new_string"]
    try:
        p = Path(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        text = p.read_text(encoding="utf-8")
        count = text.count(old_string)
        if count == 0:
            return f"old_string not found in {file_path}"
        if count > 1:
            return f"old_string found {count} times (must be unique). Provide more context."
        text = text.replace(old_string, new_string, 1)
        p.write_text(text, encoding="utf-8")
        return f"Edited {file_path}"
    except Exception as e:
        return f"Error editing {file_path}: {e}"


def _exec_glob(inp: dict[str, Any], cwd: str) -> str:
    pattern = inp["pattern"]
    base = inp.get("path", cwd)
    try:
        base_path = Path(base)
        matches = sorted(str(p) for p in base_path.glob(pattern) if p.is_file())
        if not matches:
            return "No files matched."
        # Limit to 200 results
        if len(matches) > 200:
            return "\n".join(matches[:200]) + f"\n... ({len(matches)} total, showing first 200)"
        return "\n".join(matches)
    except Exception as e:
        return f"Error: {e}"


def _exec_grep(inp: dict[str, Any], cwd: str) -> str:
    pattern = inp["pattern"]
    search_path = inp.get("path", cwd)
    include = inp.get("include", None)
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Invalid regex: {e}"

    results: list[str] = []
    base = Path(search_path)

    if base.is_file():
        files = [base]
    else:
        glob_pattern = include or "**/*"
        files = [f for f in base.glob(glob_pattern) if f.is_file()]

    for fpath in files[:500]:  # cap file count
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                results.append(f"{fpath}:{i}: {line}")
                if len(results) >= 500:
                    break
        if len(results) >= 500:
            break

    if not results:
        return "No matches found."
    return "\n".join(results)
