"""Pytest fixtures for Vega chatbot tests."""
import os
import pytest


@pytest.fixture(scope="session")
def base_url():
    return os.getenv("CHATBOT_URL", "http://localhost:8788")


@pytest.fixture(scope="session")
def auth_headers():
    return {
        "Authorization": "Bearer test-token-for-ci",
        "X-Org-Id": "test-org-pytest",
        "X-Plan": "free",
    }


@pytest.fixture(scope="session")
def pro_headers():
    return {
        "Authorization": "Bearer test-token-for-ci",
        "X-Org-Id": "test-org-pro",
        "X-Plan": "pro",
    }
