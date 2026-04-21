"""commands.mcp — list / add / remove MCP servers across backends."""
from __future__ import annotations

import argparse
import sys

from . import render_verb_help
from ._list_helper import run_list
from ..writers import add_mcp, remove_mcp


def _run_add(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent mcp add")
    parser.add_argument("name")
    parser.add_argument("--backend", choices=("claude", "gemini", "codex"), default="claude")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    parser.add_argument("--command", help="Command to run (stdio MCP)")
    parser.add_argument("--url", help="HTTP(S) URL (remote MCP)")
    parser.add_argument("--arg", action="append", default=[], help="Command arg (repeatable)")
    ns = parser.parse_args(rest)
    result = add_mcp(
        ns.name,
        backend=ns.backend,
        scope=ns.scope,
        command=ns.command,
        url=ns.url,
        args=ns.arg,
    )
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def _run_remove(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cohrint-agent mcp remove")
    parser.add_argument("name")
    parser.add_argument("--backend", choices=("claude", "gemini", "codex"), default="claude")
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    ns = parser.parse_args(rest)
    result = remove_mcp(ns.name, backend=ns.backend, scope=ns.scope)
    out = sys.stdout if result.ok else sys.stderr
    out.write(result.message + "\n")
    return 0 if result.ok else 2


def run(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(render_verb_help("mcp"))
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "list":
        return run_list("mcp", "mcp", rest, empty_hint="No MCP servers configured.")
    if sub == "add":
        return _run_add(rest)
    if sub in ("remove", "rm"):
        return _run_remove(rest)
    sys.stderr.write(f"cohrint-agent mcp: unknown subcommand '{sub}'\n")
    print(render_verb_help("mcp"))
    return 2
