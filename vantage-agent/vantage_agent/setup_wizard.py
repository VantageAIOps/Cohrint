"""
setup_wizard.py — First-run tiered permission wizard.

Shown when a user runs vantageai-agent without an API key and
auto_detect_backend() returns 'claude' (or --backend claude is passed).

TIER_TOOLS maps tier number → tools to auto-approve.
Bash is NEVER in any tier — always requires per-call hook approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.prompt import Prompt

if TYPE_CHECKING:
    from .permissions import PermissionManager

console = Console()

_CONFIG_FILE = "config.json"

# Tools auto-approved per tier. Bash intentionally absent from all tiers.
TIER_TOOLS: dict[int, list[str]] = {
    1: ["Read", "Glob", "Grep"],
    2: ["Read", "Glob", "Grep", "Edit", "Write"],
    3: ["Read", "Glob", "Grep", "Edit", "Write"],  # Bash still excluded
}


def _config_dir(config_dir: Path | None) -> Path:
    return config_dir or Path(os.environ.get("VANTAGE_CONFIG_DIR", Path.home() / ".vantage-agent"))


def needs_setup(config_dir: Path | None = None) -> bool:
    """Return True if no tier has been configured yet."""
    cd = _config_dir(config_dir)
    cfg_path = cd / _CONFIG_FILE
    # If permissions.json already exists the user has run before — skip wizard
    if (cd / "permissions.json").exists():
        return False
    if not cfg_path.exists():
        return True
    try:
        data = json.loads(cfg_path.read_text())
        return "default_tier" not in data
    except Exception:
        return True


def get_config(config_dir: Path | None = None) -> dict:
    """Load config.json, returning defaults for missing keys."""
    cfg_path = _config_dir(config_dir) / _CONFIG_FILE
    defaults = {"hook_fail_policy": "allow", "default_tier": None}
    if not cfg_path.exists():
        return defaults
    try:
        data = json.loads(cfg_path.read_text())
        return {**defaults, **data}
    except Exception:
        return defaults


def write_config(data: dict, config_dir: Path | None = None) -> None:
    """Write (merge) keys into config.json."""
    cd = _config_dir(config_dir)
    cd.mkdir(parents=True, exist_ok=True)
    cfg_path = cd / _CONFIG_FILE
    existing: dict = {}
    if cfg_path.exists():
        try:
            existing = json.loads(cfg_path.read_text())
        except Exception:
            pass
    existing.update(data)
    cfg_path.write_text(json.dumps(existing, indent=2))


def apply_tier(tier: int, permissions: "PermissionManager") -> None:
    """Auto-approve the tools for the chosen tier. Bash always excluded."""
    tools = [t for t in TIER_TOOLS.get(tier, TIER_TOOLS[1]) if t != "Bash"]
    permissions.approve(tools, always=True)


def run_setup_wizard(permissions: "PermissionManager", config_dir: Path | None = None) -> int:
    """
    Show the interactive tier selection menu.
    Returns the chosen tier (1-4).
    """
    console.print()
    console.print("  [bold]Vantage Agent — Tool Permissions[/bold]")
    console.print()
    console.print("  Claude Code CLI detected. Select what Claude is allowed to do:")
    console.print()
    console.print("  [bold][1][/bold] Read-only   Read, Glob, Grep                    [dim](safe, auto-approve)[/dim]")
    console.print("  [bold][2][/bold] Standard    + Edit, Write                       [dim](file edits, auto-approve)[/dim]")
    console.print("  [bold][3][/bold] Full        + Bash [dim](shell commands always ask per-call)[/dim]")
    console.print("  [bold][4][/bold] Custom      Choose tools individually")
    console.print()
    console.print("  [dim]Note: Bash is never auto-approved — it always asks before each command.[/dim]")
    console.print()

    choice = Prompt.ask("  Tier", choices=["1", "2", "3", "4"], default="2")
    tier = int(choice)

    if tier == 4:
        tier = _run_custom_tier(permissions)
    else:
        apply_tier(tier, permissions)
        console.print(f"  [green]✓ Tier {tier} applied[/green]")

    write_config({"default_tier": tier}, config_dir=config_dir)
    console.print()
    return tier


def _run_custom_tier(permissions: "PermissionManager") -> int:
    """Let user pick tools individually. Returns 4."""
    from .tools import TOOL_MAP
    console.print()
    console.print("  Auto-approve which tools? [dim](Bash always asks — not listed)[/dim]")
    tools = [t for t in sorted(TOOL_MAP.keys()) if t != "Bash"]
    approved = []
    for tool in tools:
        ans = Prompt.ask(f"    Auto-approve [bold]{tool}[/bold]?", choices=["y", "n"], default="y")
        if ans == "y":
            approved.append(tool)
    if approved:
        permissions.approve(approved, always=True)
        console.print(f"  [green]✓ Auto-approved: {', '.join(approved)}[/green]")
    return 4
