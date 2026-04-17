/**
 * Structured logger for Cohrint Worker.
 * Emits single-line NDJSON to stdout so `wrangler tail` and Logpush
 * can parse/filter without regex gymnastics.
 *
 * Usage:
 *   const log = createLogger(requestId, orgId);
 *   log.info('event ingested', { model: 'gpt-4o', ms: 12 });
 *
 * Future: swap console.log → Workers Logpush or WAE when volume exceeds
 *         `wrangler tail` ergonomics. No callsite changes needed.
 */

type Level = 'debug' | 'info' | 'warn' | 'error';

export interface Logger {
  debug(msg: string, fields?: Record<string, unknown>): void;
  info(msg: string,  fields?: Record<string, unknown>): void;
  warn(msg: string,  fields?: Record<string, unknown>): void;
  error(msg: string, fields?: Record<string, unknown>): void;
}

export function createLogger(requestId: string, orgId?: string): Logger {
  function emit(level: Level, msg: string, fields?: Record<string, unknown>): void {
    const entry: Record<string, unknown> = {
      ts:        new Date().toISOString(),
      level,
      msg,
      requestId,
    };
    if (orgId) entry.orgId = orgId;
    if (fields) {
      for (const [k, v] of Object.entries(fields)) {
        if (k === 'err' && v instanceof Error) {
          entry.err   = v.message;
          entry.stack = v.stack;
        } else {
          entry[k] = v;
        }
      }
    }
    console.log(JSON.stringify(entry));
  }

  return {
    debug: (msg, f) => emit('debug', msg, f),
    info:  (msg, f) => emit('info',  msg, f),
    warn:  (msg, f) => emit('warn',  msg, f),
    error: (msg, f) => emit('error', msg, f),
  };
}
