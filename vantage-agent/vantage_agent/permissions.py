"""
permissions.py — Per-tool permission management.

Shared source of truth for both API backend (in-process) and
Claude CLI backend (via hook script reading same JSON).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt

from .tools import SAFE_TOOLS

console = Console()

_DEFAULT_CONFIG_DIR = Path(os.environ.get("VANTAGE_CONFIG_DIR", Path.home() / ".vantage-agent"))
_PERM_FILE_NAME = "permissions.json"

# Module-level aliases kept for backwards-compat with older test code
_STATE_DIR = _DEFAULT_CONFIG_DIR
_PERM_FILE = _DEFAULT_CONFIG_DIR / _PERM_FILE_NAME


def _config_dir(config_dir: Path | None) -> Path:
    return config_dir or _DEFAULT_CONFIG_DIR


class PermissionManager:
    """Manages per-tool approval state. Both backends share this."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = _config_dir(config_dir)
        self._perm_file = self._config_dir / _PERM_FILE_NAME
        self.session_approved: set[str] = set(SAFE_TOOLS)
        self.always_approved: set[str] = set(SAFE_TOOLS)
        self.always_denied: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._perm_file.exists():
            return
        try:
            import fcntl
            with open(self._perm_file) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            self.always_approved |= set(data.get("always_approved", []))
            self.always_denied = set(data.get("always_denied", []))
            self.session_approved |= set(data.get("session_approved", []))
            self.session_approved |= self.always_approved
        except Exception:
            pass  # corruption → safe defaults

    def _save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = self._read_raw()
        data.update({
            "schema_version": 1,
            "always_approved": sorted(self.always_approved),
            "always_denied": sorted(self.always_denied),
            "session_approved": sorted(self.session_approved - self.always_approved),
        })
        import fcntl
        with open(self._perm_file, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)

    def _read_raw(self) -> dict:
        if not self._perm_file.exists():
            return {"schema_version": 1, "always_approved": [], "always_denied": [],
                    "session_approved": [], "audit_log": []}
        try:
            import fcntl
            with open(self._perm_file) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                d = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            return d
        except Exception:
            return {"schema_version": 1, "always_approved": [], "always_denied": [],
                    "session_approved": [], "audit_log": []}

    def is_approved(self, tool_name: str) -> bool:
        return tool_name in self.session_approved and tool_name not in self.always_denied

    def is_denied(self, tool_name: str) -> bool:
        return tool_name in self.always_denied

    def check_permission(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if self.is_denied(tool_name):
            console.print(f"  [red]✗ {tool_name} is in your always-denied list[/red]")
            return False
        if self.is_approved(tool_name):
            return True

        console.print()
        console.print(f"  [yellow bold]⚠ Claude wants to use [white]{tool_name}[/white][/yellow bold]")
        _print_tool_preview(tool_name, tool_input)

        answer = Prompt.ask(
            "  [dim]Allow?[/dim]",
            choices=["y", "a", "n", "N"],
            default="y",
        )

        decision = "deny"
        if answer == "a":
            self.session_approved.add(tool_name)
            self.always_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (always)[/green]")
            decision = "allow_always"
        elif answer == "y":
            self.session_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (this session)[/green]")
            decision = "allow_session"
        elif answer == "N":
            self.always_denied.add(tool_name)
            self._save()
            console.print(f"  [red]✗ {tool_name} denied (always)[/red]")
            decision = "deny_always"
        else:
            console.print(f"  [red]✗ {tool_name} denied[/red]")
            decision = "deny_session"

        self.append_audit(
            tool=tool_name,
            input_preview=_input_preview(tool_name, tool_input),
            decision=decision,
            backend="api",
        )
        return decision.startswith("allow")

    def approve(self, tool_names: list[str], always: bool = False) -> None:
        for name in tool_names:
            self.session_approved.add(name)
            if always:
                self.always_approved.add(name)
        if always:
            self._save()

    def deny(self, tool_names: list[str]) -> None:
        for name in tool_names:
            self.always_denied.add(name)
            self.session_approved.discard(name)
        self._save()

    def clear_session_approved(self) -> None:
        self.session_approved = set(SAFE_TOOLS) | self.always_approved

    def reset(self) -> None:
        self.session_approved = set(SAFE_TOOLS)
        self.always_approved = set(SAFE_TOOLS)
        self.always_denied = set()
        self._save()

    def status(self) -> tuple[set[str], set[str]]:
        return self.session_approved.copy(), self.always_approved.copy()

    def append_audit(self, tool: str, input_preview: str, decision: str, backend: str) -> None:
        """Append an audit log entry to permissions.json."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "input_hash": hashlib.sha256(input_preview.encode()).hexdigest()[:16],
            "input_preview": input_preview[:200],
            "decision": decision,
            "backend": backend,
        }
        self._config_dir.mkdir(parents=True, exist_ok=True)
        import fcntl
        with open(self._perm_file, "r+" if self._perm_file.exists() else "w+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                data = json.load(f)
            except Exception:
                data = {"schema_version": 1, "always_approved": [], "always_denied": [],
                        "session_approved": [], "audit_log": []}
            data.setdefault("audit_log", []).append(entry)
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
            fcntl.flock(f, fcntl.LOCK_UN)


def _input_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return tool_input.get("command", "")[:200]
    if tool_name in ("Write", "Edit", "Read"):
        return tool_input.get("file_path", "")
    return str(tool_input)[:200]


def _print_tool_preview(tool_name: str, tool_input: dict[str, Any]) -> None:
    if tool_name == "Bash":
        console.print(f"    [dim]$[/dim] {tool_input.get('command', '')[:200]}")
    elif tool_name == "Write":
        fp = tool_input.get("file_path", "")
        lines = tool_input.get("content", "").count("\n") + 1
        console.print(f"    [dim]Create/overwrite[/dim] {fp} [dim]({lines} lines)[/dim]")
    elif tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:80]
        console.print(f"    [dim]Edit[/dim] {fp}")
        console.print(f"    [dim]Replace:[/dim] {old}...")
    elif tool_name == "Read":
        console.print(f"    [dim]Read[/dim] {tool_input.get('file_path', '')}")
    elif tool_name == "Glob":
        console.print(f"    [dim]Pattern:[/dim] {tool_input.get('pattern', '')}")
    elif tool_name == "Grep":
        console.print(f"    [dim]Search:[/dim] {tool_input.get('pattern', '')} "
                      f"[dim]in[/dim] {tool_input.get('path', '.')}")
    else:
        for k, v in list(tool_input.items())[:3]:
            console.print(f"    [dim]{k}:[/dim] {str(v)[:80]}")
    console.print("    [dim][y]es once  [a]lways  [n]o once  [N]ever[/dim]")
