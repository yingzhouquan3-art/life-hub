/* 只缓存外壳，不缓存任何生活数据。
 *
 * 数据请求一律走网络：宁可显示「离线」，也不能把昨天的余额当成今天的。
 * 写入的离线能力由 app.js 的队列负责，不在这里做后台同步。
 *
 * 缓存策略是 stale-while-revalidate：先拿缓存让页面立刻能开，同时在后台
 * 去网络取一份新的存起来，下次打开就是新的。
 *
 * 早先这里是纯 cache-first（`hit || fetch`）加一个永不变的缓存名，那意味着
 * **手机缓存过一次外壳，就永远运行那个版本**：缓存名不变所以 activate 里的
 * 清理不触发，命中缓存就不查网络，之后所有修复都到不了用户手上。
 */
'use strict';

const SHELL = 'lifehub-shell-v2';
const FILES = ['./', './index.html', './app.js', './manifest.webmanifest', './icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;          // 数据永远走网络
  if (event.request.method !== 'GET') return;

  event.respondWith((async () => {
    const cached = await caches.match(event.request);
    // 后台更新。失败不影响这次返回——离线时就是要用缓存那一份。
    const fresh = fetch(event.request).then((response) => {
      if (response && response.ok) {
        const copy = response.clone();
        caches.open(SHELL).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => null);
    return cached || (await fresh) || Response.error();
  })());
});
