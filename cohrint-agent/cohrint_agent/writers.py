"""
writers — mutating helpers for backend config files.

Read-side scanners live in ``inventory/*``. This module owns the write side:
adding / removing MCP servers, toggling plugins, copying skills / agents.

Design:
- Each writer is a plain function ``(*args) -> WriteResult``.
- Returns a ``WriteResult`` (ok=True + message, or ok=False + error) instead
  of raising, so the CLI layer can render a consistent one-liner.
- Never clobbers unrelated keys: always read → mutate → write the full doc.
- Creates parent directories when needed. Writes atomically (tmp + rename)
  so a crash mid-write leaves the previous file intact.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Backend = Literal["claude", "gemini", "codex"]
Scope = Literal["global", "project"]

# Accept identifier-safe names only — this is both a UX guard (catches typos)
# and a security guard: TOML section headers and shell paths are built from
# these strings, and quoting TOML section names is non-trivial.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _safe_name(name: str) -> bool:
    return bool(name) and len(name) <= 128 and bool(_SAFE_NAME_RE.match(name))


def _toml_quote(value: str) -> str:
    """Quote a value for a TOML basic string."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


@dataclass
class WriteResult:
    ok: bool
    message: str


# ─────────────────────────────── paths ──────────────────────────────────

def _home() -> Path:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001
        return Path.home()


def _cwd() -> Path:
    return Path.cwd()


def _claude_mcp_file(scope: Scope) -> Path:
    return (_home() / ".claude.json") if scope == "global" else (_cwd() / ".claude.json")


def _claude_settings(scope: Scope) -> Path:
    base = _home() if scope == "global" else _cwd()
    return base / ".claude" / "settings.json"


def _gemini_settings(scope: Scope) -> Path:
    base = _home() if scope == "global" else _cwd()
    return base / ".gemini" / "settings.json"


def _codex_config() -> Path:
    """Resolve ~/.codex/config.toml, honoring CODEX_HOME only if contained in $HOME.

    A hostile process that sets CODEX_HOME=/etc could otherwise redirect our
    writes outside the user's home. We resolve symlinks and require the final
    path to sit under the real home directory before trusting it.
    """
    override = os.environ.get("CODEX_HOME")
    if override:
        try:
            candidate = Path(override).expanduser().resolve()
            home_resolved = _home().resolve()
            candidate.relative_to(home_resolved)
            return candidate / "config.toml"
        except (OSError, RuntimeError, ValueError):
            pass
    return _home() / ".codex" / "config.toml"


# ─────────────────────────── atomic read/write ──────────────────────────

