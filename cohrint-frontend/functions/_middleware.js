/**
 * Staging access gate — Pages Function middleware.
 *
 * Set the STAGING_CODE env var in the Cloudflare Pages project settings
 * for the `main` branch only. Production (cohrint.com) leaves it unset,
 * so this middleware is a no-op there.
 */

export async function onRequest({ request, next, env }) {
  const stagingCode = env.STAGING_CODE;
  if (!stagingCode) return next();

  const url = new URL(request.url);

  if (url.pathname === '/staging-auth') {
    if (request.method === 'POST') {
      const form = await request.formData().catch(() => null);
      const code = form?.get('code') ?? '';
      if (code === stagingCode) {
        const dest = url.searchParams.get('next') || '/';
        return new Response(null, {
          status: 302,
          headers: {
            Location: dest,
            'Set-Cookie': `staging_access=${stagingCode}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`,
          },
        });
      }
      return stagingGatePage('Invalid access code.', url);
    }
    return stagingGatePage('', url);
  }

  const cookies = parseCookies(request.headers.get('cookie') || '');
  if (cookies.staging_access === stagingCode) return next();

  const next_ = encodeURIComponent(url.pathname + url.search);
  return Response.redirect(`${url.origin}/staging-auth?next=${next_}`, 302);
}

function parseCookies(header) {
  return Object.fromEntries(
    header.split(';').map(c => c.trim().split('=')).filter(([k]) => k)
      .map(([k, ...v]) => [k, v.join('=')])
  );
}

function stagingGatePage(error, url) {
  const next = url?.searchParams?.get('next') || '/';
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Cohrint Staging — Access Required</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#06080d;color:#e8ecf1;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#0c1017;border:1px solid #1e2a3a;border-radius:12px;padding:40px;width:340px;text-align:center}
.logo{font-family:monospace;font-size:22px;font-weight:700;color:#34d399;margin-bottom:6px}
.badge{display:inline-block;background:#1e3a2a;color:#34d399;font-size:10px;padding:2px 8px;border-radius:10px;letter-spacing:.05em;margin-bottom:24px}
h2{font-size:17px;margin-bottom:6px}
p{color:#7a8ba0;font-size:13px;margin-bottom:20px}
.err{color:#ef4444;font-size:12px;margin-bottom:12px}
input{width:100%;padding:10px 12px;background:#111823;border:1px solid #1e2a3a;border-radius:8px;color:#e8ecf1;font-size:14px;font-family:monospace;outline:none}
input:focus{border-color:#34d399}
button{width:100%;padding:10px;margin-top:10px;background:#34d399;color:#000;border:none;border-radius:8px;font-weight:600;font-size:14px;cursor:pointer}
button:hover{background:#10b981}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Cohrint</div>
  <div class="badge">STAGING</div>
  <h2>Access Required</h2>
  <p>This is the staging environment. Enter your access code to continue.</p>
  ${error ? `<div class="err">${error}</div>` : ''}
  <form method="POST" action="/staging-auth?next=${encodeURIComponent(next)}">
    <input type="password" name="code" placeholder="Access code" autofocus required>
    <button type="submit">Continue →</button>
  </form>
</div>
</body>
</html>`;
  return new Response(html, {
    status: error ? 401 : 200,
    headers: { 'Content-Type': 'text/html' },
  });
}
