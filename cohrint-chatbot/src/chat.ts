import type { Context } from "hono";
import type { Env, ChatRequest, ChatResponse } from "./types";
import { lookup } from "./knowledge";
import { buildSystemPrompt } from "./prompt";
import { sanitize } from "./sanitize";
import { checkRateLimit } from "./ratelimit";
// randomUUID is available as a global in the Workers runtime

/** Resolve the org's actual plan from the Cohrint session API.
 *  Falls back to "free" on any error so the chat remains usable. */
async function resolveOrgPlan(token: string | undefined, env: Env): Promise<string> {
  if (!token || !env.COHRINT_API_URL) return "free";
  const cacheKey = `plan:${token.slice(-16)}`;
  const cached = await env.COHRINT_KV.get(cacheKey);
  if (cached) return cached;
  try {
    const res = await fetch(`${env.COHRINT_API_URL}/v1/auth/session`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return "free";
    const data = await res.json() as { plan?: string };
    const plan = data.plan ?? "free";
    // Cache for 5 minutes to avoid per-request latency
    await env.COHRINT_KV.put(cacheKey, plan, { expirationTtl: 300 });
    return plan;
  } catch {
    return "free";
  }
}

export async function handleChat(c: Context<{ Bindings: Env }>): Promise<Response> {
  const orgId = c.req.header("X-Org-Id") ?? "anonymous";
  const token = c.req.header("Authorization")?.replace(/^Bearer\s+/i, "");

  // Resolve plan server-side — never trust the X-Plan caller header for gating
  const plan = await resolveOrgPlan(token, c.env);

  const { allowed, remaining } = await checkRateLimit(orgId, c.env);
  if (!allowed) {
    return c.json({ error: "Rate limit exceeded. Try again in an hour." }, 429);
  }

  let body: ChatRequest;
  try {
    body = await c.req.json<ChatRequest>();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const { message, history = [] } = body;
  if (!message || typeof message !== "string" || message.trim().length === 0) {
    return c.json({ error: "message is required" }, 400);
  }

  const knowledgeEntries = await lookup(message, plan, c.env);
  const systemPrompt = buildSystemPrompt(knowledgeEntries, plan);

  const messages: Array<{ role: string; content: string }> = [
    { role: "system", content: systemPrompt },
    ...history.slice(-6),
    { role: "user", content: message.slice(0, 1000) },
  ];

  let aiReply: string;
  try {
    const result = await c.env.AI.run("@cf/meta/llama-3-8b-instruct", { messages }) as { response?: string };
    aiReply = sanitize(result.response ?? "I'm sorry, I couldn't generate a response right now.");
  } catch {
    aiReply = "I'm having trouble connecting right now. Please try again shortly.";
  }

  const response: ChatResponse = {
    reply: aiReply,
    session_id: body.session_id ?? crypto.randomUUID(),
    plan_limited: remaining < 3,
  };

  return c.json(response, 200);
}
