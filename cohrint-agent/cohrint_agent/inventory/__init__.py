"""
inventory — unified filesystem scanners for each backend's resources.

Design: one module per backend (``claude.py``, ``gemini.py``, ``codex.py``),
each exposing a set of ``list_*`` functions that return a flat list of
``Resource`` records. The ``scan()`` entrypoint at this level fans out to
each backend and merges results, so callers never have to know which
backend stores what.

Each scan has a 500ms default timeout (implemented inside each scanner)
to keep the REPL responsive on slow mounts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ResourceType = Literal["mcp", "plugin", "skill", "agent", "hook", "permission"]
Scope = Literal["global", "project"]
Backend = Literal["claude", "gemini", "codex"]


@dataclass
class Resource:
    """One entry in the inventory listing."""

    name: str
    type: ResourceType
    backend: Backend
    scope: Scope
    path: str
    enabled: bool = True
    # Free-form details rendered in the `info` view (version, description, etc.)
    detail: dict[str, str] = field(default_factory=dict)


def scan(
    resource_type: ResourceType,
    *,
    backend: Backend | Literal["all"] = "all",
) -> list[Resource]:
    """Return every resource of ``resource_type`` across the selected backend(s)."""
    from . import claude as _claude
    from . import codex as _codex
    from . import gemini as _gemini

    scanners = {
        "claude": _claude,
        "gemini": _gemini,
        "codex": _codex,
    }
    targets = scanners.items() if backend == "all" else [(backend, scanners[backend])]

    out: list[Resource] = []
    for _name, mod in targets:
        fn = getattr(mod, f"list_{resource_type}s", None)
        if fn is None:
            # Backend doesn't expose this resource type (e.g. gemini has no plugins).
            continue
        try:
            out.extend(fn())
        except Exception:  # noqa: BLE001 — scanner failures must not kill the dispatcher
            # A malformed config or permission error on one backend shouldn't
            # blank out the whole list. Skip and continue.
            continue
    return out


__all__ = ["Resource", "ResourceType", "Scope", "Backend", "scan"]
