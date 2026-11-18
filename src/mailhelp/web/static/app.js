// Mailhelp web interface: comfort functions only. Every page also works without this file.
"use strict";

// 5.5: idempotency keys also over plain HTTP in the home network. crypto.randomUUID exists
// only in secure contexts; getRandomValues also outside them.
function randomHexKey() {
  var cryptography = window.crypto;
  if (cryptography && typeof cryptography.randomUUID === "function") {
    return cryptography.randomUUID().replace(/-/g, "");
  }
  var hex = "";
  if (cryptography && typeof cryptography.getRandomValues === "function") {
    var bytes = cryptography.getRandomValues(new Uint8Array(16));
    for (var index = 0; index < bytes.length; index++) hex += (bytes[index] < 16 ? "0" : "") + bytes[index].toString(16);
    return hex;
  }
  while (hex.length < 32) hex += Math.floor(Math.random() * 0x10000).toString(16).padStart(4, "0");
  return hex;
}

var MAILHELP_TEXTS = JSON.parse(document.body.dataset.uiTexts || "{}");
function mailhelpText(text) {
  return MAILHELP_TEXTS[text] || text;
}

(function () {
  var HEALTH_INTERVAL = 30000;
  var REFRESH_INTERVAL = 15000;

  function setConnection(state) {
    // Every page rendered by Mailhelp contains this status element.
    var badge = document.getElementById("verbindung");
    var texts = {
      online: mailhelpText("● Verbunden"),
      offline: mailhelpText("PC nicht erreichbar"),
      update: mailhelpText("Neue Daten – bitte neu laden")
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
    return Array.prototype.some.call(fields, function (field) { return field.value.trim() !== "" && field.value !== field.defaultValue; });
  }

  function checkState() {
    var current = document.body.dataset.fingerprint;
    return fetch(document.body.dataset.stateUrl || "/api/stand", {
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
        // The split view updates itself in place; every other page is reloaded.
        if (document.dispatchEvent(new CustomEvent("mailhelp:stale", { cancelable: true }))) {
          window.location.reload();
        }
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
    if (event.defaultPrevented) return;
    if (event.submitter && event.submitter.name) {
      var choice = document.createElement("input");
      choice.type = "hidden"; choice.name = event.submitter.name; choice.value = event.submitter.value;
      event.target.appendChild(choice);
    }
    var buttons = event.target.querySelectorAll("button");
    buttons.forEach(function (button) { button.disabled = true; });
    if (event.target.classList.contains("draft-intents")) {
      // The model needs a moment; the page reloads with the draft.
      event.target.querySelector('[role="status"]').textContent = mailhelpText("Entwurf wird erstellt …");
    }
  }

  function start() {
    var command = document.querySelector("[data-command-status]");
    if (command) {
      function progress() {
        fetch(command.dataset.commandStatus, {cache: "no-store", credentials: "same-origin", headers: {Accept: "application/json"}})
          .then(function (response) {
            if (response.status === 401) return {target: "/anmelden"};
            if (!response.ok) throw new Error(mailhelpText("Status gerade nicht verfügbar."));
            return response.json();
          })
          .then(function (result) {
            if (result && result.target) location.replace(result.target);
            else window.setTimeout(progress, 1000);
          })
          .catch(function () {
            command.textContent = mailhelpText("Verbindung unterbrochen. Die Aktion wird nicht erneut gesendet; der Status wird weiter geprüft.");
            window.setTimeout(progress, 2000);
          });
      }
      progress();
    }
    document.querySelectorAll(".setting-help").forEach(function (help) {
      function reveal() { help.classList.remove("dismissed"); }
      help.addEventListener("mouseenter", reveal);
      help.addEventListener("focusin", reveal);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        document.querySelectorAll(".setting-help:hover, .setting-help:focus-within").forEach(function (help) {
          help.classList.add("dismissed");
        });
      }
    });
    document.querySelectorAll("form[method='post']").forEach(function (form) {
      form.addEventListener("submit", lockForm);
    });
    window.addEventListener("online", checkHealth);
    window.addEventListener("offline", function () { setConnection("offline"); });
    checkHealth();
    window.setInterval(checkHealth, HEALTH_INTERVAL);
    if ("serviceWorker" in navigator) {
      // Without the worker only the offline page is missing; everything else works.
      navigator.serviceWorker.register("/sw.js?lang=" + document.documentElement.lang).catch(function () { return null; });
    }
    if (document.body.dataset.fingerprint) {
      document.addEventListener("visibilitychange", whenVisible);
      window.setInterval(checkState, REFRESH_INTERVAL);
    }
  }

  start();
})();

// A fixed layer can drift during async scrolling in iOS WebKit. Keep CSS fixed positioning
// normally; if its measured edge leaves the visible viewport, anchor it in document coordinates.
(function () {
  var bar = document.querySelector(".tab-bar"), view = window.visualViewport;
  if (!bar || !view) return;
  var frame = null, anchored = false, original = bar.style.cssText;
  function align() {
    frame = null;
    if (window.matchMedia("(min-width: 900px)").matches) {
      bar.style.cssText = original; anchored = false;
      return;
    }
    var box = bar.getBoundingClientRect(), bottom = view.offsetTop + view.height;
    if (!anchored && Math.abs(box.bottom-bottom) < 2) return;
    anchored = true;
    bar.style.position = "absolute";
    bar.style.inset = "auto";
    bar.style.top = view.pageTop + view.height - box.height + "px";
    bar.style.left = view.pageLeft + "px";
    bar.style.width = view.width + "px";
  }
  function schedule() {
    if (frame === null) frame = requestAnimationFrame(align);
  }
  window.addEventListener("scroll", schedule, {passive: true});
  window.addEventListener("resize", schedule);
  window.addEventListener("pageshow", schedule);
  view.addEventListener("scroll", schedule, {passive: true});
  view.addEventListener("resize", schedule);
  schedule();
})();
