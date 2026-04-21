"""Tests for CohrintSession and SessionStore."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cohrint_agent.session import CohrintSession, MAX_HISTORY_TOKENS, _CHARS_PER_TOKEN
from cohrint_agent.session_store import SessionStore, SessionNotFoundError
from cohrint_agent.backends.base import BackendResult, BackendCapabilities


def _mock_backend(name: str = "api", supports_process: bool = False) -> MagicMock:
    backend = MagicMock()
    backend.name = name
    backend.capabilities = BackendCapabilities(
        supports_process=supports_process,
        supports_streaming=False,
        token_count="exact",
        tool_format="anthropic",
    )
    backend.send.return_value = BackendResult(
        output_text="hello from backend",
        input_tokens=10,
        output_tokens=5,
        estimated=False,
        model="claude-sonnet-4-6",
        exit_code=0,
        cost_usd=0.0001,
    )
    backend.start_process.return_value = None  # no process by default
    return backend


def test_session_creates_with_uuid(tmp_path):
    backend = _mock_backend()
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path))
    assert session.session_id
    uuid.UUID(session.session_id)  # raises if invalid


def test_session_saves_after_successful_turn(tmp_path):
    backend = _mock_backend()
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)

    session.send("hello")

    saved = list((tmp_path / "sessions").glob("*.json"))
    assert len(saved) == 1
    data = json.loads(saved[0].read_text())
    assert data["id"] == session.session_id
    assert len(data["messages"]) == 2  # user + assistant


def test_session_resume_restores_history(tmp_path):
    backend = _mock_backend()
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)
    session.send("first message")

    session2 = CohrintSession.resume(session.session_id, backend=backend, store=store)
    assert len(session2.history) == 2
    assert session2.history[0]["role"] == "user"
    assert session2.history[0]["text"] == "first message"


def test_session_resume_restores_cost_summary(tmp_path):
    backend = _mock_backend()
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)
    session.send("test")

    session2 = CohrintSession.resume(session.session_id, backend=backend, store=store)
    assert session2._cost_summary.get("total_cost_usd", 0) > 0


def test_history_trimmed_at_max_tokens(tmp_path):
    """History exceeding MAX_HISTORY_TOKENS must be trimmed before sending."""
    backend = _mock_backend()
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path))

    # Inject huge history >> MAX_HISTORY_TOKENS
    big_text = "x" * (MAX_HISTORY_TOKENS * _CHARS_PER_TOKEN // 2 + 100)
    for _ in range(4):
        session.history.append({"role": "user", "text": big_text})
        session.history.append({"role": "assistant", "text": big_text})

    session.send("new prompt")

    call_history = backend.send.call_args[1]["history"]
    total_chars = sum(len(m.get("text", "")) for m in call_history)
    assert total_chars // _CHARS_PER_TOKEN <= MAX_HISTORY_TOKENS + 500


def test_session_id_propagated_to_tracker(tmp_path):
    """tracker.record() must be called with correct session_id."""
    backend = _mock_backend()
    tracker = MagicMock()
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path), tracker=tracker)
    session.send("test prompt")

    tracker.record.assert_called_once()
    call_kwargs = tracker.record.call_args[1]
    assert call_kwargs.get("session_id") == session.session_id


def test_interrupt_pops_orphaned_user_message(tmp_path):
    """KeyboardInterrupt during send must not leave orphaned user message."""
    backend = _mock_backend()
    backend.send.side_effect = KeyboardInterrupt
    session = CohrintSession.create(backend=backend, cwd=str(tmp_path))
    try:
        session.send("interrupted prompt")
    except KeyboardInterrupt:
        pass
    assert len(session.history) == 0


def test_session_not_found_raises(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = _mock_backend()
    # Valid UUIDv4 format but no matching file on disk — exercises the
    # SessionNotFoundError branch rather than InvalidSessionIdError (T-SAFETY.4).
    missing = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(SessionNotFoundError):
        CohrintSession.resume(missing, backend=backend, store=store)


def test_session_store_list_all(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = _mock_backend()
    for _ in range(3):
        s = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)
        s.send("hello")

    sessions = store.list_all()
    assert len(sessions) == 3


def test_session_store_total_cost(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = _mock_backend()
    for _ in range(2):
        s = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)
        s.send("hello")

    total = store.total_cost_usd()
    assert total >= 0.0
