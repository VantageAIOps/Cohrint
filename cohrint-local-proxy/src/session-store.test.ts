/**
 * TDD tests for session-store.ts
 * Written before verifying implementation passes — each was watched to fail.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtemp, rm } from "fs/promises";
import { tmpdir } from "os";
import { join } from "path";
import { SessionStore, ProxySessionRecord, PersistedEvent } from "./session-store.js";

function makeEvent(id = "evt-1"): PersistedEvent {
  return {
    event_id: id,
    timestamp: Date.now(),
    provider: "anthropic",
    model: "claude-sonnet-4-6",
    endpoint: "/v1/messages",
    team: "eng",
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    cost_total_usd: 0.001,
    latency_ms: 250,
    status_code: 200,
    source: "local-proxy",
  };
}

function makeSession(id = "sess-abc"): ProxySessionRecord {
  return {
    id,
    source: "local-proxy",
    created_at: new Date().toISOString(),
    last_active_at: new Date().toISOString(),
    org_id: "org-1",
    team: "eng",
    environment: "dev",
    events: [makeEvent()],
    cost_summary: {
      total_cost_usd: 0.001,
      total_input_tokens: 100,
      total_completion_tokens: 50,
      event_count: 1,
    },
  };
}

let tmpDir: string;
let store: SessionStore;

beforeEach(async () => {
  tmpDir = await mkdtemp(join(tmpdir(), "vantage-test-"));
  store = new SessionStore(tmpDir);
});

afterEach(async () => {
  await rm(tmpDir, { recursive: true, force: true });
});

// ── RED → GREEN ────────────────────────────────────────────────────────────

describe("SessionStore.save + load", () => {
  it("saves a session and load returns the same data", async () => {
    const session = makeSession("sess-1");
    await store.save(session);
    const loaded = await store.load("sess-1");
    expect(loaded.id).toBe("sess-1");
    expect(loaded.org_id).toBe("org-1");
    expect(loaded.events).toHaveLength(1);
    expect(loaded.events[0].event_id).toBe("evt-1");
  });

  it("save updates last_active_at to current time", async () => {
    const session = makeSession();
    const before = Date.now();
    await store.save(session);
    const loaded = await store.load(session.id);
    const savedTime = new Date(loaded.last_active_at).getTime();
    expect(savedTime).toBeGreaterThanOrEqual(before);
  });

  it("save overwrites existing session file", async () => {
    const session = makeSession("sess-2");
    await store.save(session);
    session.team = "infra";
    await store.save(session);
    const loaded = await store.load("sess-2");
    expect(loaded.team).toBe("infra");
  });

  it("load throws when session does not exist", async () => {
    await expect(store.load("nonexistent-id")).rejects.toThrow();
  });

  it("save creates the sessions directory if missing", async () => {
    const nested = join(tmpDir, "deep", "dir");
    const nestedStore = new SessionStore(nested);
    const session = makeSession("sess-nested");
    await expect(nestedStore.save(session)).resolves.not.toThrow();
    const loaded = await nestedStore.load("sess-nested");
    expect(loaded.id).toBe("sess-nested");
  });
});

describe("SessionStore.listAll", () => {
  it("returns empty array when no sessions exist", async () => {
    const sessions = await store.listAll();
    expect(sessions).toEqual([]);
  });

  it("returns all saved sessions", async () => {
    await store.save(makeSession("a"));
    await store.save(makeSession("b"));
    await store.save(makeSession("c"));
    const sessions = await store.listAll();
    expect(sessions).toHaveLength(3);
  });

  it("sorts sessions by last_active_at descending (most recent first)", async () => {
    const s1 = makeSession("old");
    s1.last_active_at = "2024-01-01T00:00:00.000Z";
    const s2 = makeSession("new");
    s2.last_active_at = "2025-01-01T00:00:00.000Z";
    // Write files directly to avoid save() overwriting last_active_at
    const { writeFile } = await import("fs/promises");
    await writeFile(join(tmpDir, "old.json"), JSON.stringify(s1));
    await writeFile(join(tmpDir, "new.json"), JSON.stringify(s2));
    const sessions = await store.listAll();
    expect(sessions[0].id).toBe("new");
    expect(sessions[1].id).toBe("old");
  });

  it("skips corrupt JSON files without throwing", async () => {
    const { writeFile } = await import("fs/promises");
    await writeFile(join(tmpDir, "corrupt.json"), "not valid json{{");
    await store.save(makeSession("good"));
    const sessions = await store.listAll();
    expect(sessions).toHaveLength(1);
    expect(sessions[0].id).toBe("good");
  });

  it("ignores non-json files in directory", async () => {
    const { writeFile } = await import("fs/promises");
    await writeFile(join(tmpDir, "readme.txt"), "hello");
    await store.save(makeSession("s1"));
    const sessions = await store.listAll();
    expect(sessions).toHaveLength(1);
  });

  it("creates directory if missing before listing", async () => {
    const fresh = join(tmpDir, "fresh-sessions");
    const freshStore = new SessionStore(fresh);
    await expect(freshStore.listAll()).resolves.toEqual([]);
  });
});

describe("SessionStore data integrity", () => {
  it("persists all PersistedEvent fields correctly", async () => {
    const event = makeEvent("evt-full");
    event.error = "timeout";
    const session = makeSession("sess-full");
    session.events = [event];
    await store.save(session);
    const loaded = await store.load("sess-full");
    expect(loaded.events[0].error).toBe("timeout");
    expect(loaded.events[0].provider).toBe("anthropic");
    expect(loaded.events[0].latency_ms).toBe(250);
  });

  it("persists cost_summary totals correctly", async () => {
    const session = makeSession("sess-cost");
    session.cost_summary.total_cost_usd = 1.2345;
    session.cost_summary.event_count = 42;
    await store.save(session);
    const loaded = await store.load("sess-cost");
    expect(loaded.cost_summary.total_cost_usd).toBe(1.2345);
    expect(loaded.cost_summary.event_count).toBe(42);
  });
});
