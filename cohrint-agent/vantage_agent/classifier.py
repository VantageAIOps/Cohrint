"""
classifier.py — Input classification and optimization pipeline.

Classifies user input by type (command, prompt, short-answer, etc.) and
optionally compresses prompts before forwarding to the agent.

Ported from test-classifier.mjs.
"""
from __future__ import annotations

import re

from .optimizer import looks_like_structured_data, optimize_prompt

# ---------------------------------------------------------------------------
# Command maps
# ---------------------------------------------------------------------------

AGENT_COMMANDS: dict[str, set[str]] = {
    "claude": {"/compact", "/clear", "/model", "/help", "/cost", "/review", "/init", "/login"},
    "gemini": {"/compress", "/clear", "/model", "/help", "/stats"},
    "codex": {"/approval", "/model", "/help"},
    "aider": {"/add", "/drop", "/clear", "/model", "/help", "/diff", "/run", "/test", "/undo"},
    "chatgpt": set(),  # Cursor has no slash commands in terminal
}

VANTAGE_COMMANDS: set[str] = {
    "/cost", "/exit-session", "/opt-off", "/opt-on", "/opt-auto", "/opt-ask",
    "/compare", "/recommend",
}

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_SHORT_ANSWERS = {"y", "yes", "no", "n"}


def classify_input(text: str, agent: str = "claude") -> str:
    """
    Classify *text* into one of:
      "unknown"         — empty input
      "short-answer"    — single word, boolean, numeric, or <=2 words
      "vantage-command" — starts with / and is a Vantage command
      "agent-command"   — starts with /, @, or ! and matches agent commands
      "structured"      — JSON, code blocks, inline code, URL-heavy, symbol-heavy
      "prompt"          — everything else (5+ words natural language)
    """
    stripped = text.strip()

    if not stripped:
        return "unknown"

    # Slash-command dispatch
    if stripped.startswith("/"):
        # Extract the bare command token (e.g. "/cost" from "/cost show details")
        command = stripped.split()[0].lower()
        if command in VANTAGE_COMMANDS:
            return "vantage-command"
        agent_cmds = AGENT_COMMANDS.get(agent, set())
        if command in agent_cmds:
            return "agent-command"

    # @ and ! prefixes are always agent commands
    if stripped.startswith("@") or stripped.startswith("!"):
        return "agent-command"

    # Structured data check (before short-answer — JSON/code can be 1 "word")
    if looks_like_structured_data(stripped):
        return "structured"

    # Short-answer check
    words = stripped.split()
    if stripped.lower() in _SHORT_ANSWERS:
        return "short-answer"
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        return "short-answer"
    if len(words) <= 2:
        return "short-answer"

    return "prompt"


# ---------------------------------------------------------------------------
# Process (classify + optional optimization)
# ---------------------------------------------------------------------------

def process_input(
    text: str,
    agent: str = "claude",
    opt_mode: str = "auto",
) -> dict:
    """
    Classify and optionally optimize *text*.

    Returns a dict with keys:
      input        — original text
      type         — classification string
      forwarded    — text to forward (original or optimized)
      optimized    — bool, whether compression was applied
      saved_tokens — int, tokens saved (0 if not optimized)
      reverted     — bool, True if compression was over-aggressive and reverted
    """
    input_type = classify_input(text, agent)

    result: dict = {
        "input": text,
        "type": input_type,
        "forwarded": text,
        "optimized": False,
        "saved_tokens": 0,
        "reverted": False,
    }

    # Only optimize natural-language prompts
    if input_type != "prompt" or opt_mode == "never":
        return result

    opt = optimize_prompt(text)

    orig_len = len(text.strip())
    comp_len = len(opt.optimized.strip())

    # Revert if over-compressed (compressed to <20% of original)
    if orig_len > 0 and comp_len < orig_len * 0.20:
        result["reverted"] = True
        return result

    # Skip if savings too small: <3 tokens or <5%
    if opt.saved_tokens < 3 or opt.saved_percent < 5:
        return result

    result["forwarded"] = opt.optimized
    result["optimized"] = True
    result["saved_tokens"] = opt.saved_tokens
    return result
