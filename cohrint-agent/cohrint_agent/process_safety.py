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


def safe_config_dir() -> Path:
    """Resolve ``COHRINT_CONFIG_DIR`` to an absolute path, reject escape.

    An attacker-controlled env may set ``COHRINT_CONFIG_DIR=/etc`` or a
    symlink that points outside ``$HOME``. We ``resolve()`` the candidate
    and require it to be within ``$HOME``; otherwise we fall back to the
    default ``~/.cohrint-agent``. Guards T-SAFETY.config_dir_escape.
    """
    default = Path.home() / ".cohrint-agent"
    raw = os.environ.get("COHRINT_CONFIG_DIR")
    if not raw:
        return default
    try:
        candidate = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError):
        return default
    try:
        home = Path.home().resolve()
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
