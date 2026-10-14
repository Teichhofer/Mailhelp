// Mailhelp service worker: caches only the application shell and the offline page.
// Pages, data and actions always go to the network and are never stored or replayed.
"use strict";

var CACHE = "mailhelp-shell-v4";
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

// Texts and targets are fixed here: a push payload only selects one of these kinds,
// so lock screens never show mail content and no injected link can be opened.
var NOTIFICATIONS = {
  decisions: { body: "Neue Entscheidungen warten in Mailhelp.", url: "/offen" },
  briefing: { body: "Dein Tagesüberblick ist verfügbar.", url: "/briefing" }
};

function notificationKind(event) {
  try {
    var tag = event.data.json().tag;
    return Object.prototype.hasOwnProperty.call(NOTIFICATIONS, tag) ? tag : "decisions";
  } catch (error) {
    return "decisions";
  }
}

self.addEventListener("push", function (event) {
  var kind = notificationKind(event);
  event.waitUntil(self.registration.showNotification("Mailhelp", {
    body: NOTIFICATIONS[kind].body, icon: "/static/icon-192.png", tag: "mailhelp-" + kind, data: { kind: kind }
  }));
});

self.addEventListener("notificationclick", function (event) {
  var kind = (event.notification.data || {}).kind;
  var target = (Object.prototype.hasOwnProperty.call(NOTIFICATIONS, kind) ? NOTIFICATIONS[kind] : NOTIFICATIONS.decisions).url;
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clients) {
    var client = clients.find(function (item) { return new URL(item.url).origin === self.location.origin; });
    if (!client) return self.clients.openWindow(target);
    // An uncontrolled window cannot be navigated; a new window is opened instead.
    return client.focus().then(function (focused) { return focused.navigate(target); })
      .catch(function () { return self.clients.openWindow(target); });
  }));
});
