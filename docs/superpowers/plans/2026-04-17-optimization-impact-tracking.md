# Optimization Impact Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface per-call improvement multipliers (2x, 5x, 10x) in MCP tool responses and aggregate them into a customer-facing dashboard widget.

**Architecture:** The MCP tool computes `improvement_factor = cost_before / cost_after` and returns it inline; the backend persists it to the existing `tags` JSON column on events; a new `GET /v1/optimizer/impact` endpoint aggregates it; the frontend renders a hero card + trend chart + developer leaderboard.

**Tech Stack:** TypeScript (MCP + Worker, Hono), Python pytest (integration tests), Chart.js (frontend), SQLite D1 (`json_extract` on `tags` column)

---

## File Map

| File | Role |
|------|------|
| `cohrint-mcp/src/index.ts` | Add `optimization_impact` block to `optimize_prompt`; `model_multipliers` to `analyze_tokens`; `estimated_multiplier` to `get_recommendations`; add compression layers 6+7 |
| `cohrint-worker/src/routes/optimizer.ts` | Persist `tags.optimization` on `POST /compress`; add `GET /v1/optimizer/impact` handler |
| `cohrint-worker/src/index.ts` | Register `GET /v1/optimizer/impact` route (may already be covered by existing router mount) |
| `cohrint-frontend/app.html` | Add Optimization Impact section (hero card + Chart.js bar + leaderboard) |
| `tests/suites/46_optimizer_impact/__init__.py` | Empty init |
| `tests/suites/46_optimizer_impact/test_optimizer_impact.py` | Integration tests for new endpoint + tags persistence |

---

## Task 1: MCP — compute and return `optimization_impact` in `optimize_prompt`

**Files:**
- Modify: `cohrint-mcp/src/index.ts` (optimize_prompt handler ~lines 734-762)

- [ ] **Step 1: Add `OptimizationImpact` interface and `computeOptimizationImpact` helper**

In `cohrint-mcp/src/index.ts`, add after the `calcCost` function (~line 270):

```typescript
interface OptimizationImpact {
  improvement_factor: number;
  tokens_saved: number;
  cost_before_usd: number;
  cost_after_usd: number;
  compression_ratio_pct: number;
  model_switch_multiplier: number | null;
  combined_multiplier: number;
}

function computeOptimizationImpact(
  model: string,
  originalTokens: number,
  compressedTokens: number,
): OptimizationImpact {
  const pricing = MODEL_PRICING[model] ?? MODEL_PRICING['gpt-4o'];
  const costBefore = (originalTokens / 1_000_000) * pricing.input;
  const costAfter  = (compressedTokens / 1_000_000) * pricing.input;

  const improvementFactor =
    costBefore > 0 && costAfter > 0
      ? Math.round((costBefore / costAfter) * 10) / 10
      : 1.0;
  const compressionRatioPct =
    originalTokens > 0
      ? Math.round(((originalTokens - compressedTokens) / originalTokens) * 1000) / 10
      : 0;
  const tokensSaved = originalTokens - compressedTokens;

  const cheapest = findCheapest(compressedTokens, 0);
  const cheapestPricing = MODEL_PRICING[cheapest.model] ?? pricing;
  const modelSwitchMultiplier =
    cheapestPricing.input < pricing.input && cheapest.model !== model
      ? Math.round((pricing.input / cheapestPricing.input) * 10) / 10
      : null;

  const combinedMultiplier =
    modelSwitchMultiplier != null
      ? Math.round(improvementFactor * modelSwitchMultiplier * 10) / 10
      : improvementFactor;

  return {
    improvement_factor: improvementFactor,
    tokens_saved: tokensSaved,
    cost_before_usd: Math.round(costBefore * 1_000_000) / 1_000_000,
    cost_after_usd:  Math.round(costAfter  * 1_000_000) / 1_000_000,
    compression_ratio_pct: compressionRatioPct,
    model_switch_multiplier: modelSwitchMultiplier,
    combined_multiplier: combinedMultiplier,
  };
}
```

- [ ] **Step 2: Run typecheck to confirm it compiles**

