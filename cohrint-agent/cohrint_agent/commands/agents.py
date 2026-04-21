"""commands.agents — list Claude agents/*.md + Codex AGENTS.md sections."""
from __future__ import annotations

import sys

from . import render_verb_help
from ._list_helper import run_list


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("agents"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list("agents", "agent", rest, empty_hint="No agents defined.")
    sys.stderr.write(f"cohrint-agent agents: unknown subcommand '{sub}'\n")
    print(render_verb_help("agents"))
    return 2
