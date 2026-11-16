// Mailhelp web interface: Web-Push on this device (enable, disable, test, worker status).
"use strict";

(function () {
  var controls = document.getElementById("push-controls");
  if (!controls) return;
  var status = document.getElementById("push-status");
  if (controls.dataset.offered === "false") return;
  var enableButton = document.getElementById("push-enable");
  var disableButton = document.getElementById("push-disable");
  var testButton = document.getElementById("push-test");
  var latest = null, busy = false, arrived = false, testing = false, receiptTimer = null;
  var MESSAGES = {
    push_disabled: "Web-Push ist auf dem Server nicht eingeschaltet. Unter Einrichtung einschalten und neu starten.",
    session_expired: "Nicht gespeichert: Anmeldung abgelaufen. Bitte neu anmelden.",
    provider_not_allowed: "Dieser Push-Anbieter ist nicht erlaubt. Einen unterstützten Browser verwenden.",
    invalid_subscription: "Das Browser-Abonnement ist ungültig. Websitedaten löschen und neu aktivieren.",
    key_conflict: "Der Serverschlüssel wurde geändert. Seite neu laden und Push neu aktivieren.",
    permission_denied: "Benachrichtigungen sind für diese Seite blockiert. In den Browsereinstellungen erlauben.",
    worker_failed: "Der Hintergrunddienst startet nicht. Seite neu laden; hilft das nicht, Websitedaten für Mailhelp löschen.",
    worker_timeout: "Der Hintergrunddienst startet nicht innerhalb von zehn Sekunden. Seite neu laden.",
    key_replace_failed: "Das alte Abonnement konnte nicht abgemeldet werden. Websitedaten löschen und neu aktivieren.",
    unsubscribe_failed: "Am Server deaktiviert; das Browser-Abonnement konnte nicht entfernt werden. Websitedaten löschen.",
    activation_failed: "Das Browser-Abonnement konnte nicht angelegt werden. Benachrichtigungseinstellungen prüfen.",
    network: "Mailhelp ist nicht erreichbar. Verbindung prüfen und erneut versuchen.",
    rate_limited: "Zu viele Testaufrufe. Eine Minute warten.",
    test_timeout: "Der Test hat das Zeitlimit erreicht. Prüfstand neu laden und später erneut testen.",
    test_failed: "Der Test konnte nicht ausgeführt werden. Verbindungen prüfen und erneut testen.",
    test_stale: "Der Prüfstand wurde geändert. Seite neu laden und erneut testen."
    ,provider_rejected: "Vom Anbieter abgelehnt. Gerät neu aktivieren und Kontaktadresse des Servers prüfen."
    ,expired: "Das Abonnement ist abgelaufen. Push neu aktivieren."
    ,retryable: "Der Push-Anbieter ist vorübergehend nicht erreichbar. Später erneut testen."
    ,device_not_registered: "Auf diesem Gerät zuerst Push aktivieren."
    ,invalid_request: "Die Testanfrage ist unvollständig. Seite neu laden."
    ,csrf_rejected: "Die Sicherheitsprüfung ist abgelaufen. Seite neu laden und erneut versuchen."
  };

  function stage(number, text) {
    controls.querySelector('[data-push-stage="' + number + '"] span').textContent = text;
  }

  function prerequisite() {
    stage(2, window.isSecureContext ? "✓" : "✗");
    if (!window.isSecureContext) return "Diese Adresse ist nicht per HTTPS erreichbar. Mailhelp über die HTTPS-Adresse öffnen.";
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    if (ios && !(navigator.standalone || window.matchMedia("(display-mode: standalone)").matches)) {
      stage(3, "✗");
      return "Auf dem iPhone zuerst zum Home-Bildschirm hinzufügen und von dort öffnen.";
    }
    var supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    stage(3, supported ? "✓" : "✗");
    return supported ? "" : "Dieser Browser unterstützt kein Web-Push.";
  }

  function json(path, options) {
    return fetch(path, Object.assign({credentials: "same-origin", cache: "no-store", headers: {Accept: "application/json"}}, options)).then(function (response) {
      if (response.redirected || response.status === 401) throw new Error("session_expired");
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.code || "network");
        return data;
      });
    }, function () { throw new Error("network"); });
  }

  function worker() {
    stage(5, "wird geprüft");
    return new Promise(function (resolve, reject) {
      var timer = window.setTimeout(function () { reject(new Error("worker_timeout")); }, 10000);
      navigator.serviceWorker.register("/sw.js").then(function () { return navigator.serviceWorker.ready; })
        .then(function (registration) {
          window.clearTimeout(timer);
          stage(5, "✓");
          if (registration.active) registration.active.postMessage({type: "mailhelp-worker-status"});
          resolve(registration);
        }, function () {
          window.clearTimeout(timer);
          reject(new Error("worker_failed"));
        });
    });
  }

  function key(text) {
    var raw = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }

  function sameKey(subscription, publicKey) {
    var previous = subscription.options && subscription.options.applicationServerKey;
    if (!previous) return false;
    var a = new Uint8Array(previous), b = key(publicKey);
    if (a.length !== b.length) return false;
    for (var i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
    return true;
  }

  function failure(error) {
    status.textContent = MESSAGES[error.message] || MESSAGES.activation_failed;
    busy = false;
    enableButton.disabled = disableButton.disabled = false;
  }

  function refresh() {
    return json("/api/push/status").then(function (data) {
      latest = data;
      stage(1, data.offered ? "✓" : "✗");
      stage(7, data.device.registered ? "✓" : "✗");
      var channels = data.profiles.every(function (profile) { return profile.decisions; });
      stage(8, channels ? "✓" : "Neue Vorschläge werden nicht per Push gemeldet.");
      stage(9, data.device.last_code === "accepted" ? "Zuletzt an den Anbieter übergeben: " + data.device.last_at :
        data.device.last_code === "provider_rejected" ? "Vom Anbieter abgelehnt – neu aktivieren." : "noch nicht geprüft");
      if (!data.offered) throw new Error("push_disabled");
      var missing = prerequisite();
      if (missing) { status.textContent = missing; return; }
      stage(4, Notification.permission === "granted" ? "✓" : "✗");
      if (Notification.permission !== "granted") {
        status.textContent = Notification.permission === "denied" ? MESSAGES.permission_denied : "Push aktivieren, um Benachrichtigungen zu erlauben.";
        return;
      }
      return worker().then(function (registration) {
        return registration.pushManager.getSubscription();
      }).then(function (subscription) {
        var matching = !!subscription && sameKey(subscription, data.public_key);
        stage(6, matching ? "✓" : "Dieses Gerät muss neu aktiviert werden.");
        var active = matching && data.device.registered && data.device.key_matches && !data.device.rejected;
        testButton.disabled = !active || !data.test_available;
        enableButton.textContent = active ? "Push aktivieren" : "Neu aktivieren";
        status.textContent = active ? (channels ? "Push ist auf diesem Gerät aktiviert." :
          "Neue Vorschläge werden nicht per Push gemeldet.") : "Dieses Gerät muss neu aktiviert werden.";
      });
    });
  }

  function changePush(enable) {
    if (busy) return;
    var missing = prerequisite();
    if (missing) { status.textContent = missing; return; }
    busy = true;
    enableButton.disabled = disableButton.disabled = true;
    var subscription = null, publicKey = null;
    // iOS requires this call synchronously within the user's tap.
    var permission = enable ? Notification.requestPermission() : Promise.resolve("granted");
    permission.then(function (result) {
      if (result !== "granted") throw new Error("permission_denied");
      return json("/api/push/public-key");
    }).then(function (data) {
      publicKey = data.public_key;
      return worker();
    }).then(function (registration) {
      return registration.pushManager.getSubscription().then(function (existing) {
        if (!enable || (existing && sameKey(existing, publicKey))) return existing;
        var remove = existing ? existing.unsubscribe() : Promise.resolve(true);
        return remove.then(function (removed) {
          if (removed === false) throw new Error("key_replace_failed");
          return registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key(publicKey)});
        });
      });
    }).then(function (value) {
      subscription = value;
      var body = new URLSearchParams({csrf: controls.dataset.csrf, key: randomHexKey(), public_key: publicKey});
      if (enable) body.set("subscription", JSON.stringify(subscription.toJSON()));
      return json("/api/push/" + (enable ? "subscribe" : "unsubscribe"), {method: "POST", body: body});
    }).then(function () {
      return enable || !subscription ? true : subscription.unsubscribe();
    }).then(function (removed) {
      if (removed === false) throw new Error("unsubscribe_failed");
      return refresh();
    }).then(function () {
      busy = false;
      enableButton.disabled = disableButton.disabled = false;
      if (!enable) status.textContent = "Push ist auf diesem Gerät deaktiviert.";
    }).catch(failure);
  }

  enableButton.addEventListener("click", function () { changePush(true); });
  disableButton.addEventListener("click", function () { changePush(false); });
  navigator.serviceWorker && navigator.serviceWorker.addEventListener("message", function (event) {
    if (event.data && event.data.type === "mailhelp-worker-status") {
      stage(5, "✓ · Stand " + event.data.version);
    }
    if (testing && event.data && event.data.type === "mailhelp-push-received" && event.data.kind === "test") {
      arrived = true;
      window.clearTimeout(receiptTimer);
      status.textContent = "Test-Push: auf diesem Gerät angekommen. Systemmeldung bitte prüfen.";
    }
  });
  testButton.addEventListener("click", function () {
    testing = true;
    arrived = false;
    testButton.disabled = true;
    status.textContent = "Test-Push wird an den Anbieter übergeben.";
    var body = new URLSearchParams({csrf: controls.dataset.csrf, key: randomHexKey(), version: latest.diagnostic_version});
    json("/api/push/test", {method: "POST", body: body}).then(function (result) {
      latest.diagnostic_version = result.diagnostic_version;
      if (result.code !== "accepted") throw new Error(result.code);
      if (!arrived) {
        status.textContent = "An den Anbieter übergeben. Warte auf dieses Gerät.";
        receiptTimer = window.setTimeout(function () {
          testing = false;
          status.textContent = "Der Anbieter hat angenommen, das Gerät hat nichts angezeigt. Fokus-Modus, Systemeinstellungen und Energiesparen prüfen.";
        }, 20000);
      }
      testButton.disabled = false;
    }).catch(function (error) { testing = false; testButton.disabled = false; failure(error); });
  });
  refresh().catch(failure);
})();
