# Cohrint — Critical Improvements Task Plan

**Version:** 2.0
**Audience:** Claude Code (agentic coder) working on the Cohrint monorepo.
**Source of truth:** This file. Read `CLAUDE.md` first for repo conventions.
**Budget constraint:** Zero-cost only. Free tiers of Cloudflare, GitHub, and existing deps. No new SaaS, no paid services, no new runtime dependencies unless explicitly listed in a task.
**Scalability promise:** Every solution must be re-pointable to a paid/scale tier later with ≤1 day of work. Document the migration path in each task's `future_scale` note.

---

## How to use this file

### Task selection

1. `git pull origin main` first. Always re-read `IMPROVEMENTS.md` fresh; a human may have updated statuses between sessions.
2. Pick the **lowest-numbered open task** where:
   - `status: pending`
   - Every T-id in `requires:` has `status: done` (or `requires: —` = no dependencies)
   - The task's Phase gate is satisfied (see below)
3. Work in a branch named `improve/T{NNN}-{slug}` off `main`.
4. One task = one PR. Detailed PR description per `CLAUDE.md` §5.
5. Do not delete files or folders. Do not merge. Do not force-push. See `CLAUDE.md` §1.
6. If blocked, update the task's `status: blocked` with a `blocker:` note and move to the next eligible task.
7. After passing CI, stop and wait for human review.

### The `requires:` field

`requires: T001` means **this task depends on T001 being `status: done`**. It does not mean "this blocks T001." Every T-id listed must be done before starting this task.

### Phase gate

Tasks are grouped into Phases 0–5. A later phase may not start until the previous phase is **entirely** `status: done` **and** has been on production `main` for ≥ 7 days. This is a soft gate above the hard `requires:` edges — it exists because some risk (schema drift, KV storm, subtle race) only surfaces under real traffic. Claude Code must check both the `requires:` list AND the Phase gate before picking a task.

Exception: Phase 6 (deferred) is not part of the sequence — those items are explicit non-goals until triggering conditions (documented per-item) are met.

### Migration number policy

Tasks reference migrations as `NNNN_short_name.sql` with a placeholder NNNN. **Do not hardcode the migration number into the PR.** At PR creation time, run `ls cohrint-worker/migrations/ | tail -1` to find the highest existing number and use `max + 1`. This prevents collisions when tasks ship out of dependency order.

### Task status values

- `pending` — not started.
- `in_progress` — a branch exists; PR not yet opened.
- `in_review` — PR open, CI green, awaiting human review. Claude Code does not merge.
- `done` — merged to main.
- `blocked` — external dependency or missing prerequisite; see `blocker:` field. Claude Code skips and moves on.

---

## Phase 0 — Guardrails & Instrumentation (prereq for every later phase)

These tasks make the rest of the work safe. They must land before structural changes.

---

### T001 — Add structured logging with request correlation IDs

- **status:** in_review
- **requires:** —
- **why:** §2.7 of guidebook review — `wrangler tail` is not sufficient past MVP. Every later task will need correlated logs to prove it didn't regress anything.
- **scope:**
  - Create `cohrint-worker/src/lib/logger.ts` exporting `createLogger(requestId, orgId?)` returning `{ info, warn, error, debug }`.
  - All output is single-line JSON: `{ts, level, msg, requestId, orgId?, path?, ms?, err?, ...fields}`.
  - Wire `corsMiddleware` to generate a `requestId` (ULID via `crypto.randomUUID()` for now; replace with ULID lib later) and stuff it into Hono context.
  - Add response header `X-Request-Id` on every response (including 4xx/5xx).
  - Replace every `console.log` and `console.error` in the worker with logger calls. Do NOT leave bare `console.*` behind.
- **files likely touched:**
  - `cohrint-worker/src/lib/logger.ts` (new)
  - `cohrint-worker/src/middleware/cors.ts`
  - `cohrint-worker/src/middleware/auth.ts`
  - `cohrint-worker/src/routes/*.ts` (replace console calls)
  - `cohrint-worker/src/index.ts` (register logger in context)
- **acceptance:**
  - `curl -I https://api.cohrint.com/v1/analytics/summary` returns `X-Request-Id: <ulid>` header.
  - `wrangler tail` output is valid NDJSON (one JSON object per line).
  - No `console.log` / `console.error` strings remain in `cohrint-worker/src` (grep check in CI).
  - Test suite 38 (security hardening) still passes; new test asserts correlation ID is present in error responses.
- **zero-cost check:** ✓ uses stdout only; Workers free tier.
- **future_scale:** When logs get too noisy for `wrangler tail`, enable Workers Logpush → R2 (free tier 10GB) or ship to Workers Analytics Engine (10M writes/mo free). No code changes needed, just wrangler config.

---

### T002 — Workers Analytics Engine counters for every ingest outcome

- **status:** in_review
- **requires:** T001
- **why:** We need to see failure rates, duplicate rates, and free-tier reject rates without querying D1. WAE is free up to 10M writes/mo and is the right long-term home for per-endpoint metrics.
- **scope:**
  - Add `[[analytics_engine_datasets]]` binding `METRICS` in `wrangler.toml`.
  - Create `cohrint-worker/src/lib/metrics.ts` with typed helpers: `emit({event, orgId?, labels?, values?})`.
  - Instrument ingest path to emit: `events.accepted`, `events.duplicate`, `events.free_tier_rejected`, `events.d1_error`, `cache.hit`, `cache.miss`, `ratelimit.rejected`.
  - Emit request-latency observations on a 1% sample for `/v1/events` and `/v1/cache/lookup`.
- **files likely touched:**
  - `cohrint-worker/src/lib/metrics.ts` (new)
  - `cohrint-worker/src/routes/events.ts`
  - `cohrint-worker/src/routes/cache.ts`
  - `wrangler.toml`
