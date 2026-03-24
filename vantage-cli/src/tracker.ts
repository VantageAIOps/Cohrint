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

interface TrackerEvent {
  type: string;
  agent: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  costUsd: number;
  savedUsd: number;
  durationMs: number;
  timestamp: number;
}

export class Tracker {
  private queue: TrackerEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private config: TrackerConfig;
  private sentIds = new Set<string>();
  private exitRegistered = false;

  constructor(config: TrackerConfig) {
    this.config = config;
    this.setupListeners();
  }

  private setupListeners(): void {
    bus.on("agent:completed", (data) => {
      const agent = getAgent(data.agent);
      const model = agent?.defaultModel ?? "unknown";
      const outputTokens = countTokens(data.outputText);
      // Estimate input tokens as ~10% of output for CLI wrappers
      const inputTokens = Math.ceil(outputTokens * 0.1);
      const costUsd = calculateCost(model, inputTokens, outputTokens);

      bus.emit("cost:calculated", {
        agent: data.agent,
        model,
        inputTokens,
        outputTokens,
        costUsd,
        savedUsd: 0,
      });

      this.enqueue({
        type: "agent:completed",
        agent: data.agent,
        model,
        inputTokens,
        outputTokens,
        costUsd,
        savedUsd: 0,
        durationMs: data.durationMs,
        timestamp: Date.now(),
      });
    });
  }

  enqueue(event: TrackerEvent): void {
    if (this.config.privacy === "local-only") return;

    if (this.config.privacy === "strict" || this.config.privacy === "anonymized") {
      // Strip identifying info — keep only numeric metrics
      delete (event as unknown as Record<string, unknown>).prompt;
      delete (event as unknown as Record<string, unknown>).output;
    }

    // Deduplication guard
    const eventKey = `${event.type}:${event.agent}:${event.timestamp}`;
    if (this.sentIds.has(eventKey)) return;
    this.sentIds.add(eventKey);

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
    const url = `${this.config.apiBase}/v1/events`;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.config.apiKey}`,
        },
        body: JSON.stringify({ events: batch }),
      });

      bus.emit("cost:reported", { success: response.ok });

      if (!response.ok && this.config.debug) {
        console.error(`[vantage] Failed to report events: ${response.status}`);
      }
    } catch (err) {
      bus.emit("cost:reported", { success: false });
      if (this.config.debug) {
        console.error("[vantage] Failed to send events:", err);
      }
      // Re-queue failed events (skip any already confirmed sent)
      const unsent = batch.filter((e) => {
        const key = `${e.type}:${e.agent}:${e.timestamp}`;
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
