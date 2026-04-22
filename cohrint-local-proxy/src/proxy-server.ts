/**
 * Local Proxy Server — runs on the client's machine.
 * Uses ONLY Node.js built-in modules — zero npm dependencies.
 *
 * ARCHITECTURE:
 *   Client App → localhost:4891 → Real LLM API (OpenAI/Anthropic/Google)
 *                     ↓
 *           Extract stats locally
 *                     ↓
 *           Strip ALL sensitive data
 *                     ↓
 *           Send ONLY stats → api.cohrint.com
 *
 * The client's API key and prompts NEVER leave their machine.
 * Only anonymized numbers (tokens, cost, latency) are forwarded.
 */

import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { randomUUID } from "node:crypto";
import { VERSION } from "./_version.js";
import { sanitizeEvent, PrivacyConfig, DEFAULT_PRIVACY } from "./privacy.js";
import { calculateCost, findCheapest } from "./pricing.js";
import { scanAll } from "./scanners/index.js";
import type { ToolName } from "./scanners/types.js";
import { SessionStore, ProxySessionRecord, PersistedEvent } from "./session-store.js";
import { classifyIntent } from "./intent-classifier.js";
import { routingDecision } from "./routing-config.js";

// ── Types ────────────────────────────────────────────────────────────────────

export interface LocalProxyConfig {
  /** Port to listen on (default: 4891) */
  port?: number;

  /** Cohrint API key for sending stats (crt_... or vnt_...) */
  apiKey: string;

  /** Cohrint ingest endpoint (default: https://api.cohrint.com) */
  apiBase?: string;

  /** Privacy configuration */
  privacy?: PrivacyConfig;

  /** Team tag for all events from this proxy */
  team?: string;

  /** Environment tag */
  environment?: string;

  /** Enable debug logging to stderr */
  debug?: boolean;

  /** Batch size before flushing stats (default: 20) */
  batchSize?: number;

  /** Flush interval in ms (default: 5000) */
  flushInterval?: number;

  /** Resume an existing session by ID instead of creating a new one */
  resumeSessionId?: string;

  /** Use a specific session ID (e.g. to link to a vantage-agent session) */
  sessionId?: string;
}

interface PendingStat {
  event: Record<string, unknown>;
  timestamp: number;
}

// ── LLM Provider Endpoints ───────────────────────────────────────────────────

const PROVIDER_ENDPOINTS: Record<string, string> = {
  openai: "https://api.openai.com",
  anthropic: "https://api.anthropic.com",
  google: "https://generativelanguage.googleapis.com",
  mistral: "https://api.mistral.ai",
  cohere: "https://api.cohere.ai",
  deepseek: "https://api.deepseek.com",
  groq: "https://api.groq.com/openai",
};

// ── Stats Queue ──────────────────────────────────────────────────────────────

class StatsQueue {
  private queue: PendingStat[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  readonly sessionStore: SessionStore;
  private currentSession: ProxySessionRecord;

  constructor(
    private readonly apiKey: string,
    private readonly apiBase: string,
    private readonly batchSize: number,
    private readonly flushInterval: number,
    private readonly privacy: PrivacyConfig,
    private readonly debug: boolean,
    orgId: string,
    team: string,
    environment: string,
    resumeSessionId?: string,
    fixedSessionId?: string,
  ) {
    this.sessionStore = new SessionStore();
    const now = new Date().toISOString();

    if (resumeSessionId) {
      const existing = this.sessionStore.loadSync(resumeSessionId);
      if (existing) {
        if (this.debug) process.stderr.write(`[cohrint-proxy] Resumed session ${resumeSessionId}\n`);
        this.currentSession = existing;
      } else {
        process.stderr.write(`[cohrint-proxy] WARN: session ${resumeSessionId} not found — starting new session\n`);
        this.currentSession = this._newSession(fixedSessionId ?? randomUUID(), orgId, team, environment, now);
      }
    } else {
      this.currentSession = this._newSession(fixedSessionId ?? randomUUID(), orgId, team, environment, now);
    }
  }

  private _newSession(
    id: string,
    orgId: string,
    team: string,
    environment: string,
    now: string,
  ): ProxySessionRecord {
    return {
      id,
      source: "local-proxy",
      created_at: now,
      last_active_at: now,
      org_id: orgId,
      team,
      environment,
      events: [],
      cost_summary: {
        total_cost_usd: 0,
        total_input_tokens: 0,
        total_completion_tokens: 0,
        event_count: 0,
      },
    };
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => this.flush(), this.flushInterval);
    process.on("beforeExit", () => this.flush());
  }

