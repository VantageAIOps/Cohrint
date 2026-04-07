"""
Test Suite 21b — VantageAI CLI: Progress Spinner + Conversation Context
Source-code verification tests for spinner, continue-conversation, and adapter checks.
"""
import sys, subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, get_results, reset_results

CLI_DIR = Path(__file__).parent.parent.parent.parent / "vantage-cli"
SRC = CLI_DIR / "src"
AGENTS = SRC / "agents"


def src(filename: str) -> str:
    """Read a source file and return its contents."""
    return (SRC / filename).read_text()


def agent_src(filename: str) -> str:
    """Read an agents/ source file and return its contents."""
    return (AGENTS / filename).read_text()


# ── Section A: ui.ts Spinner ──────────────────────────────────────────────

class TestUiSpinner:
    def test_pc01_createspinner_export(self):
        section("A — ui.ts Spinner")
        content = src("ui.ts")
        chk("PC.01 createSpinner is exported", "export function createSpinner" in content)
        assert "export function createSpinner" in content

    def test_pc02_spinner_interface_export(self):
        content = src("ui.ts")
        chk("PC.02 Spinner interface is exported", "export interface Spinner" in content)
        assert "export interface Spinner" in content

    def test_pc03_spinner_uses_stderr(self):
        content = src("ui.ts")
        chk("PC.03 spinner writes to process.stderr", "process.stderr" in content)
        assert "process.stderr" in content

    def test_pc04_spinner_has_line_clear(self):
        content = src("ui.ts")
        chk("PC.04 spinner uses \\x1b[K to clear line", r"\x1b[K" in content)
        assert r"\x1b[K" in content

    def test_pc05_spinner_checks_istty(self):
        content = src("ui.ts")
        chk("PC.05 spinner checks isTTY", "isTTY" in content)
        assert "isTTY" in content

    def test_pc06_spinner_stop_method(self):
        content = src("ui.ts")
        chk("PC.06 Spinner interface has stop() method", "stop(): void" in content or "stop()" in content)
        assert "stop()" in content


# ── Section B: runner.ts Integration ──────────────────────────────────────

class TestRunnerIntegration:
    def test_pc07_imports_createspinner(self):
        section("B — runner.ts Integration")
        content = src("runner.ts")
        chk("PC.07 runner.ts imports createSpinner", "createSpinner" in content)
        assert "createSpinner" in content

    def test_pc08_calls_createspinner(self):
        content = src("runner.ts")
        chk("PC.08 runner.ts calls createSpinner(", "createSpinner(" in content)
        assert "createSpinner(" in content

    def test_pc09_calls_spinner_stop(self):
        content = src("runner.ts")
        # runner.ts wraps spinner in a stopSpinner() closure
        chk("PC.09 runner.ts calls stopSpinner()", "stopSpinner()" in content)
        assert "stopSpinner()" in content


# ── Section C: types.ts Interface ─────────────────────────────────────────

class TestTypesInterface:
    def test_pc10_supports_continue_field(self):
        section("C — types.ts AgentAdapter Interface")
        content = agent_src("types.ts")
        chk("PC.10 AgentAdapter has supportsContinue", "supportsContinue" in content)
        assert "supportsContinue" in content

    def test_pc11_build_continue_command_field(self):
        content = agent_src("types.ts")
        chk("PC.11 AgentAdapter has buildContinueCommand", "buildContinueCommand" in content)
        assert "buildContinueCommand" in content


# ── Section D: claude.ts Adapter ──────────────────────────────────────────

class TestClaudeAdapter:
    def test_pc12_claude_supports_continue(self):
        section("D — claude.ts Adapter")
        content = agent_src("claude.ts")
        chk("PC.12 claude.ts has supportsContinue: true", "supportsContinue: true" in content)
        assert "supportsContinue: true" in content

    def test_pc13_claude_build_continue_command(self):
        content = agent_src("claude.ts")
        chk("PC.13 claude.ts implements buildContinueCommand", "buildContinueCommand" in content)
        assert "buildContinueCommand" in content

    def test_pc14_claude_continue_flag(self):
        content = agent_src("claude.ts")
        chk('PC.14 claude.ts uses "--continue" flag', '"--continue"' in content)
        assert '"--continue"' in content


