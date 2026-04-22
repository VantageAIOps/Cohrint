/**
 * Routing config — maps coding intent to ordered model candidates.
 * Cheapest-first within each provider family.
 * Scope: Python, TypeScript, Go coding tasks only (Stage 1 spec).
 */

import type { CodingIntent } from "./intent-classifier.js";

export interface ModelCandidate {
  model: string;
  provider: string;
  /** Minimum acceptable quality score (0–1). Requests below are escalated. */
  minQuality: number;
}

export interface RoutingRule {
  /** Ordered cheapest → most capable. First passing minQuality wins. */
  candidates: ModelCandidate[];
  /** Model used for quality sampling comparisons */
  premiumModel: string;
  /** Fraction of routed requests to shadow-sample against premium model */
  sampleRate: number;
}

const RULES: Record<CodingIntent, RoutingRule> = {
  autocomplete: {
    candidates: [
      { model: "gemini-2.0-flash",  provider: "google",    minQuality: 0.70 },
      { model: "gpt-4o-mini",       provider: "openai",    minQuality: 0.70 },
      { model: "claude-haiku-4-5",  provider: "anthropic", minQuality: 0.70 },
    ],
    premiumModel: "gpt-4o",
    sampleRate: 0.05,
  },
  explanation: {
    candidates: [
      { model: "gpt-4o-mini",       provider: "openai",    minQuality: 0.75 },
      { model: "gemini-2.0-flash",  provider: "google",    minQuality: 0.75 },
      { model: "claude-haiku-4-5",  provider: "anthropic", minQuality: 0.75 },
    ],
    premiumModel: "claude-sonnet-4-6",
    sampleRate: 0.03,
  },
  generation: {
    candidates: [
      { model: "gpt-4o-mini",       provider: "openai",    minQuality: 0.80 },
      { model: "claude-haiku-4-5",  provider: "anthropic", minQuality: 0.80 },
      { model: "gemini-1.5-flash",  provider: "google",    minQuality: 0.80 },
    ],
    premiumModel: "gpt-4o",
    sampleRate: 0.04,
  },
  refactor: {
    candidates: [
      { model: "gpt-4o-mini",       provider: "openai",    minQuality: 0.82 },
      { model: "claude-haiku-4-5",  provider: "anthropic", minQuality: 0.82 },
      { model: "gemini-1.5-pro",    provider: "google",    minQuality: 0.82 },
    ],
    premiumModel: "claude-sonnet-4-6",
    sampleRate: 0.05,
  },
};

export interface RoutingDecision {
  originalModel: string;
  routedModel: string;
  routedProvider: string;
  intent: CodingIntent;
  reason: "cost_optimization" | "same_model" | "no_cheaper_candidate";
  shouldSample: boolean;
  premiumModel: string;
  sampleRate: number;
}

/**
 * Decide which model to route to given the requested model and classified intent.
 * Only routes to a different model if it's in a cheaper candidate from the same
 * provider family OR the requester doesn't have a preference (no explicit model).
 */
export function routingDecision(
  requestedModel: string,
  intent: CodingIntent,
): RoutingDecision {
  const rule = RULES[intent];
  const sample = Math.random() < rule.sampleRate;

  // If requested model is already the cheapest candidate, keep it
  const firstCandidate = rule.candidates[0];
  if (!firstCandidate || requestedModel === firstCandidate.model) {
    return {
      originalModel: requestedModel,
      routedModel: requestedModel,
      routedProvider: deriveProvider(requestedModel),
      intent,
      reason: "same_model",
      shouldSample: sample,
      premiumModel: rule.premiumModel,
      sampleRate: rule.sampleRate,
    };
  }

  // Find cheapest candidate that isn't the requested (premium) model
  const cheaper = rule.candidates.find((c) => c.model !== requestedModel);
  if (!cheaper) {
    return {
      originalModel: requestedModel,
      routedModel: requestedModel,
      routedProvider: deriveProvider(requestedModel),
      intent,
      reason: "no_cheaper_candidate",
      shouldSample: sample,
      premiumModel: rule.premiumModel,
      sampleRate: rule.sampleRate,
    };
  }

  return {
    originalModel: requestedModel,
    routedModel: cheaper.model,
    routedProvider: cheaper.provider,
    intent,
    reason: "cost_optimization",
    shouldSample: sample,
    premiumModel: rule.premiumModel,
    sampleRate: rule.sampleRate,
  };
}

function deriveProvider(model: string): string {
  if (model.startsWith("gpt-") || model.startsWith("o1") || model.startsWith("o3")) return "openai";
  if (model.startsWith("claude-")) return "anthropic";
  if (model.startsWith("gemini-")) return "google";
  return "openai";
}

export { RULES };
