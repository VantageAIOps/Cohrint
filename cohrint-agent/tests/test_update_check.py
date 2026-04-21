"""
test_update_check.py — Regression tests for the startup upgrade check.

Guards test-IDs from CLI_MIGRATION_PLAN.md:
  T-UPGRADE.1  — stale local version triggers "Update available" banner
  T-UPGRADE.2  — min_supported_version newer than local forces exit(1)
  T-SAFETY.8   — malicious version string with OSC-52 escape is rejected
  T-SAFETY.5/6 — install_cmd with terminal escapes is replaced by default
  T-SAFETY.11  — http:// api_base refused unless COHRINT_ALLOW_HTTP=1 + localhost
"""
from __future__ import annotations

import io
import os
from unittest.mock import patch

import pytest

from cohrint_agent.update_check import (
    DEFAULT_INSTALL_CMD,
    UpdateInfo,
    _assert_https_api_base,
    _is_safe_install_cmd,
    _is_safe_notice,
    _is_valid_version,
    check_for_update,
    is_newer_version,
)


# -------------------------- is_newer_version --------------------------

@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("0.3.0", "0.2.4", True),
        ("0.2.5", "0.2.4", True),
        ("1.0.0", "0.9.9", True),
        ("0.2.4", "0.2.4", False),          # equal
        ("0.2.3", "0.2.4", False),          # older
        ("0.2.4-beta.1", "0.2.4", False),   # pre-release strips to equal
        ("0.2.5-beta.1", "0.2.4", True),    # pre-release of newer still newer
        ("1.2", "1.2.0", False),            # pad to 3 fields
        ("garbage", "0.2.4", False),        # invalid → False, no crash
        ("0.2.4", "", False),               # empty current → False
    ],
)
def test_is_newer_version(latest, current, expected):
    assert is_newer_version(latest, current) is expected


# -------------------------- validators --------------------------

def test_valid_version_accepts_semver():
    assert _is_valid_version("0.2.4")
    assert _is_valid_version("10.20.30")
    assert _is_valid_version("2.2.5-beta.1")


def test_valid_version_rejects_escapes():
    # T-SAFETY.8: OSC-52 injection in the version field
    assert not _is_valid_version("1.2.3\x1b]52;c;AAA\x07")
    assert not _is_valid_version("1.2.3\n")
    assert not _is_valid_version("1.2.3 ")
    assert not _is_valid_version("")
    assert not _is_valid_version(None)
    assert not _is_valid_version(12345)
    assert not _is_valid_version("A" * 65)  # length cap


def test_safe_install_cmd():
    assert _is_safe_install_cmd("pip install -U cohrint-agent")
    assert not _is_safe_install_cmd("pip\x1b[31m")       # CSI escape
    assert not _is_safe_install_cmd("pip\n install")     # newline
    assert not _is_safe_install_cmd("")
    assert not _is_safe_install_cmd("x" * 201)           # over cap


def test_safe_notice():
    assert _is_safe_notice("Planned outage at 03:00 UTC")
    assert not _is_safe_notice("notice\x1b]52;c;X\x07")
    assert not _is_safe_notice("")
    assert not _is_safe_notice("x" * 501)


# -------------------------- assert_https --------------------------

def test_https_required_by_default():
    assert _assert_https_api_base("https://api.cohrint.com")
    assert not _assert_https_api_base("http://api.cohrint.com")
    assert not _assert_https_api_base("ftp://api.cohrint.com")
    assert not _assert_https_api_base("")
    assert not _assert_https_api_base(None)


def test_http_localhost_allowed_with_env():
    with patch.dict(os.environ, {"COHRINT_ALLOW_HTTP": "1"}, clear=False):
        assert _assert_https_api_base("http://localhost:8787")
        assert _assert_https_api_base("http://127.0.0.1:8787")
        # Public host still refused even with allow-flag
        assert not _assert_https_api_base("http://evil.example")


def test_http_localhost_refused_without_env():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("COHRINT_ALLOW_HTTP", None)
        assert not _assert_https_api_base("http://localhost:8787")


# -------------------------- check_for_update --------------------------

def _make_exit_capture():
    called = {"code": None}

    def fake_exit(code=0):
        called["code"] = code
        raise SystemExit(code)

    return called, fake_exit


def test_banner_when_newer_version(monkeypatch):
    # T-UPGRADE.1: remote newer than local → banner on stderr.
    info = UpdateInfo(
        version="0.3.0",
        install_cmd="pip install --upgrade cohrint-agent",
        notice=None,
        min_supported=None,
    )
    buf = io.StringIO()
    out = check_for_update(
        current="0.2.4",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: info,
    )
    assert out is info
    text = buf.getvalue()
    assert "Update available" in text
    assert "0.2.4 → 0.3.0" in text
    assert "pip install --upgrade cohrint-agent" in text


def test_no_banner_when_up_to_date():
    info = UpdateInfo("0.2.4", DEFAULT_INSTALL_CMD, None, None)
    buf = io.StringIO()
    check_for_update(
        current="0.2.4",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: info,
    )
    assert buf.getvalue() == ""


