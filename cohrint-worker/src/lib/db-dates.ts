/**
 * Typed D1 date helpers — prevents silent full-table scans.
 *
 * SQLite coerces a TEXT date string bound to an INTEGER column to 0,
 * effectively bypassing the WHERE clause and returning every row.
 * Use these helpers instead of raw Date.now() or new Date().toISOString().
 *
 * future_scale: When migrating off D1, replace the function bodies here
 * rather than hunting 100+ callsites.
 */

export type ColType = 'int' | 'text';

/** Returns the unix epoch seconds for N days ago. Use for INTEGER columns. */
export function sinceUnix(days: number): number {
  const d = new Date(Date.now() - days * 86_400_000);
  d.setUTCHours(0, 0, 0, 0);
  return Math.floor(d.getTime() / 1000);
}

/** Returns ISO datetime string 'YYYY-MM-DD HH:MM:SS' for N days ago. Use for TEXT columns. */
export function sinceIso(days: number): string {
  const d = new Date(Date.now() - days * 86_400_000);
  d.setUTCHours(0, 0, 0, 0);
  return d.toISOString().replace('T', ' ').slice(0, 19);
}

/** Returns unix epoch seconds for start of current month (UTC). */
export function monthStartUnix(): number {
  return Math.floor(
    new Date(new Date().toISOString().slice(0, 7) + '-01T00:00:00Z').getTime() / 1000,
  );
}

/** Returns ISO datetime string for start of current month (UTC). */
export function monthStartIso(): string {
  return new Date().toISOString().slice(0, 7) + '-01 00:00:00';
}

/** Returns current unix epoch seconds. */
export function nowUnix(): number {
  return Math.floor(Date.now() / 1000);
}

/** Returns current ISO datetime string 'YYYY-MM-DD HH:MM:SS'. */
export function nowIso(): string {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

/**
 * Generic bindSince: returns the correct type based on column type.
 * Pass the ColType literal from DATE_COLUMN_TYPE.
 */
export function bindSince<T extends ColType>(colType: T, days: number): T extends 'int' ? number : string {
  return (colType === 'int' ? sinceUnix(days) : sinceIso(days)) as T extends 'int' ? number : string;
}

export function bindMonthStart<T extends ColType>(colType: T): T extends 'int' ? number : string {
  return (colType === 'int' ? monthStartUnix() : monthStartIso()) as T extends 'int' ? number : string;
}
