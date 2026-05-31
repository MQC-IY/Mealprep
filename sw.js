const CACHE = 'mahlzeit-v1';

const PRECACHE = [
  '/Mealprep/',
  '/Mealprep/index.html',
  '/Mealprep/weeks.json',
  '/Mealprep/recipe_times.json',
  '/Mealprep/recipe_images.json',
  '/Mealprep/manifest.json',
  '/Mealprep/icons/icon-192.png',
  '/Mealprep/icons/icon-512.png',
  '/Mealprep/icons/icon-180.png',
];

// Install: cache the app shell
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

// Activate: delete old cache versions
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// Fetch strategy
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // weeks.json — network-first: always try to get the latest plan
  if (url.pathname.endsWith('weeks.json')) {
    event.respondWith(
      fetch(request)
        .then(response => {
          caches.open(CACHE).then(cache => cache.put(request, response.clone()));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Same-origin assets (app shell, icons, data) — cache-first
  if (url.origin === location.origin) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            caches.open(CACHE).then(cache => cache.put(request, response.clone()));
          }
          return response;
        });
      })
    );
    return;
  }

  // External resources (Tailwind CDN, Google Fonts, Unsplash images) — cache-as-you-go
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(response => {
        if (response.ok) {
          caches.open(CACHE).then(cache => cache.put(request, response.clone()));
        }
        return response;
      }).catch(() => new Response('', { status: 503 }));
    })
  );
});