def test_no_banner_when_local_is_newer():
    # Dev build > published.
    info = UpdateInfo("0.2.4", DEFAULT_INSTALL_CMD, None, None)
    buf = io.StringIO()
    check_for_update(
        current="0.3.0-dev",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: info,
    )
    assert buf.getvalue() == ""


def test_forced_upgrade_exits():
    # T-UPGRADE.2: min_supported > local → exit(1).
    info = UpdateInfo(
        version="0.3.0",
        install_cmd="pip install --upgrade cohrint-agent",
        notice=None,
        min_supported="0.3.0",
    )
    called, fake_exit = _make_exit_capture()
    buf = io.StringIO()
    with pytest.raises(SystemExit):
        check_for_update(
            current="0.2.4",
            writer=buf,
            exit_fn=fake_exit,
            fetcher=lambda: info,
        )
    assert called["code"] == 1
    text = buf.getvalue()
    assert "below the minimum supported version" in text
    assert "0.3.0" in text


def test_fetch_failure_is_silent():
    # Network error should NOT crash the CLI, NOT print anything.
    buf = io.StringIO()
    out = check_for_update(
        current="0.2.4",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert out is None
    assert buf.getvalue() == ""


def test_fetcher_returns_none_is_silent():
    buf = io.StringIO()
    out = check_for_update(
        current="0.2.4",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: None,
    )
    assert out is None
    assert buf.getvalue() == ""


def test_skip_env_disables_check():
    info = UpdateInfo("99.0.0", DEFAULT_INSTALL_CMD, None, None)
    buf = io.StringIO()
    with patch.dict(os.environ, {"COHRINT_SKIP_UPDATE_CHECK": "1"}, clear=False):
        out = check_for_update(
            current="0.2.4",
            writer=buf,
            exit_fn=lambda *_: None,
            fetcher=lambda: info,
        )
    assert out is None
    assert buf.getvalue() == ""


def test_notice_rendered_when_safe():
    info = UpdateInfo(
        version="0.3.0",
        install_cmd=DEFAULT_INSTALL_CMD,
        notice="Security fix for prompt-injection — upgrade promptly.",
        min_supported=None,
    )
    buf = io.StringIO()
    check_for_update(
        current="0.2.4",
        writer=buf,
        exit_fn=lambda *_: None,
        fetcher=lambda: info,
    )
    assert "Security fix" in buf.getvalue()


# -------------------------- fetch validators (integration-ish) --------------------------

def test_fetch_rejects_escape_version(monkeypatch):
    """T-SAFETY.8: poisoned payload from /v1/cli/latest never renders."""
    from cohrint_agent import update_check

    def fake_reader(url, *, max_bytes, headers=None):
        # Simulate a MITM'd endpoint returning an OSC-52 payload.
        return {
            "version": "1.2.3\x1b]52;c;AAA\x07",
            "install_cmd": "pip install --upgrade cohrint-agent",
            "min_supported_version": None,
            "notice": None,
        }

    monkeypatch.setattr(update_check, "_safe_read_json", fake_reader)
    info = update_check._fetch_from_cohrint("https://api.cohrint.com", None)
    assert info is None


def test_fetch_scrubs_unsafe_install_cmd(monkeypatch):
    """T-SAFETY.5/6: unsafe install_cmd falls back to the baked-in default."""
    from cohrint_agent import update_check

    def fake_reader(url, *, max_bytes, headers=None):
        return {
            "version": "0.3.0",
            "install_cmd": "pip\x1b[31m install evil",  # CSI escape
            "min_supported_version": None,
            "notice": None,
        }

    monkeypatch.setattr(update_check, "_safe_read_json", fake_reader)
    info = update_check._fetch_from_cohrint("https://api.cohrint.com", None)
    assert info is not None
    assert info.install_cmd == update_check.DEFAULT_INSTALL_CMD


def test_fetch_refuses_http_base(monkeypatch):
    """HTTPS gate on primary endpoint."""
    from cohrint_agent import update_check

    called = []

    def fake_reader(url, *, max_bytes, headers=None):
        called.append(url)
        return {"version": "9.9.9"}

    monkeypatch.setattr(update_check, "_safe_read_json", fake_reader)
    monkeypatch.delenv("COHRINT_ALLOW_HTTP", raising=False)
    info = update_check._fetch_from_cohrint("http://api.cohrint.com", None)
    assert info is None
    assert called == []  # never even attempted the fetch


def test_forwards_bearer_token_header(monkeypatch):
    """Authorization header forwarded when api_key is provided."""
    from cohrint_agent import update_check

    captured = {}

    def fake_reader(url, *, max_bytes, headers=None):
        captured["headers"] = headers
        return {"version": "0.3.0"}

    monkeypatch.setattr(update_check, "_safe_read_json", fake_reader)
    info = update_check._fetch_from_cohrint(
        "https://api.cohrint.com", "crt_test_key"
    )
    assert info is not None
    assert captured["headers"]["Authorization"] == "Bearer crt_test_key"
    # user-agent always present, key not leaked into it
    assert "crt_test_key" not in captured["headers"].get("User-Agent", "")
