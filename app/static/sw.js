const CACHE = 'dbmilesx-v5-26-static-1';
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE)); });
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const u = new URL(e.request.url);
  if (u.origin !== location.origin || !u.pathname.startsWith('/static/')) return;
  const versioned = u.searchParams.has('v');
  if (versioned) {
    // Arquivo versionado (?v=): usa o cache primeiro; a URL muda a cada versão nova.
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); }
      return r;
    })));
    return;
  }
  // Demais estáticos: rede primeiro, cache como reserva offline.
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); }
    return r;
  }).catch(() => caches.match(e.request)));
});
