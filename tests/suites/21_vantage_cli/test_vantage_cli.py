"""
Test Suite 21 — VantageAI CLI (vantage-cli)
Tests the prompt optimizer, pricing engine, and CLI end-to-end pipe mode.
"""
import sys, json, shutil, subprocess, re, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, ok, fail, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
TSX = CLI_DIR / "node_modules" / ".bin" / "tsx"
HARNESS = CLI_DIR / "test-helpers.ts"


def js(cmd: str, *args: str, timeout: int = 10) -> dict:
    """Run test-helpers.ts via tsx and return parsed JSON."""
    result = subprocess.run(
        [str(TSX), str(HARNESS), cmd, *[str(a) for a in args]],
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"error": result.stderr, "stdout": result.stdout}


def run_cli(prompt: str, timeout: int = 45) -> tuple:
    """Run vantage CLI in pipe mode."""
    result = subprocess.run(
        ["node", "dist/index.js"],
        input=prompt,
        capture_output=True, text=True, timeout=timeout,
        cwd=str(CLI_DIR),
    )
    return result.stdout, result.stderr, result.returncode


# ── Section A: Optimizer Engine ────────────────────────────────────────────

class TestOptimizerEngine:
    def test_cl01_empty_prompt(self):
        section("A — Optimizer Engine")
        r = js("optimize", "")
        chk("CL.1 empty prompt returns empty", r.get("optimized", "") == "")
        assert r.get("optimized", "") == ""

    def test_cl02_clean_prompt(self):
        r = js("optimize", "Explain kubernetes pods")
        chk("CL.2 clean prompt unchanged or minimal change", r["savedTokens"] <= 1)
        assert r["savedTokens"] <= 1

    def test_cl03_filler_could_you_please(self):
        r = js("optimize", "Could you please explain what kubernetes is")
        chk("CL.3 'could you please' removed", "could you please" not in r["optimized"].lower())
        chk("CL.3 tokens saved > 0", r["savedTokens"] > 0)
        assert r["savedTokens"] > 0

    def test_cl04_verbose_in_order_to(self):
        r = js("optimize", "In order to deploy, we need to configure the cluster")
        chk("CL.4 'in order to' → 'to'", "in order to" not in r["optimized"].lower())
        assert "in order to" not in r["optimized"].lower()

    def test_cl05_verbose_due_to_fact(self):
        r = js("optimize", "Due to the fact that the system is slow we need to fix it")
        chk("CL.5 'due to the fact that' → 'because'", "due to the fact that" not in r["optimized"].lower())
        assert "due to the fact that" not in r["optimized"].lower()

    def test_cl06_dedup_sentences(self):
        r = js("optimize", "The system is fast. The code is clean. The system is fast.")
        chk("CL.6 duplicate sentence removed", r["optimized"].lower().count("the system is fast") == 1)
        assert r["optimized"].lower().count("the system is fast") == 1

    def test_cl07_verbose_prompt_savings(self):
        verbose = (
            "I would like you to please analyze the quarterly revenue data. "
            "It is important to note that we need year-over-year growth. "
            "Could you please take into consideration the market trends. "
            "In order to make a decision about our strategy we need patterns. "
            "Due to the fact that we are competitive it is important that we optimize."
        )
        r = js("optimize", verbose)
        chk("CL.7 verbose prompt saves 20%+", r["savedPercent"] >= 20)
        assert r["savedPercent"] >= 20

    def test_cl08_filler_words_removed(self):
        r = js("optimize", "I basically just really want to simply explain this very important concept")
        chk("CL.8 filler words reduced tokens", r["savedTokens"] >= 3)
        assert r["savedTokens"] >= 3

    def test_cl09_token_counter_short(self):
        r = js("tokens", "hello world")
        chk("CL.9 'hello world' = 2-3 tokens", 1 <= r["tokens"] <= 4)
        assert 1 <= r["tokens"] <= 4

    def test_cl10_token_counter_paragraph(self):
        text = " ".join(["word"] * 100)
        r = js("tokens", text)
        chk("CL.10 100 words ≈ 100 tokens", 90 <= r["tokens"] <= 130)
        assert 90 <= r["tokens"] <= 130


