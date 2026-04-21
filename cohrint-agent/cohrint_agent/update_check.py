"""
update_check.py — CLI self-update check.

Ports `checkForUpdate()` from the Node cohrint-cli. Fires at startup against
`/v1/cli/latest` (primary) with a PyPI fallback. All incoming strings are
validated against strict regexes before being printed — a MITM'd registry
response could otherwise inject OSC-52 / CSI terminal escapes via the
`version` or `install_cmd` fields.

Security guarantees (regression test IDs in parens):
- Version strings must match ``^[A-Za-z0-9._\\-+]{1,64}$``     (T-SAFETY.8, T-UPGRADE.*)
- Install commands must be printable ASCII, length <= 200      (T-SAFETY.5, T-SAFETY.6)
- Notice field must be printable ASCII, length <= 500          (T-SAFETY.5)
- min_supported_version > local → hard exit(1) with message    (T-UPGRADE.2)
- Network call bounded to 2 s (socket timeout) per endpoint.
- All fetches tolerate any exception — the CLI never crashes from this path.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

# Primary endpoint — CLI-language-agnostic. We pass `?client=python` so the
# worker can return the pip install command + correct `min_supported_version`
# for this package. Legacy Node CLI keeps hitting the same path with no query
# and gets npm-flavoured values.
COHRINT_UPDATE_PATH = "/v1/cli/latest"

# Fallback: query PyPI directly if the Cohrint endpoint is unreachable. We
# accept at most 256 KiB of JSON from PyPI (it usually returns far more —
# we only read the `info.version` key).
PYPI_URL = "https://pypi.org/pypi/cohrint-agent/json"

DEFAULT_API_BASE = "https://api.cohrint.com"
DEFAULT_INSTALL_CMD = "pip install --upgrade cohrint-agent"

# Byte caps for response bodies. Anything larger is refused — prevents a
# poisoned endpoint from driving us OOM on startup.
_COHRINT_MAX_BYTES = 64 * 1024
_PYPI_MAX_BYTES = 256 * 1024
_TIMEOUT_SEC = 2.0

# Use fullmatch semantics — Python's `$` would otherwise match before a
# trailing `\n`, which is exactly the escape-smuggling class we're blocking.
_VERSION_RE = re.compile(r"[A-Za-z0-9._\-+]{1,64}")
_PRINTABLE_ASCII_RE = re.compile(r"[\x20-\x7e]+")


@dataclass
class UpdateInfo:
    version: str
    install_cmd: str
    notice: str | None
    min_supported: str | None


def _is_valid_version(value: object) -> bool:
    return isinstance(value, str) and bool(_VERSION_RE.fullmatch(value))


def _is_safe_install_cmd(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and bool(_PRINTABLE_ASCII_RE.fullmatch(value))
    )


def _is_safe_notice(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 500
        and bool(_PRINTABLE_ASCII_RE.fullmatch(value))
    )


def _strip_prerelease(v: str) -> str:
    # "2.2.5-beta.1" → "2.2.5" so int() doesn't choke.
    return v.split("-", 1)[0].split("+", 1)[0]


def is_newer_version(latest: str, current: str) -> bool:
    """True iff ``latest`` strictly > ``current`` (major.minor.patch)."""
    try:
        l_parts = [int(p) for p in _strip_prerelease(latest).split(".")[:3]]
        c_parts = [int(p) for p in _strip_prerelease(current).split(".")[:3]]
    except (ValueError, AttributeError):
        return False
    # Pad to 3 fields so "1.2" vs "1.2.0" compares correctly.
    while len(l_parts) < 3:
        l_parts.append(0)
    while len(c_parts) < 3:
        c_parts.append(0)
    return tuple(l_parts) > tuple(c_parts)


def _assert_https_api_base(api_base: str) -> bool:
    """Reject http:// unless the user explicitly opted in for localhost dev.

    Also refuses **IP-literal** endpoints that resolve to private, loopback,
    or link-local ranges (RFC-1918, 127.0.0.0/8, 169.254.0.0/16, ::1, fe80::/10).
    The concrete attack: an attacker who flips ``OTEL_EXPORTER_OTLP_ENDPOINT``
    or ``COHRINT_API_BASE`` to ``https://169.254.169.254`` would otherwise
    have Bearer tokens POSTed to the AWS/GCP metadata service
    (T-SAFETY.ssrf_private_ip). Hostnames are not resolved here (that would
    be TOCTOU); only literal IPs are parsed — which covers the metadata-IP
    class of attack without requiring a stateful connection check.
    """
    if not isinstance(api_base, str) or not api_base:
        return False
    allow_local = os.environ.get("COHRINT_ALLOW_HTTP") == "1"

    # Parse scheme + host up front.
    if api_base.startswith("https://"):
        scheme = "https"
        rest = api_base[len("https://"):]
    elif api_base.startswith("http://"):
        scheme = "http"
        rest = api_base[len("http://"):]
    else:
        return False

    host = rest.split("/", 1)[0]
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    else:
        host = host.split(":", 1)[0]
    if not host:
        return False

    if scheme == "http":
        # Plaintext is only ever allowed with the opt-in AND to a
        # localhost literal — never to an arbitrary DNS name.
        if not allow_local:
            return False
        return host in ("localhost", "127.0.0.1", "::1")

    # HTTPS: block IP-literal private/metadata/loopback/link-local unless
    # the user opts in. DNS names fall through to True (we trust the
    # resolver; full socket-layer SSRF is out of scope).
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return allow_local
    return True


def _safe_read_json(url: str, *, max_bytes: int, headers: dict[str, str] | None = None):
    """Fetch JSON with hard timeout + byte cap. Returns parsed dict or None."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        # Use default system SSL context — do NOT disable verification.
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC, context=ctx) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return None  # refuse oversize payloads
            return json.loads(raw.decode("utf-8", errors="strict"))
    except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError):
        return None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    except (TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001 — fetcher must never raise
        return None


def _fetch_from_cohrint(api_base: str, api_key: str | None) -> UpdateInfo | None:
    if not _assert_https_api_base(api_base):
        return None
    url = api_base.rstrip("/") + COHRINT_UPDATE_PATH + "?client=python"
    headers: dict[str, str] = {"User-Agent": "cohrint-agent/update-check"}
    if api_key:
        # Never log; just forward. The endpoint may use this for per-plan notices.
        headers["Authorization"] = f"Bearer {api_key}"
    data = _safe_read_json(url, max_bytes=_COHRINT_MAX_BYTES, headers=headers)
    if not isinstance(data, dict):
        return None
    if not _is_valid_version(data.get("version")):
        return None
    install = data.get("install_cmd")
    if not _is_safe_install_cmd(install):
        install = DEFAULT_INSTALL_CMD
    min_supported = data.get("min_supported_version")
    min_supported = min_supported if _is_valid_version(min_supported) else None
    notice = data.get("notice")
    notice = notice if _is_safe_notice(notice) else None
    return UpdateInfo(
        version=data["version"],
        install_cmd=install,
        notice=notice,
        min_supported=min_supported,
    )


def _fetch_from_pypi() -> UpdateInfo | None:
    data = _safe_read_json(
        PYPI_URL,
        max_bytes=_PYPI_MAX_BYTES,
        headers={"User-Agent": "cohrint-agent/update-check"},
    )
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    if not _is_valid_version(version):
        return None
    return UpdateInfo(
        version=version,
        install_cmd=DEFAULT_INSTALL_CMD,
        notice=None,
        min_supported=None,
    )


def fetch_latest(api_base: str, api_key: str | None) -> UpdateInfo | None:
    """Primary → fallback. Returns None if both fail — caller should no-op."""
    return _fetch_from_cohrint(api_base, api_key) or _fetch_from_pypi()


def check_for_update(
    current: str,
    api_base: str = DEFAULT_API_BASE,
    api_key: str | None = None,
    *,
    writer=sys.stderr,
    exit_fn=sys.exit,
    fetcher=None,
) -> UpdateInfo | None:
    """Run the startup update check.

    - Prints a yellow "update available" banner when the remote version is newer.
    - If ``min_supported_version`` is newer than ``current`` the caller process
      is terminated via ``exit_fn(1)`` — this is the forced-upgrade gate.

    ``fetcher``/``writer``/``exit_fn`` are injectable for tests.
    """
    if os.environ.get("COHRINT_SKIP_UPDATE_CHECK") == "1":
        return None
    fetch = fetcher or (lambda: fetch_latest(api_base, api_key))
    try:
        info = fetch()
    except Exception:  # noqa: BLE001
        return None
    if info is None:
        return None

    # Forced upgrade: local < min_supported → refuse service.
    if info.min_supported and is_newer_version(info.min_supported, current):
        writer.write(
            f"\n  cohrint-agent {current} is below the minimum supported "
            f"version ({info.min_supported}).\n"
        )
        writer.write("  Please upgrade before continuing.\n")
        writer.write(f"  Run: {info.install_cmd}\n\n")
        writer.flush()
        exit_fn(1)
        return info  # unreachable under real sys.exit; kept for test ergonomics

    if is_newer_version(info.version, current):
        writer.write(
            f"\n  Update available: cohrint-agent {current} → {info.version}\n"
        )
        writer.write(f"  Run: {info.install_cmd}\n")
        if info.notice:
            writer.write(f"  {info.notice}\n")
        writer.write("\n")
        writer.flush()

    return info
