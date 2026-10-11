// Mailhelp web interface: comfort functions only. Every page also works without this file.
"use strict";

(function () {
  var HEALTH_INTERVAL = 30000;

  function setConnection(online) {
    // Every page rendered by Mailhelp contains this status element.
    var badge = document.getElementById("verbindung");
    badge.hidden = false;
    badge.dataset.state = online ? "online" : "offline";
    badge.textContent = online ? "● Verbunden" : "PC nicht erreichbar";
  }

  function checkHealth() {
    return fetch("/health", { cache: "no-store", credentials: "same-origin" })
      .then(function (response) { setConnection(response.ok); })
      .catch(function () { setConnection(false); });
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
    window.addEventListener("offline", function () { setConnection(false); });
    checkHealth();
    window.setInterval(checkHealth, HEALTH_INTERVAL);
  }

  start();
})();
