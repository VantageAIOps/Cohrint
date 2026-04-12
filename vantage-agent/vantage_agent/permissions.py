"""
permissions.py — Per-tool permission management.

Tracks which tools the user has approved. Prompts for unapproved tools.
Persists approved tools across sessions in ~/.vantage-agent/permissions.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Prompt
from rich.text import Text

from .tools import SAFE_TOOLS

console = Console()

_STATE_DIR = Path.home() / ".vantage-agent"
_PERM_FILE = _STATE_DIR / "permissions.json"


class PermissionManager:
    """Manages per-tool approval state."""

    def __init__(self) -> None:
        # Tools approved for this session (+ persisted "always" approvals)
        self.session_approved: set[str] = set(SAFE_TOOLS)
        self.always_approved: set[str] = set(SAFE_TOOLS)
        self._load()

    def _load(self) -> None:
        """Load persisted always-approved tools."""
        if _PERM_FILE.exists():
            try:
                data = json.loads(_PERM_FILE.read_text())
                # schema_version missing → treat as v0 (backwards-compatible)
                _schema = data.get("schema_version", 0)  # noqa: F841
                saved = set(data.get("always_approved", []))
                self.always_approved |= saved
                self.session_approved |= saved
            except Exception:
                pass

    def _save(self) -> None:
        """Persist always-approved tools."""
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _PERM_FILE.write_text(
            json.dumps(
                {"schema_version": 1, "always_approved": sorted(self.always_approved)},
                indent=2,
            )
        )

    def is_approved(self, tool_name: str) -> bool:
        return tool_name in self.session_approved

    def check_permission(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> bool:
        """
        Check if a tool is approved. If not, prompt the user.
        Returns True if approved, False if denied.
        """
        if self.is_approved(tool_name):
            return True

        # Show the tool call details
        console.print()
        console.print(f"  [yellow bold]⚠ Claude wants to use [white]{tool_name}[/white][/yellow bold]")
        _print_tool_preview(tool_name, tool_input)

        answer = Prompt.ask(
            "  [dim]Allow?[/dim]",
            choices=["y", "a", "n"],
            default="y",
        )

        if answer == "a":
            self.session_approved.add(tool_name)
            self.always_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (always)[/green]")
            return True
        elif answer == "y":
            self.session_approved.add(tool_name)
            console.print(f"  [green]✓ {tool_name} approved (this session)[/green]")
            return True
        else:
            console.print(f"  [red]✗ {tool_name} denied[/red]")
            return False

    def approve(self, tool_names: list[str], always: bool = False) -> None:
        """Programmatically approve tools (e.g. from /allow command)."""
        for name in tool_names:
            self.session_approved.add(name)
            if always:
                self.always_approved.add(name)
        if always:
            self._save()

    def reset(self) -> None:
        """Reset to safe defaults."""
        self.session_approved = set(SAFE_TOOLS)
        self.always_approved = set(SAFE_TOOLS)
        self._save()

    def status(self) -> tuple[set[str], set[str]]:
        """Return (session_approved, always_approved)."""
        return self.session_approved.copy(), self.always_approved.copy()


def _print_tool_preview(tool_name: str, tool_input: dict[str, Any]) -> None:
    """Print a concise preview of the tool call."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        console.print(f"    [dim]$[/dim] {cmd[:200]}")
    elif tool_name == "Write":
        fp = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        lines = content.count("\n") + 1
        console.print(f"    [dim]Create/overwrite[/dim] {fp} [dim]({lines} lines)[/dim]")
    elif tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:80]
        console.print(f"    [dim]Edit[/dim] {fp}")
        console.print(f"    [dim]Replace:[/dim] {old}...")
    elif tool_name == "Read":
        fp = tool_input.get("file_path", "")
        console.print(f"    [dim]Read[/dim] {fp}")
    elif tool_name == "Glob":
        pat = tool_input.get("pattern", "")
        console.print(f"    [dim]Pattern:[/dim] {pat}")
    elif tool_name == "Grep":
        pat = tool_input.get("pattern", "")
        path = tool_input.get("path", ".")
        console.print(f"    [dim]Search:[/dim] {pat} [dim]in[/dim] {path}")
    else:
        for k, v in list(tool_input.items())[:3]:
            val = str(v)[:80]
            console.print(f"    [dim]{k}:[/dim] {val}")

    console.print("    [dim][y]es once  [a]lways  [n]o[/dim]")
