import type { Context } from "hono";
import type { Env, ChatRequest, ChatResponse } from "./types";
import { lookup } from "./knowledge";
import { buildSystemPrompt } from "./prompt";
import { sanitize } from "./sanitize";
import { checkRateLimit } from "./ratelimit";
// randomUUID is available as a global in the Workers runtime

export async function handleChat(c: Context<{ Bindings: Env }>): Promise<Response> {
  const orgId = c.req.header("X-Org-Id") ?? "anonymous";
  const plan = c.req.header("X-Plan") ?? "free";

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
