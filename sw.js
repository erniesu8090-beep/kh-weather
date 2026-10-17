const CACHE_NAME = 'kh-weather-v3';
const ASSETS = ['./', './index.html', './config.json', './styles.css', './stations.js', './weather.js', './app.js', './manifest.json', './favicon.ico', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('kh-weather-') && key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.includes('/api/') || url.pathname.endsWith('/weather.json')) return;
  event.respondWith(fetch(event.request, {cache: 'no-cache'}).then(response => {
    if (response.ok && ASSETS.some(path => new URL(path, self.registration.scope).pathname === url.pathname)) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)));
    }
    return response;
  }).catch(async () => (await caches.match(event.request, {ignoreSearch: true})) || new Response('離線中，請連線後重試', {status: 503, headers: {'Content-Type': 'text/plain; charset=utf-8'}})));
});
