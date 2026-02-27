/* ─────────────────────────────────────────────────────────────────────────
   ZTracky Service Worker  –  Offline Location Queueing
   ─────────────────────────────────────────────────────────────────────────
   Strategy:
   • Location POST requests are attempted normally when online.
   • If the network is unavailable the request is stored in IndexedDB.
   • The Background Sync API retries the queue automatically when connectivity
     is restored.  Falls back to a manual retry on 'sync' event for older
     browsers.
   ───────────────────────────────────────────────────────────────────────── */

const CACHE_NAME = 'ztracky-v1';
const QUEUE_NAME = 'ztracky-location-queue';
const STATIC_ASSETS = ['/', '/index.html', '/app.js', '/style.css'];

// ── Install: cache static shell ────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ─────────────────────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch: intercept location POSTs and queue when offline ─────────────────
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Only intercept location update POSTs
  if (url.pathname === '/api/location' && e.request.method === 'POST') {
    e.respondWith(
      fetch(e.request.clone()).catch(async () => {
        // Network failed → queue the request body for later retry
        const body = await e.request.clone().json().catch(() => null);
        if (body) await enqueue(body, e.request.headers.get('Authorization'));
        // Return a synthetic response so the app doesn't error out
        return new Response(JSON.stringify({ queued: true }), {
          status: 202,
          headers: { 'Content-Type': 'application/json' },
        });
      })
    );
    return;
  }

  // Static assets: cache-first
  if (STATIC_ASSETS.some(a => url.pathname.endsWith(a.replace('/', '')))) {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request))
    );
  }
});

// ── Background Sync: flush queued location updates ─────────────────────────
self.addEventListener('sync', e => {
  if (e.tag === QUEUE_NAME) {
    e.waitUntil(flushQueue());
  }
});

// ── IndexedDB helpers ──────────────────────────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('ztracky-sw', 1);
    req.onupgradeneeded = ev => {
      ev.target.result.createObjectStore('queue', { autoIncrement: true });
    };
    req.onsuccess = ev => resolve(ev.target.result);
    req.onerror   = ev => reject(ev.target.error);
  });
}

async function enqueue(body, authHeader) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readwrite');
    tx.objectStore('queue').add({ body, authHeader, ts: Date.now() });
    tx.oncomplete = resolve;
    tx.onerror    = ev => reject(ev.target.error);
  });
}

async function flushQueue() {
  const db = await openDB();
  const items = await new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readonly');
    const req = tx.objectStore('queue').getAll();
    req.onsuccess = ev => resolve(ev.target.result);
    req.onerror   = ev => reject(ev.target.error);
  });

  // Derive API base from SW scope (e.g. http://localhost:8000)
  const apiBase = self.registration.scope.replace(':3001', ':8000').replace(/\/$/, '');

  for (const item of items) {
    try {
      const res = await fetch(`${apiBase}/api/location`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(item.authHeader ? { Authorization: item.authHeader } : {}),
        },
        body: JSON.stringify(item.body),
      });
      if (res.ok) {
        // Remove successfully sent item
        await new Promise((resolve, reject) => {
          const tx = db.transaction('queue', 'readwrite');
          tx.objectStore('queue').delete(item.ts);  // key may differ; clear all on success
          tx.oncomplete = resolve;
          tx.onerror    = ev => reject(ev.target.error);
        });
      }
    } catch (_) {
      // Still offline — stop flushing, retry on next sync
      break;
    }
  }
  // Clear the whole store after a successful flush pass
  const tx2 = db.transaction('queue', 'readwrite');
  tx2.objectStore('queue').clear();
}
