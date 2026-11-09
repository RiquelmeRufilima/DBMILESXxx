const CACHE = 'dbmilesx-v5-30-static-20261109';
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

self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch (_) {}
  const title = String(data.title || 'DBMILESX');
  const url = String(data.url || '/notifications');
  const target = url.startsWith('/') && !url.startsWith('//') ? url : '/notifications';
  event.waitUntil(self.registration.showNotification(title, {
    body: String(data.body || 'Você tem uma nova notificação.'),
    icon: '/static/icons/dbmilesx.ico?v=20261109', badge: '/static/icons/dbmilesx.ico?v=20261109',
    data: {url: target}, tag: `dbmilesx-${title}-${target}`, renotify: false,
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const path = event.notification.data?.url || '/notifications';
  event.waitUntil((async () => {
    const url = new URL(path, self.location.origin).href;
    const windows = await self.clients.matchAll({type:'window', includeUncontrolled:true});
    const client = windows.find(c => c.url.startsWith(self.location.origin));
    if (client) { await client.navigate(url); return client.focus(); }
    return self.clients.openWindow(url);
  })());
});
