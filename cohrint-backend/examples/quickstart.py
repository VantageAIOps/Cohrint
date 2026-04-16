"""
examples/quickstart.py
----------------------
Complete Vantage AI integration examples.
Copy-paste any section into your project.

Install:
    pip install vantage-ai anthropic openai litellm
"""

import vantage

# ══════════════════════════════════════════════════════════
# STEP 1: INITIALISE ONCE (e.g. in app startup or .env)
# ══════════════════════════════════════════════════════════

vantage.init(
    api_key     = "crt_your_key_here",  # from app.vantage.ai > Settings > API Keys
    org         = "acme-corp",           # your org slug
    team        = "product-team",        # default team tag
    environment = "production",          # or "staging", "development"
)


# ══════════════════════════════════════════════════════════
# PATTERN 1: OpenAI (just change the import — 1 line)
# ══════════════════════════════════════════════════════════

from vantage.proxy.openai_proxy import OpenAI  # ← was: from openai import OpenAI

openai_client = OpenAI(api_key="sk-your-openai-key")

def ask_gpt(question: str, user_id: str = "", project: str = "") -> str:
    with vantage.trace(feature="ask-gpt", user_id=user_id, project=project):
        response = openai_client.chat.completions.create(
            model    = "gpt-4o",
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user",   "content": question},
            ],
        )
    return response.choices[0].message.content


# ══════════════════════════════════════════════════════════
# PATTERN 2: Anthropic Claude (same — 1 import swap)
# ══════════════════════════════════════════════════════════

from vantage.proxy.anthropic_proxy import Anthropic  # ← was: import anthropic / anthropic.Anthropic

claude_client = Anthropic(api_key="sk-ant-your-anthropic-key")

def ask_claude(question: str, user_id: str = "") -> str:
    with vantage.trace(feature="ask-claude", user_id=user_id):
        response = claude_client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 1024,
            system     = "You are a helpful assistant.",
            messages   = [{"role": "user", "content": question}],
        )
    return response.content[0].text


# ══════════════════════════════════════════════════════════
# PATTERN 3: GitHub Copilot / Any model via litellm
# ══════════════════════════════════════════════════════════

from vantage.proxy import litellm_proxy as litellm  # ← drop-in for litellm

def ask_any_model(question: str, model: str = "gemini/gemini-2.0-flash") -> str:
    """Works with Gemini, Mistral, Cohere, Groq, Azure — any litellm model."""
    with vantage.trace(feature="multi-model", project="experiments"):
        response = litellm.completion(
            model    = model,
            messages = [{"role": "user", "content": question}]
        )
    return response.choices[0].message.content


# ══════════════════════════════════════════════════════════
# PATTERN 4: Team + Project tagging (enterprise)
# ══════════════════════════════════════════════════════════

def generate_report(user_id: str, department: str) -> str:
    """
    All events inside this block are tagged with:
      - user_id → per-user cost breakdown
      - feature  → feature-level analytics
      - team     → team cost chargeback
      - project  → project budget tracking
    """
    with vantage.trace(
        feature  = "monthly-report",
        user_id  = user_id,
        team     = department,         # e.g. "engineering", "sales", "support"
        project  = "q1-reporting",
        env      = "production",
    ):
        # Multiple AI calls — all tagged identically
        outline   = ask_gpt("Create an outline for Q1 results report")
        executive = ask_claude("Write executive summary for: " + outline[:200])
        return executive


# ══════════════════════════════════════════════════════════
# PATTERN 5: Async (FastAPI / async frameworks)
# ══════════════════════════════════════════════════════════

import asyncio

async def async_pipeline(question: str) -> str:
    """Works with async FastAPI routes."""
    from vantage.proxy.openai_proxy import AsyncOpenAI
    async_client = AsyncOpenAI(api_key="sk-your-openai-key")

    with vantage.trace(feature="async-pipeline"):
        # Run two models in parallel
        gpt_task    = async_client._wrapped_create("gpt-4o-mini",  [{"role":"user","content":question}])
        # Other async work can run here too
        result = await gpt_task
    return result.choices[0].message.content


# ══════════════════════════════════════════════════════════
# TEST — Run this file to verify everything works
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os

    # Load real keys from env for testing
    vantage.init(
        api_key     = os.getenv("VANTAGE_API_KEY", "crt_dev_test"),
        environment = "development",
        debug       = True,
    )

    print("Testing OpenAI proxy...")
    # answer = ask_gpt("What is 2+2?", user_id="test-user", project="testing")
    # print("GPT answer:", answer)

    print("Testing Anthropic proxy...")
    # answer = ask_claude("What is 2+2?")
    # print("Claude answer:", answer)

    print("\nAll SDK imports OK. Uncomment API calls to test live.")
    print("View events at: https://vantageai.aman-lpucse.workers.dev/app.html")

    # Force flush before exit
    vantage.flush()
