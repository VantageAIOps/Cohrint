/**
 * cohrint-models.js — Shared AI model pricing & metadata
 * Single source of truth used by app.html and calculator.html
 * Updated: March 2026
 */

const COHRINT_MODELS = [
  // ── OpenAI ──────────────────────────────────────────────────────────────────
  { provider:"openai",   name:"gpt-4o",               label:"GPT-4o",             input:2.50,  output:10.00, cacheRead:1.25,  context:128,  tier:"frontier", speed:"medium", released:"2024-05" },
  { provider:"openai",   name:"gpt-4o-mini",           label:"GPT-4o Mini",        input:0.15,  output:0.60,  cacheRead:0.075, context:128,  tier:"fast",     speed:"fast",   released:"2024-07" },
  { provider:"openai",   name:"o1",                    label:"o1",                 input:15.00, output:60.00, cacheRead:7.50,  context:200,  tier:"frontier", speed:"slow",   released:"2024-09" },
  { provider:"openai",   name:"o3-mini",               label:"o3-mini",            input:1.10,  output:4.40,  cacheRead:0.55,  context:200,  tier:"mid",      speed:"medium", released:"2025-01" },
  { provider:"openai",   name:"gpt-4-turbo",           label:"GPT-4 Turbo",        input:10.00, output:30.00, cacheRead:0,     context:128,  tier:"frontier", speed:"medium", released:"2024-04" },
  { provider:"openai",   name:"gpt-3.5-turbo",         label:"GPT-3.5 Turbo",      input:0.50,  output:1.50,  cacheRead:0,     context:16,   tier:"fast",     speed:"fast",   released:"2023-03" },

  // ── Anthropic ────────────────────────────────────────────────────────────────
  { provider:"anthropic",name:"claude-opus-4-6",       label:"Claude Opus 4.6",    input:15.00, output:75.00, cacheRead:1.50,  context:200,  tier:"frontier", speed:"slow",   released:"2026-02" },
  { provider:"anthropic",name:"claude-sonnet-4-6",     label:"Claude Sonnet 4.6",  input:3.00,  output:15.00, cacheRead:0.30,  context:200,  tier:"mid",      speed:"medium", released:"2026-02" },
  { provider:"anthropic",name:"claude-haiku-4-5",      label:"Claude Haiku 4.5",   input:0.80,  output:4.00,  cacheRead:0.08,  context:200,  tier:"fast",     speed:"fast",   released:"2025-10" },
  { provider:"anthropic",name:"claude-3-5-sonnet",     label:"Claude 3.5 Sonnet",  input:3.00,  output:15.00, cacheRead:0.30,  context:200,  tier:"mid",      speed:"medium", released:"2024-10" },
  { provider:"anthropic",name:"claude-3-haiku",        label:"Claude 3 Haiku",     input:0.25,  output:1.25,  cacheRead:0.03,  context:200,  tier:"fast",     speed:"fast",   released:"2024-03" },

  // ── Google ───────────────────────────────────────────────────────────────────
  { provider:"google",   name:"gemini-2.0-flash",      label:"Gemini 2.0 Flash",   input:0.10,  output:0.40,  cacheRead:0.025, context:1000, tier:"fast",     speed:"fast",   released:"2025-02" },
  { provider:"google",   name:"gemini-1.5-pro",        label:"Gemini 1.5 Pro",     input:1.25,  output:5.00,  cacheRead:0.3125,context:1000, tier:"frontier", speed:"medium", released:"2024-05" },
  { provider:"google",   name:"gemini-1.5-flash",      label:"Gemini 1.5 Flash",   input:0.075, output:0.30,  cacheRead:0.01875,context:1000,tier:"fast",     speed:"fast",   released:"2024-05" },
  { provider:"google",   name:"gemini-1.5-flash-8b",   label:"Gemini Flash 8B",    input:0.0375,output:0.15,  cacheRead:0.01,  context:1000, tier:"fast",     speed:"fast",   released:"2024-10" },

  // ── Meta / Open Source ───────────────────────────────────────────────────────
  { provider:"meta",     name:"llama-3.3-70b",         label:"Llama 3.3 70B",      input:0.23,  output:0.40,  cacheRead:0,     context:128,  tier:"mid",      speed:"fast",   released:"2024-12" },
  { provider:"meta",     name:"llama-3.1-405b",        label:"Llama 3.1 405B",     input:3.00,  output:3.00,  cacheRead:0,     context:128,  tier:"frontier", speed:"medium", released:"2024-07" },
  { provider:"meta",     name:"llama-3.1-8b",          label:"Llama 3.1 8B",       input:0.05,  output:0.08,  cacheRead:0,     context:128,  tier:"fast",     speed:"fast",   released:"2024-07" },

  // ── Mistral ───────────────────────────────────────────────────────────────────
  { provider:"mistral",  name:"mistral-large-latest",  label:"Mistral Large",      input:2.00,  output:6.00,  cacheRead:0,     context:131,  tier:"frontier", speed:"medium", released:"2024-11" },
  { provider:"mistral",  name:"mistral-small-latest",  label:"Mistral Small",      input:0.10,  output:0.30,  cacheRead:0,     context:131,  tier:"fast",     speed:"fast",   released:"2024-09" },

  // ── Cohere ────────────────────────────────────────────────────────────────────
  { provider:"cohere",   name:"command-r-plus",        label:"Command R+",         input:2.50,  output:10.00, cacheRead:0,     context:128,  tier:"frontier", speed:"medium", released:"2024-04" },
  { provider:"cohere",   name:"command-r",             label:"Command R",          input:0.15,  output:0.60,  cacheRead:0,     context:128,  tier:"fast",     speed:"fast",   released:"2024-03" },

  // ── xAI ───────────────────────────────────────────────────────────────────────
  { provider:"xai",      name:"grok-2",                label:"Grok-2",             input:2.00,  output:10.00, cacheRead:0,     context:131,  tier:"frontier", speed:"medium", released:"2024-08" },
];

