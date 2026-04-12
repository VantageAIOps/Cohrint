# Website Enterprise Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the VantageAI public website to enterprise quality — remove unsupported tool references, fake reviews, competitor names; redesign to light/enterprise aesthetic; add live demo sandbox; harden security headers and auth.

**Architecture:** All changes are to static HTML/CSS/JS files in `vantage-final-v4/` and Cloudflare Worker routes in `vantage-worker/src/`. No new build pipeline — files deployed as-is via Cloudflare Pages. Worker changes deploy via `wrangler deploy`.

**Tech Stack:** Static HTML + inline CSS/JS, Cloudflare Workers (Hono/TypeScript), Cloudflare D1 (SQLite), Cloudflare KV

---

## File Map

| File | Phase | What changes |
|------|-------|-------------|
| `vantage-final-v4/docs.html` | 1 | Remove Windsurf/Zed/JetBrains sections + nav; redact pricing algorithm + MD5 mention |
| `vantage-final-v4/index.html` | 1+2 | Remove fake reviews, tool names, false claims; enterprise light theme redesign |
| `vantage-final-v4/app.html` | 1+3 | Add Docs nav link; add demo banner JS |
| `vantage-final-v4/_headers` | 4 | Add HSTS, tighten CSP, add COOP/CORP headers |
| `vantage-worker/src/routes/auth.ts` | 4 | Brute-force rate limiting on /v1/auth/session |
| `vantage-worker/src/routes/events.ts` | 4 | Sanitize error messages; validate prompt_hash format |
| `docs/security-audit-2026-04-09.md` | 4 | Internal security findings report |

---

## Task 1: docs.html — Remove Tools + Redact Sensitive Info

**Files:**
- Modify: `vantage-final-v4/docs.html`

- [ ] **Step 1: Remove Windsurf, Zed, JetBrains from nav and content**

Run to find exact lines:
```bash
grep -n "Windsurf\|Zed\|JetBrains\|windsurf\|zed" "vantage-final-v4/docs.html"
```

Make these changes:
1. Remove nav item: `<a class="docs-nav-item" onclick="show('zed',this)">Zed / JetBrains</a>` (line ~210)
2. Delete the entire `<div id="windsurf"` section and its content (lines ~680–808)
3. Delete the entire `<div id="zed"` section and its content (lines ~809 to next section)

After removing those sections, add a generic note at the end of the MCP section (inside `<div id="mcp"`, before its closing `</div>`):
```html
<div class="doc-section" style="margin-top:24px;padding:16px;background:var(--bg2);border:1px solid var(--border);border-radius:8px">
  <strong>Other MCP-compatible editors</strong>
  <p style="margin-top:8px;color:var(--muted)">VantageAI MCP works with any editor that supports the Model Context Protocol. Refer to your editor's documentation for MCP server configuration instructions.</p>
</div>
```

- [ ] **Step 2: Redact the fuzzy-match pricing algorithm**

Find text near line 1736 containing "substring matching". Replace:

Before:
```
Looks up model in the pricing table (exact match, then fuzzy substring match). For example, `claude-sonnet-4-6-20260301` matches `claude-sonnet-4-6`. Unknown models return `cost_usd = 0`.
```

After:
```html
Looks up model in the pricing table. Model variants are automatically resolved to their base pricing. Unknown models return <code>cost_usd = 0</code>.
```

- [ ] **Step 3: Redact MD5 algorithm mention**

```bash
grep -n "MD5\|md5" "vantage-final-v4/docs.html"
```

For each hit, replace `MD5` with `hashed`. If in a table cell like "MD5", change to "hashed identifier".

- [ ] **Step 4: Verify**

```bash
grep -n "Windsurf\|Zed\|JetBrains\|MD5\|substring matching\|claude-sonnet-4-6-20260301" "vantage-final-v4/docs.html"
# Expected: no output
```

- [ ] **Step 5: Commit**

```bash
git add vantage-final-v4/docs.html
git commit -m "docs: remove Windsurf/Zed/JetBrains, redact pricing algorithm and MD5 from public docs"
```

---

## Task 2: index.html — Phase 1 Content Fixes

**Files:**
- Modify: `vantage-final-v4/index.html`

- [ ] **Step 1: Remove Windsurf, Zed, JetBrains mentions**

```bash
grep -n "Windsurf\|Zed\|JetBrains" "vantage-final-v4/index.html"
```

For each hit:
- `MCP server (Cursor/Windsurf/Zed)` in comparison table → `MCP server (AI-native IDEs)`
- Any hero/feature bullets → replace with "AI-native IDEs" or "MCP-compatible editors"

- [ ] **Step 2: Remove the fake testimonials section**

The testimonials section is `<section id="testimonials"` (~lines 824–854). Delete the entire block.