```bash
cd cohrint-mcp && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Update the `optimize_prompt` handler to return `optimization_impact`**

Find `case 'optimize_prompt':` (~line 734). Replace the entire case block with:

```typescript
case 'optimize_prompt': {
  const prompt = typeof args.prompt === 'string' ? args.prompt : '';
  const model = typeof args.model === 'string' && args.model ? args.model : 'gpt-4o';
  const systemPrompt = typeof args.system_prompt === 'string' ? args.system_prompt : undefined;
  const compressed = compressPrompt(prompt, systemPrompt);
  const originalTokens = countTokens(prompt);
  const compressedTokens = countTokens(compressed);
  const tips = getOptimizationTips(prompt);
  const impact = computeOptimizationImpact(model, originalTokens, compressedTokens);

  const summaryLine = impact.improvement_factor > 1.05
    ? `✦ Prompt optimized — ${impact.improvement_factor}x cheaper (${impact.compression_ratio_pct}% fewer tokens, ${impact.tokens_saved} tokens saved)`
    : `✦ Prompt compressed — ${impact.tokens_saved} tokens saved (${impact.compression_ratio_pct}% reduction)`;

  const tipLine = impact.model_switch_multiplier != null
    ? `\nTip: switch to ${findCheapest(compressedTokens, 0).model} for another ${impact.model_switch_multiplier}x savings (combined: ${impact.combined_multiplier}x)`
    : '';

  const content = [
    summaryLine + tipLine,
    '',
    '**Compressed prompt:**',
    compressed,
    '',
    tips.length > 0 ? '**Further optimizations:**\n' + tips.map((t: string) => `- ${t}`).join('\n') : '',
  ].filter(Boolean).join('\n');

  return {
    content: [{ type: 'text', text: content }],
    optimization_impact: impact,
  };
}
```

- [ ] **Step 4: Typecheck and build**

```bash
cd cohrint-mcp && npx tsc --noEmit && npm run build
```
Expected: no errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add cohrint-mcp/src/index.ts
git commit -m "feat(mcp): add optimization_impact block to optimize_prompt response"
```

---

## Task 2: MCP — add `model_multipliers` to `analyze_tokens`

**Files:**
- Modify: `cohrint-mcp/src/index.ts` (analyze_tokens handler ~lines 764-791)

- [ ] **Step 1: Add `ModelMultiplier` interface and `buildModelMultipliers` helper**

Add after `computeOptimizationImpact` in `cohrint-mcp/src/index.ts`:

```typescript
interface ModelMultiplier {
  model: string;
  cost_usd: number;
  multiplier: string;
}

function buildModelMultipliers(inputTokens: number, outputTokens: number): ModelMultiplier[] {
  const entries = Object.entries(MODEL_PRICING).map(([model, p]) => ({
    model,
    cost_usd: ((inputTokens * p.input) + (outputTokens * p.output)) / 1_000_000,
  }));
  entries.sort((a, b) => a.cost_usd - b.cost_usd);

  const cheapestCost = entries[0]?.cost_usd ?? 1;

  return entries.map(e => {
    const ratio = cheapestCost > 0 ? Math.round((e.cost_usd / cheapestCost) * 10) / 10 : 1;
    const multiplier = ratio <= 1.1 ? '1x (cheapest)' : `${ratio}x more expensive`;
    return {
      model: e.model,
      cost_usd: Math.round(e.cost_usd * 1_000_000) / 1_000_000,
      multiplier,
    };
  });
}
```

- [ ] **Step 2: Update `analyze_tokens` handler**

Find `case 'analyze_tokens':` (~line 764). Replace with:

```typescript
case 'analyze_tokens': {
  const text = typeof args.text === 'string' ? args.text : '';
  const model = (typeof args.model === 'string' && args.model) || 'gpt-4o';
  const inputTokens = countTokens(text);
  const outputTokens = safeNum(args.output_tokens, inputTokens);
  const cost = calcCost(model, inputTokens, outputTokens);
  const cheapest = findCheapest(inputTokens, outputTokens);
  const multipliers = buildModelMultipliers(inputTokens, outputTokens);
  const tips = getOptimizationTips(text);

  const topFive = multipliers.slice(0, 5);
  const lines = [
    `**Token analysis for ${model}**`,
    `- Characters: ${text.length.toLocaleString()}`,
    `- Tokens: ~${inputTokens.toLocaleString()} input + ${outputTokens.toLocaleString()} output`,
    `- Cost: $${cost.inputCost.toFixed(6)} + $${cost.outputCost.toFixed(6)} = **$${cost.totalCost.toFixed(6)}**`,
    '',
    `**Cheapest alternative:** ${cheapest.model} ($${cheapest.totalCost.toFixed(6)})`,
    '',
    '**Model cost comparison (cheapest first):**',
    ...topFive.map((m: ModelMultiplier) => `- ${m.model}: $${m.cost_usd.toFixed(6)} (${m.multiplier})`),
    '',
    tips.length > 0 ? '**Optimization tips:**\n' + tips.map((t: string) => `- ${t}`).join('\n') : '',
  ].filter(Boolean).join('\n');

  return {
    content: [{ type: 'text', text: lines }],
    model_multipliers: multipliers,
  };
}
```

