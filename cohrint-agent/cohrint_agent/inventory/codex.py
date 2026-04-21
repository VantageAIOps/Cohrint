"""
inventory.codex — scans OpenAI Codex CLI config paths.

Codex root: ``~/.codex/`` (override with ``CODEX_HOME``), project: ``.codex/``.
Config format is **TOML** (config.toml), distinct from Claude/Gemini's JSON.

Resources we surface:
- MCP: ``[mcp_servers]`` table in config.toml if present (undocumented as of
  this writing — we scan defensively).
- Skills: map to ``rules/`` directory (closest conceptual cousin).
- Agents: parsed sections inside ``~/.codex/AGENTS.md`` — each ``##`` header
  becomes one agent entry. Degrades to a single "AGENTS.md" row if no
  sections are found.
- Plugins / hooks / permissions: not supported by Codex — return empty.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import Resource

# TOML parser: stdlib tomllib on 3.11+, tomli backport on 3.9/3.10.
try:
    import tomllib as _toml  # type: ignore[import-not-found]
except ModuleNotFoundError:
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _toml = None  # type: ignore[assignment]


def _home() -> Path:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001
        return Path.home()


def _cwd() -> Path:
    return Path.cwd()


def _codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        try:
            return Path(override).expanduser().resolve()
        except (OSError, RuntimeError):
            pass
    return _home() / ".codex"


def _read_toml(path: Path) -> dict | None:
    if _toml is None:
        return None
    try:
        with path.open("rb") as f:
            return _toml.load(f)
    except (FileNotFoundError, OSError) as _:
        return None
    except Exception:  # noqa: BLE001 — malformed TOML must not crash scanner
        return None


def list_mcps() -> list[Resource]:
    out: list[Resource] = []
    for scope, base in (
        ("global", _codex_home() / "config.toml"),
        ("project", _cwd() / ".codex" / "config.toml"),
    ):
        data = _read_toml(base)
        if not isinstance(data, dict):
            continue
        servers = data.get("mcp_servers") or data.get("mcpServers") or {}
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
                    backend="codex",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(base),
                    detail=detail,
                )
            )
    return out


def list_skills() -> list[Resource]:
    """Codex ``rules/`` directory — one resource per rules file."""
    out: list[Resource] = []
    for scope, base in (
        ("global", _codex_home() / "rules"),
        ("project", _cwd() / ".codex" / "rules"),
    ):
        if not base.exists() or not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_file():
                continue
            out.append(
                Resource(
                    name=child.stem,
                    type="skill",
                    backend="codex",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(child),
                    detail={"format": "rule"},
                )
            )
    return out


_AGENT_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def list_agents() -> list[Resource]:
    """Parse AGENTS.md and return one entry per ``## Heading`` section.

    Falls back to a single-row entry if no sections exist or the file is
    a flat instruction doc.
    """
    out: list[Resource] = []
    for scope, base in (
        ("global", _codex_home() / "AGENTS.md"),
        ("project", _cwd() / "AGENTS.md"),
    ):
        if not base.exists() or not base.is_file():
            continue
        try:
            text = base.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        headers = _AGENT_HEADER.findall(text)
        if headers:
            for h in headers:
                out.append(
                    Resource(
                        name=h.strip(),
                        type="agent",
                        backend="codex",
                        scope=scope,  # type: ignore[arg-type]
                        path=str(base),
                        detail={"container": "AGENTS.md section"},
                    )
                )
        else:
            out.append(
                Resource(
                    name="AGENTS.md",
                    type="agent",
                    backend="codex",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(base),
                    detail={"container": "single-file"},
                )
            )
    return out


def list_plugins() -> list[Resource]:
    """Codex has no plugin concept."""
    return []


def list_hooks() -> list[Resource]:
    """Codex has no hooks concept."""
    return []


def list_permissions() -> list[Resource]:
    """Codex permissions are implicit via sandbox mode; no list surface."""
    return []
