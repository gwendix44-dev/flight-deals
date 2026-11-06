// Cache minimal de la coquille de l'appli ; les données (deals.json) sont toujours lues en direct.
const CACHE = "fd-shell-v1";
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "manifest.json", "icon.svg"]))));
self.addEventListener("activate", e => self.clients.claim());
self.addEventListener("fetch", e => {
  if (e.request.url.includes("deals.json")) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