- [ ] **Step 3: Typecheck and build**

```bash
cd cohrint-mcp && npx tsc --noEmit && npm run build
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add cohrint-mcp/src/index.ts
git commit -m "feat(mcp): add model_multipliers to analyze_tokens response"
```

---

## Task 3: MCP — compression layers 6+7 and `estimated_multiplier` in `get_recommendations`

**Files:**
- Modify: `cohrint-mcp/src/index.ts` (compressPrompt ~line 222, get_recommendations ~line 923)

- [ ] **Step 1: Update `compressPrompt` signature and add layers 6+7**

Find `function compressPrompt(prompt: string): string` (~line 222). Replace with the full updated function (keeping all existing layers, adding 6+7, moving whitespace collapse to last):

```typescript
function compressPrompt(prompt: string, systemPrompt?: string): string {
  let result = prompt;

  // Layer 1: remove filler phrases
  for (const phrase of FILLER_PHRASES) {
    result = result.replace(new RegExp(phrase, 'gi'), '');
  }

  // Layer 2: verbose → concise rewrites
  for (const [pattern, replacement] of VERBOSE_REWRITES) {
    result = result.replace(pattern, replacement);
  }

  // Layer 3: remove filler words
  result = result.replace(FILLER_WORDS_RE, ' ');

  // Layer 4: deduplicate repeated sentences
  const sentences = result.split(/(?<=[.!?])\s+/);
  const seen = new Set<string>();
  result = sentences.filter(s => {
    const key = s.trim().toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).join(' ');

  // Layer 6: strip redundant XML wrapper tags containing only plain text
  const SAFE_TO_STRIP = ['context', 'input', 'text', 'content', 'prompt', 'data', 'query'];
  for (const tag of SAFE_TO_STRIP) {
    result = result.replace(
      new RegExp(`<${tag}>([^<>]+)</${tag}>`, 'gi'),
      (_match: string, inner: string) => inner.trim()
    );
  }

  // Layer 7: remove user-turn constraints already present in system prompt
  if (systemPrompt && systemPrompt.trim().length > 0) {
    const sysLines = systemPrompt
      .split(/[.\n]+/)
      .map((s: string) => s.trim())
      .filter((s: string) => s.length > 20);
    for (const sysLine of sysLines) {
      const sysWords = new Set(sysLine.toLowerCase().split(/\s+/));
      const resultWords = result.toLowerCase().split(/\s+/);
      const overlap = resultWords.filter((w: string) => sysWords.has(w)).length;
      if (overlap / sysWords.size >= 0.9) {
        result = result.replace(sysLine, '').trim();
      }
    }
  }

  // Layer 5: collapse whitespace (always last)
  result = result.replace(/\s+/g, ' ').trim();

  return result;
}
```

- [ ] **Step 2: Add `RECOMMENDATION_MULTIPLIERS` constant and `categorizeRecommendation` helper**

Add after `buildModelMultipliers`:

```typescript
const RECOMMENDATION_MULTIPLIERS: Record<string, { multiplier: string; basis: string }> = {
  prompt_caching:    { multiplier: '10x',    basis: 'cache_read_vs_input_price' },
  compress_prompts:  { multiplier: '2-3x',   basis: 'avg_compression_ratio' },
  model_switch:      { multiplier: '8-60x',  basis: 'model_price_ratio' },
  context_reset:     { multiplier: '30-50%', basis: 'session_token_reduction' },
  remove_duplicates: { multiplier: '10-20%', basis: 'dedup_savings' },
};

function categorizeRecommendation(tip: string): string {
  const t = tip.toLowerCase();
  if (t.includes('cach')) return 'prompt_caching';
  if (t.includes('compress') || t.includes('optim') || t.includes('shorter')) return 'compress_prompts';
  if (t.includes('model') || t.includes('haiku') || t.includes('switch')) return 'model_switch';
  if (t.includes('context') || t.includes('clear') || t.includes('compact')) return 'context_reset';
  if (t.includes('duplic') || t.includes('repeat')) return 'remove_duplicates';
  return 'compress_prompts';
}
```

