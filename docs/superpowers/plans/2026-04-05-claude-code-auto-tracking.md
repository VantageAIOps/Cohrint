# Claude Code Auto-Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically upload Claude Code token/cost data to the Cohrint dashboard — both backfilling all historical sessions and tracking each new turn in real-time via a Claude Code `Stop` hook.

**Architecture:** The `vantage-local-proxy` already has a `claudeCodeScanner` that reads `~/.claude/projects/*/uuid.jsonl`. We fix two bugs in `pushScanResults` (wrong endpoint, missing `event_id`), add per-turn deduplication via a state file, and wire a `Stop` hook in `~/.claude/settings.json` that uploads the latest assistant turn after every Claude response.

**Tech Stack:** Node.js 18+ (hook script), TypeScript (`vantage-local-proxy`), bash (hook shell entry point), `POST /v1/events/batch` (API endpoint), `~/.claude/vantage-state.json` (dedup state)

---

## Existing Bugs (must fix before anything works)

In `vantage-local-proxy/src/cli.ts` → `pushScanResults()`:

| Bug | Location | Fix |
|-----|----------|-----|
| Wrong endpoint | `fetch(\`${apiBase}/v1/events\`)` | Change to `/v1/events/batch` |
| Missing `event_id` | Event object has no `event_id` | Add `event_id: \`${s.sessionId}-scan\`` |
| Wrong field name | `cached_tokens` | Change to `cache_tokens` |

These mean every push attempt currently fails with 400/404 silently.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `vantage-local-proxy/src/cli.ts` | Modify | Fix bugs + add per-turn push + dedup |
| `~/.claude/hooks/vantage-track.js` | Create | Stop hook: upload latest assistant turn |
| `~/.claude/settings.json` | Modify | Register `Stop` hook |

State file created at runtime: `~/.claude/vantage-state.json`

---

## Task 1: Fix `pushScanResults` bugs in `cli.ts`

**Files:**
- Modify: `vantage-local-proxy/src/cli.ts` (lines 220–266)

- [ ] **Step 1: Read the current file**

```bash
cat vantage-local-proxy/src/cli.ts | grep -n "pushScanResults" -A 50
```

Expected: shows the broken function with `/v1/events` and missing `event_id`.

- [ ] **Step 2: Replace the entire `pushScanResults` function**

Replace the function at the bottom of `vantage-local-proxy/src/cli.ts` (from `async function pushScanResults(` to the closing `}`) with:

```typescript
async function pushScanResults(
  result: ScanResult,
  apiKey: string,
  apiBase: string,
): Promise<void> {
  console.log("  Pushing scan results to Cohrint...");

  // Load dedup state — skip sessions already uploaded
  const stateFile = join(homedir(), ".claude", "vantage-state.json");
  let uploadedIds: Set<string> = new Set();
  try {
    const raw = await readFile(stateFile, "utf-8");
    const state = JSON.parse(raw) as { uploadedIds?: string[] };
    uploadedIds = new Set(state.uploadedIds ?? []);
  } catch {
    // First run — state file doesn't exist yet
  }

  // Build one event per assistant turn (per message, not per session)
  const events: Record<string, unknown>[] = [];
  for (const s of result.sessions) {
    for (let i = 0; i < s.messages.length; i++) {
      const m = s.messages[i];
      // Use ISO timestamp + index as a stable dedup key
      const eventId = `${s.sessionId}-${m.timestamp}-${i}`;
      if (uploadedIds.has(eventId)) continue;

      events.push({
        event_id:         eventId,
        provider:         s.provider,
        model:            m.model,
        prompt_tokens:    m.inputTokens,
        completion_tokens: m.outputTokens,
        cache_tokens:     m.cacheReadTokens,
        total_tokens:     m.inputTokens + m.outputTokens,
        total_cost_usd:   m.costUsd,
        environment:      "local",
        agent_name:       "claude-code",
        timestamp:        m.timestamp,
        tags:             { tool: s.tool, scanner: "local-file", session: s.sessionId },
      });
    }
  }

  if (events.length === 0) {
    console.log("  Nothing new to upload — all sessions already pushed.\n");
    return;
  }

  console.log(`  Uploading ${events.length} new turns (${result.sessions.length} sessions)...`);

  // Send in batches of 500 (API max)
  const newIds: string[] = [];
  for (let i = 0; i < events.length; i += 500) {
    const batch = events.slice(i, i + 500);
    try {
      const res = await fetch(`${apiBase}/v1/events/batch`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          events: batch,
          sdk_version: "1.0.0",
          sdk_language: "local-scanner",
        }),
      });
      if (res.ok) {
        newIds.push(...batch.map((e) => e.event_id as string));
        console.log(`  Batch ${Math.floor(i / 500) + 1}: ${batch.length} turns → ${res.status}`);
      } else {
        const err = await res.text();
        console.error(`  Batch ${Math.floor(i / 500) + 1} failed: ${res.status} ${err}`);
      }
    } catch (err) {
      console.error(`  Network error on batch ${Math.floor(i / 500) + 1}: ${err}`);
    }
  }

  // Save updated dedup state
  const updated = [...uploadedIds, ...newIds];
  await writeFile(stateFile, JSON.stringify({ uploadedIds: updated, lastUploadAt: new Date().toISOString() }, null, 2));
  console.log(`  Done — uploaded ${newIds.length} turns. State saved to ${stateFile}\n`);
}
```