  async stop(): Promise<void> {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    this.flush();
    await this.sessionStore.save(this.currentSession);
  }

  enqueue(raw: Record<string, unknown>): void {
    const sanitized = sanitizeEvent(raw, this.privacy);
    this.queue.push({ event: sanitized as unknown as Record<string, unknown>, timestamp: Date.now() });
    if (this.debug) {
      process.stderr.write(`[cohrint-proxy] Queued: ${sanitized.model} ${sanitized.prompt_tokens}→${sanitized.completion_tokens} tokens $${sanitized.cost_total_usd.toFixed(4)}\n`);
    }

    // Persist to session
    const persistedEvent: PersistedEvent = {
      event_id: randomUUID(),
      timestamp: Date.now(),
      provider: String(sanitized.provider ?? ""),
      model: String(sanitized.model ?? ""),
      endpoint: String(sanitized.endpoint ?? ""),
      team: String(sanitized.team ?? ""),
      prompt_tokens: Number(sanitized.prompt_tokens ?? 0),
      completion_tokens: Number(sanitized.completion_tokens ?? 0),
      total_tokens: Number(sanitized.total_tokens ?? 0),
      cost_total_usd: Number(sanitized.cost_total_usd ?? 0),
      latency_ms: Number(sanitized.latency_ms ?? 0),
      status_code: Number(sanitized.status_code ?? 0),
      error: sanitized.error !== undefined ? String(sanitized.error) : undefined,
      source: "local-proxy",
    };
    this.currentSession.events.push(persistedEvent);
    this.currentSession.cost_summary.total_cost_usd += persistedEvent.cost_total_usd;
    this.currentSession.cost_summary.total_input_tokens += persistedEvent.prompt_tokens;
    this.currentSession.cost_summary.total_completion_tokens += persistedEvent.completion_tokens;
    this.currentSession.cost_summary.event_count += 1;
    this.sessionStore.save(this.currentSession).catch(() => {});

    if (this.queue.length >= this.batchSize) this.flush();
  }

  flush(): void {
    if (this.queue.length === 0) return;
    const batch = this.queue.splice(0, this.batchSize);
    this._send(batch.map((s) => s.event)).catch((err) => {
      if (this.debug) process.stderr.write(`[cohrint-proxy] Flush error: ${err}\n`);
      // Re-queue on failure so stats aren't permanently lost
      this.queue.unshift(...batch);
    });
  }

