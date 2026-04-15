"""
data.py — Random test data generators for Cohrint test suite
"""

import string
import random
import time
import uuid


def rand_tag(n=8) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


def rand_email(prefix="test") -> str:
    return f"{prefix}_{rand_tag()}@vantage-test.dev"


def rand_org(prefix="org") -> str:
    return f"{prefix}{rand_tag(6)}"


def rand_name() -> str:
    first = random.choice(["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"])
    last  = random.choice(["Smith", "Jones", "Lee", "Chen", "Kim", "Patel", "Brown", "Taylor"])
    return f"{first} {last}"


def make_event(i=0, model="gpt-4o", cost=0.005, prompt_tokens=100,
               completion_tokens=50, tags=None, team=None) -> dict:
    """Generate a valid event payload matching the Worker's EventIn schema."""
    ev = {
        "event_id":          f"test-{uuid.uuid4().hex[:12]}-{i}",
        "provider":          "openai",
        "model":             model,
        "prompt_tokens":     prompt_tokens + i * 10,
        "completion_tokens": completion_tokens + i * 5,
        "total_cost_usd":    round(cost * (i + 1), 6),
        "latency_ms":        120 + i * 10,
        "environment":       "test",
    }
    if tags:
        ev["tags"] = tags
    if team:
        ev["team"] = team
    return ev
