self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Clean old caches if needed later
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  // Simple cache-first for static assets
  if (url.pathname.startsWith('/static/')) {
    event.respondWith((async () => {
      const cache = await caches.open('static-v1');
      const cached = await cache.match(event.request);
      if (cached) return cached;
      const resp = await fetch(event.request);
      cache.put(event.request, resp.clone());
      return resp;
    })());
  }
});