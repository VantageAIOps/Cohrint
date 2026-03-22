import { Context, Next } from 'hono';
import { Bindings } from '../types';

export async function corsMiddleware(c: Context<{ Bindings: Bindings }>, next: Next): Promise<void | Response> {
  const origin = c.req.header('Origin') ?? '';
  const allowed = (c.env.ALLOWED_ORIGINS ?? '').split(',').map(s => s.trim());

  const isAllowed =
    allowed.includes('*') ||
    allowed.includes(origin) ||
    allowed.some(p => p.endsWith('*') && origin.startsWith(p.slice(0, -1)));

  // Safari/WebKit requires explicit origin (not *) when credentials are used.
  // If origin is allowed, echo it back; otherwise use first allowed origin.
  // Never combine credentials: true with wildcard *.
  const corsOrigin = isAllowed && origin ? origin : (allowed.find(a => a !== '*') || origin || '*');
  const canCredential = corsOrigin !== '*';

  // Preflight
  if (c.req.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin':      corsOrigin,
        'Access-Control-Allow-Methods':     'GET, POST, PUT, PATCH, DELETE, OPTIONS',
        'Access-Control-Allow-Headers':     'Authorization, Content-Type, X-Vantage-Org',
        ...(canCredential ? { 'Access-Control-Allow-Credentials': 'true' } : {}),
        'Access-Control-Max-Age':           '86400',
        'Vary':                             'Origin',
      },
    });
  }

  await next();
  c.res.headers.set('Access-Control-Allow-Origin',      corsOrigin);
  c.res.headers.set('Access-Control-Allow-Headers',     'Authorization, Content-Type, X-Vantage-Org');
  if (canCredential) c.res.headers.set('Access-Control-Allow-Credentials', 'true');
  c.res.headers.set('Vary', 'Origin');
}
