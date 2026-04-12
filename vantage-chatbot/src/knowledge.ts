import type { Env, KnowledgeEntry } from "./types";
import STATIC from "../knowledge/static.json";

const entries = STATIC as KnowledgeEntry[];

function score(entry: KnowledgeEntry, query: string): number {
  const q = query.toLowerCase();
  const text = (entry.q + " " + entry.a + " " + entry.tags.join(" ")).toLowerCase();
  const words = q.split(/\s+/).filter((w) => w.length > 2);
  return words.filter((w) => text.includes(w)).length;
}

export async function lookup(
  query: string,
  plan: string,
  env: Env
): Promise<KnowledgeEntry[]> {
  const allowed = entries.filter((e) => {
    if (!e.plan_gate) return true;
    if (e.plan_gate === "pro") return plan === "pro" || plan === "enterprise";
    if (e.plan_gate === "enterprise") return plan === "enterprise";
    return true;
  });

  const scored = allowed
    .map((e) => ({ entry: e, score: score(e, query) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((x) => x.entry);

  const kvKey = `chunk:${query.slice(0, 40).replace(/\W/g, "_")}`;
  const chunk = await env.VEGA_KV.get(kvKey);
  if (chunk) {
    scored.push({ q: "doc chunk", a: chunk, tags: ["docs"] });
  }

  return scored;
}
