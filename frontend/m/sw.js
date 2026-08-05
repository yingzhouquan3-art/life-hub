/* 只缓存外壳，不缓存任何生活数据。
 *
 * 数据请求一律走网络：宁可显示「离线」，也不能把昨天的余额当成今天的。
 * 写入的离线能力由 app.js 的队列负责，不在这里做后台同步。
 */
'use strict';

const SHELL = 'lifehub-shell-v1';
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
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request))
  );
});
