import { randomUUID } from "crypto";
import { bus } from "./event-bus.js";
import { countTokens } from "./optimizer.js";
import { calculateCost } from "./pricing.js";
import { getAgent } from "./agents/registry.js";
import { VERSION } from "./_version.js";

export interface TrackerConfig {
  apiKey: string;
  apiBase?: string;
  batchSize: number;
  flushInterval: number;
  privacy: string;
  debug?: boolean;
}

interface TrackingEvent {
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
  session_id?: string;
}

export class Tracker {
  private queue: TrackingEvent[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;
  private config: TrackerConfig;
  private sentIds = new Set<string>(); // confirmed-delivered IDs
  private queuedIds = new Set<string>(); // IDs currently in the send queue
  private exitRegistered = false;
  // Queue of submitted prompt texts — consumed FIFO on agent:completed.
  // Using a queue (not a scalar) handles session mode where N prompts are
  // submitted before a single agent:completed fires at session end.
  private promptTexts: string[] = [];
  // Accumulated optimization savings since the last agent:completed.
  // Scalar lastSavedTokens only captured the last prompt's savings;
  // in session mode all intermediate prompts' savings were dropped.
  private pendingSavedTokens = 0;

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
      this.pendingSavedTokens += data.savedTokens;
    });

    bus.on("prompt:submitted", (data) => {
      this.promptTexts.push(data.prompt);
    });

    bus.on("agent:completed", (data) => {
      const agent = getAgent(data.agent);
      if (!agent && this.config?.debug) {
        console.warn(`[vantage] Unknown agent: ${data.agent} — skipping cost calculation`);
      }
      const model = agent?.defaultModel ?? "unknown";
      const outputTokens = countTokens(data.outputText);

      if (outputTokens === 0 && data.exitCode !== 0) {
        this.promptTexts = [];
        this.pendingSavedTokens = 0;
        return;
      }

      const inputTokens =
        this.promptTexts.length > 0
          ? this.promptTexts.reduce((sum, t) => sum + countTokens(t), 0)
          : Math.ceil(outputTokens * 0.25);
      this.promptTexts = [];

      const costUsd = calculateCost(model, inputTokens, outputTokens);
      const savedTokens = this.pendingSavedTokens;
      this.pendingSavedTokens = 0;
      const savedCost = savedTokens > 0 ? calculateCost(model, savedTokens, 0) : 0;

      const sessionId = data.sessionId;

      bus.emit("cost:calculated", {
        agent: data.agent,
        model,
        inputTokens,
        outputTokens,
        costUsd,
        savedUsd: savedCost,
        sessionId,
      });

      const event: TrackingEvent = {
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
        session_id: sessionId,
      };

      this.enqueue(event);
    });
  }

  private enqueue(event: TrackingEvent): void {
    if (this.config.privacy === "local-only") return;
    if (this.config.privacy === "strict" || this.config.privacy === "anonymized") {
      event.agent_name = "anonymous";
      event.team = "";
    }

    const eventKey = event.event_id;
    if (this.sentIds.has(eventKey) || this.queuedIds.has(eventKey)) return;
    this.queuedIds.add(eventKey);
    if (this.queuedIds.size > 1000) {
      const arr = Array.from(this.queuedIds);
      this.queuedIds = new Set(arr.slice(-500));
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
    const base = this.config.apiBase || "https://api.cohrint.com";
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
          sdk_version: `vantage-cli-${VERSION}`,
          sdk_language: "typescript",
        }),
        signal: AbortSignal.timeout(15000),
      });

      bus.emit("cost:reported", { success: response.ok });

      if (response.ok) {
        for (const e of batch) {
          this.sentIds.add(e.event_id);
          this.queuedIds.delete(e.event_id);
        }
        if (this.sentIds.size > 1000) {
          const arr = Array.from(this.sentIds);
          this.sentIds = new Set(arr.slice(-500));
        }
      } else {
        console.error(`  [vantage] Dashboard sync failed: HTTP ${response.status}`);
        const unsent = batch.filter((e) => !this.sentIds.has(e.event_id));
        if (response.status >= 500 || response.status === 429 || response.status === 408) {
          this.queue.unshift(...unsent);
        } else if (response.status >= 400) {
          console.warn(`[vantage] Dropping ${unsent.length} events: HTTP ${response.status}`);
        }
      }
    } catch (err) {
      bus.emit("cost:reported", { success: false });
      if (this.config.debug) {
        console.error("[vantage] Failed to send events:", err);
      }
      const unsent = batch.filter((e) => !this.sentIds.has(e.event_id));
      this.queue.unshift(...unsent);
    }
  }

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      this.flush().catch(() => {});
    }, this.config.flushInterval);
    if (!this.exitRegistered) {
      this.exitRegistered = true;
      process.on("beforeExit", () => {
        this.flush().catch((err) => {
          if (this.config?.debug) console.error("[vantage] Final flush failed:", err);
        });
      });
    }
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