const PROVIDER_META = {
  openai:    { label:"OpenAI",    color:"#74aa9c", bg:"rgba(116,170,156,.15)" },
  anthropic: { label:"Anthropic", color:"#d97757", bg:"rgba(217,119,87,.15)"  },
  google:    { label:"Google",    color:"#4285f4", bg:"rgba(66,133,244,.15)"  },
  meta:      { label:"Meta",      color:"#a78bfa", bg:"rgba(167,139,250,.15)" },
  mistral:   { label:"Mistral",   color:"#f97316", bg:"rgba(249,115,22,.15)"  },
  cohere:    { label:"Cohere",    color:"#06b6d4", bg:"rgba(6,182,212,.15)"   },
  xai:       { label:"xAI",       color:"#e2e8f0", bg:"rgba(226,232,240,.15)" },
};

// Cost calculation utilities
function calcCost(model, promptTokens, completionTokens, cachedTokens = 0) {
  const m = COHRINT_MODELS.find(x => x.name === model);
  if (!m) return 0;
  const uncached = Math.max(0, promptTokens - cachedTokens);
  return (uncached / 1e6) * m.input + (cachedTokens / 1e6) * m.cacheRead + (completionTokens / 1e6) * m.output;
}

function cheapestAlternative(model, promptTokens, completionTokens) {
  const current = calcCost(model, promptTokens, completionTokens);
  return COHRINT_MODELS
    .filter(m => m.name !== model)
    .map(m => ({ ...m, cost: calcCost(m.name, promptTokens, completionTokens) }))
    .filter(m => m.cost < current)
    .sort((a, b) => a.cost - b.cost)[0] || null;
}

function allCosts(promptTokens, completionTokens) {
  return COHRINT_MODELS
    .map(m => ({ ...m, cost: calcCost(m.name, promptTokens, completionTokens) }))
    .sort((a, b) => a.cost - b.cost);
}

if (typeof module !== "undefined") module.exports = { COHRINT_MODELS, PROVIDER_META, calcCost, cheapestAlternative, allCosts };
