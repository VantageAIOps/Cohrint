"""
optimizer.py — Prompt optimization engine.

6-layer compression that preserves code blocks:
0. Remove duplicate sentences
1. Remove filler phrases
2. Apply verbose rewrites (regex)
3. Strip filler words
4. Collapse whitespace
5. Trim

Ported from vantage-cli/src/optimizer.ts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Filler phrases to strip entirely
# ---------------------------------------------------------------------------
FILLER_PHRASES: list[str] = [
    "i'd like you to", "i want you to", "i need you to",
    "would you mind", "could you please", "can you please",
    "please note that", "it is important to note that",
    "as an ai language model", "as a helpful assistant",
    "in order to", "for the purpose of", "with regard to",
    "in the context of", "it should be noted that",
    "it is worth mentioning that", "i was wondering if you could",
    "it goes without saying", "needless to say",
    "as previously mentioned", "as stated above",
    "for your information", "i would appreciate it if you could",
    "please be advised that", "at the end of the day",
    "in today's world", "in this day and age",
    "each and every", "first and foremost",
    "due to the fact that", "on account of the fact that",
    "in light of the fact that", "despite the fact that",
    "the reason is because",
]

# ---------------------------------------------------------------------------
# Verbose phrase → concise replacement
# ---------------------------------------------------------------------------
VERBOSE_REWRITES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\bfor the purpose of\b", re.I), "to"),
    (re.compile(r"\bwith regard to\b", re.I), "regarding"),
    (re.compile(r"\bin the context of\b", re.I), "in"),
    (re.compile(r"\bdue to the fact that\b", re.I), "because"),
    (re.compile(r"\bon account of the fact that\b", re.I), "because"),
    (re.compile(r"\bin light of the fact that\b", re.I), "since"),
    (re.compile(r"\bdespite the fact that\b", re.I), "although"),
    (re.compile(r"\bthe reason is because\b", re.I), "because"),
    (re.compile(r"\bin the event that\b", re.I), "if"),
    (re.compile(r"\bin the near future\b", re.I), "soon"),
    (re.compile(r"\bat this point in time\b", re.I), "now"),
    (re.compile(r"\bat the present time\b", re.I), "now"),
    (re.compile(r"\bfor all intents and purposes\b", re.I), "effectively"),
    (re.compile(r"\bin a manner of speaking\b", re.I), ""),
    (re.compile(r"\bby means of\b", re.I), "by"),
    (re.compile(r"\bin the amount of\b", re.I), "for"),
    (re.compile(r"\bhas the ability to\b", re.I), "can"),
    (re.compile(r"\bis able to\b", re.I), "can"),
    (re.compile(r"\bit is possible that\b", re.I), "possibly"),
    (re.compile(r"\bthere is a possibility that\b", re.I), "possibly"),
    (re.compile(r"\bit is necessary that\b", re.I), "must"),
    (re.compile(r"\bit is important that\b", re.I), "must"),
    (re.compile(r"\bhas the capacity to\b", re.I), "can"),
    (re.compile(r"\bin close proximity to\b", re.I), "near"),
    (re.compile(r"\ba large number of\b", re.I), "many"),
    (re.compile(r"\ba small number of\b", re.I), "few"),
    (re.compile(r"\bthe vast majority of\b", re.I), "most"),
    (re.compile(r"\bon a regular basis\b", re.I), "regularly"),
    (re.compile(r"\bin an effort to\b", re.I), "to"),
    (re.compile(r"\bwith the exception of\b", re.I), "except"),
    (re.compile(r"\bas a consequence of\b", re.I), "because of"),
    (re.compile(r"\bas a result of\b", re.I), "from"),
    (re.compile(r"\bfor the reason that\b", re.I), "because"),
    (re.compile(r"\bin such a way that\b", re.I), "so that"),
    (re.compile(r"\bin spite of\b", re.I), "despite"),
    (re.compile(r"\buntil such time as\b", re.I), "until"),
    (re.compile(r"\bwith reference to\b", re.I), "about"),
    (re.compile(r"\bin relation to\b", re.I), "about"),
    (re.compile(r"\bin connection with\b", re.I), "about"),
    (re.compile(r"\btake into consideration\b", re.I), "consider"),
    (re.compile(r"\bmake a decision\b", re.I), "decide"),
]

FILLER_WORDS_RE = re.compile(
    r"\b(just|really|very|quite|basically|actually|simply|honestly|literally|"
    r"definitely|certainly|absolutely|obviously|clearly|essentially|practically|"
    r"virtually|merely|somewhat|rather|fairly|pretty much)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Structured data detection — skip optimization for code/JSON/URLs
# ---------------------------------------------------------------------------

def looks_like_structured_data(text: str) -> bool:
    """Return True if text is JSON, code, or URL-heavy (should skip optimizer)."""
    trimmed = text.strip()
    if trimmed.startswith("{") or trimmed.startswith("["):
        return True
    if trimmed.startswith("```"):
        return True
    if re.search(r"```[\s\S]*?```", text):
        return True
    if re.search(r"`[^`\n]+`", text):
        return True
    if len(re.findall(r"https?://", text)) > 2:
        return True
    symbols = len(re.findall(r"[{}()\[\];=<>]", text))
    if symbols > len(text) * 0.1:
        return True
    return False


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    """Approximate token count. ~4 chars/token for prose, ~3 for code."""
    if not text or not text.strip():
        return 0
    trimmed = text.strip()
    code_chars = len(re.findall(r"[{}()\[\];=<>|&!~^%]", trimmed))
    is_code_heavy = code_chars > len(trimmed) * 0.05
    chars_per_token = 3 if is_code_heavy else 4
    return max(1, len(trimmed) // chars_per_token)


# ---------------------------------------------------------------------------
# Compression engine
# ---------------------------------------------------------------------------

_CODE_PATTERN = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]+`")


def _split_code_and_prose(text: str) -> list[tuple[str, str]]:
    """Split text into (type, content) pairs. Code blocks are never compressed."""
    segments: list[tuple[str, str]] = []
    last = 0
    for m in _CODE_PATTERN.finditer(text):
        if m.start() > last:
            segments.append(("prose", text[last : m.start()]))
        segments.append(("code", m.group()))
        last = m.end()
    if last < len(text):
        segments.append(("prose", text[last:]))
    return segments or [("prose", text)]


def _deduplicate_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        key = re.sub(r"[.!?]+$", "", part.strip().lower()).strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(part)
    return " ".join(unique)


def _compress_prose(prose: str) -> str:
    result = prose
    # Layer 0: deduplicate
    result = _deduplicate_sentences(result)
    # Layer 1: filler phrases
    for phrase in FILLER_PHRASES:
        result = re.sub(re.escape(phrase), "", result, flags=re.I)
    # Layer 2: verbose rewrites
    for pattern, replacement in VERBOSE_REWRITES:
        result = pattern.sub(replacement, result)
    # Layer 3: filler words
    result = FILLER_WORDS_RE.sub("", result)
    # Layer 4: collapse whitespace
    result = re.sub(r"\s{2,}", " ", result)
    # Layer 5: trim
    return result.strip()


def compress_prompt(prompt: str) -> str:
    """Apply 6-layer compression. Code blocks are preserved."""
    segments = _split_code_and_prose(prompt)
    return "".join(
        content if stype == "code" else _compress_prose(content)
        for stype, content in segments
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    original: str
    optimized: str
    original_tokens: int
    optimized_tokens: int
    saved_tokens: int
    saved_percent: int


def optimize_prompt(prompt: str) -> OptimizationResult:
    """Optimize a prompt and return before/after stats. Skips structured data."""
    if looks_like_structured_data(prompt):
        tokens = count_tokens(prompt)
        return OptimizationResult(
            original=prompt, optimized=prompt,
            original_tokens=tokens, optimized_tokens=tokens,
            saved_tokens=0, saved_percent=0,
        )
    optimized = compress_prompt(prompt)
    orig_tokens = count_tokens(prompt)
    opt_tokens = count_tokens(optimized)
    saved = orig_tokens - opt_tokens
    pct = round((saved / orig_tokens) * 100) if orig_tokens > 0 else 0
    return OptimizationResult(
        original=prompt,
        optimized=optimized,
        original_tokens=orig_tokens,
        optimized_tokens=opt_tokens,
        saved_tokens=saved,
        saved_percent=pct,
    )
