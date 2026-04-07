#!/usr/bin/env tsx
/**
 * test-recommendations.ts — TDD harness for recommendations.ts
 * Runs via tsx so it imports real production code directly.
 *
 * Usage:
 *   tsx test-recommendations.ts recommendations  '{"metrics": {...}, "maxTips": 3}'
 *   tsx test-recommendations.ts inline_tip       '{"metrics": {...}}'
 *   tsx test-recommendations.ts format           '{"metrics": {...}, "maxTips": 3}'
 */

import {
  getRecommendations,
  getInlineTip,
  formatRecommendations,
  type SessionMetrics,
} from "./src/recommendations.js";

const cmd = process.argv[2] ?? "";
const raw = process.argv[3] ?? "{}";

let payload: { metrics: SessionMetrics; maxTips?: number };
try {
  payload = JSON.parse(raw);
} catch {
  console.log(JSON.stringify({ error: "invalid JSON payload" }));
  process.exit(1);
}

const metrics = payload.metrics ?? ({} as SessionMetrics);
const maxTips = payload.maxTips ?? 3;

if (cmd === "recommendations") {
  const tips = getRecommendations(metrics, maxTips);
  console.log(JSON.stringify({
    count: tips.length,
    ids: tips.map(t => t.id),
    priorities: tips.map(t => t.priority),
    actions: tips.map(t => t.action),
    titles: tips.map(t => t.title),
  }));

} else if (cmd === "inline_tip") {
  const tip = getInlineTip(metrics);
  console.log(JSON.stringify({ tip }));

} else if (cmd === "format") {
  const tips = getRecommendations(metrics, maxTips);
  const output = formatRecommendations(tips);
  console.log(JSON.stringify({ output }));

} else {
  console.log(JSON.stringify({ error: `unknown command: ${cmd}` }));
  process.exit(1);
}
