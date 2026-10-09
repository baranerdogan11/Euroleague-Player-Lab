// Euroleague Player Lab service worker: the page and every JSON go network-first (a rebuild is never masked), the heavy
// static files (photos, crests, fonts, the 3D library) cache-first for thirty days so a club already opened reads offline.
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
const V = 'pl-2026-10-09_2051_UTC';
=======
const V = 'pl-2026-10-08_1536_UTC';
>>>>>>> Minutes and usage trend as rows that read like the log
=======
const V = 'pl-2026-10-05_1108_UTC';
>>>>>>> Turkish mode keeps Latin capitals
=======
const V = 'pl-2026-10-05_0853_UTC';
>>>>>>> Drop the shots-charted count from the opening page
=======
const V = 'pl-2026-10-02_1430_UTC';
>>>>>>> Turkish and English, switched with two flags at the top right
const STATIC = /\/(photos|logos|fonts|icons)\/|cdnjs\.cloudflare\.com/;
const DAY = 864e5, TTL = 30 * DAY;
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (STATIC.test(url.href)) {
    e.respondWith(caches.open(V).then(async c => {
      const hit = await c.match(req);
      if (hit && (hit.type === 'opaque' || Date.now() - +(hit.headers.get('sw-at') || 0) < TTL)) return hit;   // opaque entries live until the next build replaces the cache
      try {
        const r = await fetch(req);
        if (r.type === 'opaque') c.put(req, r.clone());   // cross-origin (the 3D library): stored as is; an opaque response cannot be rebuilt with headers
        else if (r.ok) { const h = new Headers(r.headers); h.set('sw-at', String(Date.now())); c.put(req, new Response(await r.clone().blob(), {status: r.status, statusText: r.statusText, headers: h})); }
        return r;
      }
      catch (err) { if (hit) return hit; throw err; }
    }));
    return;
  }
  if (req.mode === 'navigate' || url.pathname.endsWith('.json') || url.pathname.endsWith('.html') || url.pathname.endsWith('/')) {
    e.respondWith(caches.open(V).then(async c => {
      try { const r = await fetch(req); if (r.ok) c.put(req, r.clone()); return r; }
      catch (err) { const hit = await c.match(req, {ignoreSearch: true}); if (hit) return hit; if (req.mode === 'navigate') { const home = await c.match('/', {ignoreSearch: true}); if (home) return home; } throw err; }
    }));
  }
});
