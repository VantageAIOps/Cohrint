# The State of AI Coding Spend 2026
## A Research White Paper by Cohrint
**April 2026 · cohrint.com**

---

## Abstract

AI coding tools — large language model APIs, IDE copilots, and autonomous agent frameworks — have become a material budget line for engineering organisations in 2026. Yet most engineering leaders lack a unified view of what they spend, who spends it, and whether the investment delivers measurable productivity return. This paper documents the problem, the architectural approach Cohrint takes to solve it, the key algorithms that power the platform, and research directions that will define the next phase of AI cost intelligence.

---

## 1. The AI Coding Spend Problem

### 1.1 Fragmented Toolchain, Unified Bill

A typical engineering team in 2026 uses 3–7 AI coding tools simultaneously:

- **GitHub Copilot** — seat-licensed, billed per developer per month ($10–19/user)
- **Claude Code / Anthropic API** — token-billed, usage proportional to session depth
- **OpenAI API** — token-billed, model-dependent pricing (GPT-4o: $2.50/1M input, $10/1M output)
- **Gemini CLI / Google AI** — token-billed
- **Cursor / Codeium / Windsurf** — seat-licensed or token-hybrid
- **Custom LLM agents** — company-built automation using raw API calls

Each tool reports cost in a different unit, on a different cadence, through a different dashboard. None of them cross-reference the others. A CTO trying to answer "what is our total AI coding spend per developer per month?" must manually aggregate 5+ dashboards — and even then, has no benchmark to judge whether $500/developer/month is high or low for their industry.

### 1.2 The Attribution Gap

Cost without attribution is noise. Engineering leaders need to answer:

- Which team is consuming 40% of the LLM API budget?
- Which developer's agent sessions are generating $50/day in tokens?
- Is the $2,000/month Copilot contract delivering measurable code suggestions?
- If we switched 30% of Team B's requests from GPT-4o to Claude Haiku, what would we save?

These questions require **cross-tool, per-developer attribution at the API call level** — something no provider can offer (they see only their own calls) and no observability tool has built (they observe LLM API calls, not Copilot seat billing).

### 1.3 The Benchmark Vacuum

Without cross-company data, every AI spend number is unanchored. Is $300/developer/month high? It depends entirely on industry, company size, and AI maturity. No public dataset provides AI coding spend benchmarks at the per-developer, per-tool granularity engineering leaders need.

The closest analog: **Bloomberg Terminal**. Bloomberg provides neutral market data that financial institutions cannot generate internally (conflict of interest prevents any single bank from publishing competitor pricing). AI model pricing intelligence faces the same structural constraint — providers cannot publish objective cross-provider cost comparisons.

---

## 2. Platform Architecture

### 2.1 Design Principles

Cohrint is built on four architectural principles:

1. **No proxy** — The platform never sits in the call path between application and LLM. Cost and usage data is captured via SDK interception, OTel emission, or provider API polling. This eliminates the security risk of traffic interception.

2. **Privacy by design** — Three privacy modes (strict/standard/relaxed) allow organisations to control whether prompt and response content ever leaves their network. In strict mode, only token counts, cost, and metadata are transmitted. Prompt text never leaves the developer's machine.

3. **Edge-native** — Deployed on Cloudflare Workers (zero cold starts, global distribution). D1 SQLite as the primary database provides serverless SQL without provisioning. Vectorize handles semantic embeddings at edge latency.

4. **Multi-source normalisation** — Events from SDK calls, OTel logs, Copilot Metrics API, and Datadog are normalised into a unified schema before storage. Downstream analytics sees one event table regardless of source.

### 2.2 Data Ingestion Sources