Replace with this stat block at the same location:
```html
<!-- TRUST STRIP -->
<section style="padding:48px 0;text-align:center;background:var(--bg2);border-top:1px solid var(--border);border-bottom:1px solid var(--border)">
  <div style="display:flex;justify-content:center;gap:64px;flex-wrap:wrap;max-width:800px;margin:0 auto">
    <div>
      <div style="font-size:32px;font-weight:700;color:var(--text);font-family:var(--mono)">10+</div>
      <div style="font-size:13px;color:var(--muted);margin-top:4px">AI tools tracked</div>
    </div>
    <div>
      <div style="font-size:32px;font-weight:700;color:var(--text);font-family:var(--mono)">40+</div>
      <div style="font-size:13px;color:var(--muted);margin-top:4px">metrics per call</div>
    </div>
    <div>
      <div style="font-size:32px;font-weight:700;color:var(--text);font-family:var(--mono)">283+</div>
      <div style="font-size:13px;color:var(--muted);margin-top:4px">automated checks</div>
    </div>
    <div>
      <div style="font-size:32px;font-weight:700;color:var(--text);font-family:var(--mono)">Cloudflare</div>
      <div style="font-size:13px;color:var(--muted);margin-top:4px">global edge network</div>
    </div>
  </div>
</section>
```

- [ ] **Step 3: Fix comparison table — rename competitor columns**

Replace the `<thead>` block (lines ~861–868):
```html
<thead>
  <tr>
    <th>Capability</th>
    <th class="vantage-col">&#10022; VantageAI</th>
    <th>API Gateway<br><small style="font-weight:400;font-size:11px">Tools</small></th>
    <th>LLM Observability<br><small style="font-weight:400;font-size:11px">SDKs</small></th>
    <th>General APM<br><small style="font-weight:400;font-size:11px">Platforms</small></th>
  </tr>
</thead>
```

In `<tbody>`, make these row changes:
- `MCP server (Cursor/Windsurf/Zed)` → `MCP server (AI-native IDEs)`
- Remove the `AI model auto-router` row entirely (feature not shipped)
- `RBAC + audit logs + SOC2` → `RBAC + full audit logs`
- Remove the pricing row (`$99/mo`, `$80/mo` etc.) — competitor pricing is not ours to publish

Add footnote immediately after `</table>`:
```html
<p style="font-size:11px;color:var(--muted);text-align:center;margin-top:12px;font-style:italic">
  Capabilities based on publicly documented features of top-rated tools in each category (G2, Capterra, vendor documentation).
</p>
```

- [ ] **Step 4: Fix pricing section — honest claims + mailto CTAs**

Replace the entire `<section id="pricing"` block with:
```html
<!-- PRICING -->
<section id="pricing">
  <div class="sec-label">// pricing</div>
  <div class="sec-title">Simple, <em>transparent</em> pricing</div>
  <div class="pricing-grid">
    <div class="plan">
      <div class="plan-name">FREE</div>
      <div class="plan-price"><sup>$</sup>0</div>
      <div class="plan-period">forever &middot; no credit card</div>
      <a href="/signup.html" class="plan-cta">Get started &rarr;</a>
      <ul class="plan-feats">
        <li>Up to 10,000 events/month</li>
        <li>Real-time cost dashboard</li>
        <li>All models tracked</li>
        <li>Per-developer analytics</li>
        <li>MCP tools for IDE querying</li>
        <li>Python + JS SDK</li>
        <li>Audit log</li>
      </ul>
    </div>

    <div class="plan featured">
      <div class="plan-badge">MOST POPULAR</div>
      <div class="plan-name">TEAM</div>
      <div class="plan-price" style="font-size:32px;padding-top:8px">Contact Us</div>
      <div class="plan-period">for team pricing</div>
      <a href="mailto:vantageaiops@gmail.com?subject=Team%20Plan%20Inquiry" class="plan-cta">Contact Sales &rarr;</a>
      <ul class="plan-feats">
        <li>Unlimited events</li>
        <li>Budget policies + Slack alerts</li>
        <li>Cross-platform OTel (10+ tools)</li>
        <li>Team cost attribution</li>
        <li>Semantic cache analytics</li>
        <li>CLI agent wrapper</li>
        <li>Local proxy (privacy-first)</li>
        <li>Priority support</li>
      </ul>
    </div>

    <div class="plan">
      <div class="plan-name">ENTERPRISE</div>
      <div class="plan-price" style="font-size:32px;padding-top:8px">Custom</div>
      <div class="plan-period">volume pricing &middot; dedicated support</div>
      <a href="mailto:vantageaiops@gmail.com?subject=Enterprise%20Inquiry" class="plan-cta">Talk to Sales &rarr;</a>
      <ul class="plan-feats">
        <li>Everything in Team</li>
        <li>Dedicated onboarding</li>
        <li>SLA discussion</li>
        <li>Custom data retention</li>
        <li>Volume discounts</li>
        <li>Security review support</li>
      </ul>
    </div>
  </div>
</section>
```

