import { yellow } from "./ui.js";

const MIN_AVG_COST = 0.001; // $0.001 minimum average before flagging

/**
 * Check whether the current prompt's cost is anomalously high relative to the
 * session average. Prints a warning if so.
 *
 * @param currentCost   Cost of the current prompt in USD.
 * @param priorTotal    Sum of all PRIOR prompts' costs (current excluded).
 * @param priorCount    Number of PRIOR prompts (current excluded).
 */
export function checkCostAnomaly(
  currentCost: number,
  priorTotal: number,
  priorCount: number,
): void {
  if (priorCount < 2 || priorTotal <= 0) return;
  if (!Number.isFinite(priorTotal) || priorTotal < 0) return;
  const avgCost = priorTotal / priorCount;
  if (avgCost < MIN_AVG_COST) return;
  if (Number.isFinite(avgCost) && currentCost > avgCost * 3) {
    console.log(yellow(`  ⚠ Anomaly: this prompt cost $${currentCost.toFixed(4)} — ${(currentCost / avgCost).toFixed(1)}x your session average`));
  }
}
