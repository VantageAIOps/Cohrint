import { createHash, randomUUID } from "crypto";

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cachedTokens: number;
  systemPromptTokens: number;
}

export interface CostInfo {
  inputCostUsd: number;
  outputCostUsd: number;
  totalCostUsd: number;
  cheapestModel: string;
  cheapestCostUsd: number;
  potentialSavingUsd: number;
}

export interface QualityMetrics {
  hallucinationScore: number;
  hallucinationType: string;
  coherenceScore: number;
  relevanceScore: number;
  completenessScore: number;
  factualityScore: number;
  toxicityScore: number;
  overallQuality: number;
  promptClarityScore: number;
  promptEfficiencyScore: number;
  evaluatedBy: string;
  evalLatencyMs: number;
}

export interface VantageEvent {
  eventId: string;
  timestamp: number;
  orgId: string;
  environment: string;
  provider: string;
  model: string;
  endpoint: string;
  sessionId: string;
  userId: string;
  feature: string;
  project: string;
  team: string;
  tags: Record<string, string>;
  latencyMs: number;
  ttftMs: number;
  statusCode: number;
  error?: string;
  usage: TokenUsage;
  cost: CostInfo;
  quality: QualityMetrics;
  requestPreview: string;
  responsePreview: string;
  systemPreview: string;
  promptHash: string;
}

export function defaultTokenUsage(): TokenUsage {
  return { promptTokens: 0, completionTokens: 0, totalTokens: 0, cachedTokens: 0, systemPromptTokens: 0 };
}

export function defaultCostInfo(): CostInfo {
  return { inputCostUsd: 0, outputCostUsd: 0, totalCostUsd: 0, cheapestModel: "", cheapestCostUsd: 0, potentialSavingUsd: 0 };
}

export function defaultQualityMetrics(): QualityMetrics {
  return {
    hallucinationScore: -1, hallucinationType: "", coherenceScore: -1,
    relevanceScore: -1, completenessScore: -1, factualityScore: -1,
    toxicityScore: -1, overallQuality: -1, promptClarityScore: -1,
    promptEfficiencyScore: -1, evaluatedBy: "", evalLatencyMs: 0,
  };
}

export function makeEventId(): string {
  return randomUUID();
}

export function hashPrompt(text: string): string {
  return createHash("sha256").update(text).digest("hex").slice(0, 12);
}

export function efficiencyScore(usage: TokenUsage): number | null {
  const totalTokens = usage.promptTokens + usage.completionTokens;
  if (!totalTokens) return null;
  const sysOverhead = usage.promptTokens > 0
    ? (usage.systemPromptTokens / usage.promptTokens) * 100 : 0;
  const cacheHit = usage.promptTokens > 0
    ? usage.cachedTokens / usage.promptTokens : 0;
  return Math.max(0, Math.min(100, 100 - Math.min(50, sysOverhead) + cacheHit * 20));
}

export function flattenEvent(e: VantageEvent): Record<string, unknown> {
  return {
    event_id: e.eventId,
    timestamp: e.timestamp,
    org_id: e.orgId,
    environment: e.environment,
    provider: e.provider,
    model: e.model,
    endpoint: e.endpoint,
    session_id: e.sessionId,
    user_id: e.userId,
    feature: e.feature,
    project: e.project,
    team: e.team,
    tags: e.tags,
    latency_ms: e.latencyMs,
    ttft_ms: e.ttftMs,
    status_code: e.statusCode,
    error: e.error ?? null,
    prompt_tokens: e.usage.promptTokens,
    completion_tokens: e.usage.completionTokens,
    total_tokens: e.usage.totalTokens,
    cache_tokens: e.usage.cachedTokens,
    system_prompt_tokens: e.usage.systemPromptTokens,
    cost_input_usd: e.cost.inputCostUsd,
    cost_output_usd: e.cost.outputCostUsd,
    cost_total_usd: e.cost.totalCostUsd,
    cheapest_model: e.cost.cheapestModel,
    cheapest_cost_usd: e.cost.cheapestCostUsd,
    potential_saving_usd: e.cost.potentialSavingUsd,
    quality_hallucination_score: e.quality.hallucinationScore,
    quality_hallucination_type: e.quality.hallucinationType,
    quality_coherence: e.quality.coherenceScore,
    quality_relevance: e.quality.relevanceScore,
    quality_completeness: e.quality.completenessScore,
    quality_factuality: e.quality.factualityScore,
    quality_toxicity: e.quality.toxicityScore,
    quality_overall: e.quality.overallQuality,
    quality_prompt_clarity: e.quality.promptClarityScore,
    quality_prompt_efficiency: e.quality.promptEfficiencyScore,
    quality_evaluated_by: e.quality.evaluatedBy,
    quality_eval_latency_ms: e.quality.evalLatencyMs,
    request_preview: e.requestPreview,
    response_preview: e.responsePreview,
    system_preview: e.systemPreview,
    prompt_hash: e.promptHash,
  };
}