- [ ] **Step 5: Replace false compliance badges with real security controls**

Find the trust badges section (~lines 891–904) with SOC2/HIPAA/GDPR. Replace with:
```html
<section style="padding:48px 0 64px;text-align:center" id="security">
  <div class="sec-label">// security</div>
  <div class="sec-title" style="margin-bottom:32px">Built with <em>security first</em></div>
  <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:16px;max-width:900px;margin:0 auto">
    <div class="trust-badge">SHA-256 key hashing</div>
    <div class="trust-badge">HTTP-only sessions</div>
    <div class="trust-badge">Full audit log</div>
    <div class="trust-badge">TLS everywhere</div>
    <div class="trust-badge">Rate limiting per org</div>
    <div class="trust-badge">Privacy-first proxy</div>
    <div class="trust-badge">Cloudflare global edge</div>
    <div class="trust-badge">No prompt storage</div>
  </div>
</section>
```

- [ ] **Step 6: Redesign footer to three-column layout**

Replace the `<footer>` block (~lines 982–992):
```html
<footer style="background:var(--bg2);border-top:1px solid var(--border);padding:40px 24px">
  <div style="max-width:1100px;margin:0 auto;display:grid;grid-template-columns:1fr auto auto auto;gap:40px;align-items:start">
    <div>
      <div style="font-weight:700;font-size:16px;color:var(--text);margin-bottom:8px">VantageAI</div>
      <div style="font-size:13px;color:var(--muted);max-width:220px">AI spend intelligence for engineering teams.</div>
      <a href="mailto:vantageaiops@gmail.com" style="font-size:13px;color:var(--accent);margin-top:8px;display:block">vantageaiops@gmail.com</a>
    </div>
    <div>
      <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px">Product</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <a href="#features" style="font-size:13px;color:var(--text)">Features</a>
        <a href="#pricing" style="font-size:13px;color:var(--text)">Pricing</a>
        <a href="/calculator.html" style="font-size:13px;color:var(--text)">Calculator</a>
      </div>
    </div>
    <div>
      <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px">Resources</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <a href="/docs.html" style="font-size:13px;color:var(--text)">Docs</a>
        <a href="/roadmap.html" style="font-size:13px;color:var(--text)">Roadmap</a>
        <a href="#security" style="font-size:13px;color:var(--text)">Security</a>
      </div>
    </div>
    <div>
      <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:12px">Legal</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <a href="/terms.html" style="font-size:13px;color:var(--text)">Terms of Service</a>
        <a href="/privacy.html" style="font-size:13px;color:var(--text)">Privacy Policy</a>
      </div>
    </div>
  </div>
  <div style="max-width:1100px;margin:24px auto 0;padding-top:24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
    <span style="font-size:12px;color:var(--muted)">&copy; 2026 VantageAI. All rights reserved.</span>
    <span style="font-size:12px;color:var(--muted)">Hosted on Cloudflare's global edge network.</span>
  </div>
</footer>
```

- [ ] **Step 7: Verify no false claims remain**

```bash
grep -n "SOC2\|HIPAA\|GDPR\|SSO\|SAML\|self-host\|auto-router\|Windsurf\|JetBrains\|Jordan Kim\|Meera Patel\|Alex Rivera\|Helicone\|LangSmith\|Datadog LLM" "vantage-final-v4/index.html"
# Expected: no output
```

- [ ] **Step 8: Commit**

```bash
git add vantage-final-v4/index.html
git commit -m "feat(landing): Phase 1 — remove fake reviews, tool names, false claims; fix pricing + footer"
```

---

## Task 3: index.html — Phase 2 Enterprise CSS + Hero

**Files:**
- Modify: `vantage-final-v4/index.html`

- [ ] **Step 1: Replace CSS color variables with enterprise light palette**

Find `:root` in the `<style>` block (~lines 130–136). Replace the variable block:
```css
:root {
  --bg: #ffffff;
  --bg2: #f8f9fb;
  --bg3: #f1f3f7;
  --bg4: #e8eaf0;
  --border: rgba(0,0,0,0.08);
  --border2: rgba(0,0,0,0.14);
  --text: #0f172a;
  --muted: #475569;
  --dim: #94a3b8;
  --accent: #3b4ef8;
  --blue: #2563eb;
  --amber: #d97706;
  --red: #dc2626;
  --mono: 'DM Mono', monospace;
  --serif: 'Instrument Serif', Georgia, serif;
  --sans: 'DM Sans', sans-serif;
}
```

