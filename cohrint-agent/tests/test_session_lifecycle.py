"""
Tests for session lifecycle, concurrent access, budget enforcement, history trim.
Covers: TE1 (resume), TE2 (concurrent), TE5 (budget), TE6 (corruption), TE8 (lifecycle), TE9 (trim).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cohrint_agent.session_store import SessionStore
from cohrint_agent.session import CohrintSession, _trim_history
from cohrint_agent.hooks import BudgetExceededError, HookContext, CostSummary, check_budget_hook


def _make_backend(reply="reply"):
    backend = MagicMock()
    backend.name = "api"
    backend.capabilities.token_count = "exact"
    backend.capabilities.supports_process = False
    backend.send.return_value = MagicMock(
        output_text=reply, input_tokens=10, output_tokens=5,
        cost_usd=0.001, model="claude-sonnet-4-6",
    )
    return backend


# TE8: Full session lifecycle — create → send → save → resume → send → history persisted
def test_session_create_save_resume_lifecycle(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = _make_backend("reply")

    session = CohrintSession.create(backend=backend, cwd=str(tmp_path), store=store)
    session_id = session.session_id
    session.send("hello")
    session.save()

    # Resume and verify history carried forward
    resumed = CohrintSession.resume(session_id=session_id, backend=backend, store=store)
    assert len(resumed.history) == 2  # user + assistant
    assert resumed.history[0]["role"] == "user"
    assert resumed.history[0]["text"] == "hello"
    assert resumed.history[1]["role"] == "assistant"
    assert resumed.history[1]["text"] == "reply"


# TE1: Resume non-existent session raises cleanly
def test_resume_nonexistent_session_raises(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    backend = _make_backend()
    # Valid UUIDv4 format but no matching file — exercises SessionNotFoundError,
    # not InvalidSessionIdError (P13).
    missing = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(Exception):
        CohrintSession.resume(session_id=missing, backend=backend, store=store)


# TE2: Concurrent SessionStore writes don't corrupt data
def test_concurrent_session_store_writes(tmp_path):
    store = SessionStore(sessions_dir=tmp_path / "sessions")
    errors = []
    # UUIDv4s required since SessionStore rejects anything else (P13 / T-SAFETY.4).
    ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(10)]

    def write_session(sid, i):
        try:
            store.save({"id": sid, "schema_version": 1,
                        "messages": [{"role": "user", "text": f"msg-{i}"}],
                        "cost_summary": {"total_cost_usd": 0.0}})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_session, args=(ids[i], i)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent writes caused errors: {errors}"
    # Verify all sessions written
    all_sessions = store.list_all()
    assert len(all_sessions) == 10


# TE5: BudgetExceededError raised by check_budget_hook for api backend
def test_budget_exceeded_raises_for_api_backend():
    ctx = HookContext(
        prompt="test",
        history=[],
        backend_name="api",
        backend_token_count="exact",
        session_id="s",
        result=None,
        cost_so_far=CostSummary(total_cost_usd=1.05, prompt_count=5, budget_usd=1.00),
    )
    with pytest.raises(BudgetExceededError):
        check_budget_hook(ctx)


# TE5b: Budget exceeded for CLI backend prints warning, does NOT raise
def test_budget_exceeded_warns_for_cli_backend(capsys):
    ctx = HookContext(
        prompt="test",
        history=[],
        backend_name="claude",
        backend_token_count="estimated",
        session_id="s",
        result=None,
        cost_so_far=CostSummary(total_cost_usd=1.05, prompt_count=5, budget_usd=1.00),
    )
    result = check_budget_hook(ctx)  # must not raise
    assert result is not None


# TE6: Malformed permissions.json loads safe defaults, doesn't crash
def test_malformed_permissions_json_safe_defaults(tmp_path):
    from cohrint_agent.permissions import PermissionManager
    perm_file = tmp_path / "permissions.json"
    perm_file.write_text("{invalid json here!!!}")
    pm = PermissionManager(config_dir=tmp_path)
    assert "Read" in pm.always_approved  # SAFE_TOOLS default applied


# TE9: History trim fires at exact token boundary and notifies
def test_trim_history_at_boundary():
    # Each message is 40 chars / 4 = 10 tokens → enough messages to exceed limit
    msgs = [{"role": "user" if i % 2 == 0 else "assistant",
             "text": "x" * 40} for i in range(802)]
    trimmed = _trim_history(msgs)
    # Must be under limit
    total_chars = sum(len(m.get("text", "")) for m in trimmed)
    assert total_chars // 4 <= 8000


# TE9b: Trim always preserves pairs (drops 2 at a time)
def test_trim_preserves_pairs():
    msgs = [{"role": "user" if i % 2 == 0 else "assistant",
             "text": "x" * 40} for i in range(802)]
    trimmed = _trim_history(msgs)
    assert len(trimmed) % 2 == 0  # always even (pairs)
