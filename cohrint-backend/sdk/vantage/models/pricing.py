"""
Live pricing for 23 models — used for cost calculation and savings analysis.
"""
PRICES = {
    "gpt-4o":               {"provider":"openai",    "input":2.50,   "output":10.00,  "cache":1.25},
    "gpt-4o-mini":          {"provider":"openai",    "input":0.15,   "output":0.60,   "cache":0.075},
    "o1":                   {"provider":"openai",    "input":15.00,  "output":60.00,  "cache":7.50},
    "o3-mini":              {"provider":"openai",    "input":1.10,   "output":4.40,   "cache":0.55},
    "gpt-3.5-turbo":        {"provider":"openai",    "input":0.50,   "output":1.50,   "cache":0},
    "claude-opus-4-6":      {"provider":"anthropic", "input":15.00,  "output":75.00,  "cache":1.50},
    "claude-sonnet-4-6":    {"provider":"anthropic", "input":3.00,   "output":15.00,  "cache":0.30},
    "claude-haiku-4-5":     {"provider":"anthropic", "input":0.80,   "output":4.00,   "cache":0.08},
    "claude-3-5-sonnet":    {"provider":"anthropic", "input":3.00,   "output":15.00,  "cache":0.30},
    "claude-3-haiku":       {"provider":"anthropic", "input":0.25,   "output":1.25,   "cache":0.03},
    "gemini-2.0-flash":     {"provider":"google",    "input":0.10,   "output":0.40,   "cache":0.025},
    "gemini-1.5-pro":       {"provider":"google",    "input":1.25,   "output":5.00,   "cache":0.3125},
    "gemini-1.5-flash":     {"provider":"google",    "input":0.075,  "output":0.30,   "cache":0.01875},
    "gemini-1.5-flash-8b":  {"provider":"google",    "input":0.0375, "output":0.15,   "cache":0.01},
    "llama-3.3-70b":        {"provider":"meta",      "input":0.23,   "output":0.40,   "cache":0},
    "llama-3.1-405b":       {"provider":"meta",      "input":3.00,   "output":3.00,   "cache":0},
    "llama-3.1-8b":         {"provider":"meta",      "input":0.05,   "output":0.08,   "cache":0},
    "mistral-large-latest": {"provider":"mistral",   "input":2.00,   "output":6.00,   "cache":0},
    "mistral-small-latest": {"provider":"mistral",   "input":0.10,   "output":0.30,   "cache":0},
    "command-r-plus":       {"provider":"cohere",    "input":2.50,   "output":10.00,  "cache":0},
    "command-r":            {"provider":"cohere",    "input":0.15,   "output":0.60,   "cache":0},
    "grok-2":               {"provider":"xai",       "input":2.00,   "output":10.00,  "cache":0},
}

_FLAT = {}
for name, p in PRICES.items():
    _FLAT[name] = p


def calculate_cost(model: str, prompt: int, completion: int, cached: int = 0) -> dict:
    p = _FLAT.get(model)
    if not p:
        # fuzzy match
        for k in _FLAT:
            if model.startswith(k) or k.startswith(model):
                p = _FLAT[k]; break
    if not p:
        return {"input": 0.0, "output": 0.0, "total": 0.0}
    uncached = max(0, prompt - cached)
    inp  = (uncached / 1e6) * p["input"] + (cached / 1e6) * p.get("cache", 0)
    out  = (completion / 1e6) * p["output"]
    return {"input": round(inp, 8), "output": round(out, 8), "total": round(inp + out, 8)}


def find_cheapest(model: str, prompt: int, completion: int) -> dict | None:
    current = calculate_cost(model, prompt, completion)["total"]
    best    = None
    for name, p in _FLAT.items():
        if name == model: continue
        cost = calculate_cost(name, prompt, completion)["total"]
        if cost < current and (best is None or cost < best["cost"]):
            best = {"model": name, "cost": cost}
    return best
