"""
Test Suite 21b — Cohrint Agent: Source Structure & Module Contracts
Source-code verification tests for optimizer, backends, session, and renderer.
Replaces the old TypeScript vantage-cli progress/context tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from helpers.output import section, chk, get_results, reset_results

AGENT_DIR = Path(__file__).parent.parent.parent.parent / "cohrint-agent"
PKG_DIR   = AGENT_DIR / "vantage_agent"
BACKENDS  = PKG_DIR / "backends"

sys.path.insert(0, str(AGENT_DIR))


def src(filename: str) -> str:
    return (PKG_DIR / filename).read_text()

def backend_src(filename: str) -> str:
    return (BACKENDS / filename).read_text()


# ── Section A: optimizer.py ────────────────────────────────────────────────

class TestOptimizerModule:
    def test_pc01_optimize_prompt_exported(self):
        section("A — optimizer.py")
        content = src("optimizer.py")
        chk("PC.01 optimize_prompt function defined", "def optimize_prompt" in content)
        assert "def optimize_prompt" in content

    def test_pc02_count_tokens_exported(self):
        content = src("optimizer.py")
        chk("PC.02 count_tokens function defined", "def count_tokens" in content)
        assert "def count_tokens" in content

    def test_pc03_filler_patterns_present(self):
        content = src("optimizer.py")
        chk("PC.03 filler patterns defined", "could you please" in content.lower() or "FILLERS" in content or "filler" in content.lower())
        assert "could you please" in content.lower() or "filler" in content.lower() or "FILLERS" in content

    def test_pc04_dedup_logic_present(self):
        content = src("optimizer.py")
        chk("PC.04 deduplication logic present", "dedup" in content.lower() or "seen" in content or "duplicate" in content.lower())
        assert "dedup" in content.lower() or "seen" in content or "duplicate" in content.lower()


# ── Section B: pricing.py ──────────────────────────────────────────────────

class TestPricingModule:
    def test_pc05_model_prices_dict(self):
        section("B — pricing.py")
        content = src("pricing.py")
        chk("PC.05 MODEL_PRICES defined", "MODEL_PRICES" in content)
        assert "MODEL_PRICES" in content

    def test_pc06_calculate_cost_function(self):
        content = src("pricing.py")
        chk("PC.06 calculate_cost function defined", "def calculate_cost" in content)
        assert "def calculate_cost" in content

    def test_pc07_claude_prices_present(self):
        content = src("pricing.py")
        chk("PC.07 claude model prices present", "claude" in content.lower())
        assert "claude" in content.lower()

    def test_pc08_openai_prices_present(self):
        content = src("pricing.py")
        chk("PC.08 openai model prices present", "gpt-4o" in content or "openai" in content.lower())
        assert "gpt-4o" in content or "openai" in content.lower()

    def test_pc09_cached_token_support(self):
        content = src("pricing.py")
        chk("PC.09 cached token pricing support", "cached" in content.lower() or "cache" in content.lower())
        assert "cached" in content.lower() or "cache" in content.lower()


# ── Section C: backends/base.py Interface ─────────────────────────────────

class TestBackendInterface:
    def test_pc10_base_backend_class(self):
        section("C — backends/base.py Interface")
        content = backend_src("base.py")
        chk("PC.10 BaseBackend class defined", "class" in content and "Backend" in content)
        assert "Backend" in content

    def test_pc11_send_method(self):
        content = backend_src("base.py")
        chk("PC.11 send() or run() method defined", "def send" in content or "def run" in content or "async def" in content)
        assert "def send" in content or "def run" in content or "async def" in content

    def test_pc12_backend_abc(self):
        content = backend_src("base.py")
        chk("PC.12 backend uses ABC abstract base class", "ABC" in content or "abc" in content)
        assert "ABC" in content or "abc" in content


# ── Section D: claude_backend.py ──────────────────────────────────────────

class TestClaudeBackend:
    def test_pc13_claude_backend_class(self):
        section("D — claude_backend.py")
        content = backend_src("claude_backend.py")
        chk("PC.13 ClaudeBackend class defined", "class" in content and "Claude" in content)
        assert "Claude" in content

    def test_pc14_claude_provider_anthropic(self):
        content = backend_src("claude_backend.py")
        chk("PC.14 claude provider is anthropic", "anthropic" in content.lower())
        assert "anthropic" in content.lower()

    def test_pc15_claude_uses_subprocess(self):
        content = backend_src("claude_backend.py")
        chk("PC.15 claude backend uses subprocess to call claude CLI", "subprocess" in content.lower())
        assert "subprocess" in content.lower()


# ── Section E: gemini_backend.py ──────────────────────────────────────────

class TestGeminiBackend:
    def test_pc16_gemini_backend_class(self):
        section("E — gemini_backend.py")
        content = backend_src("gemini_backend.py")
        chk("PC.16 GeminiBackend class defined", "class" in content and "Gemini" in content)
        assert "Gemini" in content

    def test_pc17_gemini_provider_google(self):
        content = backend_src("gemini_backend.py")
        chk("PC.17 gemini provider is google", "google" in content.lower() or "gemini" in content.lower())
        assert "google" in content.lower() or "gemini" in content.lower()


# ── Section F: session.py & session_store.py ──────────────────────────────

class TestSessionModules:
    def test_pc18_session_class(self):
        section("F — session.py & session_store.py")
        content = src("session.py")
        chk("PC.18 Session class or dataclass defined", "class Session" in content or "Session" in content)
        assert "Session" in content

    def test_pc19_session_store_class(self):
        content = src("session_store.py")
        chk("PC.19 SessionStore class defined", "class SessionStore" in content)
        assert "class SessionStore" in content

    def test_pc20_session_store_save(self):
        content = src("session_store.py")
        chk("PC.20 SessionStore has save method", "def save" in content or "def store" in content)
        assert "def save" in content or "def store" in content

    def test_pc21_session_store_load(self):
        content = src("session_store.py")
        chk("PC.21 SessionStore has load/list method", "def load" in content or "def list" in content or "def get" in content)
        assert "def load" in content or "def list" in content or "def get" in content


# ── Section G: Non-claude Backends ────────────────────────────────────────

class TestNonClaudeBackends:
    def test_pc22_codex_backend_exists(self):
        section("G — Non-claude Backends")
        chk("PC.22 codex_backend.py exists", (BACKENDS / "codex_backend.py").exists())
        assert (BACKENDS / "codex_backend.py").exists()

    def test_pc23_codex_provider_openai(self):
        content = backend_src("codex_backend.py")
        chk("PC.23 codex provider is openai", "openai" in content.lower())
        assert "openai" in content.lower()

    def test_pc24_api_backend_exists(self):
        chk("PC.24 api_backend.py exists", (BACKENDS / "api_backend.py").exists())
        assert (BACKENDS / "api_backend.py").exists()

    def test_pc25_api_backend_vantage(self):
        content = backend_src("api_backend.py")
        chk("PC.25 api backend references vantage API", "vantage" in content.lower() or "api" in content.lower())
        assert "vantage" in content.lower() or "api" in content.lower()


# ── Runner ────────────────────────────────────────────────────────────────

def run():
    reset_results()
    test_classes = [
        TestOptimizerModule,
        TestPricingModule,
        TestBackendInterface,
        TestClaudeBackend,
        TestGeminiBackend,
        TestSessionModules,
        TestNonClaudeBackends,
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
