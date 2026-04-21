"""
_list_helper — shared rendering for every `<verb> list` subcommand.

Each inventory Resource is printed in a unified table. An ``--interactive``
flag opens a questionary selector; pressing Enter prints the ``info`` view
for the chosen row.
"""
from __future__ import annotations

import argparse
import json

from rich.console import Console
from rich.table import Table

from ..inventory import Resource, ResourceType, scan
from ..tui import select_one

console = Console()


def _render_table(resources: list[Resource], empty_hint: str) -> None:
    if not resources:
        console.print(f"[dim]{empty_hint}[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("NAME")
    table.add_column("SCOPE")
    table.add_column("BACKEND")
    table.add_column("ENABLED")
    table.add_column("PATH", style="dim", overflow="fold")
    for r in resources:
        table.add_row(
            r.name,
            r.scope,
            r.backend,
            "yes" if r.enabled else "no",
            r.path,
        )
    console.print(table)


def _render_info(r: Resource) -> None:
    console.print(f"[bold]{r.name}[/bold]  [dim]({r.type})[/dim]")
    console.print(f"  backend: {r.backend}")
    console.print(f"  scope:   {r.scope}")
    console.print(f"  path:    {r.path}")
    console.print(f"  enabled: {r.enabled}")
    if r.detail:
        console.print("  detail:")
        for k, v in r.detail.items():
            console.print(f"    {k}: {v}")


def run_list(
    verb: str,
    resource_type: ResourceType,
    argv: list[str],
    *,
    empty_hint: str = "(none)",
) -> int:
    """Shared entrypoint for `<verb> list` subcommands."""
    parser = argparse.ArgumentParser(prog=f"cohrint-agent {verb} list")
    parser.add_argument(
        "--backend",
        choices=("all", "claude", "gemini", "codex"),
        default="all",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Open a TUI selector — press Enter on a row for detail.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON (for scripts).")
    ns = parser.parse_args(argv)

    resources = scan(resource_type, backend=ns.backend)

    if ns.json:
        payload = [
            {
                "name": r.name,
                "type": r.type,
                "backend": r.backend,
                "scope": r.scope,
                "path": r.path,
                "enabled": r.enabled,
                "detail": r.detail,
            }
            for r in resources
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if ns.interactive:
        labels = [
            f"{r.name}  [{r.scope}/{r.backend}]" for r in resources
        ]
        chosen_label = select_one(f"Select a {resource_type}:", labels)
        if chosen_label is None:
            return 0
        idx = labels.index(chosen_label)
        _render_info(resources[idx])
        return 0

    _render_table(resources, empty_hint=empty_hint)
    return 0
