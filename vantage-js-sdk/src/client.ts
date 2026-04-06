import { VantageEvent } from "./models/event.js";
import { EventQueue } from "./utils/queue.js";

export type PrivacyMode = "full" | "stats-only" | "hashed";

export interface VantageClientOptions {
  apiKey: string;
  org?: string;
  team?: string;
  project?: string;
  environment?: string;
  ingestUrl?: string;
  flushInterval?: number;
  batchSize?: number;
  debug?: boolean;
  /**
   * Privacy mode controls what data is sent to VantageAI servers:
   *  - "full"       — sends everything including prompt/response previews (default, existing behavior)
   *  - "stats-only" — sends ONLY token counts, cost, latency, model. NO text whatsoever.
   *  - "hashed"     — like stats-only but includes SHA-256 prompt hash for dedup detection
   */
  privacy?: PrivacyMode;
}

export class VantageClient {
  readonly orgId: string;
  readonly environment: string;
  readonly team: string;
  readonly project: string;
  readonly privacy: PrivacyMode;
  private readonly queue: EventQueue;
  private readonly debug: boolean;

  constructor(opts: VantageClientOptions) {
    const _keyParts = opts.apiKey.split("_");
    if (!opts.org && _keyParts.length < 2) {
      throw new Error("Invalid API key format: expected 'vnt_<orgId>_...' or provide opts.org explicitly.");
    }
    this.orgId = opts.org ?? _keyParts[1] ?? "";
    this.environment = opts.environment ?? "production";
    this.team = opts.team ?? "";
    this.project = opts.project ?? "";
    this.privacy = opts.privacy ?? "full";
    this.debug = opts.debug ?? false;

    this.queue = new EventQueue(
      opts.apiKey,
      opts.ingestUrl ?? "https://api.vantageaiops.com",
      (opts.flushInterval ?? 2) * 1000,
      opts.batchSize ?? 50,
      this.debug
    );
    this.queue.start();
  }

  capture(event: VantageEvent): void {
    // Inject client-level defaults if not set on event
    if (!event.orgId) event.orgId = this.orgId;
    if (!event.environment) event.environment = this.environment;
    if (!event.team) event.team = this.team;
    if (!event.project) event.project = this.project;

    // Apply privacy mode — strip sensitive text before queueing
    if (this.privacy === "stats-only") {
      event.requestPreview = "";
      event.responsePreview = "";
      event.systemPreview = "";
      event.promptHash = "";
    } else if (this.privacy === "hashed") {
      event.requestPreview = "";
      event.responsePreview = "";
      event.systemPreview = "";
      // promptHash is kept — it's a non-reversible SHA hash
    }

    this.queue.enqueue(event);
  }

  flush(): void {
    this.queue.flush();
  }

  shutdown(): void {
    this.queue.flush();
    this.queue.stop();
  }
}
