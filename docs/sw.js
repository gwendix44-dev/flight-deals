// Cache minimal de la coquille de l'appli ; les données (deals.json) sont toujours lues en direct.
const CACHE = "fd-shell-v2";
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "manifest.json", "icon-192.png"]))));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || /deals\.json|preferences\.json|api\.github\.com/.test(e.request.url)) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
