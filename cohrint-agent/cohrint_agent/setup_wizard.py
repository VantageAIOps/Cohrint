"""
setup_wizard.py — First-run tiered permission wizard.

Shown when a user runs cohrint-agent without an API key and
auto_detect_backend() returns 'claude' (or --backend claude is passed).

TIER_TOOLS maps tier number → tools to auto-approve.
Bash is NEVER in any tier — always requires per-call hook approval.
"""
from __future__ import annotations

import fcntl
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
    from .process_safety import safe_config_dir
    return config_dir or safe_config_dir()


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
    """Load config.json, returning defaults for missing keys.

    Values are shape-validated: a tampered config.json carrying wrong
    types (e.g. ``hook_fail_policy: ["deny"]``) must fall back to the
    default rather than propagate into the bash hook's string compare
    (T-INPUT.config_shape)."""
    cfg_path = _config_dir(config_dir) / _CONFIG_FILE
    defaults: dict = {"hook_fail_policy": "deny", "default_tier": None}
    if not cfg_path.exists():
        return defaults
    try:
        data = json.loads(cfg_path.read_text())
    except Exception:
        return defaults
    if not isinstance(data, dict):
        return defaults
    out = dict(defaults)
    hfp = data.get("hook_fail_policy")
    if hfp in ("allow", "deny"):
        out["hook_fail_policy"] = hfp
    dt = data.get("default_tier")
    if isinstance(dt, int) and 1 <= dt <= 4:
        out["default_tier"] = dt
    return out


def write_config(data: dict, config_dir: Path | None = None) -> None:
    """Write (merge) keys into config.json.

    Concurrent cohrint-agent invocations (REPL + one-shot in parallel) can
    race read-modify-write and clobber each other's keys. Serialize via
    flock on a sidecar lockfile, read-merge-rename atomically under the
    lock (T-CONCUR.config_rmw).
    """
    cd = _config_dir(config_dir)
    cd.mkdir(parents=True, exist_ok=True)
    cfg_path = cd / _CONFIG_FILE
    lockfile = cfg_path.with_suffix(cfg_path.suffix + ".lock")
    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    from .process_safety import open_lockfile
    with open_lockfile(lockfile) as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            existing: dict = {}
            if cfg_path.exists():
                try:
                    # O_NOFOLLOW: refuse to follow a config.json symlink
                    # pointed at an attacker target.
                    fd = os.open(cfg_path, os.O_RDONLY | os.O_NOFOLLOW)
                    with os.fdopen(fd, "r") as f:
                        existing = json.loads(f.read())
                except (OSError, ValueError):
                    existing = {}
            if not isinstance(existing, dict):
                existing = {}
            existing.update(data)
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            fd = os.open(
                tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC, 0o600
            )
            with os.fdopen(fd, "w") as f:
                json.dump(existing, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, cfg_path)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    try:
        os.unlink(lockfile)
    except OSError:
        pass


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
    console.print("  [bold]Cohrint Agent — Tool Permissions[/bold]")
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
