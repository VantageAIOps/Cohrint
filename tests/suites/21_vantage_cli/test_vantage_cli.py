"""
Test Suite 21 — Cohrint Agent (Python)
Tests the prompt optimizer, pricing engine, and CLI structure.
Replaces the old TypeScript vantage-cli tests.
"""
import sys, json, os, subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, ok, fail, get_results, reset_results

AGENT_DIR = Path(__file__).parent.parent.parent.parent / "vantage-agent"
PKG_DIR   = AGENT_DIR / "vantage_agent"
BACKENDS  = PKG_DIR / "backends"


# ── Section A: Optimizer Engine ────────────────────────────────────────────

class TestOptimizerEngine:
    def setup_method(self):
        sys.path.insert(0, str(AGENT_DIR))

    def test_cl01_empty_prompt(self):
        section("A — Optimizer Engine")
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("")
        chk("CL.1 empty prompt returns empty", r.optimized == "")
        assert r.optimized == ""

    def test_cl02_clean_prompt(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("Explain kubernetes pods")
        chk("CL.2 clean prompt unchanged or minimal change", r.saved_tokens <= 1)
        assert r.saved_tokens <= 1

    def test_cl03_filler_could_you_please(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("Could you please explain what kubernetes is")
        chk("CL.3 'could you please' removed", "could you please" not in r.optimized.lower())
        chk("CL.3 tokens saved > 0", r.saved_tokens > 0)
        assert r.saved_tokens > 0

    def test_cl04_verbose_in_order_to(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("In order to deploy, we need to configure the cluster")
        chk("CL.4 'in order to' → 'to'", "in order to" not in r.optimized.lower())
        assert "in order to" not in r.optimized.lower()

    def test_cl05_verbose_due_to_fact(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("Due to the fact that the system is slow we need to fix it")
        chk("CL.5 'due to the fact that' → 'because'", "due to the fact that" not in r.optimized.lower())
        assert "due to the fact that" not in r.optimized.lower()

    def test_cl06_dedup_sentences(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("The system is fast. The code is clean. The system is fast.")
        chk("CL.6 duplicate sentence removed", r.optimized.lower().count("the system is fast") == 1)
        assert r.optimized.lower().count("the system is fast") == 1

    def test_cl07_verbose_prompt_savings(self):
        from vantage_agent.optimizer import optimize_prompt
        verbose = (
            "I would like you to please analyze the quarterly revenue data. "
            "It is important to note that we need year-over-year growth. "
            "Could you please take into consideration the market trends. "
            "In order to make a decision about our strategy we need patterns. "
            "Due to the fact that we are competitive it is important that we optimize."
        )
        r = optimize_prompt(verbose)
        chk("CL.7 verbose prompt saves 20%+", r.saved_percent >= 20)
        assert r.saved_percent >= 20

    def test_cl08_filler_words_removed(self):
        from vantage_agent.optimizer import optimize_prompt
        r = optimize_prompt("I basically just really want to simply explain this very important concept")
        chk("CL.8 filler words reduced tokens", r.saved_tokens >= 3)
        assert r.saved_tokens >= 3

    def test_cl09_token_counter_short(self):
        from vantage_agent.optimizer import count_tokens
        tokens = count_tokens("hello world")
        chk("CL.9 'hello world' = 2-3 tokens", 1 <= tokens <= 4)
        assert 1 <= tokens <= 4

    def test_cl10_token_counter_paragraph(self):
        from vantage_agent.optimizer import count_tokens
        text = " ".join(["word"] * 100)
        tokens = count_tokens(text)
        chk("CL.10 100 words ≈ 100 tokens", 90 <= tokens <= 130)
        assert 90 <= tokens <= 130


# ── Section B: CLI Structure ──────────────────────────────────────────────

class TestCLIStructure:
    def test_cl11_help_flag(self):
        section("B — CLI Structure")
        r = subprocess.run(
            ["python", "-m", "vantage_agent.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(AGENT_DIR),
        )
        chk("CL.11 --help exits 0", r.returncode == 0)
        assert r.returncode == 0

    def test_cl12_backend_flag_in_help(self):
        r = subprocess.run(
            ["python", "-m", "vantage_agent.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(AGENT_DIR),
        )
        out = r.stdout + r.stderr
        chk("CL.12 --backend flag present in help", "--backend" in out)
        assert "--backend" in out

    def test_cl13_resume_flag_in_help(self):
        r = subprocess.run(
            ["python", "-m", "vantage_agent.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(AGENT_DIR),
        )
        out = r.stdout + r.stderr
        chk("CL.13 --resume flag present in help", "--resume" in out)
        assert "--resume" in out

    def test_cl14_model_flag_in_help(self):
        r = subprocess.run(
            ["python", "-m", "vantage_agent.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(AGENT_DIR),
        )
        out = r.stdout + r.stderr
        chk("CL.14 --model flag present in help", "--model" in out)
        assert "--model" in out

    def test_cl15_no_optimize_flag_in_help(self):
        r = subprocess.run(
            ["python", "-m", "vantage_agent.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(AGENT_DIR),
        )
        out = r.stdout + r.stderr
        chk("CL.15 --no-optimize flag present in help", "--no-optimize" in out)
        assert "--no-optimize" in out


# ── Section C: Pricing Engine ─────────────────────────────────────────────

class TestPricingEngine:
    def setup_method(self):
        sys.path.insert(0, str(AGENT_DIR))

    def test_cl16_model_prices_exists(self):
        section("C — Pricing Engine")
        from vantage_agent.pricing import MODEL_PRICES
        chk("CL.16 MODEL_PRICES dict exists", isinstance(MODEL_PRICES, dict))
        assert isinstance(MODEL_PRICES, dict)

    def test_cl17_model_count(self):
        from vantage_agent.pricing import MODEL_PRICES
        chk("CL.17 pricing table has 15+ models", len(MODEL_PRICES) >= 15)
        assert len(MODEL_PRICES) >= 15

    def test_cl18_claude_cost(self):
        from vantage_agent.pricing import calculate_cost
        cost = calculate_cost("claude-sonnet-4-6", 1000, 500)
        chk("CL.18 claude-sonnet-4-6 cost > 0", cost > 0)
        assert cost > 0

    def test_cl19_gpt4o_cost(self):
        from vantage_agent.pricing import calculate_cost
        cost = calculate_cost("gpt-4o", 1000, 500)
        chk("CL.19 gpt-4o cost > 0", cost > 0)
        assert cost > 0

    def test_cl20_unknown_model_zero(self):
        from vantage_agent.pricing import calculate_cost
        cost = calculate_cost("totally-unknown-model-xyz", 1000, 500)
        chk("CL.20 unknown model cost = 0", cost == 0)
        assert cost == 0

    def test_cl21_zero_tokens_zero_cost(self):
        from vantage_agent.pricing import calculate_cost
        cost = calculate_cost("gpt-4o", 0, 0)
        chk("CL.21 zero tokens = zero cost", cost == 0)
        assert cost == 0

    def test_cl22_opus_more_expensive_than_sonnet(self):
        from vantage_agent.pricing import calculate_cost
        opus   = calculate_cost("claude-opus-4-6", 1000, 500)
        sonnet = calculate_cost("claude-sonnet-4-6", 1000, 500)
        chk("CL.22 opus more expensive than sonnet", opus > sonnet)
        assert opus > sonnet

    def test_cl23_cache_reduces_cost(self):
        from vantage_agent.pricing import calculate_cost
        no_cache   = calculate_cost("claude-sonnet-4-6", 1000, 500)
        with_cache = calculate_cost("claude-sonnet-4-6", 1000, 500, cached_tokens=500)
        chk("CL.23 cached tokens reduce cost", with_cache < no_cache)
        assert with_cache < no_cache


# ── Section D: Config & File Structure ────────────────────────────────────

class TestConfigAndStructure:
    def test_cl24_pyproject_exists(self):
        section("D — Config & File Structure")
        chk("CL.24 pyproject.toml exists", (AGENT_DIR / "pyproject.toml").exists())
        assert (AGENT_DIR / "pyproject.toml").exists()

    def test_cl25_package_name_correct(self):
        import re
        content = (AGENT_DIR / "pyproject.toml").read_text()
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.MULTILINE)
        name = m.group(1) if m else ""
        chk("CL.25 package name is cohrint-agent", name == "cohrint-agent")
        assert name == "cohrint-agent", f"got: {name!r}"

    def test_cl26_cli_entry_point(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(AGENT_DIR / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        scripts = data.get("project", {}).get("scripts", {})
        chk("CL.26 cohrint-agent script entry point", "cohrint-agent" in scripts)
        assert "cohrint-agent" in scripts

    def test_cl27_source_files_present(self):
        expected = [
            "cli.py", "optimizer.py", "pricing.py", "tracker.py",
            "session.py", "session_store.py", "permissions.py",
            "cost_tracker.py", "renderer.py",
        ]
        for f in expected:
            assert (PKG_DIR / f).exists(), f"Missing {f}"
        chk("CL.27 all core source files present", True)

    def test_cl28_backends_present(self):
        expected = ["base.py", "claude_backend.py", "codex_backend.py",
                    "gemini_backend.py", "api_backend.py"]
        for f in expected:
            assert (BACKENDS / f).exists(), f"Missing backends/{f}"
        chk("CL.28 all 4 backend files present", True)

    def test_cl29_no_runtime_deps_except_allowed(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        with open(AGENT_DIR / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        # Only anthropic and rich are allowed runtime deps
        for dep in deps:
            pkg = dep.split(">=")[0].split("==")[0].strip()
            assert pkg in ("anthropic", "rich"), f"Unexpected runtime dep: {pkg}"
        chk("CL.29 only allowed runtime dependencies", True)

    def test_cl30_four_backends_registered(self):
        sys.path.insert(0, str(AGENT_DIR))
        from vantage_agent.backends import _REGISTRY as backend_map
        backend_names = list(backend_map.keys()) if hasattr(backend_map, 'keys') else []
        # At minimum api, claude, codex, gemini
        expected = {"api", "claude", "codex", "gemini"}
        registered = set(str(k) for k in backend_names)
        chk("CL.30 all 4 backends registered", expected.issubset(registered))
        assert expected.issubset(registered)


# ── Runner ────────────────────────────────────────────────────────────────

def run():
    reset_results()
    for cls in [TestOptimizerEngine, TestCLIStructure, TestPricingEngine, TestConfigAndStructure]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    if hasattr(obj, "setup_method"):
                        obj.setup_method()
                    getattr(obj, name)()
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
