const CACHE_NAME = "talabiytak-static-v1";
const APP_CACHE_PREFIX = "talabiytak-static-";
const STATIC_ASSETS = [
  "/static/manifest.webmanifest",
  "/static/style.css",
  "/static/app.js",
  "/static/branding/talabiytak-logo-48.png",
  "/static/branding/talabiytak-favicon-32.png",
  "/static/branding/talabiytak-apple-touch-180.png",
  "/static/branding/talabiytak-icon-192.png",
  "/static/branding/talabiytak-icon-512.png",
  "/static/branding/talabiytak-maskable-512.png"
];
const STATIC_ASSET_SET = new Set(STATIC_ASSETS);

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith(APP_CACHE_PREFIX) && key !== CACHE_NAME).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !STATIC_ASSET_SET.has(url.pathname)) return;
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
    }
    return response;
  })));
});
