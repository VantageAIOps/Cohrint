"""
Test Suite 16: Token Optimizer
Tests prompt compression, context management, token counting, and API endpoints.
"""
import sys
import os
import json
import time
import requests

# Add project root to path so vantage_optimizer is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Test configuration
BASE_URL = os.getenv("VANTAGE_API_URL", "https://api.cohrint.com")
API_KEY = os.getenv("VANTAGE_API_KEY", "")


# ── Unit Tests: Compressor ────────────────────────────────────────────────

def test_simple_compressor_basic():
    """SimpleCompressor removes filler words and extra whitespace."""
    from vantage_optimizer.compressor import SimpleCompressor

    comp = SimpleCompressor()
    result = comp.compress("Please could you kindly help me write a function that sorts a list")

    assert "compressed_prompt" in result
    assert "original_tokens" in result
    assert "compressed_tokens" in result
    assert "ratio" in result
    assert result["compressed_tokens"] <= result["original_tokens"]
    assert 0 < result["ratio"] <= 1.0
    # Filler words should be removed
    assert "please" not in result["compressed_prompt"].lower() or "kindly" not in result["compressed_prompt"].lower()
    print(f"  PASS: compressed {result['original_tokens']} -> {result['compressed_tokens']} tokens (ratio: {result['ratio']:.2f})")


def test_simple_compressor_empty():
    """SimpleCompressor handles empty input gracefully."""
    from vantage_optimizer.compressor import SimpleCompressor

    comp = SimpleCompressor()
    result = comp.compress("")
    assert result["compressed_tokens"] == 0
    assert result["original_tokens"] == 0
    print("  PASS: empty string handled correctly")


def test_simple_compressor_short():
    """SimpleCompressor handles short prompts without breaking."""
    from vantage_optimizer.compressor import SimpleCompressor

    comp = SimpleCompressor()
    result = comp.compress("Hello world")
    assert result["compressed_prompt"] == "Hello world"
    print("  PASS: short prompt preserved")


def test_prompt_compressor_fallback():
    """PromptCompressor falls back to SimpleCompressor when LLMLingua is not available."""
    from vantage_optimizer.compressor import PromptCompressor

    comp = PromptCompressor()
    result = comp.compress("Please could you kindly write a comprehensive function that processes data")
    assert "compressed_prompt" in result
    assert result["compressed_tokens"] <= result["original_tokens"]
    print(f"  PASS: fallback works, ratio: {result['ratio']:.2f}")


def test_compressor_long_text():
    """Compressor handles long text with significant compression."""
    from vantage_optimizer.compressor import SimpleCompressor

    long_prompt = (
        "I would like you to please help me write a comprehensive and detailed function "
        "that can basically process and transform data. Could you kindly make sure it "
        "handles edge cases? I need you to actually implement error handling as well. "
        "In order to make it robust, would you mind adding input validation? "
        "It is important to note that the function should be efficient. "
        "As a matter of fact, it should also be well-documented."
    )
    comp = SimpleCompressor()
    result = comp.compress(long_prompt)
    savings_pct = (1 - result["ratio"]) * 100
    assert savings_pct > 5, f"Expected >5% savings, got {savings_pct:.1f}%"
    print(f"  PASS: long text compressed by {savings_pct:.1f}%")


# ── Unit Tests: Context Manager ───────────────────────────────────────────

def test_context_manager_add_messages():
    """ContextManager stores and retrieves messages."""
    from vantage_optimizer.context_manager import ContextManager

    cm = ContextManager(max_messages=100)
    cm.add_message("user", "Hello")
    cm.add_message("assistant", "Hi there!")
    ctx = cm.get_context()
    assert len(ctx) == 2
    assert ctx[0]["role"] == "user"
    assert ctx[1]["role"] == "assistant"
    print("  PASS: messages stored and retrieved")


def test_context_manager_max_messages():
    """ContextManager respects max_messages limit."""
    from vantage_optimizer.context_manager import ContextManager

    cm = ContextManager(max_messages=5)
    for i in range(10):
        cm.add_message("user", f"Message {i}")
    ctx = cm.get_context()
    assert len(ctx) <= 5
    print(f"  PASS: limited to {len(ctx)} messages (max 5)")


