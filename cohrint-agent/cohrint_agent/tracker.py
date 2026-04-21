"""
tracker.py — Dashboard telemetry client.

Batches cost/usage events and sends them to the Cohrint backend API.
Respects privacy modes: full, strict, anonymized, local-only.
Cost tracking module for cohrint-agent.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .cost_tracker import SessionCost
from .telemetry import OTelExporter
from .update_check import _assert_https_api_base

# ── Spool helpers ─────────────────────────────────────────────────────────────

# Lazy resolution so minimal containers without a /etc/passwd entry for
# the UID (Path.home() raises RuntimeError) don't crash at import
# (T-SAFETY.lazy_spool_dir, scan 18). Mirrors the rate_limiter pattern.
def __getattr__(name: str):
    if name == "_SPOOL_DIR":
        return Path.home() / ".cohrint"
    if name == "_SPOOL_FILE":
        return Path.home() / ".cohrint" / "spool.jsonl"
    if name == "_SPOOL_LOCK_FILE":
        return Path.home() / ".cohrint" / "spool.lock"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_MAX_SPOOL = 1000
# Absolute spool size cap enforced at read time. _MAX_SPOOL bounds line
# count during WRITE, but a concurrent writer without the cap (test
# harness, older version, manual tamper) can grow the file past any line
# count we compute — so cap read bytes too (T-DOS.spool_read_size_cap).
_MAX_SPOOL_BYTES = 16 * 1024 * 1024  # 16 MiB
_spool_lock = threading.Lock()  # in-process; cross-process uses fcntl below

# In-memory queue ceiling. If the dashboard keeps rejecting events (e.g. a
# persistent HTTP 400 from a misconfigured endpoint) the queue would
# otherwise grow unboundedly on each REPL turn and OOM the process.
# Matches Node tracker.ts MAX_QUEUE_SIZE.
MAX_QUEUE_SIZE = 500


def _spool_write(events: list[dict[str, Any]]) -> None:
    """Append events to ~/.cohrint/spool.jsonl (best-effort, never raises).

    Uses 0o700 dir + 0o600 file + atomic tmp+replace. On shared boxes
    (CI runners, Docker multi-tenant, university servers) the default
    umask 0o022 otherwise leaves spool.jsonl world-readable; token
    counts, model names, and cost figures then leak to other local
    UIDs (T-PRIVACY.spool_perms). Atomic replace also survives a
    SIGKILL mid-write without zero-byting the spool
    (T-SAFETY.spool_atomic).
    """
    # Resolve via module __getattr__ (lazy) and import fcntl / open_lockfile
    # inside the try so a missing fcntl on non-POSIX is caught by the outer
    # "never raises" guarantee.
    import sys as _sys
    _mod = _sys.modules[__name__]
    spool_dir = getattr(_mod, "_SPOOL_DIR")
    spool_file = getattr(_mod, "_SPOOL_FILE")
    spool_lock_file = getattr(_mod, "_SPOOL_LOCK_FILE")
    try:
        import fcntl
        from .process_safety import open_lockfile
        spool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(spool_dir, 0o700)
        except OSError:
            pass
        # Cross-process lock — threading.Lock only serializes threads in
        # THIS process. Two REPL processes sharing the spool would otherwise
        # race read+unlink vs read+write and lose events
        # (T-SAFETY.spool_cross_process, scan 18).
        with _spool_lock, open_lockfile(spool_lock_file) as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            existing: list[str] = []
            # Open-then-read under lock; ignore FileNotFoundError since the
            # drain path may have unlinked between mkdir and here.
            try:
                rfd = os.open(str(spool_file), os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    with os.fdopen(rfd, "rb") as rf:
                        if os.fstat(rf.fileno()).st_size > _MAX_SPOOL_BYTES:
                            existing = []
                        else:
                            raw = rf.read(_MAX_SPOOL_BYTES + 1)
                            if len(raw) > _MAX_SPOOL_BYTES:
                                existing = []
                            else:
                                existing = raw.decode(
                                    "utf-8", errors="replace"
                                ).splitlines()
                except Exception:
                    try:
                        os.close(rfd)
                    except OSError:
                        pass
            except FileNotFoundError:
                existing = []
            new_lines = [json.dumps(e) for e in events]
            combined = existing + new_lines
            if len(combined) > _MAX_SPOOL:
                combined = combined[len(combined) - _MAX_SPOOL:]
            tmp_path = spool_file.with_suffix(spool_file.suffix + ".tmp")
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            fd = os.open(
                str(tmp_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(combined) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, spool_file)
            fcntl.flock(lk, fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001
        try:
            # Only emit the exception type. ``exc`` from OSError includes
            # the full user path (e.g. "/home/alice/.cohrint/...") which
            # gets captured in CI logs and stdout pipes. The type alone
            # is sufficient for a debugging hint
            # (T-PRIVACY.spool_error_path).
            print(f"  [tracker] WARN: could not write to spool ({type(exc).__name__})")
        except Exception:  # noqa: BLE001
            pass


def _spool_drain() -> list[dict[str, Any]]:
    """Read and delete the spool file. Returns list of event dicts."""
    import sys as _sys
    _mod = _sys.modules[__name__]
    spool_file = getattr(_mod, "_SPOOL_FILE")
    spool_lock_file = getattr(_mod, "_SPOOL_LOCK_FILE")
    try:
        import fcntl
        from .process_safety import open_lockfile
        # Cross-process lock — serializes drain vs concurrent _spool_write
        # so we don't race read vs append (T-SAFETY.spool_cross_process).
        try:
            spool_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            pass
        with _spool_lock, open_lockfile(spool_lock_file) as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                rfd = os.open(str(spool_file), os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(rfd, "rb") as rf:
                    if os.fstat(rf.fileno()).st_size > _MAX_SPOOL_BYTES:
                        lines = []
                    else:
                        raw = rf.read(_MAX_SPOOL_BYTES + 1)
                        if len(raw) > _MAX_SPOOL_BYTES:
                            lines = []
                        else:
                            lines = raw.decode(
                                "utf-8", errors="replace"
                            ).splitlines()
                spool_file.unlink(missing_ok=True)
            except FileNotFoundError:
                fcntl.flock(lk, fcntl.LOCK_UN)
                return []
            fcntl.flock(lk, fcntl.LOCK_UN)
        events: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # corrupt line — skip
        return events
    except Exception:  # noqa: BLE001
        return []


# Closed set. Any value outside this table is normalised to the strictest
# sensible default ("anonymized") rather than silently falling through to
# the full-telemetry branch — guards the Finding-6 class where a config
# typo like "FULL" would bypass every `privacy == "..."` comparison and
# leak agent_name in cleartext.
_VALID_PRIVACY = frozenset({"full", "strict", "anonymized", "local-only"})


def _normalize_privacy(value: object) -> str:
    if isinstance(value, str) and value in _VALID_PRIVACY:
        return value
    return "anonymized"


_PRIVACY_RANK = {"full": 0, "strict": 1, "anonymized": 2, "local-only": 3}


def _enforce_privacy(event: dict[str, Any], current: str) -> dict[str, Any]:
    """Strip fields from a spooled event so its content can't be stricter
    than the current privacy level. No-op if the event was never tagged
    (old spool format) — we default to treating as the strictest, since
    we can't know its original level (T-PRIVACY.spool_reanonymize)."""
    spooled_level = event.get("_privacy")
    cur = _PRIVACY_RANK.get(current, 2)
    src = _PRIVACY_RANK.get(spooled_level if isinstance(spooled_level, str) else "", -1)
    out = {k: v for k, v in event.items() if k != "_privacy"}
    if cur >= _PRIVACY_RANK["strict"] or src < cur:
        out.pop("agent_name", None)
    if cur >= _PRIVACY_RANK["anonymized"] or src < cur:
        out.pop("team", None)
        # event_id may have been raw; rehash just in case.
        raw = out.get("event_id")
        if isinstance(raw, str) and len(raw) != 64:
            out["event_id"] = hashlib.sha256(raw.encode()).hexdigest()
    return out


