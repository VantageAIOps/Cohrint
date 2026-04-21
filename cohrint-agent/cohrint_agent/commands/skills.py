"""commands.skills — list / add / remove skills (Claude skills + Codex rules)."""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import add_skill, remove_skill


def _run_add(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent skills add")
    parser.add_argument("source", help="Path to a skill directory (claude) or .md file (codex)")
    parser.add_argument("--name", help="Override destination name")
    parser.add_argument("--backend", choices=("claude", "codex"), default="claude")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = add_skill(ns.source, name=ns.name, backend=ns.backend, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def _run_remove(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent skills remove")
    parser.add_argument("name")
    parser.add_argument("--backend", choices=("claude", "codex"), default="claude")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = remove_skill(ns.name, backend=ns.backend, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("skills"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list("skills", "skill", rest, empty_hint="No skills installed.")
    if sub == "add":
        return _run_add(rest)
    if sub in ("remove", "rm"):
        return _run_remove(rest)
    sys.stderr.write(f"cohrint-agent skills: unknown subcommand '{sub}'\n")
    print(render_verb_help("skills"))
    return 2