def _read_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: Path, data: dict) -> None:
    """Write ``data`` to ``path`` atomically.

    - Preserves insertion order (no sort_keys) so round-trips are byte-stable.
    - Refuses to follow a pre-planted symlink at the tmp path (O_NOFOLLOW).
    - Preserves the original file's mode when it exists; otherwise 0o600.
    - Uses a PID-suffixed tmp name so concurrent writers don't collide.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".cohrint.{os.getpid()}.tmp")
    try:
        orig_mode = path.stat().st_mode & 0o7777
    except (FileNotFoundError, OSError):
        orig_mode = 0o600
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        os.chmod(tmp, orig_mode)
    except OSError:
        pass
    os.replace(tmp, path)


# ─────────────────────────────── MCP ────────────────────────────────────

def add_mcp(
    name: str,
    *,
    backend: Backend,
    scope: Scope = "global",
    command: str | None = None,
    url: str | None = None,
    args: list[str] | None = None,
) -> WriteResult:
    if not _safe_name(name):
        return WriteResult(False, f"mcp add: name must match [A-Za-z0-9_.-]+ (got {name!r})")
    if not command and not url:
        return WriteResult(False, "mcp add: --command or --url is required.")
    if backend == "codex":
        return _add_mcp_codex(name, command=command, args=args or [])
    path = _claude_mcp_file(scope) if backend == "claude" else _gemini_settings(scope)
    data = _read_json(path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return WriteResult(False, f"mcp add: malformed mcpServers in {path}")
    entry: dict = {}
    if command:
        entry["command"] = command
    if args:
        entry["args"] = list(args)
    if url:
        entry["url"] = url
    servers[name] = entry
    _write_json_atomic(path, data)
    return WriteResult(True, f"added '{name}' to {backend} ({scope}): {path}")


def remove_mcp(name: str, *, backend: Backend, scope: Scope = "global") -> WriteResult:
    if not _safe_name(name):
        return WriteResult(False, f"mcp remove: name must match [A-Za-z0-9_.-]+ (got {name!r})")
    if backend == "codex":
        return _remove_mcp_codex(name)
    path = _claude_mcp_file(scope) if backend == "claude" else _gemini_settings(scope)
    data = _read_json(path)
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict) or name not in servers:
        return WriteResult(False, f"mcp remove: '{name}' not found in {path}")
    del servers[name]
    data["mcpServers"] = servers
    _write_json_atomic(path, data)
    return WriteResult(True, f"removed '{name}' from {backend} ({scope})")


def _add_mcp_codex(name: str, *, command: str | None, args: list[str]) -> WriteResult:
    """Append an ``[mcp_servers.<name>]`` block to ~/.codex/config.toml.

    We append rather than round-trip: TOML serializers aren't in stdlib, and
    round-tripping loses formatting/comments. Append + a section marker is
    safe because Codex reads the LAST occurrence of a duplicate key.
    """
    path = _codex_config()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not command:
        return WriteResult(False, "mcp add (codex): --command is required.")
    lines = [f"\n[mcp_servers.{name}]", f"command = {_toml_quote(command)}"]
    if args:
        joined = ", ".join(_toml_quote(a) for a in args)
        lines.append(f"args = [{joined}]")
    lines.append("")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return WriteResult(True, f"appended '{name}' to {path}")


def _remove_mcp_codex(name: str) -> WriteResult:
    """Remove an ``[mcp_servers.<name>]`` block from ~/.codex/config.toml.

    Naive line-based section strip: we drop the header line and every line
    until the next ``[`` header or EOF. Comments immediately above the
    section are preserved (we only touch from ``[mcp_servers.<name>]`` on).
    """
    path = _codex_config()
    if not path.exists():
        return WriteResult(False, f"mcp remove (codex): {path} not found")
    src = path.read_text(encoding="utf-8")
    header = f"[mcp_servers.{name}]"
    # Also recognise nested sub-tables `[mcp_servers.<name>.env]` as belonging
    # to this server so we strip them along with the parent section.
    nested_prefix = f"[mcp_servers.{name}."
    out: list[str] = []
    skipping = False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped == header or stripped.startswith(nested_prefix):
            skipping = True
            continue
        if skipping and stripped.startswith("[") and stripped.endswith("]"):
            # Any non-matching section ends the skip region.
            skipping = False
        if not skipping:
            out.append(line)
    new = "\n".join(out).rstrip() + "\n"
    if new == src:
        return WriteResult(False, f"mcp remove (codex): '{name}' not found in {path}")
    path.write_text(new, encoding="utf-8")
    return WriteResult(True, f"removed '{name}' from {path}")


# ─────────────────────────────── plugins (claude only) ──────────────────

def toggle_plugin(name: str, *, enabled: bool, scope: Scope = "global") -> WriteResult:
    """Flip enabledPlugins[name] in Claude Code settings.json."""
    path = _claude_settings(scope)
    data = _read_json(path)
    plugins = data.setdefault("enabledPlugins", {})
    if not isinstance(plugins, dict):
        return WriteResult(False, f"plugin: malformed enabledPlugins in {path}")
    plugins[name] = bool(enabled)
    _write_json_atomic(path, data)
    action = "enabled" if enabled else "disabled"
    return WriteResult(True, f"{action} plugin '{name}' ({scope})")


# ─────────────────────────────── skills ─────────────────────────────────

def add_skill(
    source: str,
    *,
    name: str | None = None,
    backend: Backend = "claude",
    scope: Scope = "global",
) -> WriteResult:
    """Copy a skill dir (claude) or .md file (codex rules) into place."""
    src = Path(source).expanduser().resolve()
    if not src.exists():
        return WriteResult(False, f"skill add: source not found: {src}")
    if backend == "gemini":
        return WriteResult(False, "skill add: gemini has no skills concept.")
    if backend == "claude":
        if not src.is_dir():
            return WriteResult(False, f"skill add (claude): expected a directory, got {src}")
        dest_name = name or src.name
        root = (_home() / ".claude" / "skills") if scope == "global" else (_cwd() / ".claude" / "skills")
        root.mkdir(parents=True, exist_ok=True)
        dest = root / dest_name
        if dest.exists():
            return WriteResult(False, f"skill add: '{dest}' already exists.")
        shutil.copytree(src, dest)
        return WriteResult(True, f"installed skill '{dest_name}' → {dest}")
    # codex rules — accept a .md file or dir of .md files
    root = _home() / ".codex" / "rules"
    root.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        dest_name = (name or src.stem) + ".md"
        dest = root / dest_name
        if dest.exists():
            return WriteResult(False, f"rule already exists: {dest}")
        shutil.copy2(src, dest)
        return WriteResult(True, f"installed codex rule → {dest}")
    # directory of rules
    copied = 0
    for md in sorted(src.glob("*.md")):
        dest = root / md.name
        if dest.exists():
            continue
        shutil.copy2(md, dest)
        copied += 1
    return WriteResult(copied > 0, f"installed {copied} codex rule(s) into {root}")


def remove_skill(name: str, *, backend: Backend = "claude", scope: Scope = "global") -> WriteResult:
    if backend == "gemini":
        return WriteResult(False, "skill remove: gemini has no skills concept.")
    if backend == "claude":
        root = (_home() / ".claude" / "skills") if scope == "global" else (_cwd() / ".claude" / "skills")
        target = root / name
        if not target.exists():
            return WriteResult(False, f"skill remove: '{target}' not found.")
        shutil.rmtree(target)
        return WriteResult(True, f"removed skill '{name}' ({target})")
    # codex
    target = _home() / ".codex" / "rules" / (name if name.endswith(".md") else f"{name}.md")
    if not target.exists():
        return WriteResult(False, f"rule remove: {target} not found")
    target.unlink()
    return WriteResult(True, f"removed codex rule {target}")


# ─────────────────────────────── agents (claude) ────────────────────────

def add_agent(
    source: str,
    *,
    name: str | None = None,
    scope: Scope = "global",
) -> WriteResult:
    src = Path(source).expanduser().resolve()
    if not src.exists() or not src.is_file():
        return WriteResult(False, f"agent add: expected a .md file, got {src}")
    if src.suffix != ".md":
        return WriteResult(False, f"agent add: file must be .md ({src.suffix} given)")
    dest_name = (name or src.stem) + ".md"
    root = (_home() / ".claude" / "agents") if scope == "global" else (_cwd() / ".claude" / "agents")
    root.mkdir(parents=True, exist_ok=True)
    dest = root / dest_name
    if dest.exists():
        return WriteResult(False, f"agent add: '{dest}' already exists.")
    shutil.copy2(src, dest)
    return WriteResult(True, f"installed agent '{dest.stem}' → {dest}")


def remove_agent(name: str, *, scope: Scope = "global") -> WriteResult:
    root = (_home() / ".claude" / "agents") if scope == "global" else (_cwd() / ".claude" / "agents")
    target = root / (name if name.endswith(".md") else f"{name}.md")
    if not target.exists():
        return WriteResult(False, f"agent remove: {target} not found")
    target.unlink()
    return WriteResult(True, f"removed agent '{target.stem}'")


# ─────────────────────────────── settings.json set ─────────────────────

def set_setting(key: str, value: str, *, scope: Scope = "global") -> WriteResult:
    """Set ``settings.json[key]`` to ``value`` (coerced to int / bool / JSON / string).

    Supports nested keys via dotted path: ``permissions.defaultMode``.
    """
    path = _claude_settings(scope)
    data = _read_json(path)
    parts = key.split(".")
    coerced = _coerce(value)
    cursor: dict = data
    for p in parts[:-1]:
        nxt = cursor.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[p] = nxt
        cursor = nxt
    cursor[parts[-1]] = coerced
    _write_json_atomic(path, data)
    return WriteResult(True, f"set {key}={coerced!r} in {path}")


def _coerce(value: str):
    """Best-effort coerce a CLI string into int / bool / JSON / str."""
    lower = value.strip().lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower == "null":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        pass
    return value


# ─────────────────────────────── hooks ──────────────────────────────────

VALID_HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "PermissionRequest", "Notification",
    "Stop", "PreCompact", "PostCompact", "UserPromptSubmit", "SessionStart",
)


def add_hook(
    event: str,
    matcher: str,
    command: str,
    *,
    scope: Scope = "global",
) -> WriteResult:
    if event not in VALID_HOOK_EVENTS:
        return WriteResult(False, f"add_hook: unknown event '{event}'. Valid: {', '.join(VALID_HOOK_EVENTS)}")
    path = _claude_settings(scope)
    data = _read_json(path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return WriteResult(False, f"add_hook: malformed hooks block in {path}")
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        return WriteResult(False, f"add_hook: hooks.{event} is not a list")
    new_entry = {"type": "command", "command": command}
    for g in groups:
        if isinstance(g, dict) and g.get("matcher") == matcher:
            entries = g.setdefault("hooks", [])
            if new_entry in entries:
                return WriteResult(False, f"add_hook: {event}[{matcher}] already has this command")
            entries.append(new_entry)
            _write_json_atomic(path, data)
            return WriteResult(True, f"appended hook to {event}[{matcher}]")
    groups.append({"matcher": matcher, "hooks": [new_entry]})
    _write_json_atomic(path, data)
    return WriteResult(True, f"added {event}[{matcher}] → {command[:60]}")


def remove_hook(event: str, matcher: str, *, scope: Scope = "global") -> WriteResult:
    path = _claude_settings(scope)
    data = _read_json(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return WriteResult(False, f"remove_hook: no hooks in {path}")
    groups = hooks.get(event)
    if not isinstance(groups, list):
        return WriteResult(False, f"remove_hook: no {event} hooks")
    before = len(groups)
    hooks[event] = [g for g in groups if not (isinstance(g, dict) and g.get("matcher") == matcher)]
    if len(hooks[event]) == before:
        return WriteResult(False, f"remove_hook: no {event}[{matcher}] found")
    if not hooks[event]:
        del hooks[event]
    _write_json_atomic(path, data)
    return WriteResult(True, f"removed {event}[{matcher}]")


# ─────────────────────────────── permissions ────────────────────────────

def add_permission(kind: str, rule: str, *, scope: Scope = "global") -> WriteResult:
    if kind not in ("allow", "deny", "ask"):
        return WriteResult(False, f"add_permission: kind must be allow/deny/ask, got '{kind}'")
    path = _claude_settings(scope)
    data = _read_json(path)
    perm = data.setdefault("permissions", {})
    if not isinstance(perm, dict):
        return WriteResult(False, f"add_permission: malformed permissions in {path}")
    bucket = perm.setdefault(kind, [])
    if not isinstance(bucket, list):
        return WriteResult(False, f"add_permission: permissions.{kind} is not a list")
    if rule in bucket:
        return WriteResult(False, f"add_permission: '{rule}' already in {kind}")
    # Cross-bucket dedup: a rule can't live in two different buckets (e.g.
    # the same pattern in both allow and deny yields an ambiguous policy).
    for other in ("allow", "deny", "ask"):
        if other == kind:
            continue
        existing = perm.get(other)
        if isinstance(existing, list) and rule in existing:
            return WriteResult(
                False,
                f"add_permission: '{rule}' already in {other}; remove it first or the effective policy is ambiguous",
            )
    bucket.append(rule)
    _write_json_atomic(path, data)
    return WriteResult(True, f"added '{rule}' to permissions.{kind}")


def remove_permission(kind: str, rule: str, *, scope: Scope = "global") -> WriteResult:
    if kind not in ("allow", "deny", "ask"):
        return WriteResult(False, f"remove_permission: kind must be allow/deny/ask, got '{kind}'")
    path = _claude_settings(scope)
    data = _read_json(path)
    perm = data.get("permissions")
    if not isinstance(perm, dict):
        return WriteResult(False, f"remove_permission: no permissions in {path}")
    bucket = perm.get(kind)
    if not isinstance(bucket, list) or rule not in bucket:
        return WriteResult(False, f"remove_permission: '{rule}' not in {kind}")
    bucket.remove(rule)
    _write_json_atomic(path, data)
    return WriteResult(True, f"removed '{rule}' from permissions.{kind}")


# ─────────────────────────────── init ───────────────────────────────────

COHRINT_BEGIN = "<!-- cohrint:begin -->"
COHRINT_END = "<!-- cohrint:end -->"

COHRINT_BLOCK_TEMPLATE = """{begin}
## Cohrint tooling

This project uses `cohrint-agent`. Managed settings live in the cohrint block
below — do not edit by hand; use `cohrint-agent` commands instead.

- MCP servers: `cohrint-agent mcp list`
- Plugins:     `cohrint-agent plugins list`
- Skills:      `cohrint-agent skills list`
- Agents:      `cohrint-agent agents list`
- Hooks:       `cohrint-agent hooks list`
{end}
"""


def init_project(*, force: bool = False) -> WriteResult:
    """Set up cohrint tooling in the current project.

    Append-safe. Inserts a cohrint-managed block into CLAUDE.md / AGENTS.md
    surrounded by ``<!-- cohrint:begin -->`` / ``<!-- cohrint:end -->`` markers
    so subsequent re-runs update the block without clobbering user edits.
    Creates ``.claude/settings.local.json`` if missing (empty object).
    """
    project = _cwd()
    touched: list[str] = []

    # 1. CLAUDE.md — append cohrint block
    claude_md = project / "CLAUDE.md"
    block = COHRINT_BLOCK_TEMPLATE.format(begin=COHRINT_BEGIN, end=COHRINT_END)
    if claude_md.exists():
        src = claude_md.read_text(encoding="utf-8")
        if COHRINT_BEGIN in src:
            if not force:
                return WriteResult(False, "init: CLAUDE.md already has a cohrint block. Use --force to overwrite.")
            # Strip ALL existing cohrint blocks first (handles a file that got
            # duplicated blocks from a buggy earlier run) then append one fresh
            # block. This is idempotent: N blocks collapse to 1.
            stripped, n = re.subn(
                rf"{re.escape(COHRINT_BEGIN)}.*?{re.escape(COHRINT_END)}\n?",
                "",
                src,
                flags=re.DOTALL,
            )
            if n == 0:
                # Marker present but pattern didn't match — corrupt/partial
                # block. Refuse rather than silently stacking on top.
                return WriteResult(
                    False,
                    "init: CLAUDE.md has a cohrint:begin marker without a matching end. "
                    "Fix manually or delete the block before retrying.",
                )
            claude_md.write_text(stripped.rstrip() + "\n\n" + block, encoding="utf-8")
            touched.append(f"CLAUDE.md (replaced {n} block{'s' if n > 1 else ''})")
        else:
            claude_md.write_text(src.rstrip() + "\n\n" + block, encoding="utf-8")
            touched.append("CLAUDE.md (appended block)")
    else:
        claude_md.write_text(f"# Project Claude Brain\n\n{block}", encoding="utf-8")
        touched.append("CLAUDE.md (created)")

    # 2. .claude/settings.local.json — create empty if missing
    local_settings = project / ".claude" / "settings.local.json"
    if not local_settings.exists():
        local_settings.parent.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(local_settings, {})
        touched.append(str(local_settings.relative_to(project)))

    # 3. .gitignore — add settings.local.json if a .gitignore exists
    gi = project / ".gitignore"
    if gi.exists():
        current = gi.read_text(encoding="utf-8")
        if ".claude/settings.local.json" not in current:
            gi.write_text(current.rstrip() + "\n.claude/settings.local.json\n", encoding="utf-8")
            touched.append(".gitignore (added settings.local.json)")

    return WriteResult(True, f"init complete. Touched: {', '.join(touched) if touched else '(nothing)'}")


__all__ = [
    "WriteResult",
    "VALID_HOOK_EVENTS",
    "add_mcp",
    "remove_mcp",
    "toggle_plugin",
    "add_skill",
    "remove_skill",
    "add_agent",
    "remove_agent",
    "set_setting",
    "add_hook",
    "remove_hook",
    "add_permission",
    "remove_permission",
    "init_project",
]
