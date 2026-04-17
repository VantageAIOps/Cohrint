export interface Env {
  AI: Ai;
  VEGA_KV: KVNamespace;
  RESEND_API_KEY: string;
  RESEND_FROM: string;
  SUPPORT_EMAIL: string;
  COHRINT_API_URL: string;
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  plan_limited?: boolean;
}

export interface KnowledgeEntry {
  q: string;
  a: string;
  tags: string[];
  plan_gate?: "pro" | "enterprise";
}

export interface TicketRequest {
  subject: string;
  body: string;
  email: string;
}