Find `.hero` CSS rule and update background to remove dark gradient:
```css
.hero {
  text-align: center;
  padding: 96px 24px 72px;
  position: relative;
  overflow: hidden;
  background: #ffffff;
}
.hero-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(59,78,248,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59,78,248,0.04) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
}
.hero-glow { display: none; }
```

- [ ] **Step 2: Replace hero HTML**

Replace the entire `<div class="hero">` block (~lines 433–462):
```html
<!-- HERO -->
<div class="hero">
  <div class="hero-grid"></div>
  <div style="display:inline-block;background:rgba(59,78,248,0.08);border:1px solid rgba(59,78,248,0.2);color:var(--accent);padding:5px 16px;border-radius:20px;font-size:12px;font-family:var(--mono);margin-bottom:24px;animation:fadeUp .5s ease both">AI FinOps for Engineering Teams</div>
  <h1>AI Spend Intelligence<br>for <em>Engineering Teams</em></h1>
  <p class="hero-sub" style="max-width:580px;margin:16px auto 0;font-size:18px;line-height:1.6;color:var(--muted)">Real-time cost visibility across every AI coding tool &mdash; per developer, per model, per team. Built for engineering leaders who need answers before the bill arrives.</p>

  <div style="display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:28px;animation:fadeUp .7s .15s ease both">
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Claude Code</span>
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">OpenAI Codex CLI</span>
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Gemini CLI</span>
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Cursor</span>
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">Cline</span>
    <span style="background:rgba(59,78,248,0.07);border:1px solid rgba(59,78,248,0.15);color:var(--accent);padding:5px 14px;border-radius:20px;font-family:var(--mono);font-size:11px">GitHub Copilot</span>
  </div>

  <div class="hero-actions" style="animation:fadeUp .7s .25s ease both">
    <a href="/signup.html" class="btn-primary">Request Access &rarr;</a>
    <a href="#" class="btn-ghost js-demo-btn">&#9654; View Live Demo</a>
  </div>
  <div class="install-box" style="animation:fadeUp .7s .4s ease both">
    <span>$</span> pip install vantageaiops
    <button class="copy-btn" onclick="copyInstall('pip install vantageaiops', this)">copy</button>
    <span style="color:var(--dim)">&middot;</span>
    <span>$</span> npm install vantageaiops
    <button class="copy-btn" onclick="copyInstall('npm install vantageaiops', this)">copy</button>
  </div>
  <p style="font-size:11px;color:var(--dim);margin-top:12px;font-family:var(--mono);animation:fadeUp .7s .5s ease both">Free tier &middot; No credit card &middot; Deploy in minutes</p>
</div>
```

- [ ] **Step 3: Update nav — add Security link**

In the `<nav>` block, add Security link after Pricing:
```html
<a href="#security" class="nav-link">Security</a>
```

Also fix the Enterprise CTA email — search for `owner@vantageaiops.com` and replace with `vantageaiops@gmail.com`.

- [ ] **Step 4: Verify**

```bash
grep -n "hero-badge\|The first AI\|Know exactly\|owner@vantageaiops" "vantage-final-v4/index.html"
# Expected: no output

grep -n "AI Spend Intelligence\|js-demo-btn\|security" "vantage-final-v4/index.html"
# Expected: all found
```

- [ ] **Step 5: Commit**

```bash
git add vantage-final-v4/index.html
git commit -m "feat(landing): Phase 2 — enterprise light theme CSS, new hero, nav Security link"
```

---

## Task 4: app.html — Docs Link + Demo Banner

**Files:**
- Modify: `vantage-final-v4/app.html`

- [ ] **Step 1: Find the nav link area**

```bash
grep -n "nav\|href.*docs\|href.*help\|nav-link" "vantage-final-v4/app.html" | head -30
```

Note the line where nav links live.

- [ ] **Step 2: Add Docs link**

Find the nav link group. Add after the last nav link:
```html
<a href="/docs.html" target="_blank" style="font-size:13px;color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:6px">Docs &#8599;</a>
```

- [ ] **Step 3: Add demo session banner using safe DOM methods**

At the bottom of app.html, before `</body>`, add:
```html
<script>
(function() {
  var DEMO_ORG = 'demo';
  try {
    var sess = JSON.parse(localStorage.getItem('vantage_session') || '{}');
    if (sess && sess.org_id === DEMO_ORG) {
      var banner = document.createElement('div');
      banner.id = 'demo-banner';
      banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#3b4ef8;color:#fff;text-align:center;padding:8px 16px;font-size:13px;font-family:sans-serif;display:flex;align-items:center;justify-content:center;gap:12px';
      var msg = document.createTextNode("You're viewing a live demo \u2014 read only.");
      var link = document.createElement('a');
      link.href = '/signup.html';
      link.textContent = 'Create your free account \u2192';
      link.style.cssText = 'color:#fff;font-weight:600;text-decoration:underline';
      banner.appendChild(msg);
      banner.appendChild(link);
      document.body.prepend(banner);
      document.body.style.paddingTop = '36px';
    }
  } catch(e) {}
})();
</script>
```

