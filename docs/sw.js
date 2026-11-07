// Service worker : cache de la coquille de l'appli + notifications natives (Web Push), sans aucune appli externe.
const CACHE = "fd-shell-v4";
self.addEventListener("install", e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "manifest.json", "icon-192.png"]))); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || /deals\.json|preferences\.json|status\.json/.test(u.pathname)) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});

// Une notification arrive (même si l'appli est fermée) : on l'affiche et on prévient les fenêtres ouvertes de se rafraîchir.
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(Promise.all([
    self.registration.showNotification(d.title || "Flight Deals", {
      body: d.body || "", icon: "icon-192.png", badge: "icon-192.png", tag: d.tag || "flight-deals", renotify: true,
      data: { url: d.url || "./?fresh=1" } }),
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => cs.forEach(c => c.postMessage({ type: "refresh" }))),
  ]));
});

// Un tap sur la notification ouvre (ou ramène au premier plan) le dashboard, avec les données fraîches.
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || "./?fresh=1", self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => {
    for (const c of cs) if (c.url.startsWith(self.registration.scope) && "focus" in c) { c.postMessage({ type: "refresh" }); return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
