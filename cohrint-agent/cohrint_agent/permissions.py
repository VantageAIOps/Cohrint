"""
permissions.py — Per-tool permission management.

Shared source of truth for both API backend (in-process) and
Claude CLI backend (via hook script reading same JSON).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from rich.console import Console
from rich.prompt import Prompt

from .tools import SAFE_TOOLS

console = Console()

from .process_safety import safe_config_dir

# Resolving safe_config_dir() at import time calls Path.home() / pwd.getpwuid(),
# which crashes in minimal containers (no /etc/passwd entry for the uid).
# Wrap lazy so `import cohrint_agent.permissions` itself can't fail
# (T-SAFETY.lazy_config_dir).
def _get_default_config_dir() -> Path:
    return safe_config_dir()

_PERM_FILE_NAME = "permissions.json"

# Parse-bomb guard (T-BOUNDS.perm_file). Legitimate permissions.json files
# are <100 KiB even after months of audit-log accumulation. A 1 MiB cap
# leaves generous headroom while making OOM-by-planted-file impossible.
_MAX_PERM_FILE_BYTES = 1 * 1024 * 1024

# Audit log rotation cap (T-BOUNDS.audit_log). Without this, a high-traffic
# session can push the file toward the 1 MiB stat-gate, which then resets
# the file to defaults — silently wiping always_denied rules. Trimming the
# array to the last N entries prevents the gate from ever firing.
_AUDIT_LOG_MAX_ENTRIES = 500

def _config_dir(config_dir: Path | None) -> Path:
    return config_dir or _get_default_config_dir()


class PermissionManager:
    """Manages per-tool approval state. Both backends share this."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = _config_dir(config_dir)
        self._perm_file = self._config_dir / _PERM_FILE_NAME
        self.session_approved: set[str] = set(SAFE_TOOLS)
        self.always_approved: set[str] = set(SAFE_TOOLS)
        self.always_denied: set[str] = set()
        self._load()

    def _load(self) -> None:
        # Open-then-fstat closes the stat→open TOCTOU window: a separate
        # stat() call could see a small file, then an attacker os.replaces
        # in a bomb before json.load runs. fstat on the already-open fd
        # guarantees the size check describes the same inode we're about
        # to parse (T-SAFETY.permfile_toctou, scan 18). O_NOFOLLOW also
        # refuses a symlink swap at open time.
        try:
            import fcntl
            fd = os.open(self._perm_file, os.O_RDONLY | os.O_NOFOLLOW)
        except (OSError, FileNotFoundError):
            return
        try:
            f = os.fdopen(fd)
            fcntl.flock(f, fcntl.LOCK_SH)
            if os.fstat(f.fileno()).st_size > _MAX_PERM_FILE_BYTES:
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
                return
            data = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()
            # Refuse unknown schemas rather than silently truncating to
            # safe defaults via downstream cast errors. A future
            # forwards-incompatible version should surface as an explicit
            # log, not as a silent permissions wipe
            # (T-SAFETY.schema_version_guard).
            schema = data.get("schema_version", 1)
            if not isinstance(schema, int) or schema > 1:
                _log.warning(
                    "permissions.json schema_version=%r is newer than this "
                    "client supports (max 1); using safe defaults", schema
                )
                return
            self.always_approved |= set(data.get("always_approved", []))
            self.always_denied = set(data.get("always_denied", []))
            self.session_approved |= set(data.get("session_approved", []))
            self.session_approved |= self.always_approved
        except Exception as e:
            # Corruption → safe defaults. Log at debug so an operator
            # running with COHRINT_LOG_LEVEL=DEBUG can see which file
            # failed to parse without leaking details to stdout.
            _log.debug("permissions load failed for %s: %s", self._perm_file, e)

    def _save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = self._read_raw()
        data.update({
            "schema_version": 1,
            "always_approved": sorted(self.always_approved),
            "always_denied": sorted(self.always_denied),
            "session_approved": sorted(self.session_approved - self.always_approved),
        })
        # Atomic write via tmp + os.replace (T-CONCUR.atomic_save). The hook
        # subprocess reads this file concurrently; open("w") would truncate
        # before the lock is acquired and expose a zero-byte window that
        # silently falls through to "prompt", bypassing always-denied rules.
        import fcntl
        tmp = self._perm_file.with_suffix(self._perm_file.suffix + ".tmp")
        lockfile = self._perm_file.with_suffix(self._perm_file.suffix + ".lock")
        from .process_safety import open_lockfile
        with open_lockfile(lockfile) as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._perm_file)
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
        # Keep only one persistent lockfile — don't accumulate stale copies
        # across sessions. Other concurrent writers hold the lock via their
        # own fd and are unaffected by the unlink.
        try:
            os.unlink(lockfile)
        except OSError:
            pass

    def _read_raw(self) -> dict:
        default = {"schema_version": 1, "always_approved": [], "always_denied": [],
                   "session_approved": [], "audit_log": []}
        # Mirror _load(): open-then-fstat, closing the stat→open TOCTOU.
        try:
            import fcntl
            fd = os.open(self._perm_file, os.O_RDONLY | os.O_NOFOLLOW)
        except (OSError, FileNotFoundError):
            return default
        try:
            f = os.fdopen(fd)
            fcntl.flock(f, fcntl.LOCK_SH)
            if os.fstat(f.fileno()).st_size > _MAX_PERM_FILE_BYTES:
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
                return default
            d = json.load(f)
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()
            return d
        except Exception as e:
            _log.debug("permissions read_raw failed for %s: %s", self._perm_file, e)
            return default

    def is_approved(self, tool_name: str) -> bool:
        return tool_name in self.session_approved and tool_name not in self.always_denied

    def is_denied(self, tool_name: str) -> bool:
        return tool_name in self.always_denied

    def check_permission(self, tool_name: str, tool_input: dict[str, Any]) -> bool:
        if self.is_denied(tool_name):
            console.print(f"  [red]✗ {tool_name} is in your always-denied list[/red]")
            return False
        if self.is_approved(tool_name):
            return True

        console.print()
        console.print(f"  [yellow bold]⚠ Claude wants to use [white]{tool_name}[/white][/yellow bold]")
        _print_tool_preview(tool_name, tool_input)

        # Non-interactive invocation (pipe, cron, CI) can't answer the
        # Prompt.ask — Rich raises EOFError on a closed stdin. Treat that
        # as deny-once rather than crashing the turn (T-SAFETY.non_tty_deny).
        try:
            answer = Prompt.ask(
                "  [dim]Allow?[/dim]",
                choices=["y", "a", "n", "N"],
                default="y",
            )
        except (EOFError, KeyboardInterrupt):
            import sys as _sys
            print(
                f"[cohrint-agent] non-interactive session denied {tool_name} "
                f"(use `cohrint-agent --allow {tool_name}` to pre-approve)",
                file=_sys.stderr,
            )
            try:
                self.append_audit(tool_name, "[non-tty]", "deny_non_tty", "unknown")
            except Exception:
                pass
            return False

        decision = "deny"
        if answer == "a":
            self.session_approved.add(tool_name)
            self.always_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (always)[/green]")
            decision = "allow_always"
        elif answer == "y":
            self.session_approved.add(tool_name)
            self._save()
            console.print(f"  [green]✓ {tool_name} approved (this session)[/green]")
            decision = "allow_session"
        elif answer == "N":
            self.always_denied.add(tool_name)
            self._save()
            console.print(f"  [red]✗ {tool_name} denied (always)[/red]")
            decision = "deny_always"
        else:
            console.print(f"  [red]✗ {tool_name} denied[/red]")
            decision = "deny_session"

        self.append_audit(
            tool=tool_name,
            input_preview=_input_preview(tool_name, tool_input),
            decision=decision,
            backend="api",
        )
        return decision.startswith("allow")

    def approve(self, tool_names: list[str], always: bool = False) -> None:
        for name in tool_names:
            self.session_approved.add(name)
            if always:
                self.always_approved.add(name)
                # Enforce the invariant ``always_approved ∩ always_denied = ∅``.
                # Without this, ``check_permission`` keeps blocking the
                # tool (is_denied wins) while the user believes they've
                # approved it (T-SAFETY.approve_clears_denied).
                self.always_denied.discard(name)
            # Audit every REPL-initiated approval so operators reviewing
            # ``audit_log`` can see bulk /approve calls, not just
            # per-prompt accept decisions (T-SAFETY.approve_audited).
            self.append_audit(
                tool=name, input_preview="",
                decision="allow_always" if always else "allow_session",
                backend="repl",
            )
        if always:
            self._save()

    def deny(self, tool_names: list[str]) -> None:
        for name in tool_names:
            self.always_denied.add(name)
            self.session_approved.discard(name)
            # Keep always_approved consistent — deny always wins.
            self.always_approved.discard(name)
            self.append_audit(
                tool=name, input_preview="",
                decision="deny_always", backend="repl",
            )
        self._save()

    def clear_session_approved(self) -> None:
        self.session_approved = set(SAFE_TOOLS) | self.always_approved

    def reset(self, *, wipe_denied: bool = False) -> None:
        """Reset approvals to the safe default.

        ``wipe_denied=False`` (the new default) preserves ``always_denied``.
        Previously ``/reset`` silently re-enabled every tool a user had
        permanently blocked via ``/never`` — a quiet privilege-escalation
        footgun for users who typed /reset only to clear conversation
        history (T-SAFETY.reset_preserves_denied).
        """
        self.session_approved = set(SAFE_TOOLS)
        self.always_approved = set(SAFE_TOOLS)
        if wipe_denied:
            self.always_denied = set()
        self._save()

    def status(self) -> tuple[set[str], set[str]]:
        return self.session_approved.copy(), self.always_approved.copy()

    def append_audit(self, tool: str, input_preview: str, decision: str, backend: str) -> None:
        """Append an audit log entry to permissions.json."""
        # ``errors="replace"`` so an isolated surrogate (which the model
        # can generate) doesn't abort the audit write and leave a denied
        # action unlogged (T-SAFETY.audit_surrogate).
        _preview_bytes = input_preview.encode("utf-8", errors="replace")
        # Scrub embedded newlines before storing — otherwise a model-generated
        # command containing `\n{"tool": "X", "decision": "allow"}\n` forges
        # a second audit entry visible to any line-oriented log reader
        # (T-SAFETY.audit_log_injection).
        safe_preview = (
            input_preview[:200]
            .replace("\r", "\\r")
            .replace("\n", "\\n")
        )
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "input_hash": hashlib.sha256(_preview_bytes).hexdigest()[:16],
            "input_preview": safe_preview,
            "decision": decision,
            "backend": backend,
        }
        self._config_dir.mkdir(parents=True, exist_ok=True)
        import fcntl
        lockfile = self._perm_file.with_suffix(self._perm_file.suffix + ".lock")
        tmp = self._perm_file.with_suffix(self._perm_file.suffix + ".tmp")
        from .process_safety import open_lockfile
        with open_lockfile(lockfile) as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                # Read current state under the lock via open-then-fstat so
                # an attacker cannot swap the file between the size check
                # and the parse (T-SAFETY.append_audit_toctou, scan 18).
                # O_NOFOLLOW rejects symlink swap at open time.
                data = None
                try:
                    rfd = os.open(self._perm_file, os.O_RDONLY | os.O_NOFOLLOW)
                    try:
                        rf = os.fdopen(rfd)
                        if os.fstat(rf.fileno()).st_size <= _MAX_PERM_FILE_BYTES:
                            try:
                                data = json.load(rf)
                            except Exception:
                                data = None
                        rf.close()
                    except Exception:
                        try:
                            os.close(rfd)
                        except OSError:
                            pass
                except (OSError, FileNotFoundError):
                    data = None
                if not isinstance(data, dict):
                    data = {"schema_version": 1, "always_approved": [], "always_denied": [],
                            "session_approved": [], "audit_log": []}
                data.setdefault("audit_log", []).append(entry)
                # Bound the audit-log array so the 1 MiB stat-gate is
                # never reached by organic growth.
                if len(data["audit_log"]) > _AUDIT_LOG_MAX_ENTRIES:
                    data["audit_log"] = data["audit_log"][-_AUDIT_LOG_MAX_ENTRIES:]
                # Atomic replace — an ENOSPC or crash mid-dump can no
                # longer leave the live file truncated and silently wipe
                # always_denied (T-SAFETY.append_audit_atomic).
                with open(tmp, "w") as wf:
                    json.dump(data, wf, indent=2)
                    wf.flush()
                    os.fsync(wf.fileno())
                os.replace(tmp, self._perm_file)
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
        try:
            os.unlink(lockfile)
        except OSError:
            pass


