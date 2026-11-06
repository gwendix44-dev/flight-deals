// Cache minimal de la coquille de l'appli. Les données et les flux externes (ntfy, API GitHub) ne passent jamais par ici.
const CACHE = "fd-shell-v3";
self.addEventListener("install", e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "manifest.json", "icon-192.png"]))); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || /deals\.json|preferences\.json/.test(u.pathname)) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