def _telemetry_opted_out() -> bool:
    """Honour the community opt-out standards: COHRINT_NO_TELEMETRY=1
    and DO_NOT_TRACK=1 (consoledonottrack.com). Either one forces the
    tracker into local-only mode — no spool flush, no HTTP, no OTel
    (T-PRIVACY.opt_out)."""
    return (
        os.environ.get("COHRINT_NO_TELEMETRY") == "1"
        or os.environ.get("DO_NOT_TRACK") == "1"
    )


@dataclass
class TrackerConfig:
    api_key: str = ""
    api_base: str = "https://api.cohrint.com"
    batch_size: int = 10
    flush_interval: float = 30.0  # seconds
    privacy: str = "full"  # full | strict | anonymized | local-only
    debug: bool = False

    def __post_init__(self) -> None:
        self.privacy = _normalize_privacy(self.privacy)


@dataclass
class DashboardEvent:
    event_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    latency_ms: int
    environment: str = "cli"
    agent_name: str = "cohrint-agent"
    team: str = "default"
    session_id: str = ""


PROVIDER_MAP = {
    "claude": "anthropic",
    "codex": "openai",
    "gemini": "google",
}


class Tracker:
    """Batched telemetry sender for the Cohrint dashboard."""

    def __init__(self, config: TrackerConfig) -> None:
        self.config = config
        self._queue: list[DashboardEvent] = []
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._running = False
        # Guards reads/writes of _running and _timer so the periodic
        # callback cannot reschedule after stop() (T-CONCUR.timer_race).
        # Separate from _lock to avoid grabbing the large queue lock just
        # to flip a boolean.
        self._state_lock = threading.Lock()

    def start(self) -> None:
        if (
            self.config.privacy == "local-only"
            or not self.config.api_key
            or _telemetry_opted_out()
        ):
            return
        with self._state_lock:
            self._running = True
        self._schedule_flush()

    def stop(self) -> None:
        # Flip the flag and cancel the pending timer under the state lock
        # so a concurrent _flush_and_reschedule observes a coherent view.
        with self._state_lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self.flush()

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        agent_name: str = "cohrint-agent",
        session_id: str = "",
    ) -> None:
        """Queue a usage event."""
        raw_event_id = str(uuid.uuid4())

        if self.config.privacy == "anonymized":
            hashed_id = hashlib.sha256(raw_event_id.encode()).hexdigest()
            # Hash session_id too (T-PRIVACY.session_id). A raw session_id
            # is stable across every turn of a user's session, so leaving
            # it unredacted lets an observer reconstruct the full turn
            # sequence — the exact re-identification attack anonymized
            # mode is meant to prevent.
            hashed_session = (
                hashlib.sha256(session_id.encode()).hexdigest() if session_id else ""
            )
            event = DashboardEvent(
                event_id=hashed_id,
                provider=PROVIDER_MAP.get(agent_name, "unknown"),
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                total_cost_usd=cost_usd,
                latency_ms=latency_ms,
                agent_name="",
                team="",
                session_id=hashed_session,
            )
        else:
            event = DashboardEvent(
                event_id=raw_event_id,
                provider=PROVIDER_MAP.get(agent_name, "unknown"),
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                total_cost_usd=cost_usd,
                latency_ms=latency_ms,
                agent_name=agent_name,
                session_id=session_id,
            )
        with self._lock:
            # Drop oldest once the ceiling is hit rather than letting the
            # queue grow unboundedly when the endpoint is wedged (T-BOUNDS.queue).
            if len(self._queue) >= MAX_QUEUE_SIZE:
                self._queue.pop(0)
            self._queue.append(event)
            if len(self._queue) >= self.config.batch_size:
                self._do_flush()

    def flush(self) -> None:
        with self._lock:
            self._do_flush()

    def _do_flush(self) -> None:
        if not self._queue or not self.config.api_key:
            return
        # Opt-out honoured at the flush boundary too, so a late env change
        # or a tracker started before the env was set still stops sending.
        if _telemetry_opted_out():
            return
        # T-SAFETY.11: never send the bearer token over plaintext. Refusing
        # also spools events so switching back to HTTPS replays them.
        if not _assert_https_api_base(self.config.api_base):
            if self.config.debug:
                print(
                    f"  [tracker] refusing non-HTTPS api_base "
                    f"({self.config.api_base!r}) — spooling "
                    f"{len(self._queue)} events"
                )
            batch = self._queue[:]
            events = [
                {
                    "event_id": e.event_id,
                    "provider": e.provider,
                    "model": e.model,
                    "prompt_tokens": e.prompt_tokens,
                    "completion_tokens": e.completion_tokens,
                    "total_tokens": e.total_tokens,
                    "total_cost_usd": e.total_cost_usd,
                    "latency_ms": e.latency_ms,
                    "environment": e.environment,
                    "agent_name": e.agent_name,
                    "team": e.team,
                    # Tag with the privacy level at spool time so a later
                    # downgrade (full → anonymized) can re-strip on drain
                    # (T-PRIVACY.spool_privacy_tag).
                    "_privacy": self.config.privacy,
                }
                for e in batch
            ]
            _spool_write(events)
            self._queue = [e for e in self._queue if e not in batch]
            return
        batch = self._queue[:]  # snapshot — do NOT clear yet

        events = []
        for e in batch:
            data: dict[str, Any] = {
                "event_id": e.event_id,
                "provider": e.provider,
                "model": e.model,
                "prompt_tokens": e.prompt_tokens,
                "completion_tokens": e.completion_tokens,
                "total_tokens": e.total_tokens,
                "total_cost_usd": e.total_cost_usd,
                "latency_ms": e.latency_ms,
                "environment": e.environment,
                "agent_name": e.agent_name,
                "team": e.team,
            }
            if self.config.privacy == "strict":
                data.pop("agent_name", None)
            events.append(data)

        # Drain any previously spooled events and prepend to this batch.
        # Drained before the request so a successful send clears the spool.
        spooled = _spool_drain()
        # Re-apply the current privacy level to drained events so that
        # events spooled in "full" mode can't leak agent_name upstream
        # after the user downgrades to "anonymized"/"strict"
        # (T-PRIVACY.spool_reanonymize).
        spooled = [_enforce_privacy(e, self.config.privacy) for e in spooled]
        all_events = spooled + events

        try:
            url = f"{self.config.api_base}/v1/events/batch"
            # Per-phase timeouts so a server that stalls mid-body can't hold
            # the tracker thread hostage (T-BOUNDS.timeout). Scalar timeout=10
            # would let a 1-byte/s trickle delay flush for the full wall.
            resp = httpx.post(
                url,
                json={"events": all_events},
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": f"cohrint-agent/{__version__}",
                },
                timeout=httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0),
            )
            # 200/201/202 are the real success codes. 3xx was previously
            # folded in via ``< 400`` which silently dropped drained spool
            # events whenever a middlebox / misconfigured proxy returned a
            # 301/302/307 (T-SAFETY.tracker_redirect_no_success). Explicit
            # allowlist fixes it.
            if resp.status_code in (200, 201, 202, 204):
                # Only clear on success
                self._queue = [e for e in self._queue if e not in batch]
                if self.config.debug:
                    extra = f" (+{len(spooled)} spooled)" if spooled else ""
                    print(f"  [tracker] flushed {len(events)}{extra} events → {resp.status_code}")
                # Fire-and-forget OTel export for each event in the batch
                _otel = OTelExporter()
                for e in batch:
                    # Defence-in-depth: hash session_id HERE too. OTelExporter
                    # also hashes, but if a future refactor breaks that path
                    # the tracker layer still prevents raw-UUID leakage to
                    # the collector (T-PRIVACY.session_id_double_hash).
                    hashed_sid = (
                        hashlib.sha256(e.session_id.encode()).hexdigest()
                        if e.session_id else ""
                    )
                    _otel.export_async({
                        "model": e.model,
                        "prompt_tokens": e.prompt_tokens,
                        "completion_tokens": e.completion_tokens,
                        "total_cost_usd": e.total_cost_usd,
                        "cost_usd": e.total_cost_usd,
                        "latency_ms": e.latency_ms,
                        "session_id": hashed_sid,
                    })
            elif resp.status_code == 503:
                # Service unavailable — spool current batch for later retry
                if self.config.debug:
                    print(f"  [tracker] 503 received — spooling {len(events)} events (+{len(spooled)} re-spooled)")
                _spool_write(all_events)
                # Clear from in-memory queue (spool takes over)
                self._queue = [e for e in self._queue if e not in batch]
            else:
                if self.config.debug:
                    print(f"  [tracker] flush failed: HTTP {resp.status_code} — events retained")
                # Re-spool the drained events so they aren't lost
                if spooled:
                    _spool_write(spooled)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, OSError) as exc:
            # Connection/network error — spool for later retry.
            # Emit only the exception TYPE to stdout. Raw exception text
            # from httpx routinely includes the full URL, resolved IP,
            # and — on 4xx TLS rejections — fragments of server response
            # bodies that might echo the bearer token back
            # (T-PRIVACY.connect_error_redacted).
            if self.config.debug:
                print(
                    f"  [tracker] connection error — spooling {len(events)} events "
                    f"({type(exc).__name__})"
                )
            _spool_write(all_events)
            self._queue = [e for e in self._queue if e not in batch]
        except Exception as exc:
            if self.config.debug:
                print(
                    f"  [tracker] flush error ({type(exc).__name__}) — events retained"
                )
            if spooled:
                _spool_write(spooled)

    def _schedule_flush(self) -> None:
        # Re-check _running and assign _timer atomically so stop() cannot
        # miss the timer we're about to start (T-CONCUR.timer_race). Without
        # this guard stop() might run cancel() on a stale reference while
        # this method spawns a fresh, unreachable Timer that fires later.
        with self._state_lock:
            if not self._running:
                return
            t = threading.Timer(self.config.flush_interval, self._flush_and_reschedule)
            t.daemon = True
            self._timer = t
            t.start()

    def _flush_and_reschedule(self) -> None:
        # Skip the flush if shutdown already started — prevents a final
        # 15 s HTTP hang right after stop() when the timer races the flag.
        with self._state_lock:
            if not self._running:
                return
        self.flush()
        self._schedule_flush()
