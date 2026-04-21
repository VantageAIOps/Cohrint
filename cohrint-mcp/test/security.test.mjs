// Unit tests for cohrint-mcp security helpers.
// Run with `npm test` (delegates to `node --test`). Uses the compiled JS
// so the test is decoupled from the TS toolchain.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  LIMITS,
  READ_ONLY_TOOLS,
  WRITE_TOOLS,
  resolveAllowedTools,
  sanitizeString,
  escapeMd,
  redactKey,
  assertToolAllowed,
} from '../dist/security.js';

test('sanitizeString strips control chars but keeps \\t \\n \\r', () => {
  const input = 'hello\x00\x01world\n\t\x1b[31mok\x7f';
  const out = sanitizeString(input, 1000);
  assert.equal(out.includes('\x00'), false);
  assert.equal(out.includes('\x1b'), false);
  assert.equal(out.includes('\x7f'), false);
  assert.ok(out.includes('\n'));
  assert.ok(out.includes('\t'));
  assert.ok(out.includes('hello'));
  assert.ok(out.includes('world'));
  assert.ok(out.includes('ok'));
});

test('sanitizeString truncates to maxLen', () => {
  const input = 'a'.repeat(1_000_000);
  assert.equal(sanitizeString(input, 128).length, 128);
});

test('sanitizeString coerces non-strings', () => {
  assert.equal(sanitizeString(null, 10), '');
  assert.equal(sanitizeString(undefined, 10), '');
  assert.equal(sanitizeString(42, 10), '42');
  assert.equal(sanitizeString({ a: 1 }, 20), '[object Object]');
});

test('escapeMd neutralises pipe + newline', () => {
  assert.equal(escapeMd('foo|bar'), 'foo\\|bar');
  assert.equal(escapeMd('line1\nline2'), 'line1 line2');
  // Idempotent for already-safe text.
  assert.equal(escapeMd('plain'), 'plain');
});

test('redactKey no-ops on empty/short keys (never swallow whole message)', () => {
  assert.equal(redactKey('some error: unauthorized', ''),      'some error: unauthorized');
  assert.equal(redactKey('some error: unauthorized', 'short'), 'some error: unauthorized');
  // Prefix-only key (no secret portion) → short-circuit unchanged.
  assert.equal(redactKey('abc', 'crt_org1_xx'),                'abc');
});

test('redactKey masks only the secret tail of a crt_<org>_<secret> key', () => {
  const key = 'crt_org1_TOPSECRETVALUE';
  assert.equal(redactKey(`boom: ${key} failed`, key),          'boom: crt_org1_**** failed');
  // Raw secret substring also gets masked — belt-and-braces.
  assert.equal(redactKey('tail TOPSECRETVALUE here', key),     'tail **** here');
  // Unrelated text is untouched.
  assert.equal(redactKey('no secret here', key),               'no secret here');
});

test('resolveAllowedTools defaults to read-only', () => {
  const def = resolveAllowedTools(undefined);
  for (const t of READ_ONLY_TOOLS) assert.ok(def.has(t));
  for (const t of WRITE_TOOLS)     assert.ok(!def.has(t), `write tool ${t} leaked into default set`);
});

test('resolveAllowedTools "all" enables write tools', () => {
  const all = resolveAllowedTools('all');
  for (const t of WRITE_TOOLS) assert.ok(all.has(t));
});

test('resolveAllowedTools honours explicit whitelist', () => {
  const s = resolveAllowedTools('get_summary, get_kpis');
  assert.deepEqual([...s].sort(), ['get_kpis', 'get_summary']);
});

test('assertToolAllowed throws for disabled tool with actionable hint', () => {
  const allowed = resolveAllowedTools(undefined);
  assert.throws(
    () => assertToolAllowed('setup_claude_hook', allowed),
    /COHRINT_MCP_ALLOW_SETUP=1.*COHRINT_MCP_ALLOWED_TOOLS=setup_claude_hook/s,
  );
  assert.throws(
    () => assertToolAllowed('nonexistent_tool', allowed),
    /COHRINT_MCP_ALLOWED_TOOLS=nonexistent_tool/,
  );
});

test('assertToolAllowed succeeds for enabled tool', () => {
  const allowed = resolveAllowedTools(undefined);
  assert.doesNotThrow(() => assertToolAllowed('get_summary', allowed));
});

test('LIMITS exposes the expected caps', () => {
  assert.equal(LIMITS.MAX_PROMPT_CHARS, 200_000);
  assert.equal(LIMITS.MAX_MESSAGE_CHARS, 50_000);
  assert.equal(LIMITS.MAX_MESSAGES, 1_000);
  assert.equal(LIMITS.MAX_TAG_CHARS, 256);
});
