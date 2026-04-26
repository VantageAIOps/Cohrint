"""
conftest.py -- Pytest fixtures for Agent Trace E2E test suite (50_agent_trace_e2e)
"""

import sys
from pathlib import Path
import json

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from helpers.api import get_headers


@pytest.fixture(scope="module")
def da45_state():
    state_file = Path(__file__).parent.parent.parent / "artifacts" / "da45_seed_state.json"
    if not state_file.exists():
        pytest.skip("DA45 seed state not found — run seed.py first")
    return json.loads(state_file.read_text())


@pytest.fixture(scope="module")
def admin_headers(da45_state):
    return get_headers(da45_state["admin"]["api_key"])
