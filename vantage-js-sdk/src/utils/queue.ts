import { VantageEvent, flattenEvent } from "../models/event.js";

const SDK_VERSION = "1.0.0";
const MAX_RETRIES = 3;

interface QueuedEvent {
  event: VantageEvent;
  retries: number;
}

export class EventQueue {
  private queue: QueuedEvent[] = [];
  private readonly maxSize = 10_000;
  private timer: ReturnType<typeof setInterval> | null = null;
  private _flushing = false;

  constructor(
    private readonly apiKey: string,
    private readonly ingestUrl: string,
    private readonly flushInterval = 2000,
    private readonly batchSize = 50,
    private readonly debug = false
  ) {}

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => this.flush(), this.flushInterval);
    // Flush on process exit
    if (typeof process !== "undefined") {
      process.on("beforeExit", () => this.flush());
    }
  }

  stop(): void {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  }

  enqueue(event: VantageEvent): void {
    if (this.queue.length >= this.maxSize) {
      if (this.queue.length === this.maxSize) {
        console.warn("[vantage] Event queue full (10k). Dropping event.");
      }
      return;
    }
    if (this.queue.length >= this.maxSize * 0.8 && this.queue.length % 500 === 0) {
      console.warn(`[vantage] Queue at ${this.queue.length} events — consider flushing more frequently.`);
    }
    this.queue.push({ event, retries: 0 });
    if (this.debug) console.debug(`[vantage] Enqueued event ${event.eventId} (queue size: ${this.queue.length})`);
  }

  flush(): void {
    if (this._flushing) return;
    if (this.queue.length === 0) return;
    this._flushing = true;
    const batch = this.queue.splice(0, this.batchSize);
    this._send(batch)
      .catch((err) => {
        if (this.debug) console.warn("[vantage] Flush error:", err);
        // Re-queue only items that have not exceeded max retries
        const retryable = batch
          .map((item) => ({ ...item, retries: item.retries + 1 }))
          .filter((item) => {
            if (item.retries >= MAX_RETRIES) {
              if (this.debug) console.warn(`[vantage] Dropping event ${item.event.eventId} after ${MAX_RETRIES} failures.`);
              return false;
            }
            return true;
          });
        this.queue.unshift(...retryable);
      })
      .finally(() => { this._flushing = false; });
  }

  private async _send(items: QueuedEvent[]): Promise<void> {
    const events = items.map((i) => i.event);
    const body = JSON.stringify({
      events: events.map(flattenEvent),
      sdk_version: SDK_VERSION,
      sdk_language: "typescript",
    });

    try {
      const res = await fetch(`${this.ingestUrl}/v1/events`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        body,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (this.debug) console.debug(`[vantage] Sent ${items.length} events → ${res.status}`);
    } catch (err) {
      if (this.debug) console.warn("[vantage] Ingest failed:", err);
      throw err; // re-throw so flush() re-queues the batch
    }
  }
}
