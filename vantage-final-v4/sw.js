/**
 * Vantage AI — Service Worker
 * Provides offline shell + cache-first for static assets.
 */
const CACHE = 'vantage-v2';
const SHELL = [
  '/',
  '/index.html',
  '/app.html',
  '/docs.html',
  '/calculator.html',
  '/privacy.html',
  '/terms.html',
  '/manifest.json',
  '/seed-data.js',
  '/vantage-models.js',
];

// Install — pre-cache shell
self.addEventListener('install', ev => {
  ev.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

// Activate — remove old caches
self.addEventListener('activate', ev => {
  ev.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Fetch — cache-first for same-origin, network-first for API calls
self.addEventListener('fetch', ev => {
  const url = new URL(ev.request.url);
  // Never intercept SSE streams, API calls, or cross-origin requests
  if (
    url.pathname.startsWith('/v1/') ||
    url.pathname.includes('/stream/') ||
    url.origin !== self.location.origin
  ) {
    return; // fall through to network
  }
  ev.respondWith(
    caches.match(ev.request).then(cached => {
      if (cached) return cached;
      return fetch(ev.request).then(response => {
        if (response && response.status === 200 && response.type === 'basic') {
          const clone = response.clone();
          caches.open(CACHE).then(cache => cache.put(ev.request, clone));
        }
        return response;
      }).catch(() => {
        // Offline fallback for navigation requests
        if (ev.request.mode === 'navigate') {
          return caches.match('/app.html');
        }
      });
    })
  );
});
