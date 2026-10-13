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
    if (event.submitter && event.submitter.name) {
      var choice = document.createElement("input");
      choice.type = "hidden"; choice.name = event.submitter.name; choice.value = event.submitter.value;
      event.target.appendChild(choice);
    }
    var buttons = event.target.querySelectorAll("button");
    buttons.forEach(function (button) { button.disabled = true; });
    if (event.target.classList.contains("draft-intents")) {
      // The model needs a moment; the page reloads with the draft.
      event.target.querySelector('[role="status"]').textContent = "Entwurf wird erstellt …";
    }
  }

  function start() {
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
      navigator.serviceWorker.register("/sw.js").catch(function () { return null; });
    }
    if (document.body.dataset.fingerprint) {
      document.addEventListener("visibilitychange", whenVisible);
      window.setInterval(checkState, REFRESH_INTERVAL);
    }
  }

  start();
})();

// 2.0: split view, quick filters, shortcuts, undo, lightbox and Web-Push.
// Every form still posts to the server, which checks session, CSRF and version.
(function () {
  var UNDO_MS = Number(document.body.dataset.undoMs || 5000);
  var main = document.getElementById("inhalt");
  var desktop = window.matchMedia("(min-width: 1024px)");
  var items = null, pane = null, selected = null, pending = null, requestNumber = 0;
  var toast = document.createElement("div");
  toast.className = "undo-toast";
  toast.setAttribute("role", "status");
  toast.hidden = true;
  document.body.appendChild(toast);

  function announce(text, action) {
    toast.replaceChildren(document.createTextNode(text));
    if (action) toast.appendChild(action);
    toast.hidden = false;
  }

  function cards() { return Array.from(items.querySelectorAll("article.card")); }

  // Ids, label references and the heading of the loaded page fit into the overview.
  function show(html) {
    var content = new DOMParser().parseFromString(html, "text/html").querySelector("main");
    var heading = content.querySelector("h1"), title = document.createElement("h2");
    title.textContent = heading.textContent;
    heading.replaceWith(title);
    content.querySelectorAll("[id]").forEach(function (node) { node.id = "detail-" + node.id; });
    content.querySelectorAll("label[for]").forEach(function (label) { label.htmlFor = "detail-" + label.htmlFor; });
    content.querySelectorAll("[aria-labelledby]").forEach(function (node) {
      node.setAttribute("aria-labelledby", "detail-" + node.getAttribute("aria-labelledby"));
    });
    pane.replaceChildren.apply(pane, Array.from(content.childNodes));
    pane.dataset.dirty = "no";
  }

  function select(card) {
    if (pane.dataset.dirty === "yes") {
      announce("Ungespeicherte Änderungen zuerst speichern oder die Seite neu laden.");
      return;
    }
    selected = card;
    // Keep the selection in this history entry across automatic and manual reloads.
    history.replaceState(Object.assign({}, history.state, {mailhelpSelected: card.id}), "");
    cards().forEach(function (item) { item.classList.toggle("selected", item === card); });
    card.scrollIntoView({block: "nearest"});
    var number = ++requestNumber;
    pane.setAttribute("aria-busy", "true");
    fetch(card.querySelector(".card-links a").href, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) {
        if (!response.ok || response.redirected) throw new Error("not loaded");
        return response.text();
      })
      .then(function (html) { if (number === requestNumber) show(html); })
      .catch(function () { announce("Details nicht geladen. Bitte Verbindung und Anmeldung prüfen."); })
      .finally(function () { pane.removeAttribute("aria-busy"); });
  }

  function restoreSelection() {
    var list = cards(), saved = history.state && history.state.mailhelpSelected;
    select(list.find(function (card) { return card.id === saved; }) || list[0]);
  }

  // On wide screens the open items become a master list with a detail pane.
  // *previous* is the pane before a background refresh: it stays visible until
  // the selected item is loaded again, so the page does not flash.
  function enhance(previous) {
    items = main.querySelector(".open-items");
    pane = selected = null;
    if (!items) return;
    var split = document.createElement("div");
    pane = document.createElement("section");
    split.className = "split-view";
    pane.className = "detail-pane";
    pane.dataset.dirty = "no";
    pane.setAttribute("aria-label", "Ausgewählter Vorgang");
    items.classList.add("master-pane");
    items.setAttribute("aria-label", "Offene Vorgänge");
    items.before(split);
    split.append(items, pane);
    if (previous) pane.replaceChildren.apply(pane, Array.from(previous.childNodes));
    if (desktop.matches) restoreSelection();
  }

  // New data replaces the open items without reloading the page. A running
  // undo countdown or unsaved input in the pane waits for the next check.
  document.addEventListener("mailhelp:stale", function (event) {
    if (!pane || !desktop.matches) return;
    event.preventDefault();
    fetch(location.href, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) {
        if (!response.ok || response.redirected) throw new Error("not loaded");
        return response.text();
      })
      .then(function (html) {
        if (pending || pane.dataset.dirty === "yes") return;
        var page = new DOMParser().parseFromString(html, "text/html"), scroll = items.scrollTop;
        main.replaceChildren.apply(main, Array.from(page.querySelector("main").childNodes));
        document.body.dataset.fingerprint = page.body.dataset.fingerprint;
        enhance(pane);
        if (items) items.scrollTop = scroll;
      })
      .catch(function () { location.reload(); });
  });

  desktop.addEventListener("change", function () {
    if (pane && desktop.matches && !selected) restoreSelection();
  });
  document.addEventListener("input", function (event) {
    if (pane && pane.contains(event.target)) pane.dataset.dirty = "yes";
  });

  // Optimistic confirm and reject: the card disappears, the form is sent after the undo time.
  document.addEventListener("submit", function (event) {
    var form = event.target, kind = form.querySelector('input[name="kind"]');
    if (form.getAttribute("action") !== "/aktion" || !kind || ["confirm", "reject"].indexOf(kind.value) < 0) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (pending) return;
    var fromPane = pane !== null && pane.contains(form);
    var card = fromPane ? selected : form.closest("article");
    var verb = kind.value === "confirm" ? "wird bestätigt" : "wird verworfen";
    var title = "„" + card.querySelector("h3").textContent.trim() + "“ " + verb;
    card.classList.add("leaving");
    if (fromPane) pane.inert = true;
    var undo = document.createElement("button");
    undo.type = "button";
    undo.className = "button small";
    undo.textContent = "Rückgängig";
    announce(title + ". ", undo);
    pending = window.setTimeout(function () {
      announce(title + " …");
      form.querySelectorAll("button").forEach(function (button) { button.disabled = true; });
      form.submit();
    }, UNDO_MS);
    undo.addEventListener("click", function () {
      window.clearTimeout(pending);
      pending = null;
      card.classList.remove("leaving");
      if (fromPane) pane.inert = false;
      announce("Rückgängig gemacht – es wurde nichts gesendet.");
    });
  }, true);

  function modal(label, children) {
    var dialog = document.createElement("dialog"), close = document.createElement("button");
    var opener = document.activeElement;
    dialog.className = "modal";
    dialog.setAttribute("aria-label", label);
    close.type = "button";
    close.className = "button small";
    close.textContent = "Schließen";
    close.addEventListener("click", function () { dialog.close(); });
    dialog.addEventListener("close", function () { dialog.remove(); opener.focus(); });
    dialog.append.apply(dialog, [close].concat(children));
    document.body.appendChild(dialog);
    dialog.showModal();
    return dialog;
  }

  function help() {
    var list = document.createElement("dl");
    [["J / ↓", "Nächster Vorgang"], ["K / ↑", "Vorheriger Vorgang"], ["C / Enter", "Bestätigen"],
     ["E", "Bearbeiten"], ["X / D", "Verwerfen"], ["?", "Diese Hilfe"]].forEach(function (pair) {
      var key = document.createElement("dt"), text = document.createElement("dd");
      key.textContent = pair[0];
      text.textContent = pair[1];
      list.append(key, text);
    });
    var heading = document.createElement("h2");
    heading.textContent = "Tastenkürzel";
    var note = document.createElement("p");
    note.textContent = "Nach Bestätigen oder Verwerfen bleiben 5 Sekunden zum Rückgängigmachen.";
    modal("Tastenkürzel", [heading, list, note]);
  }

  document.addEventListener("keydown", function (event) {
    var target = event.target;
    if (event.altKey || event.ctrlKey || event.metaKey || document.querySelector("dialog[open]") ||
        target.closest("input, textarea, select, [contenteditable]") ||
        (event.key === "Enter" && target.closest("a, button, summary"))) return;
    var key = event.key.toLowerCase();
    if (key === "?") {
      event.preventDefault();
      help();
      return;
    }
    if (!pane || !desktop.matches || pending) return;
    var list = cards(), step = {j: 1, arrowdown: 1, k: -1, arrowup: -1}[key];
    if (step) {
      event.preventDefault();
      select(list[Math.min(list.length - 1, Math.max(0, list.indexOf(selected) + step))]);
      return;
    }
    var action = {c: "confirm", enter: "confirm", x: "reject", d: "reject", e: "edit"}[key];
    if (!action) return;
    event.preventDefault();
    var control = action === "edit" ? pane.querySelector('a[href$="/bearbeiten"]')
      : pane.querySelector('input[name="kind"][value="' + action + '"]');
    if (!control) {
      announce("Diese Aktion ist für den ausgewählten Vorgang nicht möglich.");
      return;
    }
    if (action === "edit") control.click();
    else control.form.requestSubmit();
  });

  function filter(chip) {
    if (pending || (pane && pane.dataset.dirty === "yes")) {
      announce("Zuerst die laufende Aktion oder Eingabe abschließen.");
      return;
    }
    fetch(chip.href, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) {
        if (!response.ok || response.redirected) throw new Error("not loaded");
        return response.text();
      })
      .then(function (html) {
        var content = new DOMParser().parseFromString(html, "text/html").querySelector("main");
        main.replaceChildren.apply(main, Array.from(content.childNodes));
        history.pushState(null, "", chip.href);
        enhance();
        main.querySelector('a[data-filter][aria-current="true"]').focus();
      })
      .catch(function () { announce("Filter nicht geladen. Bitte Verbindung prüfen."); });
  }

  function lightbox(link) {
    var image = document.createElement("img");
    image.src = link.href;
    image.alt = link.querySelector("img").alt;
    image.title = "Klicken zum Vergrößern";
    image.addEventListener("click", function () { image.classList.toggle("zoomed"); });
    modal("Bildanhang vergrößert", [image]).classList.add("lightbox");
  }

  document.addEventListener("click", function (event) {
    var chip = event.target.closest("a[data-filter]");
    if (chip) {
      event.preventDefault();
      filter(chip);
      return;
    }
    var preview = event.target.closest("a[data-lightbox]");
    if (preview) {
      event.preventDefault();
      lightbox(preview);
      return;
    }
    var card = pane && desktop.matches ? event.target.closest(".master-pane article.card") : null;
    if (!card || event.target.closest("form, details, a[target]")) return;
    event.preventDefault();
    select(card);
  });
  window.addEventListener("popstate", function () { location.reload(); });
  enhance();

  var controls = document.getElementById("push-controls");
  if (!controls) return;
  var status = document.getElementById("push-status");

  function key(text) {
    var raw = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, function (c) { return c.charCodeAt(0); });
  }

  function subscribe(registration) {
    return registration.pushManager.getSubscription().then(function (existing) {
      if (existing) return existing;
      return fetch("/api/push/public-key", {credentials: "same-origin", cache: "no-store"})
        .then(function (response) {
          if (!response.ok) throw new Error("Web-Push ist auf dem Server nicht eingeschaltet.");
          return response.json();
        })
        .then(function (data) {
          return registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key(data.public_key)});
        });
    });
  }

  function changePush(enable) {
    if (!window.isSecureContext || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      status.textContent = "Push benötigt HTTPS (oder localhost) und einen Browser mit Web-Push.";
      return;
    }
    var subscription = null;
    var permission = enable ? Notification.requestPermission() : Promise.resolve("granted");
    permission.then(function (result) {
      if (result !== "granted") throw new Error("Benachrichtigungen wurden im Browser nicht erlaubt.");
      return navigator.serviceWorker.ready;
    }).then(function (registration) {
      return enable ? subscribe(registration) : registration.pushManager.getSubscription();
    }).then(function (value) {
      subscription = value;
      var body = new URLSearchParams({csrf: controls.dataset.csrf, key: crypto.randomUUID()});
      if (enable) body.set("subscription", JSON.stringify(subscription.toJSON()));
      return fetch("/api/push/" + (enable ? "subscribe" : "unsubscribe"),
                   {method: "POST", credentials: "same-origin", body: body});
    }).then(function (response) {
      if (!response.ok) throw new Error("Nicht gespeichert. Bitte Anmeldung prüfen und erneut versuchen.");
      return enable || !subscription ? null : subscription.unsubscribe();
    }).then(function () {
      status.textContent = enable ? "Push ist auf diesem Gerät aktiviert." : "Push ist auf diesem Gerät deaktiviert.";
    }).catch(function (error) { status.textContent = error.message; });
  }

  document.getElementById("push-enable").addEventListener("click", function () { changePush(true); });
  document.getElementById("push-disable").addEventListener("click", function () { changePush(false); });
})();