- [ ] **Step 3: Add missing imports at top of `cli.ts`**

The function uses `readFile`, `writeFile`, `homedir`. Add to existing imports:

```typescript
import { readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
```

Check if they're already imported first — if `readFile` is already there from another import, just add the missing ones. The file currently imports from `"./scanners/index.js"` and `"./proxy-server.js"` — add the node imports at the top.

- [ ] **Step 4: Build the package**

```bash
cd vantage-local-proxy && npm run build
```

Expected: `dist/cli.js` and `dist/index.js` rebuilt with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
cd vantage-local-proxy
git add src/cli.ts
git commit -m "fix(proxy): fix pushScanResults — correct endpoint, event_id, dedup per turn"
```

---

## Task 2: Run the backfill (upload all historical sessions)

**Files:** None (runs the fixed CLI)

- [ ] **Step 1: Run the scan + push**

```bash
COHRINT_API_KEY=crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba \
  node vantage-local-proxy/dist/cli.js scan --tool claude-code --push
```

Expected output:
```
  Cohrint Local File Scanner
  Checking Claude Code      FOUND
  ...
  Uploading NNN new turns (MM sessions)...
  Batch 1: 500 turns → 201
  ...
  Done — uploaded NNN turns. State saved to ~/.claude/vantage-state.json
```

- [ ] **Step 2: Verify data appears in dashboard**

```bash
node -e "
const fetch = (...args) => import('node-fetch').then(({default: f}) => f(...args));
// Use built-in fetch (Node 18+)
" 
```

Actually just curl:
```bash
curl -s "https://api.cohrint.com/v1/analytics/kpis" \
  -H "Authorization: Bearer crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba" | python3 -m json.tool
```

Expected: `total_requests` > 3 (was 3 before backfill), `total_cost_usd` > 0.

- [ ] **Step 3: Verify dedup works (running twice is safe)**

```bash
COHRINT_API_KEY=crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba \
  node vantage-local-proxy/dist/cli.js scan --tool claude-code --push
```

Expected: `Nothing new to upload — all sessions already pushed.`

---

## Task 3: Create the Stop hook script

**Files:**
- Create: `~/.claude/hooks/vantage-track.js`

This script runs after every Claude response. It reads the most recent assistant message from the current project's JSONL file and uploads it as a single event.

- [ ] **Step 1: Create `~/.claude/hooks/vantage-track.js`**

```javascript
#!/usr/bin/env node
/**
 * Cohrint Claude Code Stop Hook
 *
 * Called after every Claude response. Reads the latest assistant turn
 * from the current project's JSONL file and uploads it to Cohrint.
 *
 * Requires: COHRINT_API_KEY env var (set in ~/.claude/settings.json hook env)
 */

