// Mailhelp web interface: comfort functions only. Every page also works without this file.
"use strict";

(function () {
  var HEALTH_INTERVAL = 30000;
  var REFRESH_INTERVAL = 15000;

  function setConnection(state) {
    // Every page rendered by Mailhelp contains this status element.
    var badge = document.getElementById("verbindung");
    var texts = {
      online: "● Verbunden",
      offline: "PC nicht erreichbar",
      update: "Neue Daten – bitte neu laden"
    };
    badge.hidden = false;
    badge.dataset.state = state;
    badge.textContent = texts[state];
  }

  function checkHealth() {
    return fetch("/health", { cache: "no-store", credentials: "same-origin" })
      .then(function (response) { setConnection(response.ok ? "online" : "offline"); })
      .catch(function () { setConnection("offline"); });
  }

  // Typed but unsent text must never be lost by an automatic reload.
  function hasTypedText() {
    var fields = document.querySelectorAll("input:not([type]), input[type='text'], textarea");
    return Array.prototype.some.call(fields, function (field) { return field.value.trim() !== ""; });
  }

  function checkState() {
    var current = document.body.dataset.fingerprint;
    return fetch("/api/stand", {
      cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" }
    })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (state) {
        if (!state || state.fingerprint === current) {
          return;
        }
        if (hasTypedText()) {
          setConnection("update");
          return;
        }
        window.location.reload();
      })
      .catch(function () { setConnection("offline"); });
  }

  function whenVisible() {
    if (document.visibilityState === "visible") {
      checkHealth();
      checkState();
    }
  }

  // A second tap must not send the same form twice while the first is on its way.
  function lockForm(event) {
    var buttons = event.target.querySelectorAll("button");
    buttons.forEach(function (button) { button.disabled = true; });
  }

  function start() {
    document.querySelectorAll("form[method='post']").forEach(function (form) {
      form.addEventListener("submit", lockForm);
    });
    window.addEventListener("online", checkHealth);
    window.addEventListener("offline", function () { setConnection("offline"); });
    checkHealth();
    window.setInterval(checkHealth, HEALTH_INTERVAL);
    if (document.body.dataset.fingerprint) {
      document.addEventListener("visibilitychange", whenVisible);
      window.setInterval(checkState, REFRESH_INTERVAL);
    }
  }

  start();
})();
