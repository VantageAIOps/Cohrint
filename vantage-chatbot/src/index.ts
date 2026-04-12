import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env } from "./types";

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors({ origin: ["https://vantageaiops.com", "http://localhost:*"] }));

app.get("/health", (c) => c.json({ status: "ok", name: "vega" }));

// Placeholder routes — filled in Task 5
app.post("/chat", async (c) => c.json({ reply: "coming soon" }, 501));
app.post("/ticket", async (c) => c.json({ ok: false }, 501));

export default app;