import { readdir, readFile, writeFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";

const API_KEY  = process.env.COHRINT_API_KEY ?? "";
const API_BASE = process.env.VANTAGE_API_BASE ?? "https://api.cohrint.com";
const STATE_FILE = join(homedir(), ".claude", "vantage-state.json");

// Pricing table (must stay in sync with vantage-local-proxy/src/pricing.ts)
const PRICES = {
  "claude-opus-4-6":   { input: 15.00, output: 75.00, cache: 1.50  },
  "claude-sonnet-4-6": { input: 3.00,  output: 15.00, cache: 0.30  },
  "claude-haiku-4-5":  { input: 0.80,  output: 4.00,  cache: 0.08  },
  "claude-3-5-sonnet": { input: 3.00,  output: 15.00, cache: 0.30  },
  "claude-3-haiku":    { input: 0.25,  output: 1.25,  cache: 0.03  },
};

function calcCost(model, inputTokens, outputTokens, cacheReadTokens = 0) {
  const key = Object.keys(PRICES).find(k => model.includes(k) || k.includes(model));
  const price = key ? PRICES[key] : { input: 0, output: 0, cache: 0 };
  const uncached = Math.max(0, inputTokens - cacheReadTokens);
  return (uncached / 1e6) * price.input
       + (cacheReadTokens / 1e6) * price.cache
       + (outputTokens / 1e6) * price.output;
}

async function loadState() {
  try {
    const raw = await readFile(STATE_FILE, "utf-8");
    return JSON.parse(raw);
  } catch {
    return { uploadedIds: [] };
  }
}

async function saveState(state) {
  await writeFile(STATE_FILE, JSON.stringify(state, null, 2));
}

// Find project slug for current working directory
function dirToSlug(dir) {
  return dir.replace(/\//g, "-").replace(/^-/, "");
}

// Find the most recent JSONL files for the current project
async function findProjectJsonlFiles(projectsDir, cwd) {
  const slug = dirToSlug(cwd);
  const slugDir = join(projectsDir, slug);
  try {
    const entries = await readdir(slugDir, { withFileTypes: true });
    return entries
      .filter(e => e.isFile() && e.name.endsWith(".jsonl"))
      .map(e => join(slugDir, e.name));
  } catch {
    return [];
  }
}

// Parse new assistant messages from a JSONL file
async function parseNewMessages(filePath, uploadedIds) {
  let content;
  try {
    content = await readFile(filePath, "utf-8");
  } catch {
    return [];
  }

  const events = [];
  const lines = content.split("\n").filter(l => l.trim());

  for (let i = 0; i < lines.length; i++) {
    let entry;
    try { entry = JSON.parse(lines[i]); } catch { continue; }

    if (entry.type !== "assistant" || !entry.message?.usage) continue;

    const usage = entry.message.usage;
    const model = entry.message.model ?? "unknown";
    const sessionId = entry.sessionId ?? entry.uuid?.split("-")[0] ?? "unknown";
    const msgUuid = entry.uuid ?? `${sessionId}-${i}`;
    const eventId = `${sessionId}-${msgUuid}`;

    if (uploadedIds.has(eventId)) continue;

    const inputTokens = (usage.input_tokens ?? 0) + (usage.cache_creation_input_tokens ?? 0);
    const outputTokens = usage.output_tokens ?? 0;
    const cacheRead = usage.cache_read_input_tokens ?? 0;

    events.push({
      eventId,
      event: {
        event_id:          eventId,
        provider:          "anthropic",
        model,
        prompt_tokens:     inputTokens,
        completion_tokens: outputTokens,
        cache_tokens:      cacheRead,
        total_tokens:      inputTokens + outputTokens,
        total_cost_usd:    calcCost(model, inputTokens, outputTokens, cacheRead),
        environment:       "local",
        agent_name:        "claude-code",
        timestamp:         entry.timestamp,
        tags:              { tool: "claude-code", hook: "stop" },
      },
    });
  }

  return events;
}

async function main() {
  if (!API_KEY) {
    // Silent exit — hook must not break Claude Code if unconfigured
    process.exit(0);
  }

  const cwd = process.cwd();
  const projectsDir = join(homedir(), ".claude", "projects");

  const state = await loadState();
  const uploadedIds = new Set(state.uploadedIds ?? []);

  const files = await findProjectJsonlFiles(projectsDir, cwd);
  if (files.length === 0) process.exit(0);

  const allNew = [];
  for (const f of files) {
    const msgs = await parseNewMessages(f, uploadedIds);
    allNew.push(...msgs);
  }

  if (allNew.length === 0) process.exit(0);

  // Upload
  try {
    const res = await fetch(`${API_BASE}/v1/events/batch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${API_KEY}`,
      },
      body: JSON.stringify({
        events: allNew.map(e => e.event),
        sdk_version: "hook-1.0",
        sdk_language: "node-hook",
      }),
    });

    if (res.ok) {
      // Update state with newly uploaded IDs
      const newIds = allNew.map(e => e.eventId);
      state.uploadedIds = [...(state.uploadedIds ?? []), ...newIds];
      state.lastUploadAt = new Date().toISOString();
      await saveState(state);
    }
  } catch {
    // Silent — never let hook failures break Claude Code
  }

  process.exit(0);
}

main();
```

- [ ] **Step 2: Make the script executable**

```bash
chmod +x ~/.claude/hooks/vantage-track.js
```

- [ ] **Step 3: Smoke test the script manually**

```bash
COHRINT_API_KEY=crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba \
  node ~/.claude/hooks/vantage-track.js
