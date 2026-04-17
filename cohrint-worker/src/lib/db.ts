// Enforces per-org query isolation at the SQL layer.
// Every query through scopedDb MUST include {{ORG_SCOPE}} — this is replaced
// with `org_id = ?` and the orgId is auto-injected at the correct binding position.
// Queries without {{ORG_SCOPE}} throw ScopeViolationError (wrong-thing-impossible pattern).

export class ScopeViolationError extends Error {
  constructor(sql: string) {
    super(`Missing {{ORG_SCOPE}} in scoped query: ${sql.slice(0, 100)}`)
    this.name = 'ScopeViolationError'
  }
}

const PLACEHOLDER = '{{ORG_SCOPE}}'
const PLACEHOLDER_LEN = PLACEHOLDER.length

function buildPositions(sql: string): { resolved: string; orgIdPositions: number[]; totalQ: number } {
  const resolved = sql.replaceAll(PLACEHOLDER, 'org_id = ?')
  const orgIdPositions: number[] = []
  let qPos = 0
  let i = 0
  while (i < sql.length) {
    if (sql.startsWith(PLACEHOLDER, i)) {
      orgIdPositions.push(qPos++)
      i += PLACEHOLDER_LEN
    } else if (sql[i] === '?') {
      qPos++
      i++
    } else {
      i++
    }
  }
  return { resolved, orgIdPositions, totalQ: qPos }
}

function injectOrgId(orgId: string, orgIdPositions: number[], totalQ: number, userArgs: unknown[]): unknown[] {
  const result: unknown[] = new Array(totalQ)
  let userIdx = 0
  for (let p = 0; p < totalQ; p++) {
    result[p] = orgIdPositions.includes(p) ? orgId : userArgs[userIdx++]
  }
  return result
}

export function scopedDb(db: D1Database, orgId: string) {
  function prepare(sql: string) {
    if (!sql.includes(PLACEHOLDER)) throw new ScopeViolationError(sql)
    const { resolved, orgIdPositions, totalQ } = buildPositions(sql)
    const inject = (userArgs: unknown[]) => injectOrgId(orgId, orgIdPositions, totalQ, userArgs)

    return {
      bind(...userArgs: unknown[]): D1PreparedStatement {
        return db.prepare(resolved).bind(...inject(userArgs))
      },
      first<T>(colName?: string): Promise<T | null> {
        const stmt = db.prepare(resolved).bind(...inject([]))
        return colName !== undefined ? stmt.first<T>(colName) : stmt.first<T>()
      },
      all<T>(): Promise<D1Result<T>> {
        return db.prepare(resolved).bind(...inject([])).all<T>()
      },
      run(): Promise<D1Result> {
        return db.prepare(resolved).bind(...inject([])).run()
      },
    }
  }
  return { prepare }
}
