"""
process_safety.py — Environment sanitizer for spawned subprocesses.

Before handing `os.environ` to the Claude / codex / gemini CLI subprocesses we
strip library-injection vectors (LD_PRELOAD, DYLD_*, NODE_OPTIONS, …) so a
compromised user env cannot hijack the child. Callers may opt-in to pass
extra variables via COHRINT_PASS_ENV, but the allowlist is strict — `*` is
refused and a per-name safety regex is enforced.

Guards regression tests: T-SAFETY.1, T-SAFETY.11, T-BOUNDS.argv.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Linux kernel caps a single argv/env string at MAX_ARG_STRLEN (128 KiB).
# macOS ARG_MAX is 1 MiB total across all argv+env. We cap a single prompt
# argv element at 120 KiB so the rest of the command line (flags, model name,
# session id, settings path) stays within the per-arg limit on both
# platforms. Oversized prompts are truncated to prevent a local DoS where
# execve() refuses to spawn the agent at all.
MAX_ARGV_STRLEN = 120 * 1024


def clamp_argv(value: str, *, max_len: int = MAX_ARGV_STRLEN) -> str:
    """Truncate a string so it fits safely in a subprocess argv element."""
    if not isinstance(value, str):
        return ""
    if len(value) > max_len:
        return value[:max_len]
    return value


def _real_home() -> Path | None:
    """Resolve the user's real home from the passwd DB, NOT $HOME.

    ``Path.home()`` trusts ``$HOME``, so an attacker who flips
    ``HOME=/tmp/evil`` redirects every ``~/.cohrint-agent/*`` lookup
    into attacker-controlled space. Anchoring to the uid's pw_dir
    closes that door (T-SAFETY.home_env_hijack, scan 22).

    Returns ``None`` on minimal containers where pwd lookup fails —
    callers must handle that case.
    """
    try:
        import pwd as _pwd
        return Path(_pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except (KeyError, OSError, ImportError):
        return None


def safe_config_dir() -> Path:
    """Resolve ``COHRINT_CONFIG_DIR`` to an absolute path, reject escape.

    An attacker-controlled env may set ``COHRINT_CONFIG_DIR=/etc`` or a
    symlink that points outside ``$HOME``. We ``resolve()`` the candidate
    and require it to be within the user's **real** home (pw_dir, not
    ``$HOME``); otherwise we fall back to the default
    ``~/.cohrint-agent``. Guards T-SAFETY.config_dir_escape,
    T-SAFETY.home_env_hijack.
    """
    real = _real_home()
    # Fallback used only when pwd lookup fails entirely (minimal
    # containers); in that case we honor ``$HOME`` but warn downstream
    # via the normal default.
    home = real if real is not None else Path.home().resolve()
    default = home / ".cohrint-agent"
    raw = os.environ.get("COHRINT_CONFIG_DIR")
    if not raw:
        return default
    try:
        candidate = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return default
    if candidate == home or home in candidate.parents:
        return candidate
    # Explicit tmp_path used by tests is also allowed — callers can always
    # pass a Path directly into the relevant class constructor. The env
    # override path is the only one this helper gatekeeps.
    tmp = os.environ.get("TMPDIR") or "/tmp"
    try:
        tmp_root = Path(tmp).resolve()
        if candidate == tmp_root or tmp_root in candidate.parents:
            return candidate
    except (OSError, RuntimeError):
        pass
    return default

# Variables actively used as exec-time hijack vectors. Always stripped.
# Do NOT delete from this list without a compelling reason and a test.
_STRIP_ALWAYS = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "LD_BIND_NOW",
        "LD_DEBUG",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_FORCE_FLAT_NAMESPACE",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_VERSIONED_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_VERSIONED_FRAMEWORK_PATH",
        "DYLD_PRINT_LIBRARIES",
        "DYLD_ROOT_PATH",
        "DYLD_SHARED_REGION",
        "DYLD_IMAGE_SUFFIX",
        "NODE_OPTIONS",
        "PYTHONSTARTUP",
        "PYTHONPATH",  # leak vector into Python tools on PATH
        "PERL5OPT",
        "RUBYOPT",
        "BROWSER",  # macOS / Linux — hijackable on http opens
        # ANTHROPIC_BASE_URL is honored by the anthropic SDK — if a child
        # `claude` / `codex` subprocess inherits an attacker-set value
        # (e.g. COHRINT_PASS_ENV is bypassed on the strip check), every
        # prompt + bearer token gets POSTed to the attacker. Parent-side
        # validation in api_client covers the parent; this strip covers
        # children (T-SAFETY.anthropic_base_url_strip, scan 22).
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_BASE",
        # OpenAI / Codex mirror vectors for the CLI backends we spawn.
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    }
)

# Names must be ASCII-identifier-like. Anything else is ignored outright —
# prevents smuggling values via exotic env keys.
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def _is_valid_name(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME_RE.fullmatch(name))


def _parse_allowlist(spec: str | None) -> set[str]:
    """COHRINT_PASS_ENV='FOO,BAR' → {'FOO', 'BAR'}; `*` is refused."""
    if not spec:
        return set()
    if "*" in spec:
        return set()  # refuse — `*` would defeat the strip list
    out: set[str] = set()
    for raw in spec.split(","):
        name = raw.strip()
        if _is_valid_name(name) and name not in _STRIP_ALWAYS:
            out.add(name)
    return out


def safe_child_env(
    source: dict[str, str] | None = None,
    *,
    extra_allow: set[str] | None = None,
) -> dict[str, str]:
    """Return an environment dict safe to hand to a subprocess.

    - Strips every variable in _STRIP_ALWAYS unconditionally.
    - Preserves everything else from ``source`` (default: ``os.environ``),
      minus variables disallowed by the name regex.
    - Honours COHRINT_PASS_ENV, but that var can only RE-ADD names — it can
      never bypass _STRIP_ALWAYS.

    We do NOT start from an empty dict — the child CLIs genuinely need PATH,
    HOME, and similar. We subtract threats instead.
    """
    src = source if source is not None else os.environ
    allow_extra = set(extra_allow or set())
    pass_env = _parse_allowlist(src.get("COHRINT_PASS_ENV"))
    allowed_extra = allow_extra | pass_env  # both layers are additive

    out: dict[str, str] = {}
    for name, value in src.items():
        if not _is_valid_name(name):
            continue
        if name in _STRIP_ALWAYS:
            # The allowlist cannot override _STRIP_ALWAYS. This is intentional.
            continue
        if not isinstance(value, str):
            continue
        out[name] = value

    # The allowlist is a marker — it cannot re-admit anything the strip set
    # rejected. We keep it in the signature so callers can opt-in to
    # explicit extras in future (e.g. tests), but only if not in _STRIP_ALWAYS.
    for name in allowed_extra:
        if name in _STRIP_ALWAYS:
            continue
        if _is_valid_name(name) and name in src and isinstance(src[name], str):
            out[name] = src[name]

    return out


# ────────────── binary resolver (scan 22, T-SAFETY.backend_path_pin) ───────
#
# Child CLIs (claude / codex / gemini / aider) are spawned by argv[0] bare
# name, which leaves the choice of binary to the inherited PATH. A writable
# earlier PATH entry (e.g. ``~/.local/bin``) beats the system install and
# receives every prompt verbatim. Resolve once at backend init and pin the
# absolute path; bail if the resolved file is writable by group/other.

_BACKEND_BIN_CACHE: dict[str, str | None] = {}


def resolve_backend_binary(name: str) -> str | None:
    """Return an absolute path for ``name`` on PATH, or None if missing / unsafe.

    Rejects a resolved path whose directory or the binary itself has
    group/other write bits — matches what ``ssh -V`` would tolerate for a
    trusted helper. Cached on first lookup.
    """
    import shutil as _shutil
    if name in _BACKEND_BIN_CACHE:
        return _BACKEND_BIN_CACHE[name]
    path = _shutil.which(name)
    if not path:
        _BACKEND_BIN_CACHE[name] = None
        return None
    try:
        real = os.path.realpath(path)
        st = os.stat(real)
    except OSError:
        _BACKEND_BIN_CACHE[name] = None
        return None
    # Refuse group/other writable binaries.
    if st.st_mode & 0o022:
        _BACKEND_BIN_CACHE[name] = None
        return None
    _BACKEND_BIN_CACHE[name] = real
    return real


# ────────────── lock-file helper (scan 18, T-SAFETY.lockfile_nofollow) ─────
# Python's open() on a lock path follows symlinks: `open(path, "w")` under
# O_TRUNC zero-truncates whatever the symlink points at, and `open(path, "a+")`
# still resolves the symlink. A local attacker with write access to the config
# dir can plant `rate_state.lock → ~/.bashrc` to either truncate a user file
# or hand the process an fd into an attacker-chosen target. We open via
# os.open with O_NOFOLLOW so the symlink swap yields ELOOP instead.
def open_lockfile(path):
    """Open a lock-file fd with O_NOFOLLOW, 0o600. Returns a file object.

    Caller owns the lifecycle; wrap in ``with`` or close explicitly. Only
    callers doing ``fcntl.flock`` should use this — for plain config/state
    writes use the atomic tmp+os.replace pattern instead.
    """
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    return os.fdopen(fd, "w")
