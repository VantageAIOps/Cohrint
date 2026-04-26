"""
optimizer.py — Prompt optimization engine.

6-layer compression that preserves code blocks:
0. Remove duplicate sentences
1. Remove filler phrases
2. Apply verbose rewrites (regex)
3. Strip filler words
4. Collapse whitespace
5. Trim

Prompt optimization module for cohrint-agent.
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
    """Return True if the text is *dominantly* structured (JSON, code, URL
    dump) and therefore has no prose worth compressing.

    Prior versions returned True for any prompt containing a single fenced
    block or inline backtick reference — which meant a technical prose
    prompt like "confirm that ``validateStream()`` exists in package X"
    silently skipped optimization. ``_split_code_and_prose`` already
    preserves code regions during compression, so we only bail out of
    optimization when the structured part is the *whole* prompt.
    """
    trimmed = text.strip()
    # Pure JSON / array payload.
    if trimmed.startswith("{") or trimmed.startswith("["):
        return True
    # Entire prompt opens with a code fence — no prose preamble to compress.
    if trimmed.startswith("```"):
        return True
    # URL-heavy dump (link list / sitemap paste).
    if len(re.findall(r"https?://", text)) > 2:
        return True
    # Symbol density — if the text is overwhelmingly code-like characters,
    # treat as structured.
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
    """Backward-compat shim — used by tests."""
    return _compress_prose_tracked(prose)[0]


def _compress_prose_tracked(prose: str) -> tuple[str, list[str]]:
    """Compress prose and return (result, list of human-readable change descriptions)."""
    result = prose
    changes: list[str] = []

    # Layer 0: deduplicate sentences
    deduped = _deduplicate_sentences(result)
    if deduped != result:
        changes.append("removed duplicate sentences")
    result = deduped

    # Layer 1: filler phrases — collect unique hits (up to 3 examples)
    hits: list[str] = []
    for phrase in FILLER_PHRASES:
        if re.search(re.escape(phrase), result, flags=re.I):
            hits.append(f'"{phrase}"')
        result = re.sub(re.escape(phrase), "", result, flags=re.I)
    if hits:
        sample = ", ".join(hits[:3])
        suffix = f" (+{len(hits)-3} more)" if len(hits) > 3 else ""
        changes.append(f"removed filler phrases: {sample}{suffix}")

    # Layer 2: verbose rewrites — collect unique hits (up to 3 examples)
    rewrites: list[str] = []
    for pattern, replacement in VERBOSE_REWRITES:
        if pattern.search(result):
            rewrites.append(f'"{pattern.pattern[2:-2]}" → "{replacement}"')
        result = pattern.sub(replacement, result)
    if rewrites:
        sample = ", ".join(rewrites[:3])
        suffix = f" (+{len(rewrites)-3} more)" if len(rewrites) > 3 else ""
        changes.append(f"rewrote verbose phrases: {sample}{suffix}")

    # Layer 3: filler words — count hits
    filler_hits = FILLER_WORDS_RE.findall(result)
    result = FILLER_WORDS_RE.sub("", result)
    if filler_hits:
        unique = sorted(set(w.lower() for w in filler_hits))
        sample = ", ".join(unique[:5])
        suffix = f" (+{len(unique)-5} more)" if len(unique) > 5 else ""
        changes.append(f"stripped filler words: {sample}{suffix}")

    # Layer 4+5: collapse whitespace and trim
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result, changes


def compress_prompt(prompt: str) -> str:
    """Apply compression. Code blocks are preserved."""
    segments = _split_code_and_prose(prompt)
    return "".join(
        content if stype == "code" else _compress_prose_tracked(content)[0]
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
    changes: list[str]


def estimated_cost_saved(result: OptimizationResult, model: str | None) -> float:
    """Return USD the user did NOT have to spend on input tokens thanks to
    optimization. Output price is irrelevant — we measure what we stripped
    from the prompt before send.

    Unknown / None model falls back to the ``default`` rate table so the
    value is still honest (never silently 0.0, which would mask real
    savings in dashboards — mirrors calculate_cost T-COST.unknown_model).
    """
    saved = max(0, result.saved_tokens)
    if saved == 0:
        return 0.0
    from .pricing import calculate_cost
    return calculate_cost(model or "default", prompt_tokens=saved, completion_tokens=0)


def optimize_prompt(prompt: str) -> OptimizationResult:
    """Optimize a prompt and return before/after stats with change list. Skips structured data."""
    if looks_like_structured_data(prompt):
        tokens = count_tokens(prompt)
        return OptimizationResult(
            original=prompt, optimized=prompt,
            original_tokens=tokens, optimized_tokens=tokens,
            saved_tokens=0, saved_percent=0, changes=[],
        )
    segments = _split_code_and_prose(prompt)
    parts: list[str] = []
    all_changes: list[str] = []
    for stype, content in segments:
        if stype == "code":
            parts.append(content)
        else:
            compressed, changes = _compress_prose_tracked(content)
            parts.append(compressed)
            all_changes.extend(changes)
    optimized = "".join(parts)
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
        changes=all_changes,
    )
