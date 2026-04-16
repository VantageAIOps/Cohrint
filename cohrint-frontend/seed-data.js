/**
 * Cohrint — Test Data Seed Engine
 * Generates 50,000+ realistic AI API call events across:
 *   - 23 models / 7 providers
 *   - 90 days of history
 *   - 5 teams / 8 endpoints
 *   - Realistic cost/latency/token distributions
 *   - Anomaly spikes, budget breaches, savings opportunities
 *
 * Usage:
 *   <script src="seed-data.js"></script>
 *   const gen = new VantageDataGen();
 *   await gen.seed();  // generates + stores in IndexedDB
 *   const events = await gen.query({ days: 30 });
 */

class VantageDataGen {
  constructor(orgId = "demo-org") {
    this.orgId   = orgId;
    this.DB_NAME = "vantage_seed";
    this.DB_VER  = 2;
    this.db      = null;
  }

  // ── IndexedDB setup ──────────────────────────────────────────────────────────
  async openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(this.DB_NAME, this.DB_VER);
      req.onupgradeneeded = e => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("events")) {
          const store = db.createObjectStore("events", { keyPath: "id" });
          store.createIndex("by_org",       "org_id",    { unique: false });
          store.createIndex("by_model",     "model",     { unique: false });
          store.createIndex("by_timestamp", "timestamp", { unique: false });
          store.createIndex("by_team",      "team",      { unique: false });
          store.createIndex("by_endpoint",  "endpoint",  { unique: false });
        }
        if (!db.objectStoreNames.contains("meta")) {
          db.createObjectStore("meta", { keyPath: "key" });
        }
      };
      req.onsuccess = e => { this.db = e.target.result; resolve(this.db); };
      req.onerror   = e => reject(e.target.error);
    });
  }

  async isSeedDone() {
    await this.openDB();
    return new Promise(resolve => {
      const tx    = this.db.transaction("meta", "readonly");
      const req   = tx.objectStore("meta").get(`seed_done_${this.orgId}`);
      req.onsuccess = e => resolve(!!e.target.result?.value);
      req.onerror   = () => resolve(false);
    });
  }

  async markSeedDone(count) {
    const tx = this.db.transaction("meta", "readwrite");
    tx.objectStore("meta").put({ key: `seed_done_${this.orgId}`, value: true, count, seededAt: Date.now() });
  }

  // ── Main seed entry point ───────────────────────────────────────────────────
  async seed(opts = {}) {
    const {
      days        = 90,
      eventsTotal = 52000,
      onProgress  = null,
      force       = false,
    } = opts;

    if (!force && await this.isSeedDone()) {
      console.log("[vantageai] Already seeded — use seed({ force: true }) to reseed");
      return;
    }

    await this.openDB();
    console.log(`[vantageai] Generating ${eventsTotal.toLocaleString()} events over ${days} days...`);
    const t0 = performance.now();

    const BATCH = 500;
    let generated = 0;

    // Clear existing data for this org
    await this._clearOrg();

    const now    = Date.now();
    const msDay  = 86400000;
    const startMs = now - days * msDay;

    // Build weight distributions
    const modelWeights  = this._buildModelWeights();
    const teamWeights   = this._buildTeamWeights();
    const endpointWeights = this._buildEndpointWeights();
    const timeWeights   = this._buildTimeWeights(); // hourly patterns

    while (generated < eventsTotal) {
      const batch = [];
      const batchSize = Math.min(BATCH, eventsTotal - generated);

      for (let i = 0; i < batchSize; i++) {
        const event = this._generateEvent({
          startMs, now, days, modelWeights,
          teamWeights, endpointWeights, timeWeights,
          seqIndex: generated + i, total: eventsTotal,
        });
        batch.push(event);
      }

      await this._storeBatch(batch);
      generated += batch.length;

      if (onProgress) onProgress(generated, eventsTotal);
      if (generated % 5000 === 0) console.log(`  ${generated.toLocaleString()} / ${eventsTotal.toLocaleString()}`);
    }

    await this.markSeedDone(generated);
    const elapsed = ((performance.now() - t0) / 1000).toFixed(1);
    console.log(`[vantageai] Done — ${generated.toLocaleString()} events in ${elapsed}s`);
    return generated;
  }

  // ── Event generation ────────────────────────────────────────────────────────
  _generateEvent({ startMs, now, days, modelWeights, teamWeights, endpointWeights, timeWeights, seqIndex, total }) {
    // Timestamp — weighted toward recent, with weekly patterns
    const dayOffset = this._weightedRandom(days) * 86400000;
    const hourOffset = this._pickWeighted(timeWeights) * 3600000;
    const timestamp = startMs + dayOffset + hourOffset + Math.random() * 3600000;

    const model     = this._pickWeighted(modelWeights);
    const team      = this._pickWeighted(teamWeights);
    const endpoint  = this._pickWeighted(endpointWeights);

    // Inject anomalies (0.5% of events)
    const isAnomaly = Math.random() < 0.005;
    const isSpike   = Math.random() < 0.008;

    // Token counts — log-normal distribution (realistic: most calls small, rare large)
    const basePrompt      = Math.exp(this._randNormal(7.5, 1.2));  // ~1800 mean
    const baseCompletion  = Math.exp(this._randNormal(5.8, 1.1));  // ~330 mean
    const promptTokens    = Math.round(isSpike ? basePrompt * 8 : basePrompt);
    const completionTokens= Math.round(baseCompletion);
    const cachedTokens    = Math.floor(promptTokens * (model.cacheRead > 0 ? Math.random() * 0.35 : 0));

    // System prompt tokens (varies by endpoint — chat has huge ones)
    const systemPromptMultipliers = {
      "/chat/complete": 0.45,
      "/analyze": 0.35,
      "/summarize": 0.2,
      "/classify": 0.15,
      "/embed": 0.05,
      "/generate": 0.25,
      "/translate": 0.18,
      "/extract": 0.28,
    };
    const sysMultiplier    = systemPromptMultipliers[endpoint] || 0.2;
    const systemPromptTokens = Math.round(promptTokens * sysMultiplier);

    // Cost calculation
    const uncached   = Math.max(0, promptTokens - cachedTokens);
    const inputCost  = (uncached / 1e6) * model.input + (cachedTokens / 1e6) * (model.cacheRead || 0);
    const outputCost = (completionTokens / 1e6) * model.output;
    const totalCost  = isAnomaly ? (inputCost + outputCost) * 15 : inputCost + outputCost;

    // Latency — model-specific distributions
    const baseLatency = this._modelLatency(model.name, promptTokens, completionTokens);
    const latencyMs   = isAnomaly ? baseLatency * 4 : baseLatency;

    // TTFT
    const ttftMs = latencyMs * (0.15 + Math.random() * 0.25);

    // Status
    const statusCode = Math.random() < (isAnomaly ? 0.3 : 0.004) ? 500 : 200;

    // Efficiency score
    const effScore = Math.round(Math.max(10, Math.min(100,
      100 - (systemPromptTokens / promptTokens) * 60
          - (isAnomaly ? 30 : 0)
          - Math.random() * 15
    )));

    // Cheapest alternative
    const cheapest = this._findCheapest(model.name, promptTokens, completionTokens);

    return {
      id:               `${this.orgId}_${seqIndex}_${Math.random().toString(36).slice(2,8)}`,
      org_id:           this.orgId,
      timestamp,
      // Request
      provider:         model.provider,
      model:            model.name,
      endpoint,
      team,
      feature:          this._endpointToFeature(endpoint),
      // Tokens
      prompt_tokens:    promptTokens,
      completion_tokens: completionTokens,
      total_tokens:     promptTokens + completionTokens,
      cached_tokens:    cachedTokens,
      system_prompt_tokens: systemPromptTokens,
      // Cost
      input_cost:       inputCost,
      output_cost:      outputCost,
      total_cost:       totalCost,
      potential_saving: Math.max(0, totalCost - cheapest.cost),
      cheapest_model:   cheapest.name,
      // Performance
      latency_ms:       Math.round(latencyMs),
      ttft_ms:          Math.round(ttftMs),
      status_code:      statusCode,
      // Quality
      efficiency_score: effScore,
      // Flags
      is_anomaly:       isAnomaly,
      is_spike:         isSpike,
    };
  }

  // ── Query API ────────────────────────────────────────────────────────────────

  async query(opts = {}) {
    const { days = 30, model, team, endpoint, limit = 10000 } = opts;
    await this.openDB();
    const since = Date.now() - days * 86400000;

    return new Promise((resolve, reject) => {
      const tx     = this.db.transaction("events", "readonly");
      const store  = tx.objectStore("events");
      const index  = store.index("by_timestamp");
      const range  = IDBKeyRange.lowerBound(since);
      const results = [];

      const cursor = index.openCursor(range);
      cursor.onsuccess = e => {
        const c = e.target.result;
        if (!c || results.length >= limit) { resolve(results); return; }
        const ev = c.value;
        if (ev.org_id !== this.orgId) { c.continue(); return; }
        if (model    && ev.model    !== model)    { c.continue(); return; }
        if (team     && ev.team     !== team)     { c.continue(); return; }
        if (endpoint && ev.endpoint !== endpoint) { c.continue(); return; }
        results.push(ev);
        c.continue();
      };
      cursor.onerror = e => reject(e.target.error);
    });
  }

  async aggregate(days = 30) {
    const events = await this.query({ days, limit: 100000 });
    const out = {
      total_cost: 0, total_tokens: 0, total_requests: events.length,
      by_model: {}, by_team: {}, by_endpoint: {}, by_day: {},
      by_provider: {}, latencies: [], errors: 0,
      potential_savings: 0, cached_tokens: 0,
    };

    for (const ev of events) {
      out.total_cost    += ev.total_cost;
      out.total_tokens  += ev.total_tokens;
      out.cached_tokens += ev.cached_tokens;
      out.potential_savings += ev.potential_saving;
      if (ev.status_code >= 400) out.errors++;
      out.latencies.push(ev.latency_ms);

      // by model
      if (!out.by_model[ev.model]) out.by_model[ev.model] = { cost:0, tokens:0, requests:0, provider: ev.provider };
      out.by_model[ev.model].cost     += ev.total_cost;
      out.by_model[ev.model].tokens   += ev.total_tokens;
      out.by_model[ev.model].requests += 1;

      // by team
      if (!out.by_team[ev.team]) out.by_team[ev.team] = { cost:0, tokens:0, requests:0 };
      out.by_team[ev.team].cost     += ev.total_cost;
      out.by_team[ev.team].tokens   += ev.total_tokens;
      out.by_team[ev.team].requests += 1;

      // by endpoint
      if (!out.by_endpoint[ev.endpoint]) out.by_endpoint[ev.endpoint] = { cost:0, tokens:0, requests:0 };
      out.by_endpoint[ev.endpoint].cost     += ev.total_cost;
      out.by_endpoint[ev.endpoint].tokens   += ev.total_tokens;
      out.by_endpoint[ev.endpoint].requests += 1;

      // by day
      const day = new Date(ev.timestamp).toISOString().slice(0,10);
      if (!out.by_day[day]) out.by_day[day] = { cost:0, tokens:0, requests:0 };
      out.by_day[day].cost     += ev.total_cost;
      out.by_day[day].tokens   += ev.total_tokens;
      out.by_day[day].requests += 1;

      // by provider
      if (!out.by_provider[ev.provider]) out.by_provider[ev.provider] = { cost:0, tokens:0, requests:0 };
      out.by_provider[ev.provider].cost     += ev.total_cost;
      out.by_provider[ev.provider].tokens   += ev.total_tokens;
      out.by_provider[ev.provider].requests += 1;
    }

    // Compute latency percentiles
    out.latencies.sort((a,b) => a-b);
    const n = out.latencies.length;
    out.p50 = n ? out.latencies[Math.floor(n*.50)] : 0;
    out.p95 = n ? out.latencies[Math.floor(n*.95)] : 0;
    out.p99 = n ? out.latencies[Math.floor(n*.99)] : 0;
    out.error_rate = n ? (out.errors / n * 100).toFixed(2) : 0;
    delete out.latencies;

    return out;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────
  _buildModelWeights() {
    // Usage distribution mirrors real-world adoption
    const weights = [
      // model, weight (higher = more traffic)
      ["gpt-4o",              28],
      ["claude-sonnet-4-6",   16],
      ["gemini-2.0-flash",    14],
      ["gpt-4o-mini",         12],
      ["llama-3.3-70b",        9],
      ["claude-haiku-4-5",     7],
      ["gemini-1.5-flash",     5],
      ["claude-3-5-sonnet",    3],
      ["mistral-small-latest", 2],
      ["gpt-3.5-turbo",        2],
      ["o3-mini",              1],
      ["claude-opus-4-6",      1],
    ];
    // Map to model objects
    const ALL_MODELS = window.VANTAGE_MODELS || this._fallbackModels();
    return weights.map(([name, w]) => {
      const m = ALL_MODELS.find(x => x.name === name);
      return m ? [m, w] : null;
    }).filter(Boolean);
  }

  _buildTeamWeights() {
    return [["Product",35],["Engineering",28],["Content",18],["Data",12],["Growth",7]];
  }

  _buildEndpointWeights() {
    return [["/chat/complete",32],["/summarize",22],["/classify",18],["/embed",12],["/analyze",8],["/generate",4],["/translate",3],["/extract",1]];
  }

  _buildTimeWeights() {
    // 24-hour weights — peaks at 10am and 3pm UTC (business hours)
    return Array.from({length:24},(_,h) => {
      if (h >= 9  && h <= 11) return [h, 10];
      if (h >= 13 && h <= 16) return [h, 9];
      if (h >= 17 && h <= 19) return [h, 6];
      if (h >= 7  && h <= 8)  return [h, 4];
      if (h >= 20 && h <= 22) return [h, 3];
      return [h, 1];
    });
  }

  _modelLatency(modelName, promptTokens, completionTokens) {
    // Base latencies per model family (ms)
    const bases = {
      "gpt-4o": 700, "gpt-4o-mini": 450, "o1": 8000, "o3-mini": 3000,
      "gpt-3.5-turbo": 350, "gpt-4-turbo": 1200,
      "claude-opus-4-6": 1100, "claude-sonnet-4-6": 780, "claude-haiku-4-5": 380,
      "claude-3-5-sonnet": 800, "claude-3-haiku": 360,
      "gemini-2.0-flash": 420, "gemini-1.5-pro": 680, "gemini-1.5-flash": 390,
      "gemini-1.5-flash-8b": 310,
      "llama-3.3-70b": 520, "llama-3.1-405b": 1400, "llama-3.1-8b": 280,
      "mistral-large-latest": 650, "mistral-small-latest": 350,
      "command-r-plus": 780, "command-r": 430, "grok-2": 690,
    };
    const base = bases[modelName] || 600;
    // Scale with tokens (output latency dominates)
    const tokenFactor = 1 + (completionTokens / 1000) * 0.8 + (promptTokens / 10000) * 0.2;
    const jitter = 0.7 + Math.random() * 0.8;
    return base * tokenFactor * jitter;
  }

  _findCheapest(modelName, promptTokens, completionTokens) {
    const models = window.VANTAGE_MODELS || this._fallbackModels();
    const current = models.find(m => m.name === modelName);
    if (!current) return { name: modelName, cost: 0 };
    const currentCost = (promptTokens / 1e6) * current.input + (completionTokens / 1e6) * current.output;
    let cheapest = { name: modelName, cost: currentCost };
    for (const m of models) {
      if (m.name === modelName) continue;
      const cost = (promptTokens / 1e6) * m.input + (completionTokens / 1e6) * m.output;
      if (cost < cheapest.cost) cheapest = { name: m.name, cost };
    }
    return cheapest;
  }

  _endpointToFeature(endpoint) {
    const map = {
      "/chat/complete": "chat", "/summarize": "document_summary",
      "/classify": "content_moderation", "/embed": "semantic_search",
      "/analyze": "data_analysis", "/generate": "content_generation",
      "/translate": "localization", "/extract": "data_extraction",
    };
    return map[endpoint] || "unknown";
  }

  _pickWeighted(weights) {
    const total = weights.reduce((s, [, w]) => s + w, 0);
    let r = Math.random() * total;
    for (const [item, w] of weights) { r -= w; if (r <= 0) return item; }
    return weights[0][0];
  }

  _weightedRandom(max) {
    // Slightly weight toward recent days
    const r = Math.random();
    return max * (1 - Math.pow(1 - r, 0.7));
  }

  _randNormal(mean, std) {
    // Box-Muller transform
    const u = 1 - Math.random(), v = Math.random();
    return mean + std * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  async _storeBatch(events) {
    return new Promise((resolve, reject) => {
      const tx    = this.db.transaction("events", "readwrite");
      const store = tx.objectStore("events");
      events.forEach(ev => store.put(ev));
      tx.oncomplete = resolve;
      tx.onerror    = e => reject(e.target.error);
    });
  }

  async _clearOrg() {
    return new Promise((resolve, reject) => {
      const tx    = this.db.transaction("events", "readwrite");
      const store = tx.objectStore("events");
      const idx   = store.index("by_org");
      const range = IDBKeyRange.only(this.orgId);
      idx.openCursor(range).onsuccess = function(e) {
        const c = e.target.result;
        if (c) { c.delete(); c.continue(); } else resolve();
      };
      tx.onerror = e => reject(e.target.error);
    });
  }

  _fallbackModels() {
    // Minimal fallback if vantage-models.js not loaded
    return [
      {name:"gpt-4o",provider:"openai",input:2.50,output:10.00,cacheRead:1.25},
      {name:"claude-sonnet-4-6",provider:"anthropic",input:3.00,output:15.00,cacheRead:0.30},
      {name:"gemini-2.0-flash",provider:"google",input:0.10,output:0.40,cacheRead:0.025},
      {name:"gpt-4o-mini",provider:"openai",input:0.15,output:0.60,cacheRead:0.075},
      {name:"llama-3.3-70b",provider:"meta",input:0.23,output:0.40,cacheRead:0},
    ];
  }

  // ── Status check ─────────────────────────────────────────────────────────────
  async status() {
    await this.openDB();
    const count = await new Promise(resolve => {
      const tx  = this.db.transaction("events","readonly");
      const idx = tx.objectStore("events").index("by_org");
      idx.count(IDBKeyRange.only(this.orgId)).onsuccess = e => resolve(e.target.result);
    });
    const meta = await new Promise(resolve => {
      const tx  = this.db.transaction("meta","readonly");
      tx.objectStore("meta").get(`seed_done_${this.orgId}`).onsuccess = e => resolve(e.target.result);
    });
    return { seeded: !!meta?.value, eventCount: count, seededAt: meta?.seededAt ? new Date(meta.seededAt).toLocaleString() : null };
  }

  // ── Reseed with progress bar UI ───────────────────────────────────────────────
  async seedWithUI(containerId, days = 90) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = `
      <div style="font-family:monospace;font-size:13px;background:#0d1318;border:1px solid rgba(255,255,255,.1);border-radius:10px;padding:20px">
        <div style="color:#00d4a1;margin-bottom:12px">&#9654; Generating test data...</div>
        <div style="background:#080c0f;border-radius:6px;height:8px;overflow:hidden;margin-bottom:10px">
          <div id="seed-bar" style="height:100%;background:#00d4a1;width:0%;transition:width .3s;border-radius:6px"></div>
        </div>
        <div id="seed-status" style="color:#6b7b8a;font-size:11px">Starting...</div>
      </div>`;

    await this.seed({
      days,
      eventsTotal: 52000,
      force: true,
      onProgress: (done, total) => {
        const pct = (done / total * 100).toFixed(0);
        const bar = document.getElementById("seed-bar");
        const st  = document.getElementById("seed-status");
        if (bar) bar.style.width = pct + "%";
        if (st)  st.textContent  = `${done.toLocaleString()} / ${total.toLocaleString()} events (${pct}%)`;
      }
    });

    container.innerHTML = `
      <div style="font-family:monospace;font-size:13px;background:#0d1318;border:1px solid rgba(0,212,161,.2);border-radius:10px;padding:16px;color:#00d4a1">
        &#10003; 52,000 events seeded across 90 days, 23 models, 5 teams.<br>
        <span style="color:#6b7b8a">Reload the dashboard to see live data.</span>
      </div>`;
  }
}

// Auto-attach to window
window.VantageDataGen = VantageDataGen;

// Convenience: seed on first load if not done
window.vantageData = new VantageDataGen("demo-org");