| Source | Mechanism | Data Available |
|--------|-----------|----------------|
| Python/JS SDK | Transparent proxy wrapper | Per-call: model, tokens, cost, latency, developer, team |
| OTel Collector | OTLP logs endpoint `/v1/otel/v1/logs` | Structured spans from Claude Code, Cursor, Gemini CLI, Codeium, Cline, Continue, Windsurf, Codex, Kiro |
| Claude Code Stop Hook | PostToolUse hook, dual-write | Session cost, token counts, agent name, session ID |
| GitHub Copilot Metrics API | REST polling (Sunday UTC cron) | Per-developer: suggestions shown/accepted, lines added, active time, seat cost |
| Datadog (push) | `vantage.ai.cost_usd` gauge metrics | Cohrint data pushed to customer's Datadog for unified infra + AI dashboards |

### 2.3 Unified Event Schema

All sources normalise into the `events` table:

```
id               TEXT  — unique per org (INSERT OR IGNORE for dedup)
org_id           TEXT  — organisation
provider         TEXT  — 'anthropic' | 'openai' | 'google' | 'copilot' | ...
model            TEXT  — 'claude-sonnet-4-6' | 'gpt-4o' | ...
prompt_tokens    INT   — input token count
completion_tokens INT  — output token count
cache_tokens     INT   — cache read tokens (Anthropic prompt cache)
cost_usd         REAL  — computed at ingest using live pricing table
latency_ms       INT   — end-to-end call latency
team             TEXT  — engineering team label
developer_email  TEXT  — developer identity
trace_id         TEXT  — agent session grouping
parent_event_id  TEXT  — DAG edge for nested tool calls
hallucination_score REAL  — async quality score (0–1, lower = worse)
created_at       INT   — unix timestamp
```

The composite primary key `(id, org_id)` with `INSERT OR IGNORE` provides idempotent ingest — duplicate events from SDK retries or OTel re-delivery are silently dropped.

---

## 3. Key Algorithms

### 3.1 Semantic Cache — Reducing Redundant LLM Spend

**Problem:** In enterprise settings, 30–60% of LLM API calls are semantically equivalent to a prior call — same intent, slightly different phrasing. Exact-match caching (HTTP-level) misses paraphrased duplicates.

**Approach:** Cohrint implements semantic caching using Cloudflare Vectorize (vector store) and Workers AI (embedding generation).

**Algorithm:**
1. Incoming prompt is embedded using `@cf/baai/bge-small-en-v1.5` (384-dimensional BGE model, optimised for semantic similarity tasks).
2. The embedding is queried against a per-org Vectorize namespace using cosine similarity (topK=1).
3. If the top result has similarity ≥ 0.92 (configurable per org), the cached response is returned immediately.
4. If not (cache miss), the request proceeds to the LLM. After response, the prompt+response pair is embedded and stored.

**Why 0.92?** Empirically, cosine similarity ≥ 0.92 in BGE-384 space corresponds to semantically equivalent intent with <5% false positive rate for typical English-language code-generation prompts. This threshold is configurable because code prompts (high precision domain) require a higher threshold than natural language prompts (higher tolerance for paraphrase).

**Per-org isolation:** Each organisation gets a dedicated Vectorize namespace (`{orgId}-prompt-cache`). Cross-org cache contamination is architecturally impossible — queries are namespaced at the vector store level, not filtered at the application layer.

**Cost savings calculation:**
```
saved_usd_per_hit = original_call.cost_usd
total_savings = SUM(saved_usd_per_hit) WHERE cache_hit = 1
```

Tracked at entry level in `semantic_cache_entries.total_savings_usd`, updated atomically on each hit.

### 3.2 Cost Forecasting

**Problem:** Organisations need to know whether they will exceed their monthly AI budget before the end of the month, not after the invoice arrives.

**Approach:** Three derived fields on `GET /v1/analytics/summary`:

```
days_elapsed         = MAX(UTC_day_of_month, 1)
days_in_month        = days in current UTC month
daily_avg_cost_usd   = mtd_cost_usd / days_elapsed
projected_month_end  = daily_avg_cost_usd × days_in_month
days_until_exhausted = CEIL((budget_usd - mtd_cost_usd) / daily_avg_cost_usd)
                       → 0 if budget already exceeded
                       → null if no budget set
```

**Limitations:** The linear projection assumes consistent daily spend. In practice, sprint cycles, release events, and holiday periods create non-linear patterns. Future work: ARIMA or Holt-Winters seasonal decomposition for more accurate mid-month projections.

