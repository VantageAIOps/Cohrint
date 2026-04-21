"""Tests for cohrint_agent.delegate — exec_backend passthrough."""
from __future__ import annotations

from unittest import mock

import pytest

from cohrint_agent.delegate import DelegateError, SUPPORTED_BACKENDS, exec_backend


def test_unknown_backend_raises():
    with pytest.raises(DelegateError) as exc:
        exec_backend("nosuchagent", ["--help"])
    assert "unknown backend" in str(exc.value)


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(
        "cohrint_agent.delegate.resolve_backend_binary",
        lambda name: None,
    )
    with pytest.raises(DelegateError) as exc:
        exec_backend("claude", ["mcp", "list"])
    assert "claude" in str(exc.value)
    assert "not found" in str(exc.value)


def test_execvpe_invoked_with_resolved_path(monkeypatch):
    calls: list[tuple] = []

    def fake_execvpe(path, argv, env):
        calls.append((path, list(argv), dict(env)))
        raise SystemExit(0)  # simulate exec replacement

    monkeypatch.setattr(
        "cohrint_agent.delegate.resolve_backend_binary",
        lambda name: "/usr/local/bin/claude",
    )
    monkeypatch.setattr("os.execvpe", fake_execvpe)

    with pytest.raises(SystemExit):
        exec_backend("claude", ["mcp", "add", "foo"])

    assert len(calls) == 1
    path, argv, env = calls[0]
    assert path == "/usr/local/bin/claude"
    assert argv == ["/usr/local/bin/claude", "mcp", "add", "foo"]
    # env is sanitised — LD_PRELOAD must not leak through even if set.
    assert "LD_PRELOAD" not in env


def test_safe_child_env_stripped(monkeypatch):
    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/tmp/evil.dylib")
    monkeypatch.setattr(
        "cohrint_agent.delegate.resolve_backend_binary",
        lambda name: "/usr/local/bin/claude",
    )

    captured_env = {}

    def fake_execvpe(_path, _argv, env):
        captured_env.update(env)
        raise SystemExit(0)

    monkeypatch.setattr("os.execvpe", fake_execvpe)
    with pytest.raises(SystemExit):
        exec_backend("claude", [])
    assert "LD_PRELOAD" not in captured_env
    assert "DYLD_INSERT_LIBRARIES" not in captured_env


def test_all_supported_backends_recognised():
    for backend in SUPPORTED_BACKENDS:
        # Should not raise unknown-backend error; only the missing-binary path.
        with mock.patch("cohrint_agent.delegate.resolve_backend_binary", return_value=None):
            with pytest.raises(DelegateError) as exc:
                exec_backend(backend, [])
            assert "unknown backend" not in str(exc.value)
