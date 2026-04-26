"""commands.guardrails — status / on / off toggles."""
from __future__ import annotations

import sys

from rich.console import Console

from . import render_verb_help
from ..guardrails import KINDS, get_settings, set_kind

console = Console()


def _render_status() -> None:
    s = get_settings()
    console.print("[bold]Guardrails[/bold]")
    mark = lambda on: "[green]on[/green]" if on else "[red]off[/red]"
    console.print(f"  recommendation: {mark(s.recommendation)}")
    console.print(f"  hallucination:  {mark(s.hallucination)}")


def _toggle(argv: list[str], *, enabled: bool) -> int:
    kind = argv[0] if argv else "all"
    if kind not in (*KINDS, "all"):
        sys.stderr.write(f"cohrint-agent guardrails: unknown kind '{kind}'. "
                         f"Valid: {', '.join(KINDS)} or 'all'\n")
        return 2
    set_kind(kind, enabled=enabled)
    action = "enabled" if enabled else "disabled"
    console.print(f"[dim]{action} {kind} guardrail(s).[/dim]")
    _render_status()
    return 0


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("guardrails"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "status":
        _render_status()
        return 0
    if sub == "on":
        return _toggle(rest, enabled=True)
    if sub == "off":
        return _toggle(rest, enabled=False)
    sys.stderr.write(f"cohrint-agent guardrails: unknown subcommand '{sub}'\n")
    print(render_verb_help("guardrails"))
    return 2