- **acceptance:**
  - WAE dataset `cohrint_metrics` receives data in production (verify via `wrangler analytics-engine query`).
  - Dashboard doc updated with SQL queries for the 7 event types.
  - Unit test mocks `METRICS` binding and asserts `emit()` called with correct labels for each code path.
- **zero-cost check:** ✓ WAE free tier is 10M writes/mo; at 1M events/day we'd use 30M/mo so sample ingest writes at 10% in production. Document this.
- **future_scale:** Point Grafana / Datadog at WAE SQL API when we're ready to pay.

---

### T003 — Typed D1 date-binding helper (stops silent full-table scans)

- **status:** in_review
- **requires:** T001
- **why:** §2.3 of review — documented silent-coercion bug is the highest-severity correctness risk. Banning raw date binds is the only durable fix.
- **scope:**
  - Create `cohrint-worker/src/lib/db-dates.ts` exporting:
    - `type DateColumn<T extends 'int' | 'text'>`
    - `bindSince(column: DateColumn<T>, days: number): number | string`
    - `bindNow(column: DateColumn<T>): number | string`
    - `bindStartOfMonth(column: DateColumn<T>): number | string`
  - Create `cohrint-worker/src/lib/db-schema.ts` exporting `DATE_COLUMN_TYPE` map, e.g.
    ```ts
    export const DATE_COLUMN_TYPE = {
      events: 'int',
      audit_events: 'int',
      cross_platform_usage: 'text',
      // ... all 25 tables enumerated
    } as const;
    ```
  - Add ESLint rule (custom, lightweight) or tsc-level check: any `.bind(someDate)` passed to a known date column must come from a helper. Minimum acceptable: a grep-based CI check that fails if `Date.now()` or `new Date().toISOString()` appears inside `.prepare(...).bind(...)` calls.
  - Replace all existing raw date binds across `analytics.ts`, `crossplatform.ts`, `events.ts`, `benchmark.ts`, `cache.ts`, `copilot.ts`, `datadog.ts` with helper calls.
- **files likely touched:**
  - `cohrint-worker/src/lib/db-dates.ts` (new)
  - `cohrint-worker/src/lib/db-schema.ts` (new)
  - every `cohrint-worker/src/routes/*.ts` touching dates
  - `.github/workflows/ci-*.yml` (grep guard)
- **acceptance:**
  - `grep -rn "Date.now()/1000" cohrint-worker/src/routes/` returns only imports of the helper.
  - Test suite 45 (dashboard API coverage) passes without modification.
  - New test 52_date_binding_regression asserts wrong-type bind throws at runtime (helper-level assertion, not silent coerce).
  - Guidebook §3 "CRITICAL: Date Column Type Divergence" updated to point at the helper as the enforcement mechanism.
- **zero-cost check:** ✓ pure code change.
- **future_scale:** When moving off D1 (T020), the helpers become the swap point — replace their body, not a thousand callsites.

---

### T004 — Idempotent ingest response distinguishes accepted vs duplicate

- **status:** in_review
- **requires:** T001
- **superseded_by:** T010 (see note below)
- **why:** §2.7 — SDKs can't detect client-side dedup bugs when server silently swallows duplicates. Pre-T010 this is synchronous; post-T010 the dedup-detection semantics change (see note).
- **scope:**
  - Change `POST /v1/events` response from `{ok, id}` to `{ok, id, accepted: boolean, reason?: "duplicate" | "inserted"}`.
  - Use D1 `changes()` on the `INSERT OR IGNORE` statement to determine insert vs no-op.
  - For `POST /v1/events/batch`, add `accepted_ids[]` and `duplicate_ids[]` to response.
  - Update Python SDK (`cohrint` PyPI) and JS SDK (`cohrint` npm) to log a warning when `accepted=false` and count it in an in-memory counter.
  - Document in guidebook §5.3 that `accepted` is **synchronously accurate only until T010 ships**.
- **interaction with T010:** Once T010 introduces queue-based async ingest, the HTTP response cannot synchronously know whether an event is a duplicate — dedup happens in the consumer, after the 202 is returned. T010's scope explicitly handles this transition:
  - `POST /v1/events` returns `{ok, id, accepted: true, status: "queued"}` with HTTP 202.
  - The `duplicate` signal moves to a post-hoc path: SDK can poll `GET /v1/events/:id/status` (optional), or server emits a WAE metric on duplicate for dashboard observability.
  - Batch-level `accepted_ids[]` / `duplicate_ids[]` becomes an optimistic "submitted_ids" — actual dedup outcome is observable via metrics, not the response.
- **files likely touched:**
  - `cohrint-worker/src/routes/events.ts`
  - `sdk-python/cohrint/proxy.py`
  - `sdk-js/src/proxy.ts`
  - `docs.html` (API reference)
- **acceptance:**
  - Duplicate POST returns `{ok: true, id: ..., accepted: false, reason: "duplicate"}` with 200 (not 201).
  - New test 53_ingest_idempotency covers: fresh insert (201 accepted), duplicate (200 not-accepted), batch with mix.
  - T010's acceptance criteria updates this behavior; this test must be renamed `53_ingest_idempotency_sync` and a new `53_ingest_idempotency_async` suite added when T010 lands.
- **zero-cost check:** ✓
- **future_scale:** Response shape stabilizes at T010's async version.

---

## Phase 1 — Correctness fixes (no architectural change)

Land these after Phase 0. They pay down the bugs the guidebook already documents as known issues.

---

### T005 — Atomic increment for prompt_versions rolling stats