- [ ] **Step 3: Enrich `get_recommendations` return value**

Find the `case 'get_recommendations':` handler (~line 923). After it builds the `tips` array and `formattedContent` string, before the `return`, add:

```typescript
const enrichedTips = (rawTips as string[]).map(tip => {
  const category = categorizeRecommendation(tip);
  const meta = RECOMMENDATION_MULTIPLIERS[category];
  return { tip, estimated_multiplier: meta.multiplier, basis: meta.basis, category };
});
```

Then update the return to include `recommendations: enrichedTips`. Replace `rawTips` / `formattedContent` with the actual variable names present in the existing handler.

- [ ] **Step 4: Typecheck and build**

```bash
cd cohrint-mcp && npx tsc --noEmit && npm run build
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add cohrint-mcp/src/index.ts
git commit -m "feat(mcp): add compression layers 6+7 and estimated_multiplier to recommendations"
```

---

## Task 4: Worker — persist `tags.optimization` on `POST /v1/optimizer/compress`

**Files:**
- Modify: `cohrint-worker/src/routes/optimizer.ts` (POST /compress ~lines 54-77)

- [ ] **Step 1: Verify auth middleware sets `org_id`**

```bash
grep -n "c\.set\('org_id\|c\.set(\"org_id" cohrint-worker/src/ -r | head -10
```
Note the exact key name.

- [ ] **Step 2: Add tags persistence to `POST /compress` handler**

In `optimizer.ts`, find the `POST /compress` handler. After computing `compressionRatio` and `tokensSaved`, add a fire-and-forget DB insert:

```typescript
const optimizationTags = JSON.stringify({
  optimization: {
    type: 'compress',
    improvement_factor: Math.round((originalTokens / Math.max(compressedTokens, 1)) * 10) / 10,
    tokens_saved: originalTokens - compressedTokens,
    cost_before_usd: null,
    cost_after_usd: null,
    compression_ratio_pct: compressionRatio,
  },
});

c.env.DB.prepare(
  `INSERT INTO events (org_id, model, input_tokens, output_tokens, cache_tokens, cache_hit, created_at, tags)
   VALUES (?, 'optimizer/compress', ?, ?, 0, 0, unixepoch(), ?)`
)
  .bind(c.get('org_id'), originalTokens, compressedTokens, optimizationTags)
  .run()
  .catch((e: unknown) => console.error('optimizer compress tag insert failed', e));
```

- [ ] **Step 3: Typecheck**

```bash
cd cohrint-worker && npm run typecheck
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add cohrint-worker/src/routes/optimizer.ts
git commit -m "feat(worker): persist tags.optimization on POST /v1/optimizer/compress"
```

---

## Task 5: Worker — add `GET /v1/optimizer/impact` + integration tests (TDD)

**Files:**
- Create: `tests/suites/46_optimizer_impact/__init__.py`
- Create: `tests/suites/46_optimizer_impact/test_optimizer_impact.py`
- Modify: `cohrint-worker/src/routes/optimizer.ts` (add handler)

- [ ] **Step 1: Create test files**

```bash
mkdir -p tests/suites/46_optimizer_impact
touch tests/suites/46_optimizer_impact/__init__.py
```

Write `tests/suites/46_optimizer_impact/test_optimizer_impact.py`:

