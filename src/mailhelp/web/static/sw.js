// Mailhelp service worker: caches only the application shell and the offline page.
// Pages, data and actions always go to the network and are never stored or replayed.
"use strict";

var CACHE = "mailhelp-shell-v1";
var SHELL = ["/offline.html", "/static/app.css", "/static/icon-192.png", "/static/icon-512.png"];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE)
      .then(function (cache) { return cache.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(keys
          .filter(function (key) { return key !== CACHE; })
          .map(function (key) { return caches.delete(key); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  var url = new URL(request.url);
  // Actions (POST) and foreign requests are left to the browser unchanged.
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }
  if (request.mode === "navigate") {
    // Pages come from the PC; without it the offline page explains why.
    event.respondWith(fetch(request).catch(function () { return caches.match("/offline.html"); }));
    return;
  }
  if (SHELL.indexOf(url.pathname) !== -1) {
    event.respondWith(caches.match(request).then(function (cached) { return cached || fetch(request); }));
  }
});