# ── Section B: CLI Pipe Mode ──────────────────────────────────────────────

has_claude = shutil.which("claude") is not None


@pytest.mark.skipif(not has_claude, reason="claude CLI not installed")
class TestCLIPipeMode:
    def test_cl11_pipe_exit_code(self):
        section("B — CLI Pipe Mode")
        stdout, stderr, rc = run_cli("What is 2+2? Answer in one word.")
        chk("CL.11 pipe mode exit code 0", rc == 0)
        assert rc == 0

    def test_cl12_output_has_optimized(self):
        stdout, _, _ = run_cli("Could you please tell me what 2+2 is in one word")
        chk("CL.12 output contains 'Optimized'", "ptimized" in stdout)
        assert "ptimized" in stdout

    def test_cl13_output_has_cost(self):
        stdout, _, _ = run_cli("What is 1+1? One word answer.")
        chk("CL.13 output contains cost summary", "ost" in stdout)
        assert "ost" in stdout

    def test_cl14_verbose_shows_savings(self):
        stdout, _, _ = run_cli(
            "Could you please kindly explain what is basically the concept of addition in simple terms"
        )
        chk("CL.14 verbose prompt shows savings", "saved" in stdout.lower() or "Optimized" in stdout)
        assert "saved" in stdout.lower() or "Optimized" in stdout

    def test_cl15_empty_prompt_no_crash(self):
        stdout, stderr, rc = run_cli("")
        chk(
            "CL.15 empty prompt no crash",
            rc == 0 or "no prompt" in (stdout + stderr).lower() or rc == 1,
        )
        # It's ok to exit with code 1 for empty prompt, as long as no crash

    def test_cl16_output_has_model(self):
        stdout, _, _ = run_cli("Say hi")
        chk("CL.16 output contains model name", "claude" in stdout.lower() or "sonnet" in stdout.lower())
        assert "claude" in stdout.lower() or "sonnet" in stdout.lower()

    def test_cl17_cost_is_positive(self):
        stdout, _, _ = run_cli("What is 3+3? One word.")
        cost_match = re.search(r'\$(\d+\.\d+)', stdout)
        cost = float(cost_match.group(1)) if cost_match else 0
        chk("CL.17 cost value > 0", cost > 0)
        assert cost > 0

    def test_cl18_token_counts_positive(self):
        stdout, _, _ = run_cli("What is 4+4? One word.")
        input_match = re.search(r'Input tokens:\s*(\d+)', stdout)
        output_match = re.search(r'Output tokens:\s*(\d+)', stdout)
        input_tok = int(input_match.group(1)) if input_match else 0
        output_tok = int(output_match.group(1)) if output_match else 0
        chk("CL.18 input tokens > 0", input_tok > 0)
        chk("CL.18 output tokens > 0", output_tok > 0)
        assert input_tok > 0 and output_tok > 0


# ── Section C: Pricing Engine ─────────────────────────────────────────────

