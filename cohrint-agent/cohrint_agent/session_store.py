"""
session_store.py — Persist/restore CohrintSession state to ~/.cohrint-agent/sessions/.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


from .process_safety import safe_config_dir

# Lazy: a module-level `safe_config_dir() / "sessions"` at import time
# calls pwd.getpwuid() via Path.home(), which raises in minimal container
# images (no /etc/passwd entry for the uid). Resolve on first use instead
# (T-SAFETY.lazy_config_dir).
DEFAULT_SESSIONS_DIR: Path | None = None


def _default_sessions_dir() -> Path:
    return safe_config_dir() / "sessions"

# list_all() guards — prevent `cohrint-agent summary` from OOMing if the
# sessions directory has been stuffed with thousands of files or oversized
# payloads. Both limits are generous for legitimate use.
MAX_SESSIONS_LISTED = 1000
MAX_SESSION_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB per session JSON

# Highest schema_version this build understands. A future-tagged session
# (e.g. schema_version=99 written by a newer release, or a tampered
# marker) must be refused on load rather than parsed through as if it
# matched v1 — downstream code assumes v1 field shapes
# (T-INPUT.schema_version_reject).
CURRENT_SCHEMA_VERSION = 1


def _validate_schema_version(data: object, session_id: str) -> None:
    """Raise SessionNotFoundError if schema_version is missing or > current."""
    if not isinstance(data, dict):
        raise SessionNotFoundError(
            f"Session {session_id!r} payload is not an object"
        )
    sv = data.get("schema_version", 1)
    if not isinstance(sv, int) or sv < 1 or sv > CURRENT_SCHEMA_VERSION:
        raise SessionNotFoundError(
            f"Session {session_id!r} schema_version {sv!r} unsupported"
        )


# Strict UUIDv4 — version=4 nibble + RFC-4122 variant (8|9|a|b). Rejects
# legacy, malformed, or attacker-supplied IDs (e.g. "../../etc/passwd") so
# session_id can be used as a filename without escaping or sanitising
# downstream. Guards T-SAFETY.4 + T-SAFETY.10.
_UUID4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def is_valid_session_id(sid: object) -> bool:
    return isinstance(sid, str) and bool(_UUID4_RE.fullmatch(sid))


class SessionNotFoundError(Exception):
    pass


class InvalidSessionIdError(ValueError):
    """Raised when a session_id fails UUIDv4 validation."""


class SessionStore:
    def __init__(self, sessions_dir: Path | None = None) -> None:
        self.sessions_dir = Path(sessions_dir) if sessions_dir else _default_sessions_dir()
        # 0o700: sessions contain full conversation history, cwd, and
        # accumulated cost — on a shared box with the default 0o022 umask
        # these files would be world-readable. Re-chmod every init in
        # case the dir was created earlier with wider perms
        # (T-PRIVACY.sessions_dir_0700).
        self.sessions_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.sessions_dir, 0o700)
        except OSError:
            pass

    def _path(self, session_id: str) -> Path:
        if not is_valid_session_id(session_id):
            raise InvalidSessionIdError(
                f"session_id must be a UUIDv4; got {session_id!r}"
            )
        return self.sessions_dir / f"{session_id}.json"

    def save(self, data: dict) -> None:
        data.setdefault("schema_version", 1)
        data["last_active_at"] = datetime.now(timezone.utc).isoformat()
        path = self._path(data["id"])  # raises InvalidSessionIdError on bad id
        # Write to a sibling tmp file then atomically rename into place.
        # Two invariants this enforces (T-CONCUR.atomic_save):
        #   1. A SIGKILL mid-write cannot leave a half-written target —
        #      os.replace is atomic on POSIX, so readers always see either
        #      the old content or the new content, never a truncated file.
        #   2. LOCK_EX is taken on a dedicated lockfile descriptor before
        #      any truncation happens, so concurrent savers serialize
        #      correctly instead of racing on open("w") (truncate-before-lock).
        tmp = path.with_suffix(path.suffix + ".tmp")
        lockfile = path.with_suffix(path.suffix + ".lock")
        from .process_safety import open_lockfile
        with open_lockfile(lockfile) as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                # Open tmp with explicit 0o600 so session history isn't
                # readable by anyone but the owner — umask-independent
                # (T-PRIVACY.sessions_file_0600).
                # O_EXCL so a stale/attacker-planted <uuid>.json.tmp cannot
                # be silently reused; unlink any leftover then retry once
                # (T-SAFETY.tmp_excl).
                try:
                    fd = os.open(
                        tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC, 0o600
                    )
                except FileExistsError:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    fd = os.open(
                        tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC, 0o600
                    )
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)
        # Best-effort cleanup so `sessions/` doesn't accumulate a .lock
        # file per session. Advisory flock is per-fd; concurrent holders
        # keep their lock regardless of the path being unlinked.
        try:
            os.unlink(lockfile)
        except OSError:
            pass

    def load(self, session_id: str) -> dict:
        p = self._path(session_id)  # raises InvalidSessionIdError on bad id
        if not p.exists():
            raise SessionNotFoundError(f"Session {session_id!r} not found")
        # O_NOFOLLOW refuses a symlink at <uuid>.json — otherwise a local
        # attacker who can write into sessions_dir could point the file
        # at /etc/passwd and the parse error text would carry the first
        # line of the target through to the user (T-SAFETY.load_no_symlink).
        # Size cap parallels list_all — prevents an unbounded read from
        # a tampered file (T-BOUNDS.load_size_cap).
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as e:
            raise SessionNotFoundError(
                f"Session {session_id!r} not readable: {type(e).__name__}"
            ) from None
        with os.fdopen(fd, "rb") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                if os.fstat(f.fileno()).st_size > MAX_SESSION_FILE_BYTES:
                    raise SessionNotFoundError(
                        f"Session {session_id!r} exceeds {MAX_SESSION_FILE_BYTES} bytes"
                    )
                raw = f.read(MAX_SESSION_FILE_BYTES + 1)
                if len(raw) > MAX_SESSION_FILE_BYTES:
                    raise SessionNotFoundError(
                        f"Session {session_id!r} exceeds {MAX_SESSION_FILE_BYTES} bytes"
                    )
                data = json.loads(raw.decode("utf-8", errors="replace"))
                _validate_schema_version(data, session_id)
                return data
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def list_all(self) -> list[dict]:
        """Return all sessions sorted by last_active_at descending.

        Caps at ``MAX_SESSIONS_LISTED`` files and skips any file above
        ``MAX_SESSION_FILE_BYTES`` so a bloated / attacker-seeded sessions
        directory cannot OOM the process (T-BOUNDS.sessions).
        """
        sessions: list[dict] = []
        for p in self.sessions_dir.glob("*.json"):
            if len(sessions) >= MAX_SESSIONS_LISTED:
                break
            try:
                # TOCTOU-safe read: open the file, then stat the fd (not the
                # path) so an attacker can't `os.replace` between check and
                # read to slip an oversized file past the cap. Reading only
                # up to MAX_SESSION_FILE_BYTES+1 also bounds memory even if
                # the fd-stat races (T-SAFETY.list_all_toctou).
                with open(p, "rb") as f:
                    if os.fstat(f.fileno()).st_size > MAX_SESSION_FILE_BYTES:
                        continue
                    raw = f.read(MAX_SESSION_FILE_BYTES + 1)
                    if len(raw) > MAX_SESSION_FILE_BYTES:
                        continue
                parsed = json.loads(raw)
                # Skip future-schema or malformed payloads rather than
                # letting them surface into the session listing, where
                # downstream consumers assume v1 field shapes.
                if not isinstance(parsed, dict):
                    continue
                sv = parsed.get("schema_version", 1)
                if not isinstance(sv, int) or sv < 1 or sv > CURRENT_SCHEMA_VERSION:
                    continue
                sessions.append(parsed)
            except Exception:
                continue
        return sorted(sessions, key=lambda s: s.get("last_active_at", ""), reverse=True)

    def total_cost_usd(self) -> float:
        """Aggregate cost across all sessions."""
        return sum(
            s.get("cost_summary", {}).get("total_cost_usd", 0.0)
            for s in self.list_all()
        )
