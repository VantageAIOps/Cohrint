import { Context, Next } from 'hono';
import { Bindings } from '../types';

export async function corsMiddleware(c: Context<{ Bindings: Bindings }>, next: Next): Promise<void | Response> {
  const origin = c.req.header('Origin') ?? '';
  const allowed = (c.env.ALLOWED_ORIGINS ?? '').split(',').map(s => s.trim());

  const isAllowed =
    allowed.includes('*') ||
    allowed.includes(origin) ||
    allowed.some(p => p.endsWith('*') && origin.startsWith(p.slice(0, -1)));

  const corsOrigin = isAllowed ? origin : allowed[0] ?? '*';

  // Preflight
  if (c.req.method === 'OPTIONS') {
    return new Response(null, {
      status: 204,
      headers: {
        'Access-Control-Allow-Origin':  corsOrigin,
        'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
        'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-Vantage-Org',
        'Access-Control-Max-Age':       '86400',
      },
    });
  }

  await next();
  c.res.headers.set('Access-Control-Allow-Origin', corsOrigin);
  c.res.headers.set('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Vantage-Org');
  c.res.headers.set('Vary', 'Origin');
}