class TestPricingEngine:
    def test_cl19_claude_cost(self):
        section("C — Pricing Engine")
        r = js("cost", "claude-sonnet-4-6", "1000", "500")
        chk("CL.19 claude-sonnet-4-6 cost > 0", r["totalCostUsd"] > 0)
        assert r["totalCostUsd"] > 0

    def test_cl20_gpt4o_cost(self):
        r = js("cost", "gpt-4o", "1000", "500")
        chk("CL.20 gpt-4o cost > 0", r["totalCostUsd"] > 0)
        assert r["totalCostUsd"] > 0

    def test_cl21_unknown_model_zero(self):
        r = js("cost", "totally-unknown-model-xyz", "1000", "500")
        chk("CL.21 unknown model cost = 0", r["totalCostUsd"] == 0)
        assert r["totalCostUsd"] == 0

    def test_cl22_find_cheapest(self):
        r = js("cheapest", "claude-opus-4-6", "1000", "500")
        chk("CL.22 cheaper model exists for opus", r is not None and r.get("model"))
        assert r is not None and r.get("model")

    def test_cl23_cache_reduces_cost(self):
        no_cache = js("cost", "claude-sonnet-4-6", "1000", "500", "0")
        with_cache = js("cost", "claude-sonnet-4-6", "1000", "500", "500")
        chk("CL.23 cached tokens reduce cost", with_cache["totalCostUsd"] < no_cache["totalCostUsd"])
        assert with_cache["totalCostUsd"] < no_cache["totalCostUsd"]

    def test_cl24_zero_tokens_zero_cost(self):
        r = js("cost", "gpt-4o", "0", "0")
        chk("CL.24 zero tokens = zero cost", r["totalCostUsd"] == 0)
        assert r["totalCostUsd"] == 0

    def test_cl25_model_count(self):
        r = js("models")
        chk("CL.25 pricing table has 15+ models", r["count"] >= 15)
        assert r["count"] >= 15


# ── Section D: Config & File Structure ────────────────────────────────────

class TestConfigAndStructure:
    def test_cl26_package_json_exists(self):
        section("D — Config & File Structure")
        chk("CL.26 package.json exists", (CLI_DIR / "package.json").exists())
        assert (CLI_DIR / "package.json").exists()

    def test_cl27_dist_exists(self):
        chk("CL.27 dist/index.js exists (built)", (CLI_DIR / "dist" / "index.js").exists())
        assert (CLI_DIR / "dist" / "index.js").exists()

    def test_cl28_test_harness_exists(self):
        chk("CL.28 test-helpers.ts exists", HARNESS.exists())
        assert HARNESS.exists()

    def test_cl29_source_files_present(self):
        expected = [
            "index.ts", "config.ts", "optimizer.ts", "pricing.ts",
            "event-bus.ts", "tracker.ts", "runner.ts", "session.ts",
            "ui.ts", "setup.ts",
        ]
        all_present = True
        for f in expected:
            if not (CLI_DIR / "src" / f).exists():
                all_present = False
                break
        chk("CL.29 all 10 source files present", all_present)
        for f in expected:
            assert (CLI_DIR / "src" / f).exists(), f"Missing {f}"

    def test_cl30_agent_adapters_present(self):
        expected = [
            "types.ts", "registry.ts", "claude.ts", "codex.ts",
            "gemini.ts", "aider.ts", "chatgpt.ts",
        ]
        all_present = True
        for f in expected:
            if not (CLI_DIR / "src" / "agents" / f).exists():
                all_present = False
                break
        chk("CL.30 all 7 agent adapter files present", all_present)
        for f in expected:
            assert (CLI_DIR / "src" / "agents" / f).exists(), f"Missing agents/{f}"

    def test_cl31_zero_runtime_deps(self):
        pkg = json.loads((CLI_DIR / "package.json").read_text())
        deps = pkg.get("dependencies", {})
        chk("CL.31 zero runtime dependencies", len(deps) == 0)
        assert len(deps) == 0

    def test_cl32_bin_configured(self):
        pkg = json.loads((CLI_DIR / "package.json").read_text())
        chk("CL.32 bin 'vantage' configured", "vantage" in pkg.get("bin", {}))
        assert "vantage" in pkg.get("bin", {})

    def test_cl33_typecheck_passes(self):
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=30,
            cwd=str(CLI_DIR),
        )
        chk("CL.33 TypeScript typecheck passes", r.returncode == 0)
        assert r.returncode == 0


# ── Runner ────────────────────────────────────────────────────────────────

def run():
    reset_results()
    # Run all test classes
    for cls in [TestOptimizerEngine, TestCLIPipeMode, TestPricingEngine, TestConfigAndStructure]:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    getattr(obj, name)()
                except Exception as e:
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