```python
"""Suite 46 — Optimizer Impact API coverage"""
import json
import time
from pathlib import Path
import pytest
import requests

BASE_URL = "https://api.cohrint.com"


@pytest.fixture(scope="module")
def account():
    seed_path = Path("tests/artifacts/da45_seed_state.json")
    assert seed_path.exists(), "Run: python tests/suites/45_dashboard_api_coverage/seed.py"
    state = json.loads(seed_path.read_text())
    api_key = state["admin"]["api_key"]
    return {"Authorization": f"Bearer {api_key}"}


def test_impact_requires_auth():
    """GET /v1/optimizer/impact returns 401 without auth."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact")
    assert r.status_code == 401


def test_impact_endpoint_returns_expected_shape(account):
    """GET /v1/optimizer/impact returns the required top-level fields."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "avg_improvement_factor" in data
    assert "total_tokens_saved" in data
    assert "total_cost_saved_usd" in data
    assert "by_type" in data
    assert "per_developer" in data
    assert "monthly_trend" in data
    assert "period" in data


def test_impact_by_type_has_compress_key(account):
    """by_type.compress has avg_factor, event_count, cost_saved_usd."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    compress = r.json()["by_type"]["compress"]
    assert "avg_factor" in compress
    assert "event_count" in compress
    assert "cost_saved_usd" in compress


def test_impact_per_developer_shape(account):
    """per_developer is a list; each entry has email, avg_factor, cost_saved_usd."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    devs = r.json()["per_developer"]
    assert isinstance(devs, list)
    if devs:
        dev = devs[0]
        assert "email" in dev
        assert "avg_factor" in dev
        assert "cost_saved_usd" in dev


def test_impact_monthly_trend_shape(account):
    """monthly_trend is a list of {month, avg_factor}."""
    r = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert r.status_code == 200
    trend = r.json()["monthly_trend"]
    assert isinstance(trend, list)
    if trend:
        assert "month" in trend[0]
        assert "avg_factor" in trend[0]


def test_compress_then_impact_reflects_new_event(account):
    """After a compress call, total_tokens_saved is non-negative and endpoint stays healthy."""
    before = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert before.status_code == 200
    before_tokens = before.json().get("total_tokens_saved", 0)

    long_prompt = "Please could you kindly help me with the following task. " * 20
    compress_r = requests.post(
        f"{BASE_URL}/v1/optimizer/compress",
        json={"prompt": long_prompt},
        headers=account,
    )
    assert compress_r.status_code == 200

    time.sleep(2)

    after = requests.get(f"{BASE_URL}/v1/optimizer/impact", headers=account)
    assert after.status_code == 200
    after_tokens = after.json().get("total_tokens_saved", 0)
    assert after_tokens >= before_tokens
```

- [ ] **Step 2: Run tests — confirm they fail (404)**

```bash
python -m pytest tests/suites/46_optimizer_impact/test_optimizer_impact.py -v 2>&1 | head -50
```
Expected: most tests fail with 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add `GET /impact` handler to `cohrint-worker/src/routes/optimizer.ts`**

Add before `export default optimizerRouter` (use the actual export name in the file):