- **status:** in_review
- **requires:** T001
- **why:** §2.3 — read-modify-write race on `prompt_versions.total_calls` drifts at scale.
- **scope:**
  - Replace `DB.batch([INSERT prompt_usage, UPDATE prompt_versions SET avg_cost = (old_total + ?) / (old_calls + 1) ...])` with `UPDATE prompt_versions SET total_calls = total_calls + 1, total_cost_usd = total_cost_usd + ?, total_prompt_tokens = total_prompt_tokens + ?, total_completion_tokens = total_completion_tokens + ?`.
  - Remove `avg_cost_usd`, `avg_prompt_tokens`, `avg_completion_tokens` columns from `prompt_versions` (or keep as GENERATED columns if D1 supports — check; if not, compute on read).
  - Update `GET /v1/prompts/analytics/comparison` to compute averages in the SELECT: `total_cost_usd / NULLIF(total_calls, 0) AS avg_cost_usd`.
  - Migration `NNNN_prompt_versions_totals_only.sql`.
- **files likely touched:**
  - `cohrint-worker/migrations/NNNN_prompt_versions_totals_only.sql` (new)
  - `cohrint-worker/src/routes/prompts.ts`
- **acceptance:**
  - Concurrency test: 100 parallel `POST /v1/prompts/usage` for same version → `total_calls` == 100 (currently drifts to 97-99).
  - Existing test suite for prompts unchanged.
- **zero-cost check:** ✓
- **future_scale:** Atomic counters transfer cleanly to any RDBMS.

---

### T006 — Cache free-tier monthly count in KV

- **status:** in_review
- **requires:** T001, T002
- **why:** §2.5 — `SELECT COUNT(*) FROM events WHERE org_id=? AND created_at >= month_start` runs per ingest, latency grows with customer size. Exactly backwards.
- **scope:**
  - On successful `INSERT events`, increment KV key `freetier:{orgId}:{YYYY-MM}` with 45-day TTL.
  - `checkFreeTierLimit()` reads KV first; if miss, falls back to D1 COUNT and primes KV.
  - On the first day of the month, no KV key exists — D1 count is zero (cheap), primes KV at 0.
  - Paid plans skip this entirely (early return before KV read).
- **files likely touched:**
  - `cohrint-worker/src/routes/events.ts`
  - `cohrint-worker/src/lib/freetier.ts` (new)
- **acceptance:**
  - Microbenchmark: ingest latency for a free-tier org with 45k existing events drops from ~180ms p95 to ~25ms p95.
  - Counter correctness test: 1000 concurrent POSTs, KV counter === actual D1 count.
- **zero-cost check:** ✓ KV free tier: 100k reads/day, 1k writes/day. One write per ingest exceeds this at scale — so use `waitUntil` and a 10-second in-memory debounce (accumulate N ingests, one KV write). Document this in the file header.
- **future_scale:** Replace KV with a Durable Object counter when >1k writes/day free-tier limit is reached. DO is ~$0.15/mo per org so it's still nearly free.

---

### T007 — Per-API-key rate limit, keep per-org as outer guard

- **status:** in_review
- **requires:** T001
- **why:** §2.4 — one noisy key starves the org. Per-key is the correct granularity; per-org becomes the DoS backstop.
- **scope:**
  - Change `checkRateLimit()` to accept `{orgId, apiKeyHashPrefix}` and check both `rl:org:{orgId}:{min}` and `rl:key:{keyHashPrefix8}:{min}`.
  - Default limits: per-key 200 RPM, per-org 1000 RPM (configurable via env).
  - Response headers: `X-RateLimit-Limit-Key`, `X-RateLimit-Limit-Org`, `X-RateLimit-Remaining-Key`, `X-RateLimit-Remaining-Org`.
  - Add admin endpoint `PATCH /v1/admin/ratelimits` to override per-key limits per org (admin+, audit-logged).
- **files likely touched:**
  - `cohrint-worker/src/middleware/ratelimit.ts`
  - `cohrint-worker/src/routes/admin.ts` (new endpoint)
- **acceptance:**
  - One key firing 500 RPM gets 429 at 200; other keys in same org still work.
  - Existing RPM limit test updated, new per-key test added.
- **zero-cost check:** ✓ doubles KV writes per request; offset by T006's debounce and KV's 70s TTL coalescing.
- **future_scale:** Durable Object per org for accurate rolling-window limits.

---

### T008 — Fix `events` index for per-org time range scans

- **status:** in_review
- **requires:** T001
- **why:** §2.1 — PK is `(id, org_id)` so every analytics query does a table scan for time predicates. This is the single biggest analytics perf fix.
- **scope:**
  - Migration `NNNN_events_org_time_index.sql`: `CREATE INDEX IF NOT EXISTS idx_events_org_created ON events(org_id, created_at DESC);`
  - Add index on `(org_id, trace_id, created_at)` for trace detail queries.
  - Add index on `(org_id, team, created_at DESC)` for team scoping.
  - Use `ANALYZE` after migration.
- **files likely touched:**
  - `cohrint-worker/migrations/NNNN_events_org_time_index.sql` (new)
- **acceptance:**
  - `EXPLAIN QUERY PLAN SELECT ... FROM events WHERE org_id=? AND created_at >= ?` uses `idx_events_org_created` (not SCAN).
  - Timeseries endpoint p95 drops measurably on DA45 seed data.
- **zero-cost check:** ✓ D1 storage within free tier.
- **future_scale:** Irrelevant — index is standard.

---

### T009 — Distributed lock around benchmark + copilot + datadog crons

- **status:** in_review
- **requires:** T001
- **why:** §2.3 — race between a retry and a scheduled run can corrupt percentiles. Cloudflare does not guarantee cron exclusivity across deploys.
- **scope:**
  - Create `cohrint-worker/src/lib/cron-lock.ts` with `acquireLock(kv, name, ttlSec): Promise<{released: () => Promise<void>} | null>`.
  - Implementation: `KV.get` → if missing, `KV.put` with `expirationTtl` and re-read to confirm owner (eventual consistency band). Return null if another owner.
  - Wrap `syncBenchmarkContributions`, `syncCopilotMetrics`, `pushDatadogMetrics` entry points in lock acquisition; log-and-skip on failure.
  - Add `last_successful_sync_at` column to `copilot_connections` and `datadog_connections` (separate from `last_sync_at`).