# ── Section E: gemini.ts Adapter ──────────────────────────────────────────

class TestGeminiAdapter:
    def test_pc15_gemini_supports_continue(self):
        section("E — gemini.ts Adapter")
        content = agent_src("gemini.ts")
        chk("PC.15 gemini.ts has supportsContinue: true", "supportsContinue: true" in content)
        assert "supportsContinue: true" in content

    def test_pc16_gemini_build_continue_command(self):
        content = agent_src("gemini.ts")
        chk("PC.16 gemini.ts implements buildContinueCommand", "buildContinueCommand" in content)
        assert "buildContinueCommand" in content

    def test_pc17_gemini_continue_flag(self):
        content = agent_src("gemini.ts")
        chk('PC.17 gemini.ts uses "--continue" flag', '"--continue"' in content)
        assert '"--continue"' in content


# ── Section F: index.ts REPL Wiring ───────────────────────────────────────

class TestIndexReplWiring:
    def test_pc18_agent_prompt_count(self):
        section("F — index.ts REPL Wiring")
        content = src("index.ts")
        chk("PC.18 index.ts tracks agentPromptCount", "agentPromptCount" in content)
        assert "agentPromptCount" in content

    def test_pc19_continue_conversation(self):
        content = src("index.ts")
        chk("PC.19 index.ts has continueConversation", "continueConversation" in content)
        assert "continueConversation" in content

    def test_pc20_uses_supports_continue(self):
        content = src("index.ts")
        chk("PC.20 index.ts checks supportsContinue", "supportsContinue" in content)
        assert "supportsContinue" in content

    def test_pc21_uses_build_continue_command(self):
        content = src("index.ts")
        chk("PC.21 index.ts calls buildContinueCommand", "buildContinueCommand" in content)
        assert "buildContinueCommand" in content


# ── Section G: Non-continue Adapters ─────────────────────────────────────

class TestNonContinueAdapters:
    def test_pc22_aider_no_supports_continue(self):
        section("G — Non-continue Adapters")
        content = agent_src("aider.ts")
        chk("PC.22 aider.ts has supportsContinue: false", "supportsContinue: false" in content)
        assert "supportsContinue: false" in content

    def test_pc23_codex_supports_continue(self):
        content = agent_src("codex.ts")
        chk("PC.23 codex.ts has supportsContinue: true", "supportsContinue: true" in content)
        assert "supportsContinue: true" in content

    def test_pc24_chatgpt_supports_continue(self):
        content = agent_src("chatgpt.ts")
        chk("PC.24 chatgpt.ts has supportsContinue: true", "supportsContinue: true" in content)
        assert "supportsContinue: true" in content


# ── Section H: TypeScript Compilation ────────────────────────────────────

class TestTypeScriptCompilation:
    def test_pc25_typecheck_passes(self):
        section("H — TypeScript Compilation")
        r = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            capture_output=True, text=True, timeout=60,
            cwd=str(CLI_DIR),
        )
        chk(
            "PC.25 npx tsc --noEmit returns exit code 0",
            r.returncode == 0,
            r.stderr.strip()[:300] if r.returncode != 0 else "",
        )
        assert r.returncode == 0, r.stderr.strip()[:500]


# ── Runner ────────────────────────────────────────────────────────────────

def run():
    reset_results()
    test_classes = [
        TestUiSpinner,
        TestRunnerIntegration,
        TestTypesInterface,
        TestClaudeAdapter,
        TestGeminiAdapter,
        TestIndexReplWiring,
        TestNonContinueAdapters,
        TestTypeScriptCompilation,
    ]
    for cls in test_classes:
        obj = cls()
        for name in sorted(dir(obj)):
            if name.startswith("test_"):
                try:
                    getattr(obj, name)()
                except Exception as e:
                    from helpers.output import fail
                    fail(name, str(e))

    res = get_results()
    print(f"\n{'='*60}")
    print(f"Results: {res['passed']} passed, {res['failed']} failed, {res['warned']} warned")
    return res["failed"]


if __name__ == "__main__":
    sys.exit(run())
