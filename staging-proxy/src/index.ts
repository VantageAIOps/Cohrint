/**
 * Staging proxy Worker — app.vantageaiops.com
 *
 * Gate check: requires STAGING_CODE cookie before proxying to
 * the main branch Pages deployment (main.cohrint.pages.dev).
 *
 * Env vars:
 *   STAGING_CODE  — secret access code (set via wrangler secret)
 */

const UPSTREAM = 'https://main.cohrint.pages.dev';
const COOKIE_NAME = 'staging_access';
const COOKIE_MAX_AGE = 60 * 60 * 24; // 24h

export interface Env {
  STAGING_CODE: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const code = env.STAGING_CODE;

    // Gate disabled if secret not configured
    if (!code) return proxy(request, url);

    // Auth endpoint
    if (url.pathname === '/staging-auth') {
      if (request.method === 'POST') {
        const form = await request.formData().catch(() => null);
        const submitted = form?.get('code') ?? '';
        if (submitted === code) {
          const dest = url.searchParams.get('next') || '/';
          return new Response(null, {
            status: 302,
            headers: {
              Location: dest,
              'Set-Cookie': `${COOKIE_NAME}=${code}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}`,
            },
          });
        }
        return gatePage('Invalid access code.', url);
      }
      return gatePage('', url);
    }

    // Check cookie
    const cookies = parseCookies(request.headers.get('cookie') || '');
    if (cookies[COOKIE_NAME] === code) return proxy(request, url);

    // Redirect to gate
    const next = encodeURIComponent(url.pathname + url.search);
    return Response.redirect(`${url.origin}/staging-auth?next=${next}`, 302);
  },
};

function parseCookies(header: string): Record<string, string> {
  return Object.fromEntries(
    header.split(';')
      .map(c => c.trim().split('='))
      .filter(([k]) => k)
      .map(([k, ...v]) => [k.trim(), v.join('=')])
  );
}

async function proxy(request: Request, url: URL): Promise<Response> {
  const upstream = new URL(url.pathname + url.search, UPSTREAM);
  const req = new Request(upstream.toString(), {
    method: request.method,
    headers: request.headers,
    body: request.body,
    redirect: 'follow',
  });
  req.headers.set('host', new URL(UPSTREAM).host);
  return fetch(req);
}

function gatePage(error: string, url: URL): Response {
  const next = url?.searchParams?.get('next') || '/';
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cohrint Staging</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#06080d;color:#e8ecf1;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#0c1017;border:1px solid #1e2a3a;border-radius:12px;padding:40px;width:340px;text-align:center}
.logo{font-family:monospace;font-size:22px;font-weight:700;color:#34d399;margin-bottom:6px}
.badge{display:inline-block;background:#1e3a2a;color:#34d399;font-size:10px;padding:2px 8px;border-radius:10px;letter-spacing:.05em;margin-bottom:24px}
h2{font-size:17px;margin-bottom:6px}
p{color:#7a8ba0;font-size:13px;margin-bottom:20px}
.err{color:#ef4444;font-size:12px;margin-bottom:12px;min-height:16px}
input{width:100%;padding:10px 12px;background:#111823;border:1px solid #1e2a3a;border-radius:8px;color:#e8ecf1;font-size:14px;font-family:monospace;outline:none;margin-bottom:2px}
input:focus{border-color:#34d399}
button{width:100%;padding:10px;margin-top:10px;background:#34d399;color:#000;border:none;border-radius:8px;font-weight:600;font-size:14px;cursor:pointer}
button:hover{background:#10b981}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Cohrint</div>
  <div class="badge">STAGING</div>
  <h2>Internal Access</h2>
  <p>Enter the staging access code to continue.</p>
  <div class="err">${error}</div>
  <form method="POST" action="/staging-auth?next=${encodeURIComponent(next)}">
    <input type="password" name="code" placeholder="Access code" autofocus required>
    <button type="submit">Continue →</button>
  </form>
</div>
</body>
</html>`;
  return new Response(html, {
    status: error ? 401 : 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}
