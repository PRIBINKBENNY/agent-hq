/* Agent HQ service worker: push notifications + offline shell for the phone app */
self.addEventListener("install", e => { self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(self.clients.claim()); });
self.addEventListener("push", e => {
  let d = { title: "Agent HQ", body: "", url: "/m", tag: "hq" };
  try { d = { ...d, ...e.data.json() }; } catch (_) { d.body = e.data ? e.data.text() : ""; }
  e.waitUntil(self.registration.showNotification(d.title, { body: d.body, tag: d.tag, icon: "/icon.png", badge: "/icon.png", data: { url: d.url } }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/m";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => { for (const c of cs) { if ("focus" in c) { c.navigate(url); return c.focus(); } } return self.clients.openWindow(url); }));
});
self.addEventListener("fetch", e => {
  if (e.request.mode === "navigate") { e.respondWith(fetch(e.request).catch(() => new Response("<h1 style='font-family:system-ui;color:#e6eaf2;background:#080b14;height:100vh;margin:0;display:grid;place-items:center'>Agent HQ is unreachable. Is the Mac awake and the tunnel up?</h1>", { headers: { "content-type": "text/html" } }))); }
});
