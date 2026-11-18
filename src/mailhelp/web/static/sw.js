// Mailhelp service worker: caches only the application shell and the offline page.
// Pages, data and actions always go to the network and are never stored or replayed.
"use strict";

// Replaced by the server with a hash of the shell files: a changed stylesheet changes this file,
// so browsers install the new worker and drop the stale shell cache.
var CACHE = "mailhelp-shell-__SHELL_VERSION__";
var SHELL = ["/offline.html", "/offline-en.html", "/static/app.css", "/static/icon-192.png", "/static/icon-512.png"];
var LANGUAGE = new URLSearchParams(self.location.search).get("lang");
var OFFLINE = LANGUAGE === "en" ? "/offline-en.html" : "/offline.html";

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
    event.respondWith(fetch(request).catch(function () { return caches.match(OFFLINE); }));
    return;
  }
  if (SHELL.indexOf(url.pathname) !== -1) {
    event.respondWith(caches.match(request).then(function (cached) { return cached || fetch(request); }));
  }
});

// Texts and targets are fixed here: a push payload only selects one of these kinds,
// so lock screens never show mail content and no injected link can be opened.
var NOTIFICATIONS = {
  decisions: { body: "Neue Aufgaben oder Termine zur Entscheidung.", url: "/offen" },
  daily_briefing: { body: "Dein Tagesüberblick ist verfügbar.", url: "/briefing" },
  briefing: { body: "Dein Tagesüberblick ist verfügbar.", url: "/briefing" },
  action_results: { body: "Ein Aktionsergebnis ist in Mailhelp verfügbar.", url: "/verlauf" },
  system_errors: { body: "Ein Betriebsproblem benötigt deine Aufmerksamkeit.", url: "/status" },
  test: { body: "Test: Web-Push funktioniert auf diesem Gerät.", url: "/einstellungen?bereich=benachrichtigungen" },
  information: { body: "Neue Informationen in Mailhelp.", url: "/" }
};
var NOTIFICATIONS_EN = {
  decisions: { body: "New tasks or events are ready for your decision." },
  daily_briefing: { body: "Your daily briefing is available." },
  briefing: { body: "Your daily briefing is available." },
  action_results: { body: "An action result is available in Mailhelp." },
  system_errors: { body: "An operating problem needs your attention." },
  test: { body: "Test: web push works on this device." },
  information: { body: "New information in Mailhelp." }
};

self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "mailhelp-worker-status" && event.source) {
    event.source.postMessage({type: "mailhelp-worker-status", version: CACHE});
  }
});

function notificationKind(event) {
  try {
    var tag = event.data.json().tag;
    return Object.prototype.hasOwnProperty.call(NOTIFICATIONS, tag) ? tag : "information";
  } catch (error) {
    return "information";
  }
}

self.addEventListener("push", function (event) {
  var kind = notificationKind(event);
  event.waitUntil(self.registration.showNotification("Mailhelp", {
    body: (LANGUAGE === "en" ? NOTIFICATIONS_EN : NOTIFICATIONS)[kind].body,
    icon: "/static/icon-192.png", tag: "mailhelp-" + kind, data: { kind: kind }
  }).then(function () {
    return self.clients.matchAll({type: "window", includeUncontrolled: true}).then(function (clients) {
      clients.forEach(function (client) { client.postMessage({type: "mailhelp-push-received", kind: kind}); });
    });
  }));
});

self.addEventListener("notificationclick", function (event) {
  var kind = (event.notification.data || {}).kind;
  var target = (Object.prototype.hasOwnProperty.call(NOTIFICATIONS, kind) ? NOTIFICATIONS[kind] : NOTIFICATIONS.information).url;
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clients) {
    var client = clients.find(function (item) { return new URL(item.url).origin === self.location.origin; });
    if (!client) return self.clients.openWindow(target);
    // An uncontrolled window cannot be navigated; a new window is opened instead.
    return client.focus().then(function (focused) { return focused.navigate(target); })
      .catch(function () { return self.clients.openWindow(target); });
  }));
});