def test_context_manager_stats():
    """ContextManager provides stats."""
    from vantage_optimizer.context_manager import ContextManager

    cm = ContextManager()
    cm.add_message("user", "Test message one two three")
    stats = cm.get_stats()
    assert "total_messages" in stats
    assert stats["total_messages"] == 1
    print(f"  PASS: stats returned correctly")


# ── Unit Tests: Token Counter ────────────────────────────────────────────

def test_token_counter():
    """TokenCounter estimates tokens correctly."""
    from vantage_optimizer.utils import TokenCounter

    count = TokenCounter.count_tokens("Hello world this is a test")
    assert count > 0
    assert isinstance(count, int)
    print(f"  PASS: counted {count} tokens for 6-word text")


def test_cost_estimation():
    """TokenCounter estimates costs for known models."""
    from vantage_optimizer.utils import TokenCounter

    result = TokenCounter.estimate_cost("gpt-4", 1000, 500)
    assert "input_cost" in result
    assert "output_cost" in result
    assert "total_cost" in result
    assert result["total_cost"] > 0
    print(f"  PASS: gpt-4 cost estimate: ${result['total_cost']:.4f}")


def test_savings_calculation():
    """TokenCounter calculates savings correctly."""
    from vantage_optimizer.utils import TokenCounter

    result = TokenCounter.calculate_savings(1000, 600, "gpt-4")
    assert "token_saving" in result
    assert result["token_saving"] == 400
    assert result["compression_ratio"] == 0.6
    print(f"  PASS: savings: {result['token_saving']} tokens, ratio: {result['compression_ratio']}")


# ── API Integration Tests ────────────────────────────────────────────────

def test_api_compress_endpoint():
    """POST /v1/optimizer/compress returns compressed prompt."""
    if not API_KEY:
        print("  SKIP: no API_KEY set")
        return

    resp = requests.post(
        f"{BASE_URL}/v1/optimizer/compress",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"prompt": "Please could you kindly help me write a function that sorts a list of items"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert "compressed_prompt" in data
    assert data["compressed_tokens"] <= data["original_tokens"]
    print(f"  PASS: API compressed {data['original_tokens']} -> {data['compressed_tokens']} tokens")


def test_api_analyze_endpoint():
    """POST /v1/optimizer/analyze returns token analysis."""
    if not API_KEY:
        print("  SKIP: no API_KEY set")
        return

    resp = requests.post(
        f"{BASE_URL}/v1/optimizer/analyze",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"text": "Hello world, this is a test prompt for token analysis", "model": "gpt-4"},
        timeout=10,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert "token_count" in data
    assert data["token_count"] > 0
    print(f"  PASS: API analyzed {data['token_count']} tokens")


def test_api_estimate_endpoint():
    """POST /v1/optimizer/estimate returns cost comparison."""
    if not API_KEY:
        print("  SKIP: no API_KEY set")
        return

    resp = requests.post(
        f"{BASE_URL}/v1/optimizer/estimate",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"prompt": "Write a function to sort an array", "completion_tokens": 200},
        timeout=10,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert "comparisons" in data
    assert len(data["comparisons"]) > 0
    print(f"  PASS: API estimated costs for {len(data['comparisons'])} models")


# ── Runner ────────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("SimpleCompressor: basic compression", test_simple_compressor_basic),
        ("SimpleCompressor: empty input", test_simple_compressor_empty),
        ("SimpleCompressor: short prompt", test_simple_compressor_short),
        ("PromptCompressor: LLMLingua fallback", test_prompt_compressor_fallback),
        ("Compressor: long text", test_compressor_long_text),
        ("ContextManager: add messages", test_context_manager_add_messages),
        ("ContextManager: max messages", test_context_manager_max_messages),
        ("ContextManager: stats", test_context_manager_stats),
        ("TokenCounter: count tokens", test_token_counter),
        ("TokenCounter: cost estimation", test_cost_estimation),
        ("TokenCounter: savings calculation", test_savings_calculation),
        ("API: /v1/optimizer/compress", test_api_compress_endpoint),
        ("API: /v1/optimizer/analyze", test_api_analyze_endpoint),
        ("API: /v1/optimizer/estimate", test_api_estimate_endpoint),
    ]

    passed = failed = skipped = 0
    print(f"\n{'='*60}")
    print(f"  Suite 16: Token Optimizer ({len(tests)} tests)")
    print(f"{'='*60}\n")

    for name, fn in tests:
        try:
            print(f"  [{name}]")
            fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'='*60}\n")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
