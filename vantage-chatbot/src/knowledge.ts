import type { Env, KnowledgeEntry } from "./types";
import STATIC from "../knowledge/static.json";

const entries = STATIC as KnowledgeEntry[];

function score(text: string, query: string): number {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  const words = q.split(/\s+/).filter((w) => w.length > 2);
  return words.filter((w) => t.includes(w)).length;
}

/** Load doc chunks from KV. All chunks are stored under one key ("docs:chunks")
 *  to keep uploads at 1 KV write regardless of how many headings docs.html has. */
async function loadDocChunks(
  env: Env
): Promise<Array<{ heading: string; body: string }>> {
  const raw = await env.VEGA_KV.get("docs:chunks");
  if (!raw) return [];
  try {
    return JSON.parse(raw) as Array<{ heading: string; body: string }>;
  } catch {
    return [];
  }
}

export async function lookup(
  query: string,
  plan: string,
  env: Env
): Promise<KnowledgeEntry[]> {
  // Score static Q&A entries
  const allowed = entries.filter((e) => {
    if (!e.plan_gate) return true;
    if (e.plan_gate === "pro") return plan === "pro" || plan === "enterprise";
    if (e.plan_gate === "enterprise") return plan === "enterprise";
    return true;
  });

  const scored = allowed
    .map((e) => ({ entry: e, score: score(e.q + " " + e.a + " " + e.tags.join(" "), query) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((x) => x.entry);

  // Score doc chunks in-memory (single KV read for all chunks)
  const docChunks = await loadDocChunks(env);
  const topChunk = docChunks
    .map((c) => ({ c, s: score(c.heading + " " + c.body, query) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)[0];

  if (topChunk) {
    scored.push({
      q: topChunk.c.heading,
      a: topChunk.c.body,
      tags: ["docs"],
    });
  }

  return scored;
}