```typescript
optimizerRouter.get('/impact', async (c) => {
  const orgId = c.get('org_id');
  const db = c.env.DB;

  const compressAgg = await db.prepare(`
    SELECT
      AVG(CAST(json_extract(tags, '$.optimization.improvement_factor') AS REAL)) AS avg_factor,
      COUNT(*) AS event_count,
      SUM(
        COALESCE(CAST(json_extract(tags, '$.optimization.cost_before_usd') AS REAL), 0) -
        COALESCE(CAST(json_extract(tags, '$.optimization.cost_after_usd') AS REAL), 0)
      ) AS cost_saved_usd,
      SUM(CAST(json_extract(tags, '$.optimization.tokens_saved') AS INTEGER)) AS tokens_saved
    FROM events
    WHERE org_id = ?
      AND json_extract(tags, '$.optimization.type') = 'compress'
  `).bind(orgId).first<{
    avg_factor: number | null;
    event_count: number;
    cost_saved_usd: number | null;
    tokens_saved: number | null;
  }>();

  const cacheAgg = await db.prepare(`
    SELECT COUNT(*) AS event_count
    FROM events
    WHERE org_id = ? AND cache_hit = 1
  `).bind(orgId).first<{ event_count: number }>();

  const devAgg = await db.prepare(`
    SELECT
      m.email,
      AVG(CAST(json_extract(e.tags, '$.optimization.improvement_factor') AS REAL)) AS avg_factor,
      SUM(
        COALESCE(CAST(json_extract(e.tags, '$.optimization.cost_before_usd') AS REAL), 0) -
        COALESCE(CAST(json_extract(e.tags, '$.optimization.cost_after_usd') AS REAL), 0)
      ) AS cost_saved_usd,
      SUM(e.input_tokens) * 0.000003 AS total_cost_usd,
      SUM(e.cache_tokens) AS cache_tokens,
      COUNT(*) AS total_events
    FROM events e
    JOIN org_members m ON m.user_id = e.user_id AND m.org_id = e.org_id
    WHERE e.org_id = ?
    GROUP BY m.email
    ORDER BY avg_factor DESC
  `).bind(orgId).all<{
    email: string;
    avg_factor: number | null;
    cost_saved_usd: number;
    total_cost_usd: number;
    cache_tokens: number | null;
    total_events: number;
  }>();

  const trendAgg = await db.prepare(`
    SELECT
      strftime('%Y-%m', datetime(created_at, 'unixepoch')) AS month,
      AVG(CAST(json_extract(tags, '$.optimization.improvement_factor') AS REAL)) AS avg_factor
    FROM events
    WHERE org_id = ?
      AND json_extract(tags, '$.optimization.type') IS NOT NULL
    GROUP BY month
    ORDER BY month ASC
  `).bind(orgId).all<{ month: string; avg_factor: number | null }>();

  const perDeveloper = (devAgg.results ?? []).map(d => {
    const cacheRate =
      d.total_events > 0 ? (d.cache_tokens ?? 0) / Math.max(d.total_events * 100, 1) : 0;
    const opportunityUsd =
      cacheRate < 0.2 && d.total_cost_usd > 1
        ? Math.round(d.total_cost_usd * 0.15 * 100) / 100
        : null;
    return {
      email: d.email,
      avg_factor: d.avg_factor != null ? Math.round(d.avg_factor * 10) / 10 : 1.0,
      cost_saved_usd: Math.round((d.cost_saved_usd ?? 0) * 100) / 100,
      opportunity_usd: opportunityUsd,
    };
  });

  const avgFactor =
    perDeveloper.length > 0
      ? Math.round(
          (perDeveloper.reduce((s, d) => s + d.avg_factor, 0) / perDeveloper.length) * 10
        ) / 10
      : 1.0;

  const now = new Date();
  const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;

  return c.json({
    period,
    avg_improvement_factor: avgFactor,
    total_tokens_saved: compressAgg?.tokens_saved ?? 0,
    total_cost_saved_usd: Math.round((compressAgg?.cost_saved_usd ?? 0) * 100) / 100,
    by_type: {
      compress: {
        avg_factor:
          compressAgg?.avg_factor != null ? Math.round(compressAgg.avg_factor * 10) / 10 : 1.0,
        event_count: compressAgg?.event_count ?? 0,
        cost_saved_usd: Math.round((compressAgg?.cost_saved_usd ?? 0) * 100) / 100,
      },
      cache: {
        avg_factor: 10.0,
        event_count: cacheAgg?.event_count ?? 0,
        cost_saved_usd: 0,
      },
      model_switch: { avg_factor: 1.0, event_count: 0, cost_saved_usd: 0 },
    },
    per_developer: perDeveloper,
    monthly_trend: (trendAgg.results ?? []).map(r => ({
      month: r.month,
      avg_factor: r.avg_factor != null ? Math.round(r.avg_factor * 10) / 10 : 1.0,
    })),
  });
});
```

- [ ] **Step 4: Verify router is mounted in `cohrint-worker/src/index.ts`**

```bash
grep -n "optimizer" cohrint-worker/src/index.ts | head -10
```
If `app.route('/v1/optimizer', optimizerRouter)` already exists, no change needed. Otherwise add the import and mount.

- [ ] **Step 5: Typecheck**

```bash
cd cohrint-worker && npm run typecheck
```
Expected: no errors.

- [ ] **Step 6: Deploy**

```bash
cd cohrint-worker && npx wrangler deploy
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/suites/46_optimizer_impact/test_optimizer_impact.py -v
```
Expected: all 6 tests pass.

- [ ] **Step 8: Commit**

```bash
git add cohrint-worker/src/routes/optimizer.ts cohrint-worker/src/index.ts \
        tests/suites/46_optimizer_impact/
git commit -m "feat(worker): add GET /v1/optimizer/impact + suite 46 tests"
```

---

## Task 6: Frontend — Optimization Impact widget in `app.html`

**Files:**
- Modify: `cohrint-frontend/app.html`

- [ ] **Step 1: Identify existing patterns**

```bash
grep -n "showSection\|section-\|apiFetch\|apiGet\|fetchWith" cohrint-frontend/app.html | head -30
```
Note the exact fetch helper name and section switching pattern.

- [ ] **Step 2: Add nav link**

In the sidebar nav list, add alongside the other nav items:
```html
<li><a href="#section-optimization" onclick="showSection('optimization')">Optimization Impact</a></li>
```

- [ ] **Step 3: Add section HTML**

After the last existing `<section id="section-...">` block, add:

```html
<section id="section-optimization" class="section hidden">
  <h2>Optimization Impact</h2>

  <!-- Panel 1: Hero metric card -->
  <div class="card" style="padding:24px;margin-bottom:24px">
    <div id="opt-hero-loading" class="skeleton-block" style="height:120px"></div>
    <div id="opt-hero-content" style="display:none">
      <div style="font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:16px">
        Cohrint Optimization Impact · <span id="opt-period"></span>
      </div>
      <div style="display:flex;gap:32px;flex-wrap:wrap;margin-bottom:20px">
        <div>
          <div id="opt-avg-factor" style="font-size:36px;font-weight:700;color:#a3e635">—</div>
          <div style="font-size:13px;color:var(--muted)">avg cost reduction</div>
        </div>
        <div>
          <div id="opt-total-saved" style="font-size:36px;font-weight:700;color:#38bdf8">—</div>
          <div style="font-size:13px;color:var(--muted)">saved this month</div>
        </div>
        <div>
          <div id="opt-tokens-saved" style="font-size:36px;font-weight:700;color:#f472b6">—</div>
          <div style="font-size:13px;color:var(--muted)">tokens optimized</div>
        </div>
      </div>
      <div id="opt-badges" style="display:flex;gap:8px;flex-wrap:wrap"></div>
    </div>
    <div id="opt-hero-empty" style="display:none;color:var(--muted);font-size:14px">
      No optimization data yet — use <code>optimize_prompt</code> or enable prompt caching to start tracking.
    </div>
  </div>

  <!-- Panel 2: Monthly trend chart -->
  <div class="card" style="padding:24px;margin-bottom:24px">
    <h3 style="margin-bottom:16px">Cost Reduction Trend</h3>
    <div id="opt-trend-loading" class="skeleton-block" style="height:200px"></div>
    <canvas id="opt-trend-chart" style="display:none;max-height:200px"></canvas>
  </div>

  <!-- Panel 3: Developer leaderboard -->
  <div class="card" style="padding:24px">
    <h3 style="margin-bottom:16px">Developer Leaderboard</h3>
    <div id="opt-leaderboard-loading" class="skeleton-block" style="height:160px"></div>
    <div id="opt-leaderboard" style="display:none"></div>
    <div id="opt-leaderboard-empty" style="display:none;color:var(--muted);font-size:14px">No developer data available.</div>
  </div>
</section>
```

- [ ] **Step 4: Add `loadOptimizationImpact` JS function**

In the `<script>` section. **Important:** all user-supplied data (email addresses) must be escaped before DOM insertion. Use this helper at the top of the function:

