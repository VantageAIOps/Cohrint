"""
inventory.gemini — scans Gemini CLI config paths.

Gemini CLI stores user-level config under ~/.gemini/ and project-level
under .gemini/. The schema is not as standardised as Claude's; we read
settings.json if present and expose the pieces we recognise, returning
empty lists for types the backend doesn't support.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Resource


def _home() -> Path:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001
        return Path.home()


def _cwd() -> Path:
    return Path.cwd()


def _read_json(path: Path) -> dict | list | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def list_mcps() -> list[Resource]:
    """Gemini stores MCP servers in ~/.gemini/settings.json → mcpServers."""
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".gemini" / "settings.json"),
        ("project", _cwd() / ".gemini" / "settings.json"),
    ):
        data = _read_json(base)
        if not isinstance(data, dict):
            continue
        servers = data.get("mcpServers") or {}
        if not isinstance(servers, dict):
            continue
        for name, cfg in servers.items():
            detail: dict[str, str] = {}
            if isinstance(cfg, dict):
                if "command" in cfg:
                    detail["command"] = str(cfg["command"])
                if "url" in cfg:
                    detail["url"] = str(cfg["url"])
            out.append(
                Resource(
                    name=str(name),
                    type="mcp",
                    backend="gemini",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(base),
                    detail=detail,
                )
            )
    return out


def list_skills() -> list[Resource]:
    """Gemini has no native skills concept. Return empty."""
    return []


def list_agents() -> list[Resource]:
    """Gemini has no native agents concept."""
    return []


def list_plugins() -> list[Resource]:
    """Gemini CLI has no plugin marketplace yet."""
    return []


def list_hooks() -> list[Resource]:
    """Gemini has no hooks concept."""
    return []


def list_permissions() -> list[Resource]:
    """Gemini's permission model doesn't expose a list surface."""
    return []