- **files likely touched:**
  - `cohrint-worker/src/lib/cron-lock.ts` (new)
  - `cohrint-worker/src/crons/*.ts`
  - `cohrint-worker/migrations/NNNN_sync_watermarks.sql` (new)
- **acceptance:**
  - Concurrent invocation test: second invocation of same cron within lock TTL logs `cron_lock_skipped` and exits 0.
  - Manual `POST /v1/copilot/sync` also respects lock.
- **zero-cost check:** ✓
- **future_scale:** Replace KV lock with Durable Object when we outgrow eventual consistency (cron timing is forgiving; won't happen soon).

---

## Phase 2 — The big structural fix: decouple ingest from D1

**Phase gate:** Phase 0 and Phase 1 must each be entirely `status: done` AND have been on production `main` for ≥ 7 days. This is the single highest-leverage change in the backlog; rushing it before guardrails and correctness fixes have burned in would put billing data at risk.

---

### T010 — Introduce Cloudflare Queues between ingest and D1

- **status:** in_review
- **requires:** T001, T002, T003, T004, T008
- **why:** §3.1 of review — D1 is the SPOF. Queue decouples ingest availability from D1 availability, enables batching, and gives a retry surface.
- **scope:**
  - Add `[[queues.producers]]` and `[[queues.consumers]]` bindings in `wrangler.toml`. Queue name: `cohrint-ingest`.
  - `POST /v1/events` path (after auth, rate limit, free-tier check) writes to queue instead of D1. Response becomes `{ok: true, id, accepted: true, status: "queued"}` with HTTP 202. (Supersedes T004's sync response shape — update SDK + docs + tests in the same PR.)
  - `POST /v1/events/batch`: response becomes `{ok: true, submitted_ids: [...], count: N, status: "queued"}` with HTTP 202. The synchronous `accepted_ids[]`/`duplicate_ids[]` distinction from T004 is removed here; duplicate detection becomes observable via WAE metrics (`events.duplicate` counter) rather than the response.
  - **Critical: remove the T006-era KV counter increment from the HTTP handler.** The consumer is now the sole writer of `freetier:{orgId}:{YYYY-MM}`. Leaving both paths active causes double-counting. Add a grep check in CI to enforce this.
  - Consumer worker (new file `cohrint-worker/src/consumers/events-ingest.ts`) reads messages in batches of up to 100, does `DB.batch([INSERT OR IGNORE ...])`, updates `freetier:` KV counter (sole writer), and emits WAE `events.accepted` / `events.duplicate` metrics using D1 `changes()` output.
  - On D1 error: throw — Queues will retry with exponential backoff up to max retries, then DLQ.
  - Add DLQ queue `cohrint-ingest-dlq` and a `GET /v1/superadmin/ingest/dlq` endpoint to inspect (superadmin only, audit-logged).
  - **Critical:** maintain strict ordering is NOT required for events (they have their own `created_at`). Document this.
  - Guidebook §5.3 update: `POST /v1/events` response shape transition (sync → async, 201 → 202), with a "pre-T010 semantics" callout for historical SDK versions.
- **files likely touched:**
  - `wrangler.toml`
  - `cohrint-worker/src/routes/events.ts`
  - `cohrint-worker/src/consumers/events-ingest.ts` (new)
  - `cohrint-worker/src/consumers/events-ingest-dlq.ts` (new)
  - `cohrint-worker/src/routes/superadmin.ts`
  - `cohrint-worker/src/lib/freetier.ts` (remove HTTP-path increment, add consumer-path one)
  - `sdk-python/cohrint/proxy.py` (handle 202)
  - `sdk-js/src/proxy.ts` (handle 202)
  - `docs.html`
- **acceptance:**
  - Ingest p95 drops from 200ms+ to sub-50ms (measured via T002 sample).
  - D1 killswitch test: temporarily return 500 from D1 in consumer; queue depth grows; restore D1; queue drains with zero event loss. (Simulate via feature flag.)
  - Existing test suite 01_api (events) updated for new response shape.
  - Test 53_ingest_idempotency_sync (from T004) renamed/archived; new 53_ingest_idempotency_async asserts duplicate detection via WAE metric, not response.
  - Double-count test: fire 1000 events, assert `freetier:` KV counter is exactly 1000 (not 2000, which would indicate HTTP-path increment wasn't removed).
  - Batch endpoint benchmark: 500-event batch ingests in <100ms edge time.
- **zero-cost check:** Cloudflare Queues free tier = 1M ops/mo (both sides count, so effectively 500k ingests/mo on free tier). At Cohrint's alpha volume this is fine. **Document the free-tier ceiling in the guidebook §29** — past ~15k ingests/day we need to upgrade or fan out.
- **future_scale:** Paid Queues = $0.40/M operations. Still essentially free at any realistic scale.

---

### T011 — Daily rollup consumer for analytics

- **status:** in_review
- **requires:** T010
- **why:** §3.3 of review — dashboard endpoints currently scan raw `events` for every analytics call. Rollups make `/summary`, `/timeseries`, `/models`, `/teams` O(orgs) instead of O(events).
- **scope:**
  - New table `events_daily_rollup(org_id, date_unix_day, model, provider, team, project, environment, cost_usd, prompt_tokens, completion_tokens, cache_tokens, total_tokens, requests, cache_hits, avg_latency_ms, PRIMARY KEY (org_id, date_unix_day, model, team))`.
  - Queue consumer from T010 additionally upserts the rollup row via `INSERT ... ON CONFLICT DO UPDATE SET cost_usd = cost_usd + excluded.cost_usd, requests = requests + 1, ...`. Atomic increment, no read-modify-write.
  - Rewrite `GET /v1/analytics/summary`, `/timeseries`, `/models`, `/teams` to read from rollup (not `events`).
  - `GET /v1/analytics/traces/:traceId` continues reading `events` (drill-down is the exception).
  - Keep the KV-cached `/summary` as a second-layer cache but raise TTL to 2 minutes since underlying data is already aggregated.
  - Migration `NNNN_events_daily_rollup.sql`.
- **files likely touched:**
  - `cohrint-worker/migrations/NNNN_events_daily_rollup.sql` (new)
  - `cohrint-worker/src/consumers/events-ingest.ts` (extend)
  - `cohrint-worker/src/routes/analytics.ts` (rewrite queries)
- **acceptance:**
  - Summary endpoint latency drops ≥80% on DA45 seed data.
  - Backfill script `scripts/backfill-rollup.ts` idempotently populates rollup from existing `events`. Run once on deploy.
  - Parity test 54_rollup_parity: for 20 representative orgs, rollup query result == raw events query result (±$0.001 rounding).
- **zero-cost check:** ✓ D1 storage grows ~1KB per (org, day, model) — negligible.
- **future_scale:** When D1 cap becomes an issue, rollup is already a clean boundary for moving raw events to a columnar store (ClickHouse Cloud free tier, or Tinybird free tier). Dashboard continues pointing at D1 rollup.

---

### T012 — SDK client-side spool with retry

- **status:** in_review
- **requires:** T010
- **why:** §2.6 — paired with Queue, this gets effective event loss to ~zero even under multi-hour control-plane incidents.
- **scope:**
  - Python SDK: persist failed events to `{spool_dir}/*.ndjson`, retry on next SDK call or via background thread every 60s with exponential backoff. Cap spool at 100 MB; rotate oldest.
  - JS SDK: same, but in Node use filesystem; in browser use `localStorage` with 5MB cap.
  - **Spool directory resolution order** (applies to both SDKs in non-browser context):
    1. Env var `COHRINT_SPOOL_DIR` if set and writable.
    2. `~/.cohrint/spool/` if `~` is writable.
    3. `$TMPDIR/cohrint-spool/` (or `/tmp/cohrint-spool/` on POSIX) if writable.
    4. Fall back to in-memory ring buffer (10 MB cap); emit a one-time warn log: `spool: filesystem unavailable, events will be lost on process exit`.
  - On successful flush, delete the file/entry.
  - Add `cohrint.spool_stats()` / `cohrint.spoolStats()` API returning `{pending, oldest_ts, total_bytes, mode: "fs" | "memory", path?}`.
  - Document in SDK READMEs — explicitly call out Lambda / read-only container behavior.
- **files likely touched:**
  - `sdk-python/cohrint/spool.py` (new)
  - `sdk-python/cohrint/proxy.py`
  - `sdk-js/src/spool.ts` (new)
  - `sdk-js/src/proxy.ts`
- **acceptance:**
  - Integration test: ingest endpoint returns 503 for 30s → SDK retains events in spool → ingest recovers → all events arrive server-side.
  - Read-only-FS test: mock filesystem as read-only, assert SDK falls back to in-memory mode and emits warn log.
  - No new runtime deps (Python stdlib only; JS native `fs`).
- **zero-cost check:** ✓
- **future_scale:** No change.

---

## Phase 3 — Storage correctness and compliance

---

### T013 — Move semantic cache response bodies to R2

- **status:** in_review
- **requires:** T001
- **why:** §3.5 of review — `response_text` in D1 bloats the primary DB and caps semantic-cache size at D1's 10GB limit.
- **scope:**
  - New R2 bucket `cohrint-cache` (created via `wrangler r2 bucket create`).
  - Three-release rollout to prevent orphaned pointers and allow rollback:
    - **Release A (this task):** Add `response_r2_key TEXT NULLABLE` column. On `POST /v1/cache/store`: (1) `R2.put("cache/{orgId}/{entryId}", responseText)` **first** — fail loud if R2 errors, do not proceed; (2) `D1 INSERT` populates **both** `response_text` (existing) AND `response_r2_key` (new). On cache hit read: prefer R2 (if `response_r2_key` set AND `R2.get` succeeds), fall back to `response_text` on R2 error or missing key.
    - **Release B (follow-up task, not this one):** stop writing to `response_text`; require `response_r2_key` non-null for new entries; reads still fall back to `response_text` for entries created before Release A.
    - **Release C (follow-up task, not this one):** backfill: for entries with `response_text NOT NULL AND response_r2_key IS NULL`, write to R2 and populate pointer. Only after backfill is 100% complete, drop `response_text` column in a separate migration.
  - On `DELETE /v1/cache/entries/:id`: delete R2 object FIRST, then Vectorize vector, then D1 row. Rationale: if R2 delete fails, we can retry from the D1 row. If D1 is deleted first and R2 fails, the R2 object becomes orphaned.
  - On eviction (age check): same order as DELETE above.
  - Add reconciliation task to a cron (daily): scan last 24h of new entries; for each, assert R2 object exists. Log divergences to WAE `cache.reconciliation_drift` for human investigation.
- **files likely touched:**
  - `wrangler.toml` (R2 binding)
  - `cohrint-worker/src/routes/cache.ts`
  - `cohrint-worker/migrations/NNNN_cache_r2_pointer.sql` (new — adds nullable column only)
  - `cohrint-worker/src/crons/cache-reconcile.ts` (new)
- **acceptance:**
  - Existing cache tests (36_semantic_cache) pass unchanged from the caller's perspective.
  - R2-fail-first test: inject R2 put error → D1 row is NOT created → client gets 5xx. Verifies write ordering.
  - D1-fail-after-R2 test: inject D1 insert error after R2 put → orphaned R2 object is logged to reconciliation drift metric (documented known case; cleanup via cron).
  - Rollback test: flip feature flag off → reads fall back to `response_text` column; all existing tests still pass.
- **zero-cost check:** ✓ R2 free tier = 10GB storage, 1M Class A ops/mo, 10M Class B ops/mo. Cache responses average ~2KB → 5M entries free.
- **future_scale:** R2 scales indefinitely; this is the terminal architecture for cache bodies.

---

### T014 — Append-only audit log to R2 + D1 index

- **status:** in_review
- **requires:** T001
- **why:** §2.4 — audit log is "immutable by convention" which is not immutable. SOC 2 wants tamper-evident.
- **note:** Earlier drafts had this depending on T013. That was wrong — T013 and T014 both use R2 but are otherwise independent concerns. T014 can ship without waiting for cache migration. The R2 bucket may be shared (`cohrint-cache` with `cache/` and `audit/` prefixes) or split into two buckets; prefer one bucket with prefixes to stay under free-tier bucket count.
- **scope:**
  - Dual-write audit events: `D1 INSERT audit_events` (unchanged) AND `R2.put("audit/{orgId}/{YYYY-MM-DD}/{ulid}.json")` with object lock / retention policy.
  - R2 objects immutable via bucket-level lifecycle rule (no DELETE permission for non-superadmin; superadmin deletes are themselves audited in a separate root-level log).
  - `GET /v1/audit-log` reads from D1 (fast); `GET /v1/audit-log/verify?id=...` compares D1 row hash against R2 object → returns `{consistent: true|false}`.
  - Add `GET /v1/audit-log/export?format=csv&from=&to=` for SOC 2 evidence (admin+).
- **files likely touched:**
  - `cohrint-worker/src/routes/auditlog.ts`
  - `cohrint-worker/src/lib/audit.ts`
  - `wrangler.toml` (R2 binding reuse)
- **acceptance:**
  - Every `logAudit()` call produces one R2 object.
  - Tamper test: manually modify D1 row → `/verify` returns `consistent: false`.
  - Export endpoint returns valid CSV with all columns matching the schema in §24.10.
- **zero-cost check:** ✓ audit events are ~200B; 100k events = 20MB, well within R2 free tier.
- **future_scale:** When SOC 2 Type II requires external attestation, add AWS S3 Object Lock mirror via Cloudflare's S3-compatible API.

---

### T015 — Kill the `TEXT`-date tables (unify on INTEGER unix seconds)

- **status:** in_review
- **requires:** T003
- **phase_b_gate:** Phase A migration must have been on production `main` for ≥ 14 days AND survived at least one production deploy before Phase B (column drops) is allowed.
- **why:** §2.3 — one date convention ends an entire bug class.
- **scope:**
  - For each TEXT-date table (cross_platform_usage, otel_events, benchmark_snapshots, copilot_connections, datadog_connections, prompts, prompt_versions, prompt_usage, semantic_cache_entries, org_cache_config):
    - **Phase A (this PR):** Add new column `created_at_unix INTEGER`. Backfill via one-time data migration script `migrations/data/NNNN_backfill_created_at_unix.ts`: `UPDATE t SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER)`. Update all read paths to use `created_at_unix`. Keep writes to old `created_at` column for rollback safety.
    - **Phase B (separate follow-up PR, after phase_b_gate satisfied):** stop writing to old `created_at`; then drop column in a separate migration `MMMM_unify_dates_phase_b.sql`. This is a second task that Claude Code should surface once the gate is satisfied, not part of this PR.
  - Remove `crossplatform.ts` date helpers; single source is `db-dates.ts` from T003.
  - Update `DATE_COLUMN_TYPE` map in `db-schema.ts` to all `'int'` **after Phase B lands**. Until then it retains both.
  - **Guidebook cleanup (same PR as Phase A):** Replace the entire "CRITICAL: Date Column Type Divergence" block in §3 with a short sentence: *"All dates are stored as INTEGER unix seconds. Use helpers in `src/lib/db-dates.ts`; direct `Date.now()` or `datetime('now')` usage is banned by CI grep check."* The current warning becomes misleading once migration completes and should not linger as a historical artifact that confuses new engineers.
- **files likely touched:**
  - `cohrint-worker/migrations/NNNN_unify_dates_phase_a.sql` (add columns only)
  - `cohrint-worker/migrations/data/NNNN_backfill_created_at_unix.ts` (new)
  - every consumer of those tables
  - `docs/GUIDEBOOK.docx` (§3 rewrite)
- **acceptance:**
  - All read paths use INTEGER dates via `db-dates.ts`; grep check confirms.
  - Parity test: for each migrated table, row count and max(created_at_unix) match pre-migration.
  - Guidebook §3 updated; CI grep check prevents the phrase "Date Column Type Divergence" from being re-added.
- **zero-cost check:** ✓
- **future_scale:** Any future DB migration has one date type to carry over.

---

## Phase 4 — Isolation & safety rails

---

### T016 — Query wrapper enforces `org_id` in every query

- **status:** in_review
- **requires:** T001
- **why:** §2.4 — SQL-layer isolation is one forgotten WHERE away from a CVE. Make the wrong thing impossible.
- **scope:**
  - Create `cohrint-worker/src/lib/db.ts` exporting `scopedDb(env.DB, orgId)` returning a wrapper with `prepare(sql)`.
  - Wrapper scans for `{{ORG_SCOPE}}` placeholder; refuses queries without it.
  - Queries against scoped tables MUST use the placeholder, e.g. `SELECT * FROM events WHERE {{ORG_SCOPE}} AND created_at >= ?`.
  - Replace every `env.DB.prepare(...)` with `scopedDb(env.DB, orgId).prepare(...)` in route handlers.
  - Exceptions (cross-org queries): must go through `env.DB.prepareUnsafe(...)`, which is only exported to cron files and gated by lint rule.
- **files likely touched:**
  - `cohrint-worker/src/lib/db.ts` (new)
  - every `cohrint-worker/src/routes/*.ts`
  - `cohrint-worker/src/crons/*.ts` (use prepareUnsafe)
- **acceptance:**
  - Negative test: a new route handler that omits `{{ORG_SCOPE}}` fails at the first query with `ScopeViolationError`.
  - Existing tests pass.
- **zero-cost check:** ✓
- **future_scale:** When moving to Postgres, the wrapper becomes an RLS session setter.

---

### T017 — Circuit breakers around third-party calls (per-region best-effort)

- **status:** in_review
- **requires:** T001
- **why:** §2.6 — slow Slack/Resend/GitHub/Datadog wastes Worker CPU and delays user-visible responses.
- **known limitation (document in the PR):** KV is eventually consistent with ~60s global propagation. The breaker is effectively **per-region best-effort**: state propagates to other regions within ~60s, so during that window some regions may still call a failing service while others short-circuit. This is acceptable given the alternative (Durable Objects) is deferred to Phase 6. Customer-facing impact: ≤60s additional failed-call exposure during the propagation window — trivial compared to the baseline "no breaker at all." Revisit if we observe breaker flapping or customer reports of slow responses caused by cross-region state drift.
- **scope:**
  - Create `cohrint-worker/src/lib/circuit.ts`: primary state is **in-memory** (per Worker isolate, per region); KV is a **secondary, eventually-consistent hint** to speed up cross-region convergence.
    - On failure → increment in-memory counter; if threshold crossed → open locally AND write to KV (`circuit:{service}:open = "1"` with 30s TTL).
    - On any request → check in-memory first; if closed, also check KV (with a 5s cache to avoid read storm); if KV says open, honor it.
    - Cooldown after 30s → half-open (local decision); one test request; if success, close locally AND clear KV hint.
  - 3-state (closed/open/half-open). Failure threshold 5 in 60s, cooldown 30s. Per-service breakers.
  - Wrap `sendSlackMessage`, `sendResendEmail`, `githubCopilotFetch`, `datadogPush` with breaker.
  - When open: log, emit WAE metric `circuit.short_circuited`, return gracefully (no throw).
- **files likely touched:**
  - `cohrint-worker/src/lib/circuit.ts` (new)
  - `cohrint-worker/src/lib/email.ts`
  - `cohrint-worker/src/lib/slack.ts`
  - `cohrint-worker/src/crons/copilot.ts`
  - `cohrint-worker/src/crons/datadog.ts`
- **acceptance:**
  - Simulated Slack 500s (feature flag) → breaker opens after 5 failures in the local region; subsequent requests in that region short-circuit in <5ms; breaker closes after 30s recovery.
  - KV-propagation test: open breaker in one region; assert KV hint is written; simulate another region reading the KV hint and honoring it.
  - Acknowledge in PR body: cross-region convergence is eventually consistent — not a bug, a tradeoff.
- **zero-cost check:** ✓
- **future_scale:** Replace KV hint with Durable Object for strongly-consistent state when Phase 6 lands.

---

### T018 — Min prompt length 100 chars default for semantic cache

- **status:** in_review
- **requires:** —
- **why:** §2.5 — for short prompts the embed+query round-trip beats the LLM call for cheap models; caching is net-negative.
- **scope:**
  - Change default `min_prompt_length` from 10 to 100 in `0015_semantic_cache.sql` defaults (and in `org_cache_config` upsert logic for new orgs).
  - Existing orgs: no migration; keep their setting.
  - Add short-circuit in `POST /v1/cache/lookup`: if `len(prompt) < 100`, skip Workers AI embedding entirely, return miss with reason `prompt_too_short`. Saves the AI inference cost.
  - Add reason codes to miss response: `{hit: false, reason: "below_threshold" | "prompt_too_short" | "disabled" | "entry_expired"}`.
- **files likely touched:**
  - `cohrint-worker/src/routes/cache.ts`
  - `cohrint-worker/migrations/NNNN_cache_config_min_length.sql` (new — bumps default for new orgs only)
  - Dashboard UI copy update
- **acceptance:**
  - Existing test 36_semantic_cache passes; new assertion for `prompt_too_short` reason.
  - Benchmark: no embed-call fired for 50-char prompts.
- **zero-cost check:** ✓ reduces Workers AI usage.
- **future_scale:** No change.

---

## Phase 5 — Operational polish

---

### T019 — Replay/backfill endpoint for score corrections

- **status:** in_review
- **requires:** T001, T010, T016
- **why:** §2.7 — right now a buggy scoring run requires manual D1 script.
- **scope:**
  - `POST /v1/superadmin/events/rescore` body: `{org_id, from, to, fields_to_clear: ["hallucination_score", ...]}` — clears those fields and re-queues events for async scoring.
  - **Queue usage:** Do NOT create a new `cohrint-rescore` queue. Reuse T010's `cohrint-ingest` queue with a message-type discriminator field (`type: "rescore"` vs `type: "event"`). The consumer routes by type. Rationale: Queues free tier is 1M ops/mo shared across all queues; adding a second queue cannibalizes T010's budget for rare administrative use. Rescore is a backfill operation expected to run infrequently (monthly at most), so it can share T010's budget without meaningful contention.
  - Superadmin-only. Every call audit-logged with full target range.
  - Rate-limit the endpoint to 1 request / 15 minutes per superadmin to prevent accidental queue flooding.
- **files likely touched:**
  - `cohrint-worker/src/routes/superadmin.ts`
  - `cohrint-worker/src/consumers/events-ingest.ts` (add `type: "rescore"` handler)
- **acceptance:**
  - Superadmin-only enforced (403 for admin).
  - Audit event `score.rescore_triggered` written with full metadata.
  - Rate-limit test: second call within 15min returns 429.
- **zero-cost check:** ✓ shared queue budget with T010.
- **future_scale:** Same endpoint works for any column-reset use case.

---

### T020 — Guidebook Section 29: document exit paths from every free-tier ceiling

- **status:** in_review
- **requires:** T010, T011, T013, T014
- **why:** Every free-tier choice is a ceiling. Document where each one breaks so future-us is not surprised.
- **scope:**
  - Add new section §29 "Free-Tier Ceilings & Exit Paths" to the guidebook (§27 is the existing Research White Paper).
  - For each service (D1, KV, R2, Queues, Workers AI, Vectorize, WAE): table with current usage, free-tier ceiling, first paid tier cost, estimated month-to-exceed at current growth, exit architecture.
- **files likely touched:**
  - Guidebook docx (new section)
- **acceptance:**
  - Table has all 7 services.
  - Each row names a specific alternative (e.g. "D1 → Neon Postgres free tier → Postgres with RDS Proxy").
- **zero-cost check:** ✓ docs only.
- **future_scale:** This section IS the scale plan.

---

## Phase 6 — Deferred (don't do yet)

These are in the review but are not worth doing while Cohrint is pre-revenue. Revisit when you cross 1M events/day, hire a second engineer, or a triggering event forces the issue.

- **Durable Objects for rate limiting** — accurate rolling windows, per-tenant QoS. Trigger: KV-based limits cause real customer complaints about burstiness.
- **Durable Objects for circuit breaker state** — strongly consistent cross-region breaker. Trigger: observe breaker flapping or customer reports of slow responses caused by stale KV state.
- **Move raw events to ClickHouse Cloud / Tinybird free tier** — Trigger: D1 hits 5 GB.
- **Replace SSE KV polling with Durable Object sockets** — Trigger: concurrent streams per org routinely exceed 10.
- **Typed query builder (Drizzle/Kysely)** — bigger refactor than T016 and T016 is the 80/20. Trigger: query complexity starts outgrowing raw SQL.
- **`TOKEN_ENCRYPTION_SECRET` rotation procedure** — current state: rotation requires re-encrypting every Copilot PAT and Datadog key in KV/D1 using both old and new keys during transition. No tooling exists. **Trigger: any key compromise, annual SOC 2 control rotation requirement, or a second secret being added.** When triggered, work: (a) add `TOKEN_ENCRYPTION_SECRET_PREVIOUS` env var, (b) decrypt attempts try current key then previous, (c) write-back re-encrypts with current, (d) after grace period, remove previous secret. Design this before it's needed; build it when triggered.
- **Deprecate `vnt_*` legacy identifiers** — `VANTAGE_CI_SECRET`, `vantage_session` cookie, `vantage-events` D1 name still reference the old brand. Trigger: coordinated rename window with SDK users and migration guide. Risk: breaks every existing customer integration.

---

## Appendix A — Task ordering

The `requires:` field on each task is the authoritative dependency. Claude Code must also honor the Phase gate (Phase N+1 cannot start until Phase N is entirely done AND burned in on production for ≥ 7 days).

### Dependency table (hard requirements)

| Task | Phase | Requires | Notes |
|------|-------|----------|-------|
| T001 | 0 | — | Everything depends on this; do it first. |
| T002 | 0 | T001 | |
| T003 | 0 | T001 | |
| T004 | 0 | T001 | Superseded by T010 for `/v1/events`; see task note. |
| T005 | 1 | T001 | |
| T006 | 1 | T001, T002 | |
| T007 | 1 | T001 | |
| T008 | 1 | T001 | |
| T009 | 1 | T001 | |
| T010 | 2 | T001, T002, T003, T004, T008 | Phase gate: Phase 0+1 done + 7 days on main. |
| T011 | 2 | T010 | |
| T012 | 2 | T010 | |
| T013 | 3 | T001 | Multi-release rollout; this task is Release A only. |
| T014 | 3 | T001 | (Corrected in v2 — was erroneously gated on T013.) |
| T015 | 3 | T003 | Phase B (column drops) is a separate follow-up task after 14-day burn-in. |
| T016 | 4 | T001 | |
| T017 | 4 | T001 | Per-region best-effort; see task note. |
| T018 | 4 | — | Can ship any time. |
| T019 | 5 | T001, T010, T016 | Shares T010's queue budget. |
| T020 | 5 | T010, T011, T013, T014 | Docs only. |

### Picking order at a glance

Given the Phase gate + `requires:` rules, the expected picking order is roughly:

**Phase 0:** T001 → T002, T003, T004 (any order after T001).
**Phase 1:** T005, T006, T007, T008, T009 (parallel-eligible; T006 additionally waits on T002).
**[Phase gate: 7 days on main]**
**Phase 2:** T010 → T011, T012.
**Phase 3:** T013 (Release A), T014, T015 (Phase A) — parallel-eligible.
**Phase 4:** T016, T017, T018 — parallel-eligible.
**Phase 5:** T019, T020.

Claude Code: if every eligible task in the current phase is `done` or `blocked`, check whether the Phase gate for the next phase is satisfied; if yes, proceed. If no, stop and wait.

## Appendix B — v2 changelog

v2 addresses findings from the v1 review:

- Renamed field `blocks:` → `requires:` throughout; intent is "this task needs X before it can start." Prior naming was ambiguous and invited misordering.
- Added Phase gate: later phases wait ≥ 7 days after prior phase is fully done.
- Migration numbers are now allocated at PR time via `ls migrations/ | tail -1` + 1, not hardcoded in task bodies.
- T004 scope clarified: it is pre-T010 semantics only; T010 explicitly updates response shape and test naming.
- T010 scope explicitly removes the T006-era KV-counter HTTP-path increment (prevents double-counting) and updates the response shape.
- T012 adds `COHRINT_SPOOL_DIR` env var override and in-memory fallback for read-only filesystems (Lambda etc.).
- T013 write-order is explicit: R2 first (fail loud), then D1 with both columns. Multi-release rollout spelled out. Reconciliation cron added.
- T014 dependency corrected from T013 → T001.
- T015 adds phase_b_gate + explicit guidebook §3 cleanup.
- T017 acknowledges per-region best-effort consistency; primary state is in-memory, KV is a convergence hint.
- T019 shares T010's queue budget via a discriminator instead of creating a new queue.
- Phase 6 deferred list expanded with `TOKEN_ENCRYPTION_SECRET` rotation and `vnt_*` deprecation.
- Appendix A ordering "graph" replaced with a table + picking order narrative.
