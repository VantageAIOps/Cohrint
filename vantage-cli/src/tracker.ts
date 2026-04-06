import { randomUUID } from "node:crypto";
import { bus } from "./event-bus.js";
import { calculateCost } from "./pricing.js";
import { countTokens } from "./optimizer.js";
import { getAgent } from "./agents/registry.js";

export interface TrackerConfig {
  apiKey: string;
  apiBase: string;
  batchSize: number;
  flushInterval: number;
  privacy: "full" | "strict" | "anonymized" | "local-only";
  debug: boolean;
}

interface DashboardEvent {
  event_id: string;
  provider: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost_usd: number;
  latency_ms: number;
  environment: string;
  agent_name: string;
  team: string;
}

export class Tracker {
  private queue: DashboardEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private config: TrackerConfig;
  private sentIds = new Set<string>();
  private exitRegistered = false;
  private lastSavedTokens = 0;
  private lastPromptText = "";

  constructor(config: TrackerConfig) {
    this.config = config;
    this.setupListeners();
  }

  private resolveProvider(agent: string): string {
    const map: Record<string, string> = {
      claude: "anthropic",
      codex: "openai",
      gemini: "google",
      aider: "anthropic",
      chatgpt: "openai",
    };
    return map[agent] || "other";
  }

  private setupListeners(): void {
    bus.on("prompt:optimized", (data) => {
      this.lastSavedTokens = data.savedTokens;
    });

    bus.on("prompt:submitted", (data) => {
      this.lastPromptText = data.prompt;
    });

    bus.on("agent:completed", (data) => {
      const agent = getAgent(data.agent);
      const model = agent?.defaultModel ?? "unknown";
      const outputTokens = countTokens(data.outputText);
      // Use actual prompt text for input tokens when available
      const inputTokens = this.lastPromptText
        ? countTokens(this.lastPromptText)
        : Math.ceil(outputTokens * 0.25); // Fallback: ~25% of output (more realistic)
      this.lastPromptText = "";
      const costUsd = calculateCost(model, inputTokens, outputTokens);

      // Calculate saved cost from optimization
      const savedTokens = this.lastSavedTokens;
      this.lastSavedTokens = 0; // reset for next prompt
      const savedCost = savedTokens > 0 ? calculateCost(model, savedTokens, 0) : 0;

      bus.emit("cost:calculated", {
        agent: data.agent,
        model,
        inputTokens,
        outputTokens,
        costUsd,
        savedUsd: savedCost,
      });

      const event: DashboardEvent = {
        event_id: randomUUID(),
        provider: this.resolveProvider(data.agent),
        model,
        prompt_tokens: inputTokens,
        completion_tokens: outputTokens,
        total_tokens: inputTokens + outputTokens,
        total_cost_usd: costUsd,
        latency_ms: data.durationMs,
        environment: "production",
        agent_name: data.agent,
        team: "",
      };

      this.enqueue(event);
    });
  }

  enqueue(event: DashboardEvent): void {
    if (this.config.privacy === "local-only") return;

    if (this.config.privacy === "strict" || this.config.privacy === "anonymized") {
      // Strip identifying info — keep only numeric metrics
      event.agent_name = "anonymous";
      event.team = "";
    }

    // Deduplication guard
    const eventKey = event.event_id;
    if (this.sentIds.has(eventKey)) return;
    this.sentIds.add(eventKey);
    // Cap dedup set to prevent memory leak in long sessions
    if (this.sentIds.size > 10000) {
      const arr = Array.from(this.sentIds);
      this.sentIds = new Set(arr.slice(-5000));
    }

    this.queue.push(event);

    if (this.queue.length >= this.config.batchSize) {
      this.flush().catch(() => {});
    }
  }

  async flush(): Promise<void> {
    if (this.queue.length === 0) return;
    if (!this.config.apiKey) return;

    if (this.config.apiBase && !this.config.apiBase.startsWith("https://")) {
      if (this.config.debug) console.warn("[vantage] Skipping tracking: API base is not HTTPS");
      return;
    }

    const batch = this.queue.splice(0, this.queue.length);
    const base = this.config.apiBase || "https://api.vantageaiops.com";
    const url = `${base}/v1/events/batch`;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({
          events: batch,
          sdk_version: "vantage-cli-1.0.0",
          sdk_language: "typescript",
        }),
        signal: AbortSignal.timeout(15000),
      });

      bus.emit("cost:reported", { success: response.ok });

      if (!response.ok) {
        // Never log response body — could contain echoed credentials
        console.error(`  [vantage] Dashboard sync failed: HTTP ${response.status}`);
        // Re-queue events so they're not lost on server-side errors
        const unsent = batch.filter((e) => !this.sentIds.has(e.event_id));
        this.queue.unshift(...unsent);
      }
    } catch (err) {
      bus.emit("cost:reported", { success: false });
      if (this.config.debug) {
        console.error("[vantage] Failed to send events:", err);
      }
      // Re-queue failed events (skip any already confirmed sent)
      const unsent = batch.filter((e) => {
        const key = e.event_id;
        return !this.sentIds.has(key);
      });
      this.queue.unshift(...unsent);
    }
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      this.flush().catch(() => {});
    }, this.config.flushInterval);

    // Ensure final flush on exit — register only once
    if (!this.exitRegistered) {
      this.exitRegistered = true;
      process.on("beforeExit", () => this.flush().catch(() => {}));
      process.on("SIGTERM", () => { this.flush().catch(() => {}); process.exit(0); });
      process.on("SIGINT", () => { this.flush().catch(() => {}); process.exit(0); });
    }
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