def _input_preview(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return tool_input.get("command", "")[:200]
    if tool_name in ("Write", "Edit", "Read"):
        return tool_input.get("file_path", "")
    return str(tool_input)[:200]


def _print_tool_preview(tool_name: str, tool_input: dict[str, Any]) -> None:
    # Any external string (model-generated tool args) passed to
    # console.print must be escaped or Rich will interpret ``[...]`` as
    # markup — ``[link=file:///etc/passwd]click[/link]`` or a spoofed
    # ``[green]✓ approved[/green]`` around the approval prompt would
    # mislead the user (T-SAFETY.rich_markup_injection). In addition,
    # the raw value may contain OSC-52 or CSI escapes — run the central
    # terminal scrubber first so ``\x1b]52;c;...\x07`` clipboard-write
    # sequences never reach the tty (T-SAFETY.preview_terminal_scrub).
    from rich.markup import escape as _esc
    from .sanitize import scrub_for_terminal as _scrub

    def _ext(s: object, limit: int | None = None) -> str:
        text = _scrub(str(s or ""))
        if limit is not None:
            text = text[:limit]
        return _esc(text)

    if tool_name == "Bash":
        console.print(f"    [dim]$[/dim] {_ext(tool_input.get('command', ''), 200)}")
    elif tool_name == "Write":
        fp = _ext(tool_input.get("file_path", ""))
        lines = tool_input.get("content", "").count("\n") + 1
        console.print(f"    [dim]Create/overwrite[/dim] {fp} [dim]({lines} lines)[/dim]")
    elif tool_name == "Edit":
        fp = _ext(tool_input.get("file_path", ""))
        old = _ext(tool_input.get("old_string", ""), 80)
        console.print(f"    [dim]Edit[/dim] {fp}")
        console.print(f"    [dim]Replace:[/dim] {old}...")
    elif tool_name == "Read":
        console.print(f"    [dim]Read[/dim] {_ext(tool_input.get('file_path', ''))}")
    elif tool_name == "Glob":
        console.print(f"    [dim]Pattern:[/dim] {_ext(tool_input.get('pattern', ''))}")
    elif tool_name == "Grep":
        console.print(f"    [dim]Search:[/dim] {_ext(tool_input.get('pattern', ''))} "
                      f"[dim]in[/dim] {_ext(tool_input.get('path', '.'))}")
    else:
        for k, v in list(tool_input.items())[:3]:
            console.print(f"    [dim]{_esc(str(k))}:[/dim] {_ext(v, 80)}")
    console.print("    [dim]\\[y]es once  \\[a]lways  \\[n]o once  \\[N]ever[/dim]")
