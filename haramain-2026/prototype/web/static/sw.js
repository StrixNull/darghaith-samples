/* Hawnan service worker: caches the guest shell so the holding card opens
   without a network. API calls are never cached (the page keeps its own last
   known state). Registration is optional; the pages work without it. */
var CACHE = "hawnan-shell-v1";
var SHELL = ["/guest", "/static/hawnan.css", "/static/hawnan.js", "/static/qr.js", "/static/icon.svg", "/manifest.webmanifest"];
self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).catch(function () {}));
  self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) { return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); })); }));
  self.clients.claim();
});
self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.indexOf("/api/") === 0 || url.origin !== location.origin) return;
  var key = url.pathname === "/guest" ? "/guest" : e.request;
  e.respondWith(
    caches.match(key).then(function (hit) {
      var net = fetch(e.request).then(function (r) {
        if (r && r.ok) { var copy = r.clone(); caches.open(CACHE).then(function (c) { c.put(key, copy); }); }
        return r;
      }).catch(function () { return hit; });
      return hit || net;
    })
  );
});
