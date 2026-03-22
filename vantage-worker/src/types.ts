// ─────────────────────────────────────────────────────────────────────────────
// Shared types for the Vantage Worker
// ─────────────────────────────────────────────────────────────────────────────

export type Bindings = {
  // Cloudflare bindings
  DB:  D1Database;
  KV:  KVNamespace;
  // Env vars
  ENVIRONMENT:         string;
  ALLOWED_ORIGINS:     string;
  RATE_LIMIT_RPM:      string;
  // Optional — set via: wrangler secret put RESEND_API_KEY
  RESEND_API_KEY?:     string;
  FROM_EMAIL?:         string;   // defaults to noreply@vantageaiops.com
  // Superadmin — set via: wrangler secret put SUPERADMIN_SECRET
  SUPERADMIN_SECRET?:  string;
};

export type Variables = {
  orgId:     string;
  role:      string;        // 'owner' | 'admin' | 'member' | 'viewer'
  scopeTeam: string | null; // null = see all; 'backend' = scoped to that team
  memberId:  string | null; // null when using the org owner key
};

// Inbound event from SDK
export interface EventIn {
  event_id:           string;
  provider:           string;
  model:              string;
  prompt_tokens?:     number;
  completion_tokens?: number;
  cache_tokens?:      number;
  total_tokens?:      number;
  total_cost_usd?:    number;   // preferred field name
  cost_total_usd?:    number;   // legacy alias
  latency_ms?:        number;
  team?:              string;
  project?:           string;
  user_id?:           string;
  feature?:           string;
  endpoint?:          string;
  environment?:       string;
  is_streaming?:      boolean;
  stream_chunks?:     number;
  trace_id?:          string;
  parent_event_id?:   string;
  agent_name?:        string;
  span_depth?:        number;
  tags?:              Record<string, string>;
  sdk_language?:      string;
  sdk_version?:       string;
  timestamp?:         string;
}

export interface BatchIn {
  events:       EventIn[];
  sdk_version?: string;
  sdk_language?: string;
}

export interface KpiRow {
  total_cost_usd:     number;
  total_tokens:       number;
  total_requests:     number;
  avg_latency_ms:     number;
  today_cost_usd:     number;
  mtd_cost_usd:       number;
}

export interface TimeseriesRow {
  date:         string;
  cost_usd:     number;
  tokens:       number;
  requests:     number;
}
