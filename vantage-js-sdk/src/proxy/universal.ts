import { AsyncLocalStorage } from "async_hooks";
import { randomUUID } from "crypto";
import {
  VantageEvent, TokenUsage, CostInfo, defaultCostInfo, defaultQualityMetrics,
  defaultTokenUsage, makeEventId, hashPrompt,
} from "../models/event.js";
import { calculateCost, findCheapest } from "../models/pricing.js";

export interface TraceContext {
  sessionId: string;
  userId: string;
  feature: string;
  project: string;
  team: string;
  tags: Record<string, string>;
}

const _store = new AsyncLocalStorage<TraceContext>();

export function getContext(): TraceContext {
  return _store.getStore() ?? { sessionId: "", userId: "", feature: "", project: "", team: "", tags: {} };
}

export interface TraceOptions {
  sessionId?: string;
  userId?: string;
  feature?: string;
  project?: string;
  team?: string;
  tags?: Record<string, string>;
}

export function trace<T>(opts: TraceOptions, fn: () => T): T {
  const ctx: TraceContext = {
    sessionId: opts.sessionId ?? randomUUID(),
    userId: opts.userId ?? "",
    feature: opts.feature ?? "",
    project: opts.project ?? "",
    team: opts.team ?? "",
    tags: opts.tags ?? {},
  };
  return _store.run(ctx, fn);
}

export interface BuildEventOptions {
  provider: string;
  model: string;
  endpoint: string;
  promptTokens: number;
  completionTokens: number;
  cachedTokens?: number;
  latencyMs: number;
  ttftMs?: number;
  statusCode?: number;
  error?: string;
  promptText?: string;
  responseText?: string;
  systemPrompt?: string;
  extraTags?: Record<string, string>;
  orgId: string;
  environment: string;
}

export function buildEvent(opts: BuildEventOptions): VantageEvent {
  const ctx = getContext();
  const cachedTokens = opts.cachedTokens ?? 0;
  const systemTokens = opts.systemPrompt
    ? Math.floor((opts.systemPrompt.split(/\s+/).length * 4) / 3) : 0;

  const { inputCostUsd, outputCostUsd, totalCostUsd } = calculateCost(
    opts.model, opts.promptTokens, opts.completionTokens, cachedTokens
  );
  const cheapest = findCheapest(opts.model, opts.promptTokens, opts.completionTokens);

  const usage: TokenUsage = {
    promptTokens: opts.promptTokens,
    completionTokens: opts.completionTokens,
    totalTokens: opts.promptTokens + opts.completionTokens,
    cachedTokens,
    systemPromptTokens: systemTokens,
  };

  const cost: CostInfo = {
    inputCostUsd,
    outputCostUsd,
    totalCostUsd,
    cheapestModel: cheapest?.model ?? "",
    cheapestCostUsd: cheapest?.costUsd ?? 0,
    potentialSavingUsd: cheapest ? Math.max(0, totalCostUsd - cheapest.costUsd) : 0,
  };

  const tags = { ...ctx.tags, ...(opts.extraTags ?? {}) };

  return {
    eventId: makeEventId(),
    timestamp: Date.now() / 1000,
    orgId: opts.orgId,
    environment: opts.environment,
    provider: opts.provider,
    model: opts.model,
    endpoint: opts.endpoint,
    sessionId: ctx.sessionId,
    userId: tags["user_id"] ?? ctx.userId,
    feature: tags["feature"] ?? ctx.feature,
    project: tags["project"] ?? ctx.project,
    team: tags["team"] ?? ctx.team,
    tags,
    latencyMs: Math.round(opts.latencyMs * 100) / 100,
    ttftMs: opts.ttftMs ?? 0,
    statusCode: opts.statusCode ?? 200,
    error: opts.error,
    usage,
    cost,
    quality: defaultQualityMetrics(),
    requestPreview: (opts.promptText ?? "").slice(0, 600),
    responsePreview: (opts.responseText ?? "").slice(0, 600),
    systemPreview: (opts.systemPrompt ?? "").slice(0, 200),
    promptHash: opts.systemPrompt ? hashPrompt(opts.systemPrompt) : "",
  };
}
