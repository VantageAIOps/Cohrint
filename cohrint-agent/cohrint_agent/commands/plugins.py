"""commands.plugins — list / enable / disable Claude Code plugins.

Gemini and Codex have no plugin concept — those backends error out.
"""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import toggle_plugin


def _run_toggle(rest: list[str], *, enabled: bool) -> int:
    parser = argparse.ArgumentParser(
        prog=f"cohrint-agent plugins {'enable' if enabled else 'disable'}"
    )
    parser.add_argument("name", help="Plugin id (e.g. foo@market)")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = toggle_plugin(ns.name, enabled=enabled, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("plugins"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list(
            "plugins",
            "plugin",
            rest,
            empty_hint="No plugins enabled. (Codex and Gemini have no plugin concept.)",
        )
    if sub == "enable":
        return _run_toggle(rest, enabled=True)
    if sub == "disable":
        return _run_toggle(rest, enabled=False)
    sys.stderr.write(f"cohrint-agent plugins: unknown subcommand '{sub}'\n")
    print(render_verb_help("plugins"))
    return 2