### 3.3 Agent Trace DAG Reconstruction

**Problem:** Multi-step AI agents generate chains of LLM calls — a root agent calls a sub-agent which calls tools which call models. Understanding the cost of a full agent session requires reconstructing the call graph.

**Approach:** The `events` table stores a directed acyclic graph via three fields:

```
trace_id          — groups all spans in one agent session
parent_event_id   — FK to parent span (NULL for root)
span_depth        — integer depth hint (0 = root, 1 = child, ...)
```

**Reconstruction algorithm (frontend, O(n)):**
```javascript
// spans: ordered by created_at ASC
const byId = new Map(spans.map(s => [s.id, {...s, children: []}]))
const roots = []
for (const span of spans) {
  if (span.parent_id) {
    byId.get(span.parent_id)?.children.push(span)
  } else {
    roots.push(span)
  }
}
// Render: roots → recursive tree
```

**RBAC enforcement:** Members below `admin` rank can only view spans where `developer_email` matches their own email. Admins see all spans. This prevents cross-developer trace leakage within the same organisation.

### 3.4 Anomaly Detection — Z-Score Budget Alert

**Problem:** Graduated budget alerts (50%/75%/100%) fire at known thresholds but miss sudden runaway spend events that could exhaust the budget within hours.

**Approach:** Z-score anomaly detection on a rolling spend window.

```
baseline    = AVG(hourly_spend) over last 30 days
baseline_sd = STDDEV(hourly_spend) over last 30 days
current     = SUM(cost_usd) in last 10 minutes × 6  (annualised to hourly rate)
z_score     = (current - baseline) / baseline_sd
alert_if    z_score > 3.0
```

A 30-minute KV throttle key (`alert:{orgId}:{threshold}`) prevents duplicate alerts within a short window.

**Limitation:** Z-score assumes normal distribution of hourly spend. Sprint cycles and batch inference jobs create multi-modal distributions that a Gaussian model handles poorly. Future work: isolation forest or Prophet-based anomaly detection for non-stationary spend patterns.

### 3.5 k-Anonymity for Benchmark Data

**Problem:** Publishing per-org benchmark data would expose sensitive competitive intelligence. Even "anonymised" benchmarks with small cohorts can be re-identified if the cohort size is small enough.

**Approach:** Cohrint enforces a k-anonymity floor of k=5: any benchmark cohort with fewer than 5 contributing organisations returns a 404 (not zero or masked data — the endpoint itself is suppressed to prevent fishing attacks).

```sql
SELECT p50, p75, p90, sample_size
FROM benchmark_snapshots
WHERE cohort_id = ? AND quarter = ? AND metric_name = ?
-- application layer: if sample_size < 5 → 404
```

Cohort bucketing: `(size_band × industry)` — size bands are `1-10`, `11-50`, `51-200`, `200+`. Industry: `tech`, `finance`, `healthcare`, `other`.

**Contribution tracking:** `benchmark_contributions` table records `(org_id, snapshot_id)` pairs. Each contributing org is counted once per cohort per quarter regardless of event volume — preventing large organisations from dominating the percentile distribution.

---

## 4. Quality Scoring — 6-Dimension Framework

Cohrint tracks six quality dimensions per LLM event, written asynchronously by an LLM judge (Claude Opus 4.6):

| Dimension | Definition | Score Range |
|-----------|-----------|-------------|
| `hallucination_score` | Factual accuracy — does the response contain false claims? | 0 (hallucinated) — 1 (accurate) |
| `faithfulness_score` | Does the response stay grounded in the provided context? | 0 — 1 |
| `relevancy_score` | Is the response on-topic for the question asked? | 0 — 1 |
| `consistency_score` | Is the response internally consistent (no self-contradictions)? | 0 — 1 |
| `toxicity_score` | Does the response contain harmful, offensive, or inappropriate content? | 0 (toxic) — 1 (safe) |
| `efficiency_score` | Does the response achieve the goal with appropriate brevity? | 0 — 1 |

