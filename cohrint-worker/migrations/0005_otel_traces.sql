-- otel_traces: span-level debugging for GenAI agent traces
-- Populated by POST /v1/otel/v1/traces (OTLP HTTP/JSON)

CREATE TABLE IF NOT EXISTS otel_traces (
  id               TEXT PRIMARY KEY,
  org_id           TEXT NOT NULL,
  trace_id         TEXT,
  span_id          TEXT,
  parent_span_id   TEXT,
  operation_name   TEXT,
  start_time_ms    INTEGER,
  end_time_ms      INTEGER,
  duration_ms      INTEGER,
  status           TEXT DEFAULT 'ok',
  attributes       TEXT DEFAULT '[]',
  created_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_otel_traces_org_trace   ON otel_traces(org_id, trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_traces_org_created ON otel_traces(org_id, created_at);
