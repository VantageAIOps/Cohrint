# Cost Forecasting Widget — Design Spec

> **Status:** SHIPPED — PR #70 (2026-04-17)
> **Date:** 2026-04-17
> **Scope:** `GET /v1/analytics/summary` + KPI dashboard cards

---

## Problem

The dashboard shows month-to-date spend but gives users no forward visibility. Engineering managers need to know whether they are on track to exceed budget before the month ends — not after. Budget runway ("how many days left at current burn rate?") is the most actionable signal.

---

## Solution

Add three computed fields to the existing `GET /v1/analytics/summary` response and surface them as two new KPI cards in the dashboard. No DB migrations needed — all values are derived from existing `events` table data at query time.

---

## Backend Changes

### New Fields on `GET /v1/analytics/summary`

Three fields added to the existing JSON response:

```json
{
  "total_cost_usd": 142.50,
  "projected_month_end_usd": 201.43,
  "budget_runway_days": 8.2,
  "daily_avg_usd": 6.52
}
```

| Field | Type | Description |
|-------|------|-------------|
| `projected_month_end_usd` | `number` | Projected total spend if current daily average continues to month end |
| `budget_runway_days` | `number \| null` | Days until budget exhausted at current burn rate. `null` if no budget set or daily avg is 0 |
| `daily_avg_usd` | `number` | Average daily spend for days elapsed so far this month |

### Formula

```
days_elapsed      = current day-of-month (e.g. 17 for April 17)
days_in_month     = total days in current month (e.g. 30 for April)
daily_avg         = mtd_cost / days_elapsed
projected         = daily_avg × days_in_month
runway            = (monthly_budget_usd − mtd_cost) / daily_avg
                    null if no budget or daily_avg == 0
```

All computed in TypeScript in `cohrint-worker/src/routes/analytics.ts` after the existing D1 query — no schema changes or new SQL queries required.

Edge cases:
- `days_elapsed = 0` (first day before any events): `daily_avg = 0`, `projected = 0`, `runway = null`
- No budget configured: `runway = null`
- Budget already exceeded: `runway` is negative (rendered as `0d` in UI with red styling)

---

## Frontend Changes

### Two New KPI Cards

Added after the existing "Month-to-Date Spend" card in the KPI grid:

#### Card 1 — Projected Month-End

- **Label:** "Projected Month-End"
- **Value:** `$XX.XX`
- **Subtext:** "at current daily avg of $X.XX/day"
- **Color coding:**
  - Green: projected ≤ 80% of monthly budget
  - Amber: projected between 80–100% of budget
  - Red: projected > budget (over-budget trajectory)
  - Grey: no budget configured

#### Card 2 — Budget Runway

- **Label:** "Budget Runway"
- **Value:** `Xd` (days, rounded to 1 decimal) or "No budget"
- **Subtext:** "$XX.XX remaining of $XX.XX budget"
- **Color coding:**
  - Green: runway > 10 days
  - Amber: runway 3–10 days
  - Red: runway < 3 days or already exceeded
  - Grey: no budget set or `runway = null`

---

## Test Suite — Suite 52

**Directory:** `tests/suites/52_cost_forecasting/`
**Total checks:** 11

| # | Test |
|---|------|
| 1 | `projected_month_end_usd` present in summary response |
| 2 | `budget_runway_days` present in summary response |
| 3 | `daily_avg_usd` present in summary response |
| 4 | `projected_month_end_usd` ≥ `total_cost_usd` (projected ≥ actual) |
| 5 | `daily_avg_usd` = `total_cost_usd / days_elapsed` (within float tolerance) |
| 6 | `projected_month_end_usd` = `daily_avg × days_in_month` (within float tolerance) |
| 7 | `budget_runway_days` is `null` when no budget configured |
| 8 | `budget_runway_days` is negative when spend already exceeds budget |
| 9 | `daily_avg_usd` = 0 when no events this month |
| 10 | `projected_month_end_usd` = 0 when no events this month |
| 11 | All three fields are `number` or `null` (never string, never absent) |

---

## Implementation Notes

- No DB migrations needed — derived entirely from existing `total_cost_usd` (MTD) and `budget` values already returned
- `budget` value sourced from `team_budgets` table (existing query in summary handler)
- TypeScript: `days_elapsed = new Date().getUTCDate()`, `days_in_month = new Date(year, month, 0).getUTCDate()`
- Runway floored at `null` rather than `Infinity` when `daily_avg = 0`

---

## Files Modified (PR #70)

| File | Change |
|------|--------|
| `cohrint-worker/src/routes/analytics.ts` | Add three computed fields to summary handler |
| `cohrint-frontend/app.html` | Two new KPI card elements + render logic |
| `tests/suites/52_cost_forecasting/test_forecasting.py` | 11 checks |
| `tests/suites/52_cost_forecasting/conftest.py` | Suite fixtures |
