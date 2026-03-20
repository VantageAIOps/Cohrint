"""
data.py — Random test data generators for VantageAI test suite
"""

import string
import random


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
