"""
guardrails — toggles for recommendation + hallucination guardrails.

Persists to ``~/.cohrint-agent/config.json``. The prompt pipeline reads
``get_settings()`` at turn start and prepends a short system message
reflecting the enabled guardrails. Keeping the store here (not in
settings.json) avoids colliding with Claude Code's schema — this is a
cohrint concept, not a Claude one.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

KINDS = ("recommendation", "hallucination")


@dataclass
class GuardrailSettings:
    recommendation: bool = True
    hallucination: bool = True


def _home() -> Path:
    try:
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001
        return Path.home()


def _config_path() -> Path:
    return _home() / ".cohrint-agent" / "config.json"


def _read_config() -> dict:
    path = _config_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write_config(data: dict) -> None:
    """Write config atomically. PID-suffixed tmp avoids concurrent-write races
    between two `cohrint-agent guardrails` invocations running at the same
    time (common for scripted flips)."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


def get_settings() -> GuardrailSettings:
    data = _read_config().get("guardrails") or {}
    return GuardrailSettings(
        recommendation=bool(data.get("recommendation", True)),
        hallucination=bool(data.get("hallucination", True)),
    )


def set_kind(kind: str, *, enabled: bool) -> GuardrailSettings:
    """Flip one kind (or ``all``) and persist."""
    if kind not in KINDS and kind != "all":
        raise ValueError(f"unknown guardrail '{kind}'. Valid: {', '.join(KINDS)} or 'all'")
    data = _read_config()
    bucket = data.setdefault("guardrails", {})
    if kind == "all":
        for k in KINDS:
            bucket[k] = enabled
    else:
        bucket[kind] = enabled
    _write_config(data)
    return get_settings()


def system_preamble() -> str:
    """Render a short system-prompt preamble reflecting active guardrails.

    Returned string is empty when all guardrails are off — caller should
    skip prepending entirely in that case.
    """
    s = get_settings()
    lines: list[str] = []
    if s.recommendation:
        lines.append(
            "- Recommendation guardrail: when uncertain, recommend the safest "
            "option and explicitly state remaining risk."
        )
    if s.hallucination:
        lines.append(
            "- Hallucination guardrail: never invent file paths, APIs, or "
            "function signatures. If unsure, say 'I don't know' and offer "
            "how to verify."
        )
    if not lines:
        return ""
    return "Cohrint guardrails (active):\n" + "\n".join(lines)


__all__ = [
    "GuardrailSettings",
    "KINDS",
    "get_settings",
    "set_kind",
    "system_preamble",
]
