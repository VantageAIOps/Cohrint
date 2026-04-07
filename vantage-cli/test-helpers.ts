#!/usr/bin/env tsx
/**
 * test-helpers.ts — Unit test harness called by pytest.
 * Imports real production code via tsx — no logic duplication.
 *
 * Usage:
 *   tsx test-helpers.ts optimize    "prompt text"
 *   tsx test-helpers.ts tokens      "text to count"
 *   tsx test-helpers.ts cost        "model" inputTokens outputTokens [cachedTokens]
 *   tsx test-helpers.ts cheapest    "model" inputTokens outputTokens
 *   tsx test-helpers.ts models
 *   tsx test-helpers.ts structured  "text to classify"
 */

import { optimizePrompt, countTokens } from "./src/optimizer.js";
import { calculateCost, findCheapest, PRICES } from "./src/pricing.js";
import { looksLikeStructuredData } from "./src/classify.js";

const cmd  = process.argv[2] ?? "";
const arg1 = process.argv[3] ?? "";
const arg2 = process.argv[4] ?? "0";
const arg3 = process.argv[5] ?? "0";
const arg4 = process.argv[6] ?? "0";

switch (cmd) {
  case "optimize": {
    const result = optimizePrompt(arg1);
    console.log(JSON.stringify({
      original:       result.original,
      optimized:      result.optimized,
      originalTokens: countTokens(result.original),
      optimizedTokens: countTokens(result.optimized),
      savedTokens:    result.savedTokens,
      savedPercent:   result.savedPercent,
    }));
    break;
  }

  case "tokens":
    console.log(JSON.stringify({ text: arg1, tokens: countTokens(arg1) }));
    break;

  case "cost": {
    // calculateCost returns a number; wrap in object to match test expectations
    const totalCostUsd = calculateCost(arg1, parseInt(arg2), parseInt(arg3), parseInt(arg4));
    console.log(JSON.stringify({ totalCostUsd }));
    break;
  }

  case "cheapest": {
    const inputTokens  = parseInt(arg2);
    const outputTokens = parseInt(arg3);
    const r = findCheapest(arg1, inputTokens, outputTokens);
    if (r) {
      // Normalize to test-expected shape: { model, costUsd, savingsUsd }
      console.log(JSON.stringify({ model: r.model, costUsd: r.cost, savingsUsd: r.savings }));
    } else {
      console.log(JSON.stringify(null));
    }
    break;
  }

  case "models":
    console.log(JSON.stringify({ count: Object.keys(PRICES).length, models: Object.keys(PRICES) }));
    break;

  case "structured":
    console.log(JSON.stringify({ isStructured: looksLikeStructuredData(arg1) }));
    break;

  default:
    console.error("Usage: tsx test-helpers.ts <optimize|tokens|cost|cheapest|models|structured> [args...]");
    process.exit(1);
}
