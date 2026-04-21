// Minimal Upstash Redis HTTP client — rate limiting only.
// Uses pipeline to batch INCR + EXPIRE into a single HTTP round-trip.
// Configure via wrangler secrets: UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN

interface PipelineResult {
  result: number | string | null;
  error?: string;
}

export async function redisPipeline(
  url: string,
  token: string,
  commands: [string, ...string[]][],
): Promise<PipelineResult[]> {
  const res = await fetch(`${url}/pipeline`, {
    method:  'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body:    JSON.stringify(commands),
  });
  if (!res.ok) throw new Error(`Upstash pipeline ${res.status}`);
  return res.json() as Promise<PipelineResult[]>;
}
