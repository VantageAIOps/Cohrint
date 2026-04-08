"""
session_store.py — Persist/restore VantageSession state to ~/.vantage/sessions/.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SESSIONS_DIR = Path.home() / ".vantage" / "sessions"


class SessionNotFoundError(Exception):
    pass


class SessionStore:
    def __init__(self, sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def save(self, data: dict) -> None:
        data["last_active_at"] = datetime.now(timezone.utc).isoformat()
        self._path(data["id"]).write_text(json.dumps(data, indent=2))

    def load(self, session_id: str) -> dict:
        p = self._path(session_id)
        if not p.exists():
            raise SessionNotFoundError(f"Session {session_id!r} not found")
        return json.loads(p.read_text())

    def list_all(self) -> list[dict]:
        """Return all sessions sorted by last_active_at descending."""
        sessions = []
        for p in self.sessions_dir.glob("*.json"):
            try:
                sessions.append(json.loads(p.read_text()))
            except Exception:
                continue
        return sorted(sessions, key=lambda s: s.get("last_active_at", ""), reverse=True)

    def total_cost_usd(self) -> float:
        """Aggregate cost across all sessions."""
        return sum(
            s.get("cost_summary", {}).get("total_cost_usd", 0.0)
            for s in self.list_all()
        )
