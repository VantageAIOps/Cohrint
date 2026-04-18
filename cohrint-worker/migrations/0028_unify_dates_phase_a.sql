-- T015 Phase A: Add created_at_unix INTEGER columns to TEXT-date tables.
-- Writes still go to old created_at column for rollback safety.
-- Phase B (separate PR, 14-day burn-in after Phase A) will drop old columns.

ALTER TABLE cross_platform_usage   ADD COLUMN created_at_unix INTEGER;
ALTER TABLE otel_events             ADD COLUMN created_at_unix INTEGER;
ALTER TABLE benchmark_snapshots     ADD COLUMN created_at_unix INTEGER;
ALTER TABLE copilot_connections     ADD COLUMN created_at_unix INTEGER;
ALTER TABLE datadog_connections     ADD COLUMN created_at_unix INTEGER;
ALTER TABLE prompts                 ADD COLUMN created_at_unix INTEGER;
ALTER TABLE prompt_versions         ADD COLUMN created_at_unix INTEGER;
ALTER TABLE prompt_usage            ADD COLUMN created_at_unix INTEGER;
ALTER TABLE semantic_cache_entries  ADD COLUMN created_at_unix INTEGER;
ALTER TABLE org_cache_config        ADD COLUMN created_at_unix INTEGER;

-- Backfill from TEXT column using strftime('%s', ...)
UPDATE cross_platform_usage   SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE otel_events             SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE benchmark_snapshots     SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE copilot_connections     SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE datadog_connections     SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE prompts                 SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE prompt_versions         SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE prompt_usage            SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE semantic_cache_entries  SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
UPDATE org_cache_config        SET created_at_unix = CAST(strftime('%s', created_at) AS INTEGER) WHERE created_at_unix IS NULL;