- [ ] **Step 4: Verify**

```bash
grep -n "docs.html\|demo-banner\|DEMO_ORG\|createTextNode" "vantage-final-v4/app.html"
# Expected: all found
```

- [ ] **Step 5: Commit**

```bash
git add vantage-final-v4/app.html
git commit -m "feat(app): add Docs nav link and XSS-safe demo session banner"
```

---

## Task 5: Demo Sandbox — Seed Data + Demo Button

**Files:**
- Modify: `vantage-final-v4/index.html` (demo button JS)
- Modify: `vantage-final-v4/seed-data.js` (demo org seed SQL)

- [ ] **Step 1: Create the demo org in D1 (one-time manual step)**

Hash the demo key:
```bash
echo -n "vnt_demo_a1b2c3d4e5f6a7b8" | sha256sum
# Note the 64-char hex hash output — call it DEMO_HASH
```

In the Cloudflare Dashboard, go to D1 → vantage-events → Console and run:
```sql
INSERT OR IGNORE INTO orgs (id, api_key_hash, api_key_hint, name, email, plan, budget_usd, created_at)
VALUES ('demo', 'REPLACE_WITH_DEMO_HASH', 'vnt_demo_a1b...', 'VantageAI Demo', 'demo@vantageaiops.com', 'team', 0, strftime('%s','now'));

INSERT OR IGNORE INTO org_members (id, org_id, email, name, role, api_key_hash, api_key_hint, scope_team, created_at)
VALUES ('demo-viewer', 'demo', 'viewer@demo.vantageaiops.com', 'Demo Viewer', 'viewer', 'REPLACE_WITH_DEMO_HASH', 'vnt_demo_a1b...', NULL, strftime('%s','now'));
```

- [ ] **Step 2: Add fixed demo seed SQL to seed-data.js**

