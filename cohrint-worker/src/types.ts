// ─────────────────────────────────────────────────────────────────────────────
// Shared types for the Cohrint Worker
// ─────────────────────────────────────────────────────────────────────────────

export type Bindings = {
  // Cloudflare bindings
  DB:  D1Database;
  KV:  KVNamespace;
  AI:  Ai;
  VECTORIZE: VectorizeIndex;
  METRICS?: AnalyticsEngineDataset;
  INGEST_QUEUE?: Queue;  // Cloudflare Queue for async event ingest (T010)
  INGEST_DLQ?:   Queue;  // Dead-letter queue for failed ingest messages
  CACHE_BUCKET?: R2Bucket; // R2 for semantic cache responses + audit logs (T013/T014)
  // Env vars
  ENVIRONMENT:         string;
  ALLOWED_ORIGINS:     string;
  RATE_LIMIT_RPM:      string;
  // Optional — set via: wrangler secret put RESEND_API_KEY
  RESEND_API_KEY?:     string;
  FROM_EMAIL?:         string;   // defaults to noreply@cohrint.com
  // Superadmin — set via: wrangler secret put SUPERADMIN_SECRET
  SUPERADMIN_SECRET?:  string;
  // CI bypass for signup rate limiting — set via: wrangler secret put COHRINT_CI_SECRET
  COHRINT_CI_SECRET?:  string;
  VANTAGE_CI_SECRET?:  string;  // legacy alias — prefer COHRINT_CI_SECRET
  // AES-256-GCM key material for Copilot PAT encryption — set via: wrangler secret put TOKEN_ENCRYPTION_SECRET
  TOKEN_ENCRYPTION_SECRET?: string;
  // Demo viewer key used by the Live Demo button — set via: wrangler secret put DEMO_API_KEY
  // Never exposed to the client; /v1/auth/demo reads this server-side.
  DEMO_API_KEY?:       string;
  // Upstash Redis — rate limiting (replaces KV writes)
  // Set via: wrangler secret put UPSTASH_REDIS_REST_URL
  //          wrangler secret put UPSTASH_REDIS_REST_TOKEN
  UPSTASH_REDIS_REST_URL?:   string;
  UPSTASH_REDIS_REST_TOKEN?: string;
};

export type AccountType = 'individual' | 'team' | 'organization';

export type OrgRole = 'owner' | 'superadmin' | 'ceo' | 'admin' | 'member' | 'viewer';

export type Variables = {
  requestId:   string;        // UUID injected by corsMiddleware; echoed as X-Request-Id
  orgId:       string;
  role:        OrgRole;       // role hierarchy: owner > superadmin > ceo > admin > member > viewer
  accountType: AccountType;   // individual | team | organization
  scopeTeam:   string | null; // legacy free-text team scope
  teamId:      string | null; // canonical FK to teams table (org accounts only)
  memberId:    string | null; // null when using the org owner key
  memberEmail: string | null; // actual member email; null for owner key
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
  prompt_hash?:       string;
  cache_hit?:         number;
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
