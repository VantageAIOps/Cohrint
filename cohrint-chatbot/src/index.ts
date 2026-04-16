import { Hono } from "hono";
import { cors } from "hono/cors";
import type { Env } from "./types";
import { handleChat } from "./chat";
import { handleTicket } from "./ticket";

const app = new Hono<{ Bindings: Env }>();

app.use("*", cors({
  origin: (origin) =>
    origin === "https://cohrint.com" || /^http:\/\/localhost(:\d+)?$/.test(origin)
      ? origin
      : null,
}));

app.get("/health", (c) => c.json({ status: "ok", name: "vega" }));
app.post("/chat", handleChat);
app.post("/ticket", handleTicket);

export default app;