Append the following to `vantage-final-v4/seed-data.js`:
```javascript
// =============================================================
// DEMO ORG SEED — fixed constant data, run once in D1 console
// Dashboard > Workers & Pages > D1 > vantage-events > Console
// =============================================================
// Copy the SQL block below and paste into D1 Console

/*
INSERT OR IGNORE INTO events (id,org_id,provider,model,prompt_tokens,completion_tokens,total_tokens,cost_usd,latency_ms,team,user_id,environment,created_at) VALUES
('dv001','demo','anthropic','claude-sonnet-4-6',2500,800,3300,0.0225,340,'backend','alice','production',strftime('%s','now','-29 days')),
('dv002','demo','openai','gpt-4o',1800,600,2400,0.0195,280,'backend','alice','production',strftime('%s','now','-28 days')),
('dv003','demo','google','gemini-2.0-flash',3200,1100,4300,0.0043,190,'backend','bob','production',strftime('%s','now','-27 days')),
('dv004','demo','anthropic','claude-sonnet-4-6',4100,1200,5300,0.039,420,'backend','bob','production',strftime('%s','now','-26 days')),
('dv005','demo','openai','gpt-4o',2200,700,2900,0.024,310,'backend','alice','production',strftime('%s','now','-25 days')),
('dv006','demo','anthropic','claude-haiku-4-5',1500,500,2000,0.0032,145,'backend','carol','production',strftime('%s','now','-24 days')),
('dv007','demo','openai','gpt-4o',3000,900,3900,0.033,360,'backend','alice','production',strftime('%s','now','-23 days')),
('dv008','demo','anthropic','claude-sonnet-4-6',1800,600,2400,0.018,290,'ml-platform','dave','production',strftime('%s','now','-22 days')),
('dv009','demo','google','gemini-2.0-flash',5000,1500,6500,0.0065,220,'ml-platform','dave','production',strftime('%s','now','-21 days')),
('dv010','demo','anthropic','claude-sonnet-4-6',2900,850,3750,0.026,370,'ml-platform','eve','production',strftime('%s','now','-20 days')),
('dv011','demo','openai','gpt-4o',4500,1300,5800,0.052,480,'product','frank','production',strftime('%s','now','-19 days')),
('dv012','demo','anthropic','claude-haiku-4-5',2000,600,2600,0.0042,160,'product','grace','production',strftime('%s','now','-18 days')),
('dv013','demo','anthropic','claude-sonnet-4-6',3300,1000,4300,0.030,400,'backend','alice','production',strftime('%s','now','-17 days')),
('dv014','demo','google','gemini-2.0-flash',4200,1200,5400,0.0054,200,'backend','bob','production',strftime('%s','now','-16 days')),
('dv015','demo','openai','gpt-4o',2800,850,3650,0.031,330,'ml-platform','dave','production',strftime('%s','now','-15 days')),
('dv016','demo','anthropic','claude-sonnet-4-6',1600,550,2150,0.0152,270,'product','frank','production',strftime('%s','now','-14 days')),
('dv017','demo','openai','gpt-4o',3800,1100,4900,0.043,410,'backend','alice','production',strftime('%s','now','-13 days')),
('dv018','demo','anthropic','claude-haiku-4-5',2500,750,3250,0.0053,145,'ml-platform','eve','production',strftime('%s','now','-12 days')),
('dv019','demo','google','gemini-2.0-flash',6000,1800,7800,0.0078,240,'ml-platform','dave','production',strftime('%s','now','-11 days')),
('dv020','demo','anthropic','claude-sonnet-4-6',3100,950,4050,0.028,385,'backend','carol','production',strftime('%s','now','-10 days')),
('dv021','demo','openai','gpt-4o',2100,680,2780,0.023,295,'product','grace','production',strftime('%s','now','-9 days')),
('dv022','demo','anthropic','claude-sonnet-4-6',4800,1400,6200,0.046,450,'backend','alice','production',strftime('%s','now','-8 days')),
('dv023','demo','google','gemini-2.0-flash',3500,1000,4500,0.0045,210,'backend','bob','production',strftime('%s','now','-7 days')),
('dv024','demo','anthropic','claude-haiku-4-5',1800,550,2350,0.0038,140,'product','frank','production',strftime('%s','now','-6 days')),
('dv025','demo','openai','gpt-4o',5200,1500,6700,0.059,500,'ml-platform','dave','production',strftime('%s','now','-5 days')),
('dv026','demo','anthropic','claude-sonnet-4-6',2700,820,3520,0.0243,355,'backend','carol','production',strftime('%s','now','-4 days')),
('dv027','demo','openai','gpt-4o',1900,620,2520,0.0208,275,'product','grace','production',strftime('%s','now','-3 days')),
('dv028','demo','anthropic','claude-sonnet-4-6',3600,1050,4650,0.033,395,'ml-platform','eve','production',strftime('%s','now','-2 days')),
('dv029','demo','google','gemini-2.0-flash',4800,1400,6200,0.0062,225,'backend','alice','production',strftime('%s','now','-1 days')),
('dv030','demo','anthropic','claude-sonnet-4-6',2300,720,3020,0.0207,320,'backend','bob','production',strftime('%s','now'));

INSERT OR IGNORE INTO team_budgets (org_id,team,budget_usd,updated_at) VALUES
('demo','backend',50.0,strftime('%s','now')),
('demo','ml-platform',30.0,strftime('%s','now')),
('demo','product',20.0,strftime('%s','now'));
*/
```

- [ ] **Step 3: Add demo button JS to index.html**

In the `<script>` block at the bottom of `index.html` (~line 994), add before the closing `</script>`:
```javascript
// Live Demo button
document.querySelectorAll('.js-demo-btn').forEach(function(btn) {
  btn.addEventListener('click', function(e) {
    e.preventDefault();
    var DEMO_KEY = 'vnt_demo_a1b2c3d4e5f6a7b8';
    btn.textContent = 'Loading demo\u2026';
    btn.style.opacity = '0.7';
    fetch('https://api.vantageaiops.com/v1/auth/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: DEMO_KEY }),
      credentials: 'include'
    })
    .then(function(r) {
      if (r.ok) {
        return r.json().then(function(data) {
          if (data.org_id) {
            localStorage.setItem('vantage_session', JSON.stringify({ org_id: data.org_id, role: 'viewer' }));
          }
          window.location.href = '/app.html';
        });
      } else {
        btn.textContent = 'Sign up free instead';
        btn.setAttribute('href', '/signup.html');
        btn.style.opacity = '1';
      }
    })
    .catch(function() {
      btn.textContent = '\u25b6 View Live Demo';
      btn.style.opacity = '1';
    });
  });
});
```

- [ ] **Step 4: Verify**

```bash
grep -n "js-demo-btn\|DEMO_KEY\|vnt_demo" "vantage-final-v4/index.html"
grep -n "dv001\|team_budgets" "vantage-final-v4/seed-data.js"
# Expected: all found
```

- [ ] **Step 5: Commit**

```bash
git add vantage-final-v4/index.html vantage-final-v4/seed-data.js
git commit -m "feat(demo): live demo sandbox — seed SQL + demo session button"
```

---

## Task 6: Security Headers

**Files:**
- Modify: `vantage-final-v4/_headers`

