/* VantiGo - Service Worker (offline-first para la app del vendedor)
 *
 * Estrategias:
 *  - Librerias/estaticos (Tailwind, Alpine, Leaflet, iconos): cache primero -> abre al instante.
 *  - Mosaicos del mapa: cache primero con tope de entradas -> el mapa se ve sin internet
 *    en las zonas ya recorridas.
 *  - Fotos: cache primero (no cambian).
 *  - API JSON (ruta, monitoreo, fotos): red con limite de tiempo, si falla -> ultima copia.
 *  - Paginas HTML: red primero, si falla -> copia guardada, si no hay -> /offline.
 *  - POST/PUT: pasan directo; la app encola en IndexedDB lo que falle y lo reenvia.
 */
const VERSION = 'vantigo-v4';
const CACHE_STATIC = VERSION + '-static';
const CACHE_PAGES = VERSION + '-pages';
const CACHE_API = VERSION + '-api';
const CACHE_TILES = VERSION + '-tiles';
const CACHE_PHOTOS = VERSION + '-photos';
const KEEP = [CACHE_STATIC, CACHE_PAGES, CACHE_API, CACHE_TILES, CACHE_PHOTOS];
const OFFLINE_URL = '/offline';
const MAX_TILES = 2500;     // ~ 2500 mosaicos = varias zonas de la ciudad a zoom de calle
const MAX_PHOTOS = 400;
const API_TIMEOUT_MS = 9000;

const PRECACHE = [
  OFFLINE_URL,
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache =>
      Promise.all(PRECACHE.map(u => cache.add(new Request(u, { mode: 'no-cors' })).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => !KEEP.includes(k)).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', event => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});

function isStatic(url) {
  return url.pathname.startsWith('/static/') ||
    url.hostname === 'cdn.tailwindcss.com' || url.hostname === 'cdn.jsdelivr.net' ||
    url.hostname === 'unpkg.com' || url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
}
function isTile(url) { return /tile\.openstreetmap\.org$/.test(url.hostname) || /\/tiles?\//.test(url.pathname) && url.hostname !== self.location.hostname; }
function isPhoto(url) { return url.origin === self.location.origin && url.pathname.startsWith('/sales/photo/'); }
function isApi(url) {
  return url.origin === self.location.origin && (
    url.pathname.startsWith('/sales/api/') || /^\/sales\/deal\/\d+\/photos$/.test(url.pathname) ||
    url.pathname.startsWith('/api/'));
}
function cacheable(res) { return res && (res.ok || res.type === 'opaque'); }

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length <= max) return;
  // Se borran las mas antiguas (orden de insercion)
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

async function cacheFirst(req, cacheName, max) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req, { ignoreVary: true });
  if (hit) {
    // Refresco silencioso de estaticos para recibir actualizaciones sin bloquear
    if (cacheName === CACHE_STATIC) fetch(req).then(r => { if (cacheable(r)) cache.put(req, r); }).catch(() => null);
    return hit;
  }
  try {
    const res = await fetch(req);
    if (cacheable(res)) { cache.put(req, res.clone()); if (max) trim(cacheName, max); }
    return res;
  } catch (e) {
    return new Response('', { status: 504, statusText: 'offline' });
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(v => { clearTimeout(t); resolve(v); }, e => { clearTimeout(t); reject(e); });
  });
}

async function networkFirstApi(req) {
  const cache = await caches.open(CACHE_API);
  try {
    const res = await withTimeout(fetch(req), API_TIMEOUT_MS);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (e) {
    const hit = await cache.match(req, { ignoreVary: true });
    if (hit) {
      // Se marca la respuesta para que la app avise "datos guardados"
      const h = new Headers(hit.headers); h.set('X-VG-Cache', '1');
      return new Response(await hit.blob(), { status: hit.status, headers: h });
    }
    return new Response(JSON.stringify({ ok: false, offline: true, msg: 'Sin conexion' }),
      { status: 503, headers: { 'Content-Type': 'application/json', 'X-VG-Cache': 'none' } });
  }
}

async function networkFirstPage(req) {
  const cache = await caches.open(CACHE_PAGES);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (e) {
    const hit = await cache.match(req, { ignoreVary: true, ignoreSearch: false }) ||
                await cache.match(new URL(req.url).pathname, { ignoreVary: true });
    if (hit) return hit;
    const off = await caches.match(OFFLINE_URL);
    return off || new Response('Sin conexion', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (!url.protocol.startsWith('http')) return;
  // Diagnostico y autenticacion nunca se sirven desde cache
  if (url.pathname.startsWith('/__diag') || url.pathname.startsWith('/auth/')) return;

  if (isTile(url))   { event.respondWith(cacheFirst(req, CACHE_TILES, MAX_TILES)); return; }
  if (isPhoto(url))  { event.respondWith(cacheFirst(req, CACHE_PHOTOS, MAX_PHOTOS)); return; }
  if (isStatic(url)) { event.respondWith(cacheFirst(req, CACHE_STATIC)); return; }
  if (isApi(url))    { event.respondWith(networkFirstApi(req)); return; }
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(networkFirstPage(req)); return;
  }
  // Resto (misma u otra origen): red, con respaldo en cache si existiera
  event.respondWith(fetch(req).catch(() => caches.match(req).then(h => h || new Response('', { status: 504 }))));
});

/* ---- Sincronizacion en segundo plano (visitas offline del modulo anterior) ---- */
self.addEventListener('sync', event => {
  if (event.tag === 'sync-visits') event.waitUntil(syncVisits());
  if (event.tag === 'vg-queue') event.waitUntil(notifyClients('vg-flush'));
});

async function notifyClients(type) {
  const cs = await self.clients.matchAll({ includeUncontrolled: true });
  cs.forEach(c => c.postMessage({ type }));
}

async function syncVisits() {
  try {
    const db = await openDB();
    const visits = await getAllPendingVisits(db);
    for (const visit of visits) {
      try {
        const response = await fetch('/analytics/visit-report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams(visit.data)
        });
        if (response.ok) await deletePendingVisit(db, visit.id);
      } catch (e) { /* se reintenta en el siguiente sync */ }
    }
  } catch (e) { /* sin IndexedDB */ }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('GPSComercialOffline', 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pendingVisits')) db.createObjectStore('pendingVisits', { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = e => reject(e.target.error);
  });
}
function getAllPendingVisits(db) {
  return new Promise((resolve, reject) => {
    const req = db.transaction('pendingVisits', 'readonly').objectStore('pendingVisits').getAll();
    req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error);
  });
}
function deletePendingVisit(db, id) {
  return new Promise((resolve, reject) => {
    const req = db.transaction('pendingVisits', 'readwrite').objectStore('pendingVisits').delete(id);
    req.onsuccess = () => resolve(); req.onerror = () => reject(req.error);
  });
}
