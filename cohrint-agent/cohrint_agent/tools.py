"""
tools.py — Local tool definitions and executor.

Each tool mirrors Claude Code's built-in tools. Cohrint executes them locally
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

# Default safe tools (read-only, no side effects).
# frozenset so external code can't mutate the global default and drift
# the baseline for future PermissionManager instances
# (T-SAFETY.safe_tools_immutable).
SAFE_TOOLS: frozenset[str] = frozenset({"Read", "Glob", "Grep"})


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "Bash": ["command"],
    "Write": ["file_path", "content"],
    "Edit": ["file_path", "old_string", "new_string"],
    "Read": ["file_path"],
    "Glob": ["pattern"],
    "Grep": ["pattern"],
}


def _validate_tool_input(tool_name: str, tool_input: dict) -> str | None:
    """Returns error message if invalid, None if valid."""
    required = _REQUIRED_FIELDS.get(tool_name, [])
    missing = [f for f in required if f not in tool_input]
    if missing:
        return f"Tool {tool_name} missing required fields: {missing}"
    return None


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _audit_bash(cmd: str, cwd: str, timeout: float) -> None:
    """Append a single-line JSON audit record for every Bash invocation.

    Lives at ``~/.cohrint-agent/audit/bash.log``. Best-effort: never
    raise — auditing must not block a legitimate command.
    """
    try:
        home = Path(os.path.expanduser("~")) / ".cohrint-agent" / "audit"
        home.mkdir(parents=True, exist_ok=True)
        import json, time
        rec = {
            "ts": time.time(),
            "pid": os.getpid(),
            "cwd": cwd,
            "timeout": timeout,
            "command": cmd[:4096],
        }
        with (home / "bash.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def execute_tool(name: str, tool_input: dict[str, Any], cwd: str) -> str:
    """Execute a tool locally and return the result as a string."""
    error = _validate_tool_input(name, tool_input)
    if error:
        return error
    if name == "Bash":
        return _exec_bash(tool_input, cwd)
    if name == "Read":
        return _exec_read(tool_input, cwd)
    if name == "Write":
        return _exec_write(tool_input, cwd)
    if name == "Edit":
        return _exec_edit(tool_input, cwd)
    if name == "Glob":
        return _exec_glob(tool_input, cwd)
    if name == "Grep":
        return _exec_grep(tool_input, cwd)
    return f"Unknown tool: {name}"


def _confine_to_cwd(file_path: str, cwd: str) -> tuple[Path | None, str | None]:
    """Resolve file_path and verify it stays inside cwd.

    Prevents the LLM from writing to paths like ~/.ssh/authorized_keys via
    absolute paths or ../ traversal. Returns (resolved_path, None) on success
    or (None, error_message) on any rejection.
    """
    try:
        resolved = Path(file_path).expanduser().resolve()
        cwd_resolved = Path(cwd).expanduser().resolve()
    except (OSError, ValueError) as e:
        return None, f"Invalid path: {e}"
    # is_relative_to exists on 3.9+. The check rejects absolute paths outside
    # cwd *and* resolved-symlink escapes. No try/except — a False result means
    # the path is outside cwd, which is itself the error we want.
    if not resolved.is_relative_to(cwd_resolved):
        return None, (
            f"Refused: path escapes working directory "
            f"({resolved} not under {cwd_resolved})"
        )
    return resolved, None


def _exec_bash(inp: dict[str, Any], cwd: str) -> str:
    # Model-generated tool_input may have arbitrary JSON types. Reject
    # non-string commands and coerce timeout into a finite (0, 600] float
    # so subprocess.run can't inherit NaN/inf/negative timeouts
    # (T-INPUT.bash_shape_check).
    cmd = inp.get("command")
    if not isinstance(cmd, str) or not cmd:
        return "Error: Bash 'command' must be a non-empty string"
    import math as _math
    raw_t = inp.get("timeout", 120)
    try:
        timeout = float(raw_t)
    except (TypeError, ValueError):
        timeout = 120.0
    if _math.isnan(timeout) or _math.isinf(timeout) or timeout <= 0:
        timeout = 120.0
    timeout = min(timeout, 600.0)
    _audit_bash(cmd, cwd, timeout)
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


def _exec_read(inp: dict[str, Any], cwd: str) -> str:
    file_path = inp["file_path"]
    # Clamp offset/limit to sensible bounds. Model-generated values may
    # be negative (slices from tail — leaks end-of-file when start was
    # intended) or astronomically large (huge list allocation)
    # (T-INPUT.read_bounds).
    try:
        offset = max(0, int(inp.get("offset", 0) or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(inp.get("limit", 2000) or 2000)
    except (TypeError, ValueError):
        limit = 2000
    limit = max(1, min(10000, limit))
    p, err = _confine_to_cwd(file_path, cwd)
    if err:
        return err
    try:
        assert p is not None
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


def _exec_write(inp: dict[str, Any], cwd: str) -> str:
    file_path = inp["file_path"]
    content = inp["content"]
    p, err = _confine_to_cwd(file_path, cwd)
    if err:
        return err
    try:
        assert p is not None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing {file_path}: {e}"


def _exec_edit(inp: dict[str, Any], cwd: str) -> str:
    file_path = inp["file_path"]
    old_string = inp["old_string"]
    new_string = inp["new_string"]
    p, err = _confine_to_cwd(file_path, cwd)
    if err:
        return err
    try:
        assert p is not None
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
