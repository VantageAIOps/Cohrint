"""
subcommands.py — argv dispatcher that runs BEFORE argparse in cli.main().

Rule: if ``argv[1]`` is one of our registered verbs, we handle the invocation
ourselves and exit. Otherwise control falls back to the existing cli.main()
argparse (which treats argv as a prompt). This preserves every existing
invocation: ``cohrint-agent "fix the bug"`` still routes to the prompt path.

Adding a verb: (1) extend ``commands.CATALOG`` for help text, (2) add a
``commands/<verb>.py`` with ``run(argv) -> int``, (3) register below.
"""
from __future__ import annotations

import importlib
import sys

from .commands import VERBS, render_catalog

# Map verb → module path. Modules lazy-imported to keep REPL startup fast.
_ROUTES: dict[str, str] = {
    "models": "cohrint_agent.commands.models",
    "mcp": "cohrint_agent.commands.mcp",
    "plugins": "cohrint_agent.commands.plugins",
    "skills": "cohrint_agent.commands.skills",
    "agents": "cohrint_agent.commands.agents",
    "hooks": "cohrint_agent.commands.hooks",
    "permissions": "cohrint_agent.commands.permissions",
    "settings": "cohrint_agent.commands.settings_cmd",
    "exec": "cohrint_agent.commands.exec_cmd",
}

assert set(_ROUTES) == set(VERBS), "subcommands._ROUTES drifted from commands.CATALOG"


def is_subcommand(argv: list[str]) -> bool:
    """True iff argv[1] (not argv[0], which is the program name) is a verb."""
    if len(argv) < 2:
        return False
    first = argv[1]
    # Bare `cohrint-agent help` prints the catalog.
    if first in ("help", "--help-verbs"):
        return True
    return first in _ROUTES


def dispatch(argv: list[str]) -> int:
    """Resolve argv[1] to a verb and hand off. Returns exit code."""
    if len(argv) < 2:
        print(render_catalog())
        return 0
    first = argv[1]
    if first in ("help", "--help-verbs"):
        print(render_catalog())
        return 0
    if first not in _ROUTES:
        sys.stderr.write(
            f"cohrint-agent: unknown verb '{first}'. "
            f"Try `cohrint-agent help`.\n"
        )
        return 2
    module_path = _ROUTES[first]
    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        sys.stderr.write(f"cohrint-agent: failed to load '{first}': {e}\n")
        return 1
    run_fn = getattr(mod, "run", None)
    if run_fn is None:
        sys.stderr.write(f"cohrint-agent: '{first}' module is missing run()\n")
        return 1
    return int(run_fn(argv[2:]))