```

Expected: exits silently (no errors). If it's the first run after backfill, it will upload nothing (all already in state). If run before backfill, it will upload recent turns.

Check API to verify:
```bash
curl -s "https://api.cohrint.com/v1/analytics/kpis" \
  -H "Authorization: Bearer crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba" | python3 -m json.tool
```

---

## Task 4: Register the Stop hook in Claude Code settings

**Files:**
- Modify: `~/.claude/settings.json`

- [ ] **Step 1: Read current settings**

```bash
cat ~/.claude/settings.json
```

- [ ] **Step 2: Add the `Stop` hook**

Add to the `hooks` object in `~/.claude/settings.json` (alongside existing `PreToolUse` and `PostToolUse`):

```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "COHRINT_API_KEY=crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba node ~/.claude/hooks/vantage-track.js"
      }
    ]
  }
]
```

The full `hooks` section should look like:

```json
"hooks": {
  "PreToolUse": [
    {
      "matcher": "Bash",
      "hooks": [
        {
          "type": "command",
          "command": "echo 'Bash command executing'"
        }
      ]
    }
  ],
  "PostToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [
        {
          "type": "command",
          "command": "~/.claude/hooks/lint-on-save.sh \"$CLAUDE_FILE_PATH\""
        }
      ]
    }
  ],
  "Stop": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "COHRINT_API_KEY=crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba node ~/.claude/hooks/vantage-track.js"
        }
      ]
    }
  ]
}
```

- [ ] **Step 3: Verify settings are valid JSON**

```bash
python3 -c "import json; json.load(open(f'{__import__(\"os\").path.expanduser(\"~\")}/.claude/settings.json')); print('JSON valid')"
```

Expected: `JSON valid`

- [ ] **Step 4: Commit the hook script**

```bash
git add ~/.claude/hooks/vantage-track.js 2>/dev/null || true
# settings.json is global config — don't commit it to the repo
# Just commit the hook script if it's in the repo
cd "/Users/amanjain/Documents/New Ideas/AI Cost Analysis/Cloudfare based/vantageai"
git add vantage-local-proxy/src/cli.ts
git commit -m "feat(tracking): add Claude Code Stop hook + fix backfill push"
```

---

## Task 5: End-to-end verification

- [ ] **Step 1: Check dashboard data increased from backfill**

```bash
curl -s "https://api.cohrint.com/v1/analytics/kpis" \
  -H "Authorization: Bearer crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba" | python3 -m json.tool
```

Expected:
- `total_requests` much higher than 3
- `total_cost_usd` reflects actual Claude Code usage
- `today_cost_usd` > 0 if today's sessions were scanned

- [ ] **Step 2: Check cross-platform summary also reflects data**

```bash
curl -s "https://api.cohrint.com/v1/cross-platform/summary?days=30" \
  -H "Authorization: Bearer crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba" | python3 -m json.tool
```

Note: cross-platform reads from `cross_platform_usage` table (OTel/billing) — if it's still zero, that's expected since we're writing to `events` table. The main dashboard analytics will show data.

- [ ] **Step 3: Trigger hook manually to confirm real-time tracking works**

Open a new Claude Code conversation and send a message. After the response, wait 2-3 seconds, then check:

```bash
curl -s "https://api.cohrint.com/v1/analytics/summary" \
  -H "Authorization: Bearer crt_aaravbagraab_465dd2e76ca2abe8914305acf3964eba" | python3 -m json.tool
```

The `session_cost_usd` (30-min window) should increase.

- [ ] **Step 4: Confirm state file deduplication**

```bash
cat ~/.claude/vantage-state.json | python3 -c "import sys,json; s=json.load(sys.stdin); print(f'Uploaded IDs: {len(s[\"uploadedIds\"])}\\nLast upload: {s[\"lastUploadAt\"]}')"
```

Expected: thousands of IDs from backfill, plus recent hook uploads.

---

## Known Limitations

- **`cross_platform_usage` vs `events`**: The dashboard's "All AI Spend" cross-platform view reads from `cross_platform_usage` (OTel/billing). This plan writes to `events` (analytics). The main analytics tab (`/v1/analytics/*`) will show data; the cross-platform tab will remain empty until OTel is configured separately.
- **Free tier cap**: The API has a 10,000 event/month free tier. If the backfill exceeds this, it will return 429. Upgrade to Team plan or run incrementally using `--since 2026-04-01`.
- **Session granularity**: The hook uploads per-turn events after each Claude response, giving near-real-time data (within seconds of each turn).
