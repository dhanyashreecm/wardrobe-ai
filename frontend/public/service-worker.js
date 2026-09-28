/*
 * WardrobeAI service worker - what makes the site installable as an app.
 *
 * It caches only the app's own files (HTML/JS/CSS/icons) so the app
 * opens instantly. It NEVER caches /api/ calls, so wardrobe data,
 * logins and recommendations always come live from the backend.
 */
const CACHE = "wardrobeai-v3"; // bump on releases: old app files are dropped
const SHELL = ["/", "/index.html", "/manifest.json", "/logo192.png", "/logo512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GETs for this site's own files. API calls (on port 5001
  // or under /api/) go straight to the network, never cached.
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return;
  }

  // Page loads: try the network first, fall back to the cached app
  // shell so the app still opens with a weak connection.
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/index.html")));
    return;
  }

  // Static files: serve from cache, update in the background.
  event.respondWith(
    caches.match(req).then((cached) => {
      const fresh = fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => cached);
      return cached || fresh;
    })
  );
});
