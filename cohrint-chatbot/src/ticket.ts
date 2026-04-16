import type { Context } from "hono";
import type { Env, TicketRequest } from "./types";

export async function handleTicket(c: Context<{ Bindings: Env }>): Promise<Response> {
  let body: TicketRequest;
  try {
    body = await c.req.json<TicketRequest>();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const { subject, body: msgBody, email } = body;
  if (!subject || !msgBody || !email) {
    return c.json({ error: "subject, body, and email are required" }, 400);
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return c.json({ error: "Invalid email address" }, 400);
  }

  const orgId = c.req.header("X-Org-Id") ?? "unknown";

  try {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${c.env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: c.env.RESEND_FROM,
        to: [c.env.SUPPORT_EMAIL],
        reply_to: email,
        subject: `[Support] ${subject}`,
        text: `Org: ${orgId}\nFrom: ${email}\n\n${msgBody}`,
      }),
    });

    if (!res.ok) {
      return c.json({ ok: false, error: "Email service unavailable" }, 503);
    }
    return c.json({ ok: true });
  } catch {
    return c.json({ ok: false, error: "Email service unavailable" }, 503);
  }
}