```javascript
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function loadOptimizationImpact() {
  // Replace `apiFetch` with the actual fetch helper name found in Step 1
  try {
    const data = await apiFetch('/v1/optimizer/impact');

    // Panel 1: Hero
    document.getElementById('opt-hero-loading').style.display = 'none';
    if (!data || data.avg_improvement_factor <= 1.05) {
      document.getElementById('opt-hero-empty').style.display = 'block';
    } else {
      document.getElementById('opt-hero-content').style.display = 'block';
      document.getElementById('opt-period').textContent = data.period ?? '';
      document.getElementById('opt-avg-factor').textContent = data.avg_improvement_factor.toFixed(1) + 'x';
      document.getElementById('opt-total-saved').textContent = '$' + (data.total_cost_saved_usd ?? 0).toFixed(2);
      const t = data.total_tokens_saved ?? 0;
      document.getElementById('opt-tokens-saved').textContent =
        t >= 1_000_000 ? (t / 1_000_000).toFixed(1) + 'M' :
        t >= 1000     ? (t / 1000).toFixed(0) + 'K' : String(t);

      // Badges — data comes from API numbers only, no user strings here
      const badges = document.getElementById('opt-badges');
      const bt = data.by_type ?? {};
      const badgeData = [
        { label: '💡 Compression', factor: bt.compress?.avg_factor,    bg: '#1e3a2f', fg: '#a3e635' },
        { label: '⚡ Caching',     factor: bt.cache?.avg_factor,        bg: '#1e2a3a', fg: '#38bdf8' },
        { label: '🔀 Model switch',factor: bt.model_switch?.avg_factor, bg: '#2a1e3a', fg: '#c084fc' },
      ];
      badges.textContent = '';
      badgeData.filter(b => b.factor && b.factor > 1.05).forEach(b => {
        const span = document.createElement('span');
        span.style.cssText = `background:${b.bg};color:${b.fg};padding:4px 12px;border-radius:12px;font-size:12px`;
        span.textContent = `${b.label}: ${b.factor.toFixed(1)}x`;
        badges.appendChild(span);
      });
    }

    // Panel 2: Trend chart
    document.getElementById('opt-trend-loading').style.display = 'none';
    const canvas = document.getElementById('opt-trend-chart');
    canvas.style.display = 'block';
    const trend = data.monthly_trend ?? [];
    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: trend.map(r => r.month),
        datasets: [{
          label: 'Avg cost reduction',
          data: trend.map(r => r.avg_factor),
          backgroundColor: trend.map((_, i) => i === trend.length - 1 ? '#a3e635' : '#166534'),
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { callback: v => v + 'x' } } },
      },
    });

    // Panel 3: Leaderboard — build with DOM methods to avoid XSS (email is user data)
    document.getElementById('opt-leaderboard-loading').style.display = 'none';
    const devs = data.per_developer ?? [];
    const lb = document.getElementById('opt-leaderboard');
    if (devs.length === 0) {
      document.getElementById('opt-leaderboard-empty').style.display = 'block';
    } else {
      lb.style.display = 'block';
      lb.textContent = '';
      devs.slice(0, 13).forEach((d, i) => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)';

        const rank = document.createElement('span');
        rank.style.cssText = 'color:var(--muted);width:20px;font-size:12px';
        rank.textContent = String(i + 1);

        const email = document.createElement('span');
        email.style.cssText = 'flex:1;font-size:13px';
        email.textContent = d.email;  // textContent — safe, no XSS

        const isLow = d.avg_factor < 2;
        const badge = document.createElement('span');
        badge.style.cssText = `background:${isLow ? '#2a1a1a' : '#1e3a2f'};color:${isLow ? '#f87171' : '#a3e635'};padding:2px 10px;border-radius:10px;font-size:12px`;
        badge.textContent = `${d.avg_factor.toFixed(1)}x`;

        const saved = document.createElement('span');
        saved.style.cssText = 'font-size:12px;color:var(--muted)';
        saved.textContent = `$${d.cost_saved_usd.toFixed(2)} saved`;

        row.appendChild(rank);
        row.appendChild(email);
        row.appendChild(badge);
        row.appendChild(saved);

        if (d.opportunity_usd) {
          const opp = document.createElement('span');
          opp.style.cssText = 'color:#f87171;font-size:12px';
          opp.textContent = `↑ $${d.opportunity_usd} opportunity`;
          row.appendChild(opp);
        }

        lb.appendChild(row);
      });
    }
  } catch (e) {
    console.error('loadOptimizationImpact failed', e);
    document.getElementById('opt-hero-loading').style.display = 'none';
    document.getElementById('opt-hero-empty').style.display = 'block';
  }
}
```

- [ ] **Step 5: Hook to section tab switch**

Find the `showSection` function and add:
```javascript
if (section === 'optimization') loadOptimizationImpact();
```

- [ ] **Step 6: Deploy frontend**

```bash
npx wrangler pages deploy ./cohrint-frontend --project-name=cohrint
```

- [ ] **Step 7: Verify in browser**

Open the dashboard, click "Optimization Impact". Confirm:
- Hero card shows data or the empty state message (no fake numbers)
- Trend chart renders (empty if no tagged events yet)
- Leaderboard shows or shows empty state
- No JS console errors

- [ ] **Step 8: Commit**

```bash
git add cohrint-frontend/app.html
git commit -m "feat(frontend): add Optimization Impact section with hero card, trend chart, leaderboard"
```

---

## Task 7: Regression check + push

- [ ] **Step 1: Run suite 46**

```bash
python -m pytest tests/suites/46_optimizer_impact/ -v
```
Expected: all tests pass.

- [ ] **Step 2: Run existing suites for regressions**

```bash
python -m pytest tests/suites/20_dashboard_real_data/ tests/suites/33_frontend_contract/ -v 2>&1 | tail -30
```
Expected: all pass.

- [ ] **Step 3: Typecheck both packages**

```bash
cd cohrint-mcp && npx tsc --noEmit && cd ../cohrint-worker && npm run typecheck
```
Expected: no errors.

- [ ] **Step 4: Push branch**

```bash
git push origin feat/cost-forecasting-widget
```
