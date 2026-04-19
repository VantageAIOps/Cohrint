import { yellow } from "./ui.js";

const MIN_AVG_COST = 0.001;

export function checkCostAnomaly(
  currentCost: number,
  priorTotal: number,
  priorCount: number
): void {
  if (priorCount < 2 || priorTotal <= 0) return;
  if (!Number.isFinite(priorTotal) || priorTotal < 0) return;
  const avgCost = priorTotal / priorCount;
  if (avgCost < MIN_AVG_COST) return;
  if (Number.isFinite(avgCost) && currentCost > avgCost * 3) {
    console.log(
      yellow(
        `  ⚠ Anomaly: this prompt cost $${currentCost.toFixed(4)} — ${(currentCost / avgCost).toFixed(1)}x your session average`
      )
    );
  }
}
