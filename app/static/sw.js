const CACHE_NAME = 'gps-comercial-v2';
const OFFLINE_URL = '/offline';
const URLS_TO_CACHE = [
  '/',
  '/dashboard',
  '/offline',
  '/static/manifest.json',
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js'
];

// Install
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(URLS_TO_CACHE).catch(err => {
        console.warn('Cache addAll partial fail:', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch - network first, cache fallback
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  // Skip non-http requests
  if (!event.request.url.startsWith('http')) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Clone and cache successful responses
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, clone);
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then(cached => {
          if (cached) return cached;
          // If it's a navigation request, show offline page
          if (event.request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          return new Response('Offline', { status: 503 });
        });
      })
  );
});

// Background Sync for offline visit submissions
self.addEventListener('sync', event => {
  if (event.tag === 'sync-visits') {
    event.waitUntil(syncVisits());
  }
});

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
        if (response.ok) {
          await deletePendingVisit(db, visit.id);
        }
      } catch (e) {
        console.log('Sync visit failed, will retry:', e);
      }
    }
  } catch (e) {
    console.log('Sync error:', e);
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('GPSComercialOffline', 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pendingVisits')) {
        db.createObjectStore('pendingVisits', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = e => reject(e.target.error);
  });
}

function getAllPendingVisits(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pendingVisits', 'readonly');
    const store = tx.objectStore('pendingVisits');
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function deletePendingVisit(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pendingVisits', 'readwrite');
    const store = tx.objectStore('pendingVisits');
    const req = store.delete(id);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}