  private async _send(events: Record<string, unknown>[]): Promise<void> {
    const body = JSON.stringify({
      events,
      sdk_version: VERSION,
      sdk_language: "local-proxy",
    });
    try {
      const res = await fetch(`${this.apiBase}/v1/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        body,
      });
      // Accept 201 (sync created) and 202 (async queued via INGEST_QUEUE) as success
      if (!res.ok && res.status !== 202) throw new Error(`HTTP ${res.status}`);
      if (this.debug) {
        process.stderr.write(`[cohrint-proxy] Sent ${events.length} stats → ${res.status}\n`);
      }
    } catch (err) {
      if (this.debug) process.stderr.write(`[cohrint-proxy] Send failed: ${err}\n`);
      throw err; // re-throw so flush() re-queues the batch
    }
  }
}

// ── Extract Stats from LLM Responses ─────────────────────────────────────────

function extractOpenAIStats(
  reqBody: Record<string, unknown>,
  resBody: Record<string, unknown>,
  latencyMs: number,
  statusCode: number,
): Record<string, unknown> {
  const model = String(resBody.model ?? reqBody.model ?? "unknown");
  const usage = resBody.usage as Record<string, number> | undefined;
  const promptTokens = usage?.prompt_tokens ?? 0;
  const completionTokens = usage?.completion_tokens ?? 0;
  const cachedTokens = usage?.cached_tokens ?? 0;
  const { inputCostUsd, outputCostUsd, totalCostUsd } = calculateCost(model, promptTokens, completionTokens, cachedTokens);
  const cheapest = findCheapest(model, promptTokens, completionTokens);

  return {
    provider: "openai", model, endpoint: "/chat/completions",
    prompt_tokens: promptTokens, completion_tokens: completionTokens,
    total_tokens: promptTokens + completionTokens, cache_tokens: cachedTokens,
    latency_ms: Math.round(latencyMs), status_code: statusCode,
    cost_input_usd: inputCostUsd, cost_output_usd: outputCostUsd, cost_total_usd: totalCostUsd,
    cheapest_model: cheapest?.model ?? "", cheapest_cost_usd: cheapest?.costUsd ?? 0,
    potential_saving_usd: cheapest ? Math.max(0, totalCostUsd - cheapest.costUsd) : 0,
  };
}

function extractAnthropicStats(
  reqBody: Record<string, unknown>,
  resBody: Record<string, unknown>,
  latencyMs: number,
  statusCode: number,
): Record<string, unknown> {
  const model = String(resBody.model ?? reqBody.model ?? "unknown");
  const usage = resBody.usage as Record<string, number> | undefined;
  const promptTokens = usage?.input_tokens ?? 0;
  const completionTokens = usage?.output_tokens ?? 0;
  const cachedTokens = usage?.cache_read_input_tokens ?? 0;
  const { inputCostUsd, outputCostUsd, totalCostUsd } = calculateCost(model, promptTokens, completionTokens, cachedTokens);
  const cheapest = findCheapest(model, promptTokens, completionTokens);

  return {
    provider: "anthropic", model, endpoint: "/messages",
    prompt_tokens: promptTokens, completion_tokens: completionTokens,
    total_tokens: promptTokens + completionTokens, cache_tokens: cachedTokens,
    latency_ms: Math.round(latencyMs), status_code: statusCode,
    cost_input_usd: inputCostUsd, cost_output_usd: outputCostUsd, cost_total_usd: totalCostUsd,
    cheapest_model: cheapest?.model ?? "", cheapest_cost_usd: cheapest?.costUsd ?? 0,
    potential_saving_usd: cheapest ? Math.max(0, totalCostUsd - cheapest.costUsd) : 0,
  };
}

// ── HTTP Helpers ─────────────────────────────────────────────────────────────

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString()));
    req.on("error", reject);
  });
}

function sendJson(res: ServerResponse, status: number, data: unknown): void {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  });
  res.end(body);
}

// ── Proxy Server ─────────────────────────────────────────────────────────────

export function startProxyServer(config: LocalProxyConfig): ReturnType<typeof createServer> {
  const {
    port = 4891,
    apiKey,
    apiBase = "https://api.cohrint.com",
    privacy = DEFAULT_PRIVACY,
    team = "",
    environment = "production",
    debug = false,
    batchSize = 20,
    flushInterval = 5000,
    resumeSessionId,
    sessionId,
  } = config;

  const orgId = apiKey.split("_")[1] ?? "default";

  const statsQueue = new StatsQueue(
    apiKey, apiBase, batchSize, flushInterval, privacy, debug,
    orgId, team, environment, resumeSessionId, sessionId,
  );
  statsQueue.start();

  const server = createServer(async (req, res) => {
    const url = req.url ?? "/";
    const method = req.method ?? "GET";

    // CORS preflight
    if (method === "OPTIONS") {
      res.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      });
      return res.end();
    }

    // ── Health check ────────────────────────────────────────────────────
    if (url === "/health" && method === "GET") {
      return sendJson(res, 200, {
        status: "ok",
        proxy: "cohrint-local-proxy",
        privacy: privacy.level,
        org: orgId,
        uptime: process.uptime(),
      });
    }

    // ── Local file scan ─────────────────────────────────────────────────
    if (url.startsWith("/scan") && method === "GET") {
      try {
        const urlObj = new URL(url, `http://localhost:${port}`);
        const tool = urlObj.searchParams.get("tool") as ToolName | null;
        const since = urlObj.searchParams.get("since") ?? undefined;
        const until = urlObj.searchParams.get("until") ?? undefined;
        const limit = urlObj.searchParams.get("limit");
        const includeMessages = urlObj.searchParams.get("messages") !== "false";

        const result = await scanAll({
          tools: tool ? [tool] : undefined,
          since,
          until,
          limit: limit ? parseInt(limit, 10) : undefined,
          includeMessages,
        });
        return sendJson(res, 200, result);
      } catch (err) {
        return sendJson(res, 500, {
          error: `Scan failed: ${err instanceof Error ? err.message : String(err)}`,
        });
      }
    }

    // ── Privacy info ────────────────────────────────────────────────────
    if (url === "/privacy" && method === "GET") {
      return sendJson(res, 200, {
        level: privacy.level,
        what_stays_local: [
          "Your LLM API keys (OpenAI, Anthropic, etc.)",
          "Your prompt text and content",
          "LLM response text and content",
          "System prompts",
          "User data in prompts",
        ],
        what_is_sent_to_cohrint: [
          "Model name (e.g., gpt-4o)",
          "Provider (e.g., openai)",
          "Token counts (prompt_tokens, completion_tokens)",
          "Calculated cost in USD",
          "Latency in milliseconds",
          "HTTP status code",
          "Team and environment tags",
          privacy.level === "standard" ? "SHA-256 prompt hash (non-reversible)" : null,
          privacy.level === "relaxed" ? "First 100 chars of prompt (NOT recommended)" : null,
        ].filter(Boolean),
        what_is_never_sent: [
          "API keys — your keys are used locally to call LLM APIs, never forwarded",
          "Full prompt or response text (in strict/standard mode)",
          "PII, user data, or business logic from your prompts",
        ],
      });
    }

    // ── Session history ─────────────────────────────────────────────────
    if (url === "/sessions" && method === "GET") {
      const sessions = await statsQueue.sessionStore.listAll();
      return sendJson(res, 200, { sessions });
    }

    if (url.startsWith("/sessions/") && method === "GET") {
      const id = url.slice("/sessions/".length);
      try {
        const session = await statsQueue.sessionStore.load(id);
        return sendJson(res, 200, session);
      } catch {
        return sendJson(res, 404, { error: `Session not found: ${id}` });
      }
    }

    // ── Determine provider from path ────────────────────────────────────
    let provider = "openai";
    let targetPath = url;

    if (url.startsWith("/v1/chat/completions")) {
      provider = "openai";
      targetPath = "/v1/chat/completions";
    } else if (url.startsWith("/v1/messages")) {
      provider = "anthropic";
      targetPath = "/v1/messages";
    } else if (url.startsWith("/proxy/")) {
      // /proxy/openai/v1/chat/completions → provider=openai, path=/v1/chat/completions
      const parts = url.split("/");
      provider = parts[2] ?? "openai";
      targetPath = "/" + parts.slice(3).join("/");
    } else {
      return sendJson(res, 404, {
        error: "Unknown endpoint. Use /v1/chat/completions (OpenAI), /v1/messages (Anthropic), or /proxy/:provider/*",
        endpoints: {
          openai: "/v1/chat/completions",
          anthropic: "/v1/messages",
          generic: "/proxy/:provider/path",
          health: "/health",
          privacy: "/privacy",
        },
      });
    }

    if (method !== "POST") {
      return sendJson(res, 405, { error: "POST required for LLM proxy endpoints" });
    }

    const targetBase = PROVIDER_ENDPOINTS[provider];
    if (!targetBase) {
      return sendJson(res, 400, {
        error: `Unknown provider: ${provider}`,
        supported: Object.keys(PROVIDER_ENDPOINTS),
      });
    }

    // ── Proxy the request ───────────────────────────────────────────────
    const t0 = performance.now();
    let reqBody: Record<string, unknown> = {};

    try {
      const rawBody = await readBody(req);
      if (rawBody) reqBody = JSON.parse(rawBody);
    } catch {
      // Non-JSON body, continue with empty
    }

    // Forward ALL headers from client (including their API key) to the real LLM API
    const forwardHeaders: Record<string, string> = {};
    for (const [key, val] of Object.entries(req.headers)) {
      if (!val) continue;
      const lower = key.toLowerCase();
      if (lower === "host" || lower === "content-length" || lower === "connection") continue;
      forwardHeaders[key] = Array.isArray(val) ? val.join(", ") : val;
    }
    forwardHeaders["Content-Type"] = "application/json";

    const isStreaming = reqBody.stream === true;

    // ── Routing with quality control ────────────────────────────────────
    const messages = (reqBody.messages as { role: string; content: string | { type: string; text?: string }[] }[] | undefined) ?? [];
    const systemPrompt = typeof reqBody.system === "string" ? reqBody.system : undefined;
    const originalModel = String(reqBody.model ?? "unknown");
    let routing = routingDecision(originalModel, classifyIntent(messages, systemPrompt));

    // Only reroute non-streaming calls (streaming routing is Stage 2)
    if (!isStreaming && routing.reason === "cost_optimization") {
      if (debug) process.stderr.write(`[cohrint-proxy] routing ${originalModel} → ${routing.routedModel} (${routing.intent})\n`);
      reqBody = { ...reqBody, model: routing.routedModel };
      // If provider changes, update targetBase
      if (routing.routedProvider !== provider) {
        provider = routing.routedProvider;
      }
    } else {
      // No routing applied — keep original
      routing = { ...routing, routedModel: originalModel, reason: "same_model" };
    }

    const didRoute = routing.routedModel !== originalModel;

    try {
      const targetUrl = `${PROVIDER_ENDPOINTS[provider] ?? targetBase}${targetPath}`;
      if (debug) process.stderr.write(`[cohrint-proxy] → ${provider} ${targetPath}\n`);

      // ── Fetch with fallback on 429 / 5xx ─────────────────────────────
      const doFetch = async (model: string, providerKey: string): Promise<{ res: Response; usedModel: string; usedProvider: string }> => {
        const fetchController = new AbortController();
        const fetchTimeout = setTimeout(() => fetchController.abort(), 5 * 60 * 1000);
        const body = { ...reqBody, model };
        try {
          const res = await fetch(`${PROVIDER_ENDPOINTS[providerKey] ?? targetBase}${targetPath}`, {
            method: "POST",
            headers: forwardHeaders,
            body: JSON.stringify(body),
            signal: fetchController.signal,
          });
          return { res, usedModel: model, usedProvider: providerKey };
        } finally {
          clearTimeout(fetchTimeout);
        }
      };

      let { res: upstreamRes, usedModel, usedProvider } = await doFetch(String(reqBody.model ?? routing.routedModel), provider);

      // Fallback: on 429 or 5xx try original model (if we rerouted) or next candidate
      if ((upstreamRes.status === 429 || upstreamRes.status >= 500) && didRoute) {
        if (debug) process.stderr.write(`[cohrint-proxy] fallback: ${upstreamRes.status} from ${usedModel}, retrying with ${originalModel}\n`);
        const fallbackProvider = routing.originalModel.startsWith("claude-") ? "anthropic"
          : routing.originalModel.startsWith("gemini-") ? "google" : "openai";
        const fallbackResult = await doFetch(originalModel, fallbackProvider);
        upstreamRes = fallbackResult.res;
        usedModel = fallbackResult.usedModel;
        usedProvider = fallbackResult.usedProvider;
        routing = { ...routing, routedModel: originalModel, reason: "same_model" };
      }

      const latencyMs = performance.now() - t0;

      if (isStreaming && upstreamRes.body) {
        // Stream pass-through — log basic stats, pipe body directly
        statsQueue.enqueue({
          provider, model: String(reqBody.model ?? "unknown"), endpoint: targetPath,
          latency_ms: Math.round(latencyMs), status_code: upstreamRes.status,
          prompt_tokens: 0, completion_tokens: 0, total_tokens: 0,
          cache_tokens: 0, cost_total_usd: 0, cost_input_usd: 0, cost_output_usd: 0,
          org_id: orgId, team, environment,
        });

        // Forward headers — strip hop-by-hop and sensitive upstream headers
        const HOP_BY_HOP = new Set([
          'transfer-encoding', 'content-length', 'connection', 'keep-alive',
          'upgrade', 'te', 'trailer', 'proxy-authorization',
          'x-ratelimit-limit-requests', 'x-ratelimit-limit-tokens',
          'x-ratelimit-remaining-requests', 'x-ratelimit-remaining-tokens',
          'x-ratelimit-reset-requests', 'x-ratelimit-reset-tokens', 'server',
        ]);
        const headers: Record<string, string> = {
          "Access-Control-Allow-Origin": "*",
        };
        upstreamRes.headers.forEach((v, k) => {
          if (!HOP_BY_HOP.has(k.toLowerCase())) headers[k] = v;
        });
        res.writeHead(upstreamRes.status, headers);

        // Pipe the stream
        const reader = upstreamRes.body.getReader();
        const pump = async () => {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) { res.end(); break; }
              res.write(value);
            }
          } catch (e) {
            // Stream interrupted — close response cleanly
            if (debug) process.stderr.write(`[cohrint-proxy] Stream interrupted: ${e}\n`);
            if (!res.writableEnded) res.end();
          } finally {
            reader.releaseLock();
          }
        };
        await pump();
        return;
      }

      // Non-streaming: read full response, extract stats, return to client
      const resBody = await upstreamRes.json() as Record<string, unknown>;

      let stats: Record<string, unknown>;
      if (usedProvider === "anthropic") {
        stats = extractAnthropicStats(reqBody, resBody, latencyMs, upstreamRes.status);
      } else {
        stats = extractOpenAIStats(reqBody, resBody, latencyMs, upstreamRes.status);
      }

      stats.org_id = orgId;
      stats.team = team;
      stats.environment = environment;

      // Attach routing metadata so the dashboard can show savings
      if (didRoute) {
        const promptTokens = typeof stats.prompt_tokens === "number" ? stats.prompt_tokens : 0;
        const completionTokens = typeof stats.completion_tokens === "number" ? stats.completion_tokens : 0;
        const { totalCostUsd: originalCost } = calculateCost(originalModel, promptTokens, completionTokens);
        const { totalCostUsd: routedCost } = calculateCost(usedModel, promptTokens, completionTokens);
        stats.tags = {
          ...((stats.tags as Record<string, unknown>) ?? {}),
          routing: {
            original_model: originalModel,
            routed_model: usedModel,
            intent: routing.intent,
            reason: routing.reason,
            savings_usd: Math.max(0, originalCost - routedCost),
          },
        };
      }

      // Quality sampling: fire-and-forget shadow call against premium model
      if (didRoute && routing.shouldSample) {
        void runQualitySample(
          routing.premiumModel,
          reqBody,
          forwardHeaders,
          targetPath,
          debug,
        );
      }

      // Queue sanitized stats (privacy engine strips all text)
      statsQueue.enqueue(stats);

      // Return FULL response to client — they get everything
      return sendJson(res, upstreamRes.status, resBody);

    } catch (err: unknown) {
      const latencyMs = performance.now() - t0;
      const errorMsg = err instanceof Error ? err.message : String(err);

      statsQueue.enqueue({
        provider, model: String(reqBody.model ?? "unknown"), endpoint: targetPath,
        latency_ms: Math.round(latencyMs), status_code: 502,
        error: errorMsg.split("\n")[0],
        prompt_tokens: 0, completion_tokens: 0, cost_total_usd: 0,
        org_id: orgId, team, environment,
      });

      return sendJson(res, 502, { error: `Proxy error: ${errorMsg}` });
    }
  });

  server.listen(port, () => {
    console.log(`
╔══════════════════════════════════════════════════════════════╗
║               Cohrint Local Proxy — RUNNING                 ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Address:  http://localhost:${String(port).padEnd(37)}║
║  Org:      ${orgId.padEnd(45)}║
║  Privacy:  ${String(privacy.level).padEnd(45)}║
║                                                              ║
║  YOUR DATA STAYS LOCAL:                                      ║
║    API keys    → never sent to Cohrint                       ║
║    Prompts     → never sent to Cohrint                       ║
║    Responses   → never sent to Cohrint                       ║
║    Stats only  → token counts, cost, latency                 ║
║                                                              ║
║  ENDPOINTS:                                                  ║
║  OpenAI:    http://localhost:${String(port).padEnd(6)}/v1/chat/completions   ║
║  Anthropic: http://localhost:${String(port).padEnd(6)}/v1/messages           ║
║  Scan:      http://localhost:${String(port).padEnd(6)}/scan                  ║
║  Health:    http://localhost:${String(port).padEnd(6)}/health                ║
║  Privacy:   http://localhost:${String(port).padEnd(6)}/privacy               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
`);
  });

  return server;
}

/**
 * Fire-and-forget shadow call against the premium model for quality sampling.
 * Result is currently discarded — future: compare outputs and log quality delta.
 */
async function runQualitySample(
  premiumModel: string,
  reqBody: Record<string, unknown>,
  headers: Record<string, string>,
  targetPath: string,
  debug: boolean,
): Promise<void> {
  const provider = premiumModel.startsWith("claude-") ? "anthropic"
    : premiumModel.startsWith("gemini-") ? "google" : "openai";
  const base: Record<string, string> = {
    openai: "https://api.openai.com",
    anthropic: "https://api.anthropic.com",
    google: "https://generativelanguage.googleapis.com",
  };

  try {
    await fetch(`${base[provider] ?? "https://api.openai.com"}${targetPath}`, {
      method: "POST",
      headers,
      body: JSON.stringify({ ...reqBody, model: premiumModel }),
      signal: AbortSignal.timeout(30_000),
    });
    if (debug) process.stderr.write(`[cohrint-proxy] quality sample sent to ${premiumModel}\n`);
  } catch {
    // Sampling is best-effort — never fail the main request path
  }
}
