"""
output.py — Console output helpers and test result tracking for Cohrint test suite
"""

# ── Console colour helpers ────────────────────────────────────────────────────
G  = "\033[32m✓\033[0m"
R  = "\033[31m✗\033[0m"
W  = "\033[33m⚠\033[0m"
B  = "\033[34mℹ\033[0m"

_results = {"passed": 0, "failed": 0, "warned": 0, "skipped": 0}


def ok(msg):
    _results["passed"] += 1
    print(f"  {G}  {msg}")


def fail(msg, detail=""):
    _results["failed"] += 1
    d = f"\n       └─ {detail}" if detail else ""
    print(f"  {R}  {msg}{d}")


def warn(msg):
    _results["warned"] += 1
    print(f"  {W}  {msg}")


def info(msg):
    print(f"  {B}  {msg}")


def section(title):
    print(f"\n{'━'*66}")
    print(f"  {title}")
    print(f"{'━'*66}")


def chk(label, cond, detail=""):
    if cond:
        ok(label)
    else:
        fail(label, detail)


def get_results():
    return dict(_results)


def reset_results():
    _results.update({"passed": 0, "failed": 0, "warned": 0, "skipped": 0})
