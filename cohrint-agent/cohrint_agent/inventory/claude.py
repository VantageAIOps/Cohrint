"""
inventory.claude — scans Claude Code config paths.

Paths we read (never write):
- ``~/.claude/settings.json`` — hooks, permissions, global
- ``.claude/settings.json`` / ``.claude/settings.local.json`` — project overrides
- ``~/.claude/skills/<name>/`` — global skills (directory per skill)
- ``.claude/skills/<name>/`` — project skills
- ``~/.claude/agents/<name>.md`` — global subagents
- ``.claude/agents/<name>.md`` — project subagents
- ``~/.claude.json`` — mcpServers registry

All reads are best-effort: missing files / unparseable JSON yield empty
results, never exceptions. This matches the Claude Code convention of
"no config = default everything".
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
    """Read mcpServers table from ~/.claude.json (global) and .claude.json (project)."""
    out: list[Resource] = []
    for scope, root in (("global", _home() / ".claude.json"), ("project", _cwd() / ".claude.json")):
        data = _read_json(root)
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
                if "args" in cfg:
                    detail["args"] = " ".join(map(str, cfg.get("args") or []))
                if "url" in cfg:
                    detail["url"] = str(cfg["url"])
            out.append(
                Resource(
                    name=str(name),
                    type="mcp",
                    backend="claude",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(root),
                    detail=detail,
                )
            )
    return out


def list_skills() -> list[Resource]:
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".claude" / "skills"),
        ("project", _cwd() / ".claude" / "skills"),
    ):
        if not base.exists() or not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            detail: dict[str, str] = {}
            if skill_md.exists():
                # First 200 chars of description from frontmatter if present
                try:
                    head = skill_md.read_text(encoding="utf-8", errors="replace")[:800]
                    for line in head.splitlines():
                        line = line.strip()
                        if line.startswith("description:"):
                            detail["description"] = line.split(":", 1)[1].strip()[:200]
                            break
                except OSError:
                    pass
            out.append(
                Resource(
                    name=child.name,
                    type="skill",
                    backend="claude",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(child),
                    detail=detail,
                )
            )
    return out


def list_agents() -> list[Resource]:
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".claude" / "agents"),
        ("project", _cwd() / ".claude" / "agents"),
    ):
        if not base.exists() or not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_file() or child.suffix != ".md":
                continue
            out.append(
                Resource(
                    name=child.stem,
                    type="agent",
                    backend="claude",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(child),
                )
            )
    return out


def list_plugins() -> list[Resource]:
    """Claude Code plugins — enabledPlugins in settings.json."""
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".claude" / "settings.json"),
        ("project", _cwd() / ".claude" / "settings.json"),
    ):
        data = _read_json(base)
        if not isinstance(data, dict):
            continue
        plugins = data.get("enabledPlugins") or {}
        if not isinstance(plugins, dict):
            continue
        for name, enabled in plugins.items():
            out.append(
                Resource(
                    name=str(name),
                    type="plugin",
                    backend="claude",
                    scope=scope,  # type: ignore[arg-type]
                    path=str(base),
                    enabled=bool(enabled),
                )
            )
    return out


def list_hooks() -> list[Resource]:
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".claude" / "settings.json"),
        ("project", _cwd() / ".claude" / "settings.json"),
    ):
        data = _read_json(base)
        if not isinstance(data, dict):
            continue
        hooks_root = data.get("hooks")
        if not isinstance(hooks_root, dict):
            continue
        for event_name, groups in hooks_root.items():
            if not isinstance(groups, list):
                continue
            for idx, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                matcher = str(group.get("matcher") or "*")
                entries = group.get("hooks") or []
                if not isinstance(entries, list):
                    continue
                for j, entry in enumerate(entries):
                    if not isinstance(entry, dict):
                        continue
                    out.append(
                        Resource(
                            name=f"{event_name}[{idx}.{j}]",
                            type="hook",
                            backend="claude",
                            scope=scope,  # type: ignore[arg-type]
                            path=str(base),
                            detail={
                                "event": str(event_name),
                                "matcher": matcher,
                                "type": str(entry.get("type") or ""),
                                "command": str(entry.get("command") or entry.get("prompt") or "")[:200],
                            },
                        )
                    )
    return out


def list_permissions() -> list[Resource]:
    out: list[Resource] = []
    for scope, base in (
        ("global", _home() / ".claude" / "settings.json"),
        ("project", _cwd() / ".claude" / "settings.json"),
    ):
        data = _read_json(base)
        if not isinstance(data, dict):
            continue
        perm = data.get("permissions")
        if not isinstance(perm, dict):
            continue
        for kind in ("allow", "deny", "ask"):
            rules = perm.get(kind) or []
            if not isinstance(rules, list):
                continue
            for rule in rules:
                out.append(
                    Resource(
                        name=str(rule),
                        type="permission",
                        backend="claude",
                        scope=scope,  # type: ignore[arg-type]
                        path=str(base),
                        detail={"kind": kind},
                    )
                )
    return out
