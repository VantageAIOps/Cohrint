"""commands.settings_cmd — show merged settings.json (read-only in Phase 2)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.syntax import Syntax

from . import render_verb_help

console = Console()


def _home() -> Path:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001
        return Path.home()


def _read(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _merge(base: dict, overlay: dict) -> dict:
    """Shallow merge — overlay keys replace base keys. Mirrors Claude Code's load order."""
    out = dict(base)
    out.update(overlay)
    return out


def _show() -> int:
    user = _read(_home() / ".claude" / "settings.json") or {}
    project = _read(Path.cwd() / ".claude" / "settings.json") or {}
    local = _read(Path.cwd() / ".claude" / "settings.local.json") or {}

    merged = _merge(_merge(user, project), local)

    if not merged:
        console.print("[dim]No settings.json found at any scope.[/dim]")
        return 0

    console.print("[bold]Merged settings[/bold]  [dim](user → project → local)[/dim]")
    pretty = json.dumps(merged, indent=2, sort_keys=True)
    console.print(Syntax(pretty, "json", theme="monokai", background_color="default"))
    return 0


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("settings"))
        return 0
    sub = argv[0]
    if sub == "show":
        return _show()
    sys.stderr.write(f"cohrint-agent settings: unknown subcommand '{sub}'\n")
    print(render_verb_help("settings"))
    return 2
