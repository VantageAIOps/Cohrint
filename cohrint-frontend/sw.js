/**
 * Cohrint — Service Worker v4
 *
 * Strategy:
 *   HTML pages   → network-first (always get fresh content, fall back to cache)
 *   Static assets → cache-first (JS, CSS, fonts — fast, versioned by SW cache name)
 *   API calls    → bypass (never intercept api.cohrint.com or /v1/ paths)
 *
 * Auto-update: when a new SW activates, it sends a 'reload' message to all
 * open tabs so they pick up the latest HTML without the user clearing cache.
 */
const CACHE = 'cohrint-v4';

// Static assets that change rarely — cache-first
const PRECACHE = [
  '/manifest.json',
  '/seed-data.js',
  '/cohrint-models.js',
];

// ── Install — pre-cache static assets only (NOT HTML) ────────────────────────
self.addEventListener('install', ev => {
  ev.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()) // activate immediately
  );
});

// ── Activate — delete old caches + claim clients + notify tabs ───────────────
self.addEventListener('activate', ev => {
  ev.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
      .then(() => {
        // Tell all open tabs to reload so they get fresh HTML
        self.clients.matchAll({ type: 'window' }).then(clients => {
          clients.forEach(client => client.postMessage({ type: 'SW_UPDATED' }));
        });
      })
  );
});

// ── Fetch — strategy by request type ─────────────────────────────────────────
self.addEventListener('fetch', ev => {
  const url = new URL(ev.request.url);

  // 1. Never intercept API calls, SSE streams, Cloudflare internals, or cross-origin requests
  if (
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/v1/') ||
    url.pathname.startsWith('/cdn-cgi/') ||
    url.pathname.includes('/stream/')
  ) {
    return; // fall through to browser
  }

  // 2. HTML pages → network-first (always fresh, no stale dashboards)
  if (
    ev.request.mode === 'navigate' ||
    ev.request.destination === 'document' ||
    url.pathname.endsWith('.html') ||
    url.pathname === '/' ||
    url.pathname === '/app' ||
    url.pathname === '/auth' ||
    url.pathname === '/signup'
  ) {
    ev.respondWith(networkFirstHTML(ev.request));
    return;
  }

  // 3. Static assets → cache-first (fonts, JS, CSS)
  ev.respondWith(cacheFirstAsset(ev.request));
});

async function networkFirstHTML(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      // Update cache with fresh version
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    // Offline fallback — serve cached version if available
    const cached = await caches.match(request);
    return cached || caches.match('/app.html'); // last resort
  }
}

async function cacheFirstAsset(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      const cache = await caches.open(CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return cached; // return stale if network fails
  }
}
