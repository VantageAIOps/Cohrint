import { VantageEvent } from "./models/event.js";
import { EventQueue } from "./utils/queue.js";

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
}

export class VantageClient {
  readonly orgId: string;
  readonly environment: string;
  readonly team: string;
  readonly project: string;
  private readonly queue: EventQueue;
  private readonly debug: boolean;

  constructor(opts: VantageClientOptions) {
    this.orgId = opts.org ?? opts.apiKey.split("_")[1] ?? "";
    this.environment = opts.environment ?? "production";
    this.team = opts.team ?? "";
    this.project = opts.project ?? "";
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
