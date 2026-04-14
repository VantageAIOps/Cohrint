-- Migration: benchmark snapshot tables for anonymized cross-company intelligence
-- Supports opt-in only (benchmark_opt_in added in 0008).
-- No org data stored in snapshots — cohort buckets only.
-- k-anonymity floor: never publish cohorts with sample_size < 5.

CREATE TABLE IF NOT EXISTS benchmark_cohorts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  size_band  TEXT    NOT NULL CHECK (size_band IN ('1-10', '11-50', '51-200', '201-1000', '1000+')),
  industry   TEXT    NOT NULL CHECK (industry IN ('tech', 'finance', 'healthcare', 'other')),
  created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmark_cohorts_band_industry
  ON benchmark_cohorts (size_band, industry);

-- Quarterly aggregates per cohort per metric.
-- quarter format: YYYY-Q1 | YYYY-Q2 | YYYY-Q3 | YYYY-Q4
-- p25/p50/p75/p90 are REAL to preserve sub-cent precision (e.g. cost/token).
-- sample_size tracks how many distinct orgs contributed — never expose if < 5.
CREATE TABLE IF NOT EXISTS benchmark_snapshots (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  cohort_id   INTEGER NOT NULL REFERENCES benchmark_cohorts (id) ON DELETE CASCADE,
  quarter     TEXT    NOT NULL,  -- e.g. '2026-Q1'
  metric_name TEXT    NOT NULL,  -- e.g. 'cost_per_token', 'cost_per_dev_month', 'cache_hit_rate'
  model       TEXT,              -- NULL means metric is model-agnostic
  p25         REAL    NOT NULL DEFAULT 0,
  p50         REAL    NOT NULL DEFAULT 0,
  p75         REAL    NOT NULL DEFAULT 0,
  p90         REAL    NOT NULL DEFAULT 0,
  sample_size INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmark_snapshots_cohort_quarter_metric_model
  ON benchmark_snapshots (cohort_id, quarter, metric_name, COALESCE(model, ''));

CREATE INDEX IF NOT EXISTS idx_benchmark_snapshots_quarter
  ON benchmark_snapshots (quarter);

CREATE INDEX IF NOT EXISTS idx_benchmark_snapshots_metric_model
  ON benchmark_snapshots (metric_name, model);

-- Tracks which orgs contributed to which snapshot for deduplication.
-- Deliberately separate from snapshots — org_id never leaks into aggregate tables.
CREATE TABLE IF NOT EXISTS benchmark_contributions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  org_id         TEXT    NOT NULL,
  snapshot_id    INTEGER NOT NULL REFERENCES benchmark_snapshots (id) ON DELETE CASCADE,
  contributed_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_benchmark_contributions_org_snapshot
  ON benchmark_contributions (org_id, snapshot_id);

CREATE INDEX IF NOT EXISTS idx_benchmark_contributions_snapshot
  ON benchmark_contributions (snapshot_id);

CREATE INDEX IF NOT EXISTS idx_benchmark_contributions_org
  ON benchmark_contributions (org_id);
