/* Klipal service worker: uygulama olarak yüklenebilmek ve çevrimdışı uyarısı için. */
const OFFLINE = '<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Klipal</title>' +
  '<body style="font:17px/1.55 system-ui,sans-serif;margin:0;padding:48px 20px;background:#F3F5F6;color:#0F1B2D">' +
  '<h1 style="font-size:24px;margin:0 0 8px">İnternet bağlantısı yok</h1><p style="margin:0">Video indirmek için bağlantı gerekir. Bağlandıktan sonra sayfayı yenileyin.</p></body></html>';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.mode !== 'navigate' || new URL(req.url).pathname.includes('/api/')) return;
  event.respondWith(fetch(req).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