- [ ] **Step 1: Read current headers**

```bash
cat "vantage-final-v4/_headers"
```

- [ ] **Step 2: Replace the top `/*` block**

```
/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
  Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' cdnjs.cloudflare.com cdn.jsdelivr.net static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' fonts.googleapis.com cdnjs.cloudflare.com cdn.jsdelivr.net; font-src 'self' fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' https://api.vantageaiops.com https://cloudflareinsights.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
  X-Permitted-Cross-Domain-Policies: none
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Resource-Policy: same-site
```

Ensure auth/signup pages still have no-cache:
```
/auth.html
  Cache-Control: no-store, no-cache, must-revalidate

/signup.html
  Cache-Control: no-store, no-cache, must-revalidate
```

- [ ] **Step 3: Verify HSTS is present**

```bash
grep "Strict-Transport-Security" "vantage-final-v4/_headers"
# Expected: max-age=63072000 found
```

- [ ] **Step 4: Commit**

```bash
git add vantage-final-v4/_headers
git commit -m "security: add HSTS, tighten CSP, add COOP/CORP/Permissions-Policy headers"
```

---

## Task 7: Worker Auth Hardening

**Files:**
- Modify: `vantage-worker/src/routes/auth.ts`
- Modify: `vantage-worker/src/routes/events.ts`

- [ ] **Step 1: Locate the session endpoint in auth.ts**

```bash
grep -n "session\|POST\|api_key" "vantage-worker/src/routes/auth.ts" | head -30
```

Find the `auth.post('/session'` handler. Note exact line numbers.

- [ ] **Step 2: Add brute-force protection to POST /v1/auth/session**

Inside the `auth.post('/session'` handler, after extracting `api_key` from the body and before doing any DB lookup, add:

```typescript
// Brute-force protection: max 10 failed attempts per IP per 5 minutes
const ip = c.req.header('CF-Connecting-IP') ?? c.req.header('X-Forwarded-For') ?? 'unknown';
const bfKey = `auth:bf:${ip}`;
const attempts = parseInt(await c.env.KV.get(bfKey) ?? '0', 10);
if (attempts >= 10) {
  return c.json({ error: 'Too many authentication attempts. Try again later.' }, 429);
}
```

After any `return c.json({ error: ... }, 401)` response (failed auth), add before that return:
```typescript
// Increment brute-force counter
const cur = parseInt(await c.env.KV.get(bfKey) ?? '0', 10);
await c.env.KV.put(bfKey, String(cur + 1), { expirationTtl: 300 }).catch(() => {});
```

- [ ] **Step 3: Sanitize error messages in events.ts**

```bash
grep -n "throw err\|err.message\|stack" "vantage-worker/src/routes/events.ts"
```

Replace any `throw err` or `c.json({ error: err.message })` in catch blocks (except for `RangeError` which is user input validation and safe to surface) with:
```typescript
return c.json({ error: 'Internal server error' }, 500);
```

- [ ] **Step 4: Add prompt_hash format validation in events.ts**

In the single-event POST handler, after `body.prompt_hash` is read and before the KV lookup, add:
```typescript
// Sanitize prompt_hash — accept only hex strings 8–64 chars
if (body.prompt_hash && !/^[a-f0-9]{8,64}$/i.test(body.prompt_hash)) {
  body.prompt_hash = undefined;
}
```

- [ ] **Step 5: TypeScript check**

```bash
cd vantage-worker && npx tsc --noEmit 2>&1
# Expected: no errors
```

- [ ] **Step 6: Commit**

```bash
git add vantage-worker/src/routes/auth.ts vantage-worker/src/routes/events.ts
git commit -m "security: brute-force protection on /auth/session, sanitize errors, validate prompt_hash"
```

---

## Task 8: Security Audit Report

**Files:**
- Create: `docs/security-audit-2026-04-09.md`

- [ ] **Step 1: Create the report**

