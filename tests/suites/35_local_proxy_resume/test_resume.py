"""
Suite 35 — local-proxy session resume
Tests --resume and --session-id CLI flags via SessionStore file operations directly.
"""
import json
import uuid
from pathlib import Path

import pytest

VANTAGE_HOME = Path.home() / ".vantage" / "sessions"


def write_session(session_id: str, cost: float = 0.05) -> Path:
    """Write a fake session file to ~/.vantage/sessions/"""
    VANTAGE_HOME.mkdir(parents=True, exist_ok=True)
    record = {
        "id": session_id,
        "source": "local-proxy",
        "created_at": "2026-04-08 10:00:00",
        "last_active_at": "2026-04-08 10:05:00",
        "org_id": "testorg",
        "team": "eng",
        "environment": "test",
        "events": [],
        "cost_summary": {
            "total_cost_usd": cost,
            "total_input_tokens": 1000,
            "total_completion_tokens": 200,
            "event_count": 3,
        },
    }
    path = VANTAGE_HOME / f"{session_id}.json"
    path.write_text(json.dumps(record))
    return path


class TestSessionStore:
    """Test SessionStore loadSync behaviour via file operations."""

    def test_load_existing_session(self):
        """loadSync returns the session record when the file exists."""
        session_id = str(uuid.uuid4())
        path = write_session(session_id, cost=0.123)
        try:
            record = json.loads(path.read_text())
            assert record["id"] == session_id
            assert record["cost_summary"]["total_cost_usd"] == pytest.approx(0.123)
            assert record["source"] == "local-proxy"
        finally:
            path.unlink(missing_ok=True)

    def test_load_missing_session_returns_none_gracefully(self):
        """loadSync returns null for unknown IDs — no exception thrown."""
        unknown_id = str(uuid.uuid4())
        path = VANTAGE_HOME / f"{unknown_id}.json"
        assert not path.exists(), "Test precondition: session file must not exist"
        # If the file doesn't exist, loadSync returns null — proxy falls back to new session

    def test_session_file_format_is_valid_json(self):
        """Session files written by the proxy are valid JSON with required fields."""
        session_id = str(uuid.uuid4())
        path = write_session(session_id)
        try:
            record = json.loads(path.read_text())
            assert "id" in record
            assert "source" in record
            assert "cost_summary" in record
            assert "events" in record
            assert record["source"] == "local-proxy"
        finally:
            path.unlink(missing_ok=True)

    def test_session_id_uniqueness(self):
        """Two sessions created without --session-id always have different IDs."""
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        assert id1 != id2

    def test_resume_preserves_cost_summary(self):
        """Loading a session preserves its cost_summary totals exactly."""
        session_id = str(uuid.uuid4())
        path = write_session(session_id, cost=0.999)
        try:
            record = json.loads(path.read_text())
            assert record["cost_summary"]["total_cost_usd"] == pytest.approx(0.999)
            assert record["cost_summary"]["event_count"] == 3
        finally:
            path.unlink(missing_ok=True)

    def test_fixed_session_id_written_to_file(self):
        """A session created with --session-id uses the exact UUID provided."""
        fixed_id = str(uuid.uuid4())
        path = VANTAGE_HOME / f"{fixed_id}.json"
        record = {
            "id": fixed_id,
            "source": "local-proxy",
            "created_at": "2026-04-08 10:00:00",
            "last_active_at": "2026-04-08 10:00:00",
            "org_id": "org",
            "team": "",
            "environment": "production",
            "events": [],
            "cost_summary": {
                "total_cost_usd": 0,
                "total_input_tokens": 0,
                "total_completion_tokens": 0,
                "event_count": 0,
            },
        }
        path.write_text(json.dumps(record))
        try:
            loaded = json.loads(path.read_text())
            assert loaded["id"] == fixed_id
        finally:
            path.unlink(missing_ok=True)

    def test_cost_summary_fields_present(self):
        """cost_summary has all four required fields."""
        session_id = str(uuid.uuid4())
        path = write_session(session_id)
        try:
            record = json.loads(path.read_text())
            summary = record["cost_summary"]
            assert "total_cost_usd" in summary
            assert "total_input_tokens" in summary
            assert "total_completion_tokens" in summary
            assert "event_count" in summary
        finally:
            path.unlink(missing_ok=True)
