import { VantageEvent, flattenEvent } from "../models/event.js";
import { VERSION } from "../_version.js";

const SDK_VERSION = VERSION;
const MAX_RETRIES = 3;
/** Max events kept in the Node.js file spool or in-memory spool */
const MAX_SPOOL = 100;

interface QueuedEvent {
  event: VantageEvent;
  retries: number;
}

// ── Spool helpers (best-effort, never throws) ─────────────────────────────────

/** In-memory spool used in browser environments or when the FS spool is unavailable. */
const _memorySpool: string[] = [];

/**
 * Spool path: Node.js only — `os.tmpdir()/cohrint-spool.jsonl`.
 * Returns null in non-Node environments.
 */
function _spoolPath(): string | null {
  try {
    // Dynamic import avoids bundler errors in browser builds
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const os = require("os") as { tmpdir(): string };
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const path = require("path") as { join(...parts: string[]): string };
    return path.join(os.tmpdir(), "cohrint-spool.jsonl");
  } catch {
    return null;
  }
}

function _isNodeFs(): boolean {
  return typeof process !== "undefined" && typeof process.versions?.node === "string";
}

/** Append a JSON line to the spool file (or memory). Trims oldest if over MAX_SPOOL. */
function _spoolWrite(line: string): void {
  try {
    const spoolFile = _isNodeFs() ? _spoolPath() : null;
    if (spoolFile) {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const fs = require("fs") as {
        existsSync(p: string): boolean;
        readFileSync(p: string, enc: string): string;
        writeFileSync(p: string, data: string): void;
        appendFileSync(p: string, data: string): void;
      };
      // Enforce MAX_SPOOL on file
      if (fs.existsSync(spoolFile)) {
        const existing = fs.readFileSync(spoolFile, "utf-8").split("\n").filter(Boolean);
        if (existing.length >= MAX_SPOOL) {
          // Drop oldest
          const trimmed = existing.slice(existing.length - MAX_SPOOL + 1);
          trimmed.push(line);
          fs.writeFileSync(spoolFile, trimmed.join("\n") + "\n");
          return;
        }
      }
      fs.appendFileSync(spoolFile, line + "\n");
    } else {
      // In-memory spool
      if (_memorySpool.length >= MAX_SPOOL) _memorySpool.shift();
      _memorySpool.push(line);
    }
  } catch (err) {
    // Best-effort — never throw
    try { console.warn("[cohrint] spool write failed:", err); } catch { /* ignore */ }
  }
}

/** Read and clear all spool lines. Returns array of raw JSON strings. */
function _spoolDrain(): string[] {
  try {
    const spoolFile = _isNodeFs() ? _spoolPath() : null;
    if (spoolFile) {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const fs = require("fs") as {
        existsSync(p: string): boolean;
        readFileSync(p: string, enc: string): string;
        unlinkSync(p: string): void;
      };
      if (!fs.existsSync(spoolFile)) return [];
      const lines = fs.readFileSync(spoolFile, "utf-8").split("\n").filter(Boolean);
      fs.unlinkSync(spoolFile);
      return lines;
    } else {
      const drained = _memorySpool.splice(0);
      return drained;
    }
  } catch {
    return [];
  }
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
        console.warn("[cohrint] Event queue full (10k). Dropping event.");
      }
      return;
    }
    if (this.queue.length >= this.maxSize * 0.8 && this.queue.length % 500 === 0) {
      console.warn(`[cohrint] Queue at ${this.queue.length} events — consider flushing more frequently.`);
    }
    this.queue.push({ event, retries: 0 });
    if (this.debug) console.debug(`[cohrint] Enqueued event ${event.eventId} (queue size: ${this.queue.length})`);
  }

  flush(): void {
    if (this._flushing) return;
    if (this.queue.length === 0) return;
    this._flushing = true;
    const batch = this.queue.splice(0, this.batchSize);
    this._send(batch)
      .catch((err) => {
        if (this.debug) console.warn("[cohrint] Flush error:", err);
        // Re-queue only items that have not exceeded max retries
        const retryable = batch
          .map((item) => ({ ...item, retries: item.retries + 1 }))
          .filter((item) => {
            if (item.retries >= MAX_RETRIES) {
              if (this.debug) console.warn(`[cohrint] Dropping event ${item.event.eventId} after ${MAX_RETRIES} failures.`);
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
    const flatEvents = events.map(flattenEvent);
    const body = JSON.stringify({
      events: flatEvents,
      sdk_version: SDK_VERSION,
      sdk_language: "typescript",
    });

    // Drain any previously spooled events and prepend them to this batch.
    // Do this before the fetch so a successful send clears the spool.
    const spooledLines = _spoolDrain();
    const spooledEvents: unknown[] = [];
    for (const line of spooledLines) {
      try { spooledEvents.push(JSON.parse(line)); } catch { /* corrupt line — skip */ }
    }

    const finalBody = spooledEvents.length > 0
      ? JSON.stringify({
          events: [...spooledEvents, ...flatEvents],
          sdk_version: SDK_VERSION,
          sdk_language: "typescript",
        })
      : body;

    try {
      const res = await fetch(`${this.ingestUrl}/v1/events/batch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`,
        },
        body: finalBody,
      });

      // 201 (sync created) and 202 (async queued) are both success
      if (res.status === 201 || res.status === 202 || (res.status >= 200 && res.status < 300)) {
        if (this.debug) console.debug(`[cohrint] Sent ${items.length + spooledEvents.length} events → ${res.status}`);
        return; // success — spool already drained above
      }

      // 503 Service Unavailable — spool current batch for later retry
      if (res.status === 503) {
        if (this.debug) console.warn(`[cohrint] Ingest returned 503 — spooling ${items.length} events`);
        // Re-spool the drained events too (they got drained but not sent)
        for (const ev of spooledEvents) {
          _spoolWrite(JSON.stringify(ev));
        }
        for (const ev of flatEvents) {
          _spoolWrite(JSON.stringify(ev));
        }
        return; // don't re-queue — spool handles it
      }

      throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      // Network / connection error — spool current batch
      const isNetworkError = !(err instanceof Error && err.message.startsWith("HTTP "));
      if (isNetworkError) {
        if (this.debug) console.warn("[cohrint] Network error — spooling events:", err);
        for (const ev of spooledEvents) {
          _spoolWrite(JSON.stringify(ev));
        }
        for (const ev of flatEvents) {
          _spoolWrite(JSON.stringify(ev));
        }
        return; // don't re-queue — spool handles it
      }
      // HTTP error (non-503) — re-spool drained events and re-throw to re-queue
      for (const ev of spooledEvents) {
        _spoolWrite(JSON.stringify(ev));
      }
      if (this.debug) console.warn("[cohrint] Ingest failed:", err);
      throw err; // re-throw so flush() re-queues the batch
    }
  }
}
