-- Extend audit_events with event_type for category filtering
-- (table created in 0003_audit_events.sql)
ALTER TABLE audit_events ADD COLUMN event_type TEXT NOT NULL DEFAULT 'admin_action';

CREATE INDEX IF NOT EXISTS idx_audit_event_type
  ON audit_events(org_id, event_type, created_at DESC);
