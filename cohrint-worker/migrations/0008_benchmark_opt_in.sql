-- Migration: add benchmark_opt_in to orgs
-- Opt-in flag for anonymized cross-company benchmark data sharing.
-- 0 = opted out (default), 1 = opted in.
ALTER TABLE orgs ADD COLUMN benchmark_opt_in INTEGER NOT NULL DEFAULT 0;
