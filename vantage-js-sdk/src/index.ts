export { VantageClient } from "./client.js";
export type { VantageClientOptions } from "./client.js";
export { createOpenAIProxy } from "./proxy/openai.js";
export { createAnthropicProxy } from "./proxy/anthropic.js";
export { trace } from "./proxy/universal.js";
export type { TraceOptions } from "./proxy/universal.js";
export type { VantageEvent, TokenUsage, CostInfo, QualityMetrics } from "./models/event.js";
export { calculateCost, findCheapest, PRICES } from "./models/pricing.js";

// ── Singleton convenience API (mirrors Python's vantage.init / vantage.flush) ──

import { VantageClient } from "./client.js";
import type { VantageClientOptions } from "./client.js";

let _client: VantageClient | null = null;

export function init(opts: VantageClientOptions): VantageClient {
  _client = new VantageClient(opts);
  return _client;
}

export function getClient(): VantageClient {
  if (!_client) throw new Error("[vantage] Call vantage.init() first.");
  return _client;
}

export function flush(): void {
  _client?.flush();
}

export function shutdown(): void {
  _client?.shutdown();
  _client = null;
}
