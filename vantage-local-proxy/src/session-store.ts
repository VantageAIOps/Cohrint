import { promises as fs, readFileSync } from "fs";
import { homedir } from "os";
import { join } from "path";

export const DEFAULT_SESSIONS_DIR = join(homedir(), ".vantage", "sessions");

export interface PersistedEvent {
  event_id: string;
  timestamp: number;
  provider: string;
  model: string;
  endpoint: string;
  team: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_total_usd: number;
  latency_ms: number;
  status_code: number;
  error?: string;
  source: "local-proxy";
}

export interface ProxySessionRecord {
  id: string;
  source: "local-proxy";
  created_at: string;
  last_active_at: string;
  org_id: string;
  team: string;
  environment: string;
  events: PersistedEvent[];
  cost_summary: {
    total_cost_usd: number;
    total_input_tokens: number;
    total_completion_tokens: number;
    event_count: number;
  };
}

export class SessionStore {
  constructor(private sessionsDir: string = DEFAULT_SESSIONS_DIR) {}

  private path(id: string): string {
    return join(this.sessionsDir, `${id}.json`);
  }

  async save(session: ProxySessionRecord): Promise<void> {
    await fs.mkdir(this.sessionsDir, { recursive: true });
    session.last_active_at = new Date().toISOString();
    await fs.writeFile(this.path(session.id), JSON.stringify(session, null, 2));
  }

  async load(id: string): Promise<ProxySessionRecord> {
    return JSON.parse(await fs.readFile(this.path(id), "utf-8"));
  }

  loadSync(id: string): ProxySessionRecord | null {
    try {
      return JSON.parse(readFileSync(this.path(id), "utf-8")) as ProxySessionRecord;
    } catch {
      return null;
    }
  }

  async listAll(): Promise<ProxySessionRecord[]> {
    await fs.mkdir(this.sessionsDir, { recursive: true });
    const files = (await fs.readdir(this.sessionsDir)).filter(f => f.endsWith(".json"));
    const sessions: ProxySessionRecord[] = [];
    for (const f of files) {
      try { sessions.push(JSON.parse(await fs.readFile(join(this.sessionsDir, f), "utf-8"))); }
      catch { /* skip corrupt */ }
    }
    return sessions.sort((a, b) =>
      new Date(b.last_active_at).getTime() - new Date(a.last_active_at).getTime());
  }
}