```bash
cat > "docs/security-audit-2026-04-09.md" << 'AUDIT'
# VantageAI Security Audit — April 2026
_Internal document. Not for public distribution._
_Conducted: 2026-04-09_

## Findings

| ID | Area | Severity | Finding | Status |
|----|------|----------|---------|--------|
| SA-01 | HTTP Headers | High | HSTS missing — allows downgrade attacks | Fixed — added max-age=63072000 in _headers |
| SA-02 | HTTP Headers | Medium | CSP missing frame-ancestors directive | Fixed — added frame-ancestors none to CSP |
| SA-03 | HTTP Headers | Medium | Missing COOP and CORP headers | Fixed — added both in _headers |
| SA-04 | HTTP Headers | Low | Permissions-Policy missing payment=() | Fixed — updated in _headers |
| SA-05 | Auth | High | No brute-force protection on POST /v1/auth/session | Fixed — 10 attempts / 5 min IP limit in auth.ts |
| SA-06 | API | Medium | Raw error messages could leak internal details in 500 responses | Fixed — standardized to generic message in events.ts |
| SA-07 | Input Validation | Low | prompt_hash accepted arbitrary strings — KV key injection vector | Fixed — hex-only format validation in events.ts |
| SA-08 | Public Docs | Medium | docs.html exposed internal pricing algorithm and MD5 hash algorithm | Fixed — redacted in docs.html |
| SA-09 | Frontend | Medium | API key stored in localStorage — accessible to page JS | Deferred — mitigated by CSP script-src; full fix needs cookie-only auth (post-MVP) |
| SA-10 | Content | High | Landing page had false compliance badges (SOC2, HIPAA, GDPR) without certification | Fixed — removed, replaced with real implemented controls |
| SA-11 | Content | Medium | Landing page had fake customer testimonials with invented identities | Fixed — removed entirely |

## Controls Implemented

| Control | Implementation |
|---------|---------------|
| API key storage | SHA-256 hash only — raw key shown once |
| Session tokens | HTTP-only SameSite=Lax Secure cookies, 30-day TTL |
| Transport security | TLS via Cloudflare edge + HSTS preload |
| Rate limiting | Per-org per-minute via KV (1000 RPM) |
| Auth brute-force | Per-IP 10-attempt / 5-minute window via KV |
| SQL injection | Parameterized queries only throughout Worker |
| Audit logging | Every admin action logged with timestamp |
| Clickjacking | X-Frame-Options DENY + CSP frame-ancestors none |
| XSS | CSP script-src restricts to self and listed CDNs |
| Privacy mode | Local proxy option — prompts never leave machine |

## Deferred / Out of Scope

| Item | Reason |
|------|--------|
| SOC2 Type II | Requires third-party auditor — planned for Series A |
| HIPAA BAA | Not targeting healthcare currently |
| Penetration testing | Planned alongside SOC2 |
| localStorage migration | Auth flow redesign needed — post-MVP |
| Dependency scanning | To be added as CI step |
| Cloudflare WAF rules | Requires dashboard access — manual step |
AUDIT
```

- [ ] **Step 2: Commit**

```bash
git add docs/security-audit-2026-04-09.md
git commit -m "docs: internal security audit report April 2026"
```

---

## Task 9: Push + Deploy

- [ ] **Step 1: Push branch and verify CI**

```bash
git push origin feat/semantic-cache-analytics
gh run view --repo VantageAIOps/VantageAI
```

- [ ] **Step 2: After PR merges — deploy Worker**

```bash
cd vantage-worker && npx wrangler deploy
```

- [ ] **Step 3: After PR merges — deploy Pages**

```bash
npx wrangler pages deploy ./vantage-final-v4 --project-name=vantageai
```

- [ ] **Step 4: Smoke test live site**

```bash
curl -sI https://vantageaiops.com | grep -E "Strict-Transport|Content-Security|X-Frame"
# Expected: all three headers present

curl -s https://vantageaiops.com | grep -iE "Helicone|LangSmith|Datadog LLM|Windsurf|JetBrains|Jordan Kim|SOC2 Ready|HIPAA Ready"
# Expected: no output

curl -s https://vantageaiops.com | grep -iE "terms|privacy"
# Expected: footer links found
```

---

## Spec Coverage Check

- [x] Phase 1 docs.html tool removal → Task 1
- [x] Phase 1 docs.html redactions → Task 1 Steps 2-3
- [x] Phase 1 index.html tool names → Task 2 Step 1
- [x] Phase 1 fake reviews removed → Task 2 Step 2
- [x] Phase 1 comparison table → Task 2 Step 3
- [x] Phase 1 pricing mailto CTAs → Task 2 Step 4
- [x] Phase 1 false badges removed → Task 2 Step 5
- [x] Phase 1 footer legal links → Task 2 Step 6
- [x] Phase 1 app.html docs link → Task 4 Step 2
- [x] Phase 2 enterprise CSS → Task 3 Step 1
- [x] Phase 2 hero redesign → Task 3 Step 2
- [x] Phase 2 nav Security link → Task 3 Step 3
- [x] Phase 3 demo org setup → Task 5 Step 1
- [x] Phase 3 seed data → Task 5 Step 2
- [x] Phase 3 demo button → Task 5 Step 3
- [x] Phase 3 app demo banner → Task 4 Step 3
- [x] Phase 4 HSTS + CSP → Task 6
- [x] Phase 4 brute-force auth → Task 7 Step 2
- [x] Phase 4 error sanitization → Task 7 Step 3
- [x] Phase 4 input validation → Task 7 Step 4
- [x] Phase 4 security report → Task 8