Scores are written via `PATCH /v1/events/:id/scores` in a background job. All scores are nullable at ingest time — quality scoring is a best-effort enrichment, not a blocking operation.

**Per-developer aggregation:** `hallucination_score` is aggregated as `AVG(hallucination_score)` per developer over the trailing 30 days and surfaced on the dashboard developer drill-down. This surfaces systematic quality issues (a specific developer's prompts consistently generating hallucinated code) before they reach code review.

---

## 5. Privacy Architecture

### 5.1 Three Privacy Modes

| Mode | What is transmitted | Use case |
|------|---------------------|---------|
| **Strict** | Token counts, cost, model, latency, team, developer ID. No text. | Regulated industries, IP-sensitive code |
| **Standard** | Above + prompt hash (SHA-256, one-way). No raw text. | Default for enterprise |
| **Relaxed** | Full prompt + response text. | Internal tooling, non-sensitive workloads |

Mode is set per-org via `PATCH /v1/admin/settings`. In strict mode, the SDK hashes prompt text client-side before transmission — the raw prompt never leaves the developer's machine.

### 5.2 Local Proxy Gateway

For organisations requiring strict network isolation, Cohrint provides `vantage-local-proxy` — a local HTTP proxy that runs on the developer's machine or in a private network segment. The proxy:

1. Intercepts LLM API calls at the HTTP layer
2. Extracts metadata (model, tokens, cost) without capturing prompt/response content
3. Posts only the metadata to `api.cohrint.com`
4. Forwards the original request to the LLM provider unchanged

The proxy supports all three privacy modes and can be configured to strip specific HTTP headers before forwarding.

---

## 6. Research Directions

### 6.1 Near-Term (Shipped or In Progress)

**Model Switch Advisor**
Use the existing 24-LLM price table combined with per-team quality scores to surface: "Switching 30% of Team B's requests from GPT-4o to Claude Haiku saves $X/month with a projected quality delta of -0.03 on faithfulness." This requires correlating quality scores with model selection and task type — a supervised problem with ground truth from the quality scoring pipeline.

**Chargeback Report Export**
Monthly PDF/CSV per cost center: total spend, event count, model breakdown, cache savings. Opens VP Finance as a deal champion by providing the data needed for internal chargeback accounting. First mover in this category.

### 6.2 Medium-Term (6–12 Months)

**Vendor Negotiation Intelligence**
"At your current growth rate, you qualify for Anthropic volume discounts in 6 weeks." This requires:
1. Usage trend extrapolation (linear regression on rolling 90-day spend)
2. Published volume tier data for each provider (maintained as a static lookup table)
3. Proactive notification trigger at 80% of the next volume threshold

The benchmark data moat is the prerequisite — negotiation intelligence requires knowing what comparable companies paid at similar volumes.

**Application-Layer Cost Attribution**
Per-endpoint, per-customer cost tracking: "/summarize costs $0.08/call, customer ABC costs $0.43/month." Requires instrumentation at the application request level, not just the LLM call level. SDK v2 roadmap item.

**Quality vs. Cost Tradeoff Tooling**
Connect quality scores (hallucination, faithfulness) to model pricing. Surface: "For code generation tasks, Claude Haiku achieves 0.94 faithfulness at $0.002/call vs GPT-4o at 0.97 faithfulness at $0.018/call. For your team's quality tolerance, Haiku is sufficient and 9x cheaper."

### 6.3 Long-Term (12–36 Months)

**AI Spend Index — Quarterly Public Report**
Modelled on Gartner Magic Quadrant: a quarterly public benchmark report ("State of AI Coding Spend Q2 2026") drawing on anonymised data from opted-in organisations. Each report strengthens the data moat, generates press coverage, and establishes Cohrint as the authoritative source of AI spend intelligence.

**Compliance Report Generator**
Formatted audit reports for SOC 2 / DORA evidence packages. Enterprise compliance teams need formatted output — timestamped, signed, structured — not raw CSV exports from a dashboard. The `audit_events` table (every admin action logged, immutable, append-only) is the foundation.

**Isolation Forest for Spend Anomalies**
Replace the current Z-score anomaly detection with an isolation forest model trained on per-org historical spend patterns. Isolation forests handle multi-modal, non-stationary distributions better than Gaussian models and do not require manual threshold tuning.

**Retrieval-Augmented Prompt Optimisation**
Given a prompt and its quality + cost scores, suggest a rewritten version using a retrieval corpus of high-quality, low-cost historical prompts from the same task category. This closes the loop between the prompt registry (versioning + cost tracking) and active cost reduction.

---

## 7. The Bloomberg Thesis

The most important long-term research direction is not algorithmic — it is data.

Bloomberg Terminal succeeds because it is the neutral aggregator of financial market data. No individual bank can publish competitor pricing. No market participant can offer the full picture without the conflict destroying credibility.

AI model pricing intelligence faces the same structural constraint. OpenAI cannot tell you Anthropic is cheaper for your use case. Anthropic cannot tell you GitHub Copilot is overpriced for your team's acceptance rate. No provider can do this.

The platform that accumulates cross-company, cross-provider AI spend data — with appropriate anonymisation and privacy protections — becomes the Bloomberg Terminal for AI costs. Every organisation that opts into the benchmark system strengthens this position. The data moat compounds. Competitors cannot replicate it without users. Users create the moat.

This is the 10-year defensible position. Not the features. The data.

---

## 8. References & Further Reading

| # | Source | Relevance |
|---|--------|-----------|
| 01 | CloudHealth → VMware acquisition (TechCrunch, 2018) | Best analog: how a cloud cost tool built a defensible moat despite AWS/Azure/GCP native dashboards |
| 02 | Apptio S-1 / IBM acquisition docs (2019) | ITFM/TBM market is the 5-year model. Enterprise sales motion and pricing template |
| 03 | Cloudflare Vectorize docs — vector search + metadata filtering | Architecture foundation for semantic cache |
| 04 | BGE (BAAI) embedding model paper — "C-Pack: Packaged Resources to Advance General Chinese Embedding" | Embedding model selection rationale |
| 05 | "k-Anonymity: A Model for Protecting Privacy" — Sweeney (2002) | Foundation for benchmark cohort privacy approach |
| 06 | Helicone, LangSmith, Langfuse GitHub repos + changelogs | Competitive tracking — watch weekly releases |
| 07 | GitHub Copilot Metrics API documentation (GA Feb 2026) | Data source for Copilot adapter |
| 08 | OpenTelemetry Logs specification (OTLP) | Protocol for OTel collector endpoint |
| 09 | "Isolation Forest" — Liu, Ting, Zhou (2008) | Research direction for anomaly detection improvement |
| 10 | Holt-Winters exponential smoothing — Gardner (1985) | Research direction for spend forecasting improvement |
| 11 | LLMLingua paper — "LLMLingua: Compressing Prompts for Accelerated Inference" (Microsoft, 2023) | Foundation for token optimizer / prompt compression |
| 12 | "Measuring the Impact of GitHub Copilot on Developer Productivity" — Ziegler et al. (2022) | Baseline for Copilot ROI correlation in vendor negotiation module |

---

## 9. Conclusion

The AI coding spend management problem is structural, persistent, and growing. The fragmented toolchain, the attribution gap, and the benchmark vacuum create a category that no provider can fill and that observability tools approach from the wrong angle.

Cohrint's architecture — no-proxy, edge-native, multi-source normalisation, privacy-first — is designed for the enterprise procurement requirements that will become mandatory as AI coding spend scales from experiment to infrastructure line item.

The algorithms documented here — semantic cache, cost forecasting, trace DAG reconstruction, Z-score anomaly detection, k-anonymous benchmarks, 6-dimension quality scoring — are the technical foundation. The data moat is the competitive foundation.

Both take time to build. The window to build them is now.

---

*Cohrint — cohrint.com · api.cohrint.com*
*Internal research document. Not for public distribution without review.*
