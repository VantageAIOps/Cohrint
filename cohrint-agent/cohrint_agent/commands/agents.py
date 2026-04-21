"""commands.agents — list / add / remove Claude subagents (agents/*.md)."""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import add_agent, remove_agent


def _run_add(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent agents add")
    parser.add_argument("source", help="Path to an agent .md file")
    parser.add_argument("--name", help="Override destination filename")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = add_agent(ns.source, name=ns.name, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def _run_remove(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent agents remove")
    parser.add_argument("name")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = remove_agent(ns.name, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("agents"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list("agents", "agent", rest, empty_hint="No agents defined.")
    if sub == "add":
        return _run_add(rest)
    if sub in ("remove", "rm"):
        return _run_remove(rest)
    sys.stderr.write(f"cohrint-agent agents: unknown subcommand '{sub}'\n")
    print(render_verb_help("agents"))
    return 2
