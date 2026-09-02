const CACHE = 'dbmilesx-v5-10-28-shell-1';
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE)); });
self.addEventListener('activate', e => e.waitUntil((async()=>{ for(const key of await caches.keys()) if(key!==CACHE) await caches.delete(key); await self.clients.claim(); })()));
self.addEventListener('fetch', e => { if(e.request.method!=='GET') return; const u=new URL(e.request.url); if(!u.pathname.startsWith('/static/')) return; e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{const c=r.clone();caches.open(CACHE).then(cache=>cache.put(e.request,c));return r;}).catch(()=>caches.match(e.request))); });
