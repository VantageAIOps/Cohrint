"""
conftest.py — Shared fixtures and markers for vantage-agent tests.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from vantage_agent.permissions import PermissionManager
from vantage_agent.cost_tracker import SessionCost


def _has_api_key() -> bool:
    """Check if Anthropic API key is available."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    for path in [
        os.path.expanduser("~/.vantage-agent/api_key"),
        os.path.expanduser("~/.anthropic/api_key"),
    ]:
        if os.path.exists(path):
            return True
    return False


HAS_API_KEY = _has_api_key()

# Marker: skip if no API key
live = pytest.mark.skipif(not HAS_API_KEY, reason="No ANTHROPIC_API_KEY — skipping live tests")


@pytest.fixture
def workspace(tmp_path):
    """Create a realistic project workspace for tool testing."""
    # Python files
    (tmp_path / "main.py").write_text(
        'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n\n'
        'def add(a: int, b: int) -> int:\n    return a + b\n\n'
        'if __name__ == "__main__":\n    print(greet("world"))\n'
    )
    (tmp_path / "utils.py").write_text(
        'import os\nimport json\n\n'
        'def read_config(path: str) -> dict:\n'
        '    with open(path) as f:\n        return json.load(f)\n\n'
        'def ensure_dir(path: str) -> None:\n'
        '    os.makedirs(path, exist_ok=True)\n'
    )
    (tmp_path / "test_main.py").write_text(
        'from main import greet, add\n\n'
        'def test_greet():\n    assert greet("Alice") == "Hello, Alice!"\n\n'
        'def test_add():\n    assert add(2, 3) == 5\n'
    )

    # Config files
    (tmp_path / "config.json").write_text('{"debug": true, "port": 8080}\n')
    (tmp_path / "requirements.txt").write_text("anthropic>=0.40.0\nrich>=13.0\npytest\n")

    # Nested structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.py").write_text(
        'from flask import Flask\napp = Flask(__name__)\n\n'
        '@app.route("/health")\ndef health():\n    return {"status": "ok"}\n'
    )
    (tmp_path / "src" / "__init__.py").write_text("")

    # Data files
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "users.csv").write_text("id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@test.com\n")

    # README
    (tmp_path / "README.md").write_text("# Test Project\n\nA test workspace for vantage-agent.\n")

    # .gitignore
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n.env\n")

    return tmp_path


@pytest.fixture
def perms(tmp_path, monkeypatch):
    """Isolated PermissionManager."""
    state_dir = tmp_path / ".vantage-agent"
    perm_file = state_dir / "permissions.json"
    monkeypatch.setattr("vantage_agent.permissions._STATE_DIR", state_dir)
    monkeypatch.setattr("vantage_agent.permissions._PERM_FILE", perm_file)
    return PermissionManager()


@pytest.fixture
def cost():
    """Fresh SessionCost tracker."""
    return SessionCost(model="claude-sonnet-4-6")


@pytest.fixture
def client(workspace, perms, cost):
    """
    Create an AgentClient for live testing.
    Requires ANTHROPIC_API_KEY.
    """
    if not HAS_API_KEY:
        pytest.skip("No API key")

    from vantage_agent.api_client import AgentClient
    # Pre-approve all tools for integration tests
    perms.approve(["Bash", "Write", "Edit"], always=False)
    return AgentClient(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        permissions=perms,
        cost=cost,
        cwd=str(workspace),
    )
