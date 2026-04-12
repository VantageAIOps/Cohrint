"""Tests for the Vega chatbot Worker."""
import json
import pathlib
import re
import subprocess

import pytest
import requests

BASE = "http://localhost:8788"


# ── Task 1: Health ────────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["name"] == "vega"
