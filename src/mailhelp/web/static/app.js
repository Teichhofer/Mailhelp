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
      event.target.querySelector('[role="status"]').textContent = "Entwurf wird erstellt …";
    }
  }

  function start() {
    var command = document.querySelector("[data-command-status]");
    if (command) {
      function progress() {
        fetch(command.dataset.commandStatus, {cache: "no-store", credentials: "same-origin", headers: {Accept: "application/json"}})
          .then(function (response) {
            if (response.status === 401) return {target: "/anmelden"};
            if (!response.ok) throw new Error("Status gerade nicht verfügbar.");
            return response.json();
          })
          .then(function (result) {
            if (result && result.target) location.replace(result.target);
            else window.setTimeout(progress, 1000);
          })
          .catch(function () {
            command.textContent = "Verbindung unterbrochen. Die Aktion wird nicht erneut gesendet; der Status wird weiter geprüft.";
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
  var main = document.getElementById("inhalt");
  var desktop = window.matchMedia("(min-width: 1024px)");
  var items = null, pane = null, selected = null, requestNumber = 0;
  var shown = location.pathname + location.search;
  var toast = document.createElement("div");
  toast.className = "undo-toast";
  toast.setAttribute("role", "status");
  toast.hidden = true;
  document.body.appendChild(toast);

  // A short message: it must never stay on top of the buttons it announces.
  var NOTICE_MS = Number(document.body.dataset.undoMs || 6000), hideTimer = 0;
  function announce(text) {
    toast.replaceChildren(document.createTextNode(text));
    toast.hidden = false;
    window.clearTimeout(hideTimer);
    hideTimer = window.setTimeout(function () { toast.hidden = true; }, NOTICE_MS);
  }

  function cards() { return Array.from(items.querySelectorAll("article.card")); }

  // DOMParser parses without scripting: <noscript> content (the reload fallback)
  // would become live elements, and an inserted refresh pragma reloads the page.
  function parse(html) {
    var page = new DOMParser().parseFromString(html, "text/html");
    page.querySelectorAll("noscript").forEach(function (node) { node.remove(); });
    return page;
  }

  // Ids, label references and the heading of the loaded page fit into the overview.
  function show(html) {
    var content = parse(html).querySelector("main");
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
    openSource(pane);
  }

  // 5.9.5: from 1024 px the source mail of a proposal is open at first, for events and tasks
  // alike; a later resize never closes what the user is reading.
  function openSource(root) {
    if (!desktop.matches) return;
    root.querySelectorAll("details[data-source-mail]").forEach(function (node) { node.open = true; });
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
    // 5.0.4: the marked details link, never an earlier one such as the original mail.
    fetch(card.querySelector("a[data-detail]").href, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) {
        if (!response.ok || response.redirected) throw new Error("not loaded");
        return response.text();
      })
      .then(function (html) { if (number === requestNumber) show(html); })
      .catch(function () { announce("Details nicht geladen. Bitte Verbindung und Anmeldung prüfen."); })
      .finally(function () { pane.removeAttribute("aria-busy"); });
  }

  function restoreSelection() {
    // A saved choice wins; otherwise the card of the redirect anchor (#v-…) after an action.
    var list = cards(), saved = history.state && history.state.mailhelpSelected, anchored = location.hash.slice(1);
    select(list.find(function (card) { return card.id === saved; })
      || list.find(function (card) { return card.id === anchored; }) || list[0]);
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
        if (pane.dataset.dirty === "yes") return;
        var page = parse(html), scroll = items.scrollTop;
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

  // Each card owns its request and polling. Other cards remain usable.
  var polling = new Set(), QUICK_POLLS = 30;
  function pollCard(marker) {
    var url = marker.dataset.cardCommandStatus;
    if (polling.has(url)) return;
    polling.add(url);
    var attempts = 0;
    function check() {
      fetch(url, {credentials: "same-origin", cache: "no-store", headers: {Accept: "application/json"}})
        .then(function (response) {
          if (response.status === 401) { location.replace("/anmelden"); return {expired: true}; }
          // Not (yet) known, e.g. after a lost POST response: keep the explanation and ask again.
          if (response.status === 404) return {unknown: true};
          if (!response.ok) throw new Error("Status nicht verfügbar");
          return response.json();
        })
        .then(function (result) {
          if (result && result.expired) return;
          if (result && result.unknown) { window.setTimeout(check, 1000); return; }
          if (!result) throw new Error("Status nicht verfügbar");
          if (location.pathname !== "/" && location.pathname !== "/offen") {
            location.assign("/?aktion=" + url.split("/").pop() + "#" + marker.closest("article.card").id);
            return;
          }
          // Most actions finish within a few hundred milliseconds: ask often at first.
          if (!result.target) { window.setTimeout(check, attempts++ < QUICK_POLLS ? 100 : 500); return; }
          return fetch("/", {credentials: "same-origin", cache: "no-store"})
            .then(function (response) {
              if (!response.ok || response.redirected) throw new Error("Übersicht nicht verfügbar");
              return response.text();
            }).then(function (html) {
              var page = parse(html);
              var card = marker.closest("article.card"), id = card.id.replace(/^detail-/, "");
              var updated = page.getElementById(id);
              if (!updated) throw new Error("Ergebnis noch nicht sichtbar");
              if (pane && selected && selected.id === id && pane.dataset.dirty !== "yes") {
                var copy = updated.cloneNode(true);
                copy.querySelectorAll("[id]").forEach(function (node) { node.id = "detail-" + node.id; });
                copy.querySelectorAll("label[for]").forEach(function (label) { label.htmlFor = "detail-" + label.htmlFor; });
                copy.id = "detail-" + id;
                pane.replaceChildren(copy);
                pane.dataset.dirty = "no";
              }
              var master = document.getElementById(id);
              if (master) master.replaceWith(updated);
              // A decision also moves the item to "Zuletzt erledigt" on the same fresh overview.
              var recent = page.querySelector(".recent"), shown = main.querySelector(".recent");
              if (recent && shown) shown.replaceWith(recent);
              if (selected && selected.id === id) {
                updated.classList.add("selected"); selected = updated;
              }
              // Only the result itself, not the whole card (title, evidence, links).
              var outcome = updated.querySelector("[data-command-result]");
              if (outcome) announce(outcome.textContent.trim());
              polling.delete(url);
              observeCards();
            });
        }).catch(function () {
          marker.textContent = "Verbindung unterbrochen. Die Aktion wird nicht erneut gesendet; der Status wird weiter geprüft.";
          window.setTimeout(check, 1000);
        });
    }
    check();
  }
  function observeCards() {
    document.querySelectorAll("[data-card-command-status]").forEach(pollCard);
  }
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.getAttribute("action") !== "/aktion") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    var card = form.closest("article.card");
    if (form.dataset.sending || (card && card.querySelector("[data-card-command-status]"))) return;
    form.dataset.sending = "yes";
    var fields = new URLSearchParams(new FormData(form));
    var receipt = fields.get("receipt_id"), marker = document.createElement("div");
    marker.dataset.cardCommandStatus = "/api/aktion/" + receipt;
    marker.setAttribute("role", "status"); marker.setAttribute("aria-live", "polite");
    marker.textContent = "Wird verarbeitet …";
    form.appendChild(marker);
    (card || form).querySelectorAll("button, textarea").forEach(function (button) { button.disabled = true; });
    if (card && card.id.startsWith("detail-")) {
      var master = document.getElementById(card.id.slice(7));
      if (master) {
        master.querySelectorAll("button, textarea").forEach(function (button) { button.disabled = true; });
        master.appendChild(marker.cloneNode(true));
      }
    }
    if (pane && pane.contains(form)) pane.dataset.dirty = "no";
    function admitted(id) {
      if (!card || (location.pathname !== "/" && location.pathname !== "/offen")) {
        var anchor = fields.get("proposal_id") ? "v-" + fields.get("mail_id") + "-" + fields.get("proposal_id") : "r-" + fields.get("mail_id");
        location.assign("/?aktion=" + id + "#" + anchor);
      } else {
        marker.dataset.cardCommandStatus = "/api/aktion/" + id;
        pollCard(marker);
      }
    }
    fetch("/aktion", {method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded"}, body: fields.toString()})
      .then(function (response) {
        return response.json().then(function (result) {
          if (!response.ok) {
            marker.removeAttribute("data-card-command-status");
            marker.setAttribute("role", "alert"); marker.textContent = result.error || "Die Aktion wurde nicht angenommen.";
            (card || form).querySelectorAll("button, textarea").forEach(function (button) { button.disabled = false; });
            delete form.dataset.sending;
            return;
          }
          admitted(result.id);
        });
      }).catch(function () {
        marker.textContent = "Antwort unterbrochen. Der Annahmestatus wird geprüft; es wird nichts erneut gesendet.";
        pollCard(marker);
      });
  }, true);
  observeCards();

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

  function chartDetails(figure) {
    var plot = figure.querySelector(".chart-plot"), tip = figure.querySelector(".chart-tooltip");
    figure.classList.add("chart-interactive");
    tip.hidden = true;
    function reveal(event) {
      var point = event.target.closest("[data-chart-detail]");
      if (!point) return;
      tip.textContent = point.dataset.chartDetail;
      tip.hidden = false;
    }
    function leave(event) {
      if (!plot.contains(event.relatedTarget) && !plot.contains(document.activeElement)) tip.hidden = true;
    }
    plot.addEventListener("pointerover", reveal);
    plot.addEventListener("focusin", reveal);
    plot.addEventListener("click", reveal);
    plot.addEventListener("pointerleave", leave);
    plot.addEventListener("focusout", leave);
    plot.addEventListener("keydown", function (event) {
      if (event.key === "Escape") tip.hidden = true;
    });
  }

  function zoomChart(figure) {
    var opener = figure.querySelector(".chart-zoom"), copy = figure.cloneNode(true);
    figure.querySelector(".chart-tooltip").hidden = true;
    copy.classList.add("chart-expanded");
    copy.querySelector(".chart-zoom").remove();
    copy.setAttribute("aria-labelledby", "zoom-" + copy.getAttribute("aria-labelledby"));
    // Keep every SVG title, description and caption reference unique in the document.
    copy.querySelectorAll("[id]").forEach(function (node) { node.id = "zoom-" + node.id; });
    copy.querySelectorAll("[aria-labelledby]").forEach(function (node) {
      node.setAttribute("aria-labelledby", node.getAttribute("aria-labelledby").split(" ").map(function (id) {
        return "zoom-" + id;
      }).join(" "));
    });
    chartDetails(copy);
    var title = figure.querySelector("figcaption span").textContent;
    var dialog = modal(title + " – vergrößert", [copy]);
    dialog.classList.add("chart-modal");
    dialog.addEventListener("close", function () { opener.focus(); });
  }

  // 5.9.11: the pipeline plan is a figure without SVG; it has nothing to zoom or explain.
  document.querySelectorAll("figure.chart:not(.pipeline-figure)").forEach(function (figure) {
    figure.querySelector(".chart-zoom").hidden = false;
    chartDetails(figure);
  });

  function help() {
    var list = document.createElement("dl");
    [["J / ↓", "Nächster Vorgang"], ["K / ↑", "Vorheriger Vorgang"], ["A / C / Enter", "Bestätigen"],
     ["E", "Bearbeiten"], ["X / D", "Verwerfen"], ["?", "Diese Hilfe"]].forEach(function (pair) {
      var key = document.createElement("dt"), text = document.createElement("dd");
      key.textContent = pair[0];
      text.textContent = pair[1];
      list.append(key, text);
    });
    var heading = document.createElement("h2");
    heading.textContent = "Tastenkürzel";
    var note = document.createElement("p");
    note.textContent = "Aktionen werden sofort angenommen. Weitere Vorgänge bleiben bedienbar.";
    modal("Tastenkürzel", [heading, list, note]);
  }

  // 5.0.9: the shortcuts are discoverable from the sidebar, not only by pressing "?".
  var sidebar = document.querySelector(".app-shell .top");
  if (sidebar) {
    var hint = document.createElement("button");
    hint.type = "button";
    hint.className = "shortcut-hint";
    hint.innerHTML = '<span aria-hidden="true">?</span><span class="nav-label">Tastenkürzel</span>';
    hint.addEventListener("click", help);
    sidebar.appendChild(hint);
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
    if (!pane || !desktop.matches) return;
    var list = cards(), step = {j: 1, arrowdown: 1, k: -1, arrowup: -1}[key];
    if (step) {
      event.preventDefault();
      select(list[Math.min(list.length - 1, Math.max(0, list.indexOf(selected) + step))]);
      return;
    }
    var action = {a: "confirm", c: "confirm", enter: "confirm", x: "reject", d: "reject", e: "edit"}[key];
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
    if (pane && pane.dataset.dirty === "yes") {
      announce("Zuerst die laufende Aktion oder Eingabe abschließen.");
      return;
    }
    fetch(chip.href, {credentials: "same-origin", cache: "no-store"})
      .then(function (response) {
        if (!response.ok || response.redirected) throw new Error("not loaded");
        return response.text();
      })
      .then(function (html) {
        var content = parse(html).querySelector("main");
        main.replaceChildren.apply(main, Array.from(content.childNodes));
        history.pushState(null, "", chip.href);
        shown = location.pathname + location.search;
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
    var chart = event.target.closest(".chart:not(.chart-expanded)");
    if (chart && event.target.closest("svg, .chart-zoom")) {
      zoomChart(chart);
      return;
    }
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
  // 5.4.1: only a history step to other content reloads; a jump to an anchor of this page
  // (also a popstate) must keep unsaved form values and the open help window.
  window.addEventListener("popstate", function () {
    if (location.pathname + location.search !== shown) location.reload();
  });
  enhance();
  openSource(document);

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-draft]");
    if (!button) return;
    var box = button.closest(".draft-box"), status = box.querySelector("[data-copy-status]");
    if (!navigator.clipboard) {
      status.textContent = "Bitte den Antworttext markieren und manuell kopieren.";
      return;
    }
    navigator.clipboard.writeText(box.querySelector("textarea").value).then(function () {
      status.textContent = "Antworttext kopiert.";
    }).catch(function () {
      status.textContent = "Kopieren nicht erlaubt. Bitte den Antworttext manuell kopieren.";
    });
  });

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
      var body = new URLSearchParams({csrf: controls.dataset.csrf, key: randomHexKey()});
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

// 5.0.1: from 1200 px the sidebar can be collapsed to icons; the choice is kept per device.
(function () {
  var top = document.querySelector(".app-shell .top");
  if (!top) return;
  var KEY = "mailhelp.nav-collapsed";
  var button = document.createElement("button");
  button.type = "button";
  button.className = "nav-toggle";
  function stored() {
    try { return localStorage.getItem(KEY) === "1"; } catch (error) { return false; }
  }
  function apply(collapsed) {
    document.body.classList.toggle("nav-collapsed", collapsed);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.innerHTML = '<span aria-hidden="true">' + (collapsed ? "»" : "«") + '</span><span class="nav-label">' +
      (collapsed ? "Navigation ausklappen" : "Navigation einklappen") + "</span>";
  }
  button.addEventListener("click", function () {
    var collapsed = !document.body.classList.contains("nav-collapsed");
    apply(collapsed);
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (error) { return; }
  });
  apply(stored());
  top.appendChild(button);
})();

// 5.3: a link to one setting (…#einstellung-…) opens it, also after a direct page load.
(function () {
  function openTarget() {
    var id = decodeURIComponent(location.hash.slice(1));
    var row = id ? document.getElementById(id) : null;
    if (!row || !row.classList.contains("setting-row")) return;
    var details = row.querySelector("details");
    if (details) details.open = true;
  }
  window.addEventListener("hashchange", openTarget);
  openTarget();
})();

// 5.3: live search below the settings search field; "Suchen" keeps the full result page.
(function () {
  var input = document.querySelector("input[data-live-search]");
  var list = document.getElementById("settings-live-results");
  var status = document.getElementById("settings-live-status");
  if (!input || !list || !status || !window.fetch || !window.AbortController) return;
  var form = input.form, timer = null, controller = null, sequence = 0, composing = false;
  function stop() {
    clearTimeout(timer);
    if (controller) controller.abort();
    controller = null;
    sequence += 1;
    form.classList.remove("searching");
  }
  function clear() {
    stop();
    list.textContent = "";
    list.hidden = true;
    status.textContent = "";
  }
  function entry(item) {
    var li = document.createElement("li"), link = document.createElement("a"), meta = document.createElement("span");
    link.href = item.href;
    link.textContent = item.label;
    meta.className = "meta";
    meta.textContent = item.area + (item.key ? " · " + item.key : "") + " – " + item.summary;
    li.appendChild(link);
    li.appendChild(meta);
    if (item.key) {
      var ask = document.createElement("a");
      ask.href = "/hilfe?einstellung=" + encodeURIComponent(item.key);
      ask.className = "ask-help";
      ask.textContent = "Dazu fragen";
      li.appendChild(ask);
    }
    return li;
  }
  function render(data) {
    list.textContent = "";
    data.results.forEach(function (item) { list.appendChild(entry(item)); });
    if (data.total > data.results.length) {
      var more = document.createElement("li"), link = document.createElement("a");
      link.href = data.all;
      link.textContent = "Alle " + data.total + " Ergebnisse anzeigen";
      more.appendChild(link);
      list.appendChild(more);
    }
    list.hidden = data.total === 0;
    list.setAttribute("data-query", data.query);
    status.textContent = data.total === 0 ? "Keine Einstellung gefunden." : data.total + " Treffer";
  }
  function run() {
    var query = input.value.trim(), mine;
    stop();
    mine = sequence;
    controller = new AbortController();
    form.classList.add("searching");
    fetch(input.getAttribute("data-live-search") + "?suche=" + encodeURIComponent(query), {
      signal: controller.signal, credentials: "same-origin", headers: {Accept: "application/json"}
    }).then(function (response) {
      if (!response.ok) throw new Error("status " + response.status);
      return response.json();
    }).then(function (data) {
      if (mine === sequence) render(data);
    }).catch(function (error) {
      if (error.name === "AbortError" || mine !== sequence) return;
      list.textContent = "";
      list.hidden = true;
      status.textContent = "Die Sofortsuche ist gerade nicht verfügbar – „Suchen“ funktioniert weiterhin.";
    }).then(function () {
      if (mine === sequence) form.classList.remove("searching");
    });
  }
  function schedule() {
    if (composing) return;
    if (!input.value.trim()) { clear(); return; }
    clearTimeout(timer);
    timer = setTimeout(run, 150);
  }
  input.addEventListener("compositionstart", function () { composing = true; });
  input.addEventListener("compositionend", function () { composing = false; schedule(); });
  input.addEventListener("input", schedule);
})();

// 5.4: the help window belongs to the settings shell, not to a separate page.
(function () {
  var KEY = "mailhelp.help-window.v1", root = document.getElementById("help-widget");
  function forget() { try { sessionStorage.removeItem(KEY); } catch (error) { /* Storage may be disabled. */ } }
  if (document.body.classList.contains("guest-shell")) { forget(); return; }
  if (!root || !window.fetch) return;
  var panel = document.getElementById("help-window"), content = document.getElementById("help-window-content");
  var message = document.getElementById("help-window-status"), doc = document.getElementById("help-document");
  var scope = root.dataset.scope, expires = Number(root.dataset.sessionExpires) * 1000, stamp = "", sequence = 0, docSequence = 0;
  var state = {scope: scope, opened: !panel.hidden, draft: "", setting: root.dataset.setting,
    expires: Number(root.dataset.expires) * 1000};
  var blocked = false, busy = false, stopped = false, saving = Promise.resolve(), trigger = null, timer, syncTimer;
  var unsaved = false;
  var firstInput = content.querySelector("#help-question");
  if (firstInput) state.draft = firstInput.value;
  try {
    var saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (saved && saved.scope === scope && saved.expires > Date.now() && typeof saved.opened === "boolean" &&
        typeof saved.draft === "string" && saved.draft.length <= 8000 && typeof saved.setting === "string") {
      state = saved;
    } else { forget(); }
  } catch (error) { blocked = true; }
  // 5.5.2: the reading position of the conversation; a manipulated value starts at the top.
  state.scroll = Number.isFinite(state.scroll) && state.scroll >= 0 ? state.scroll : 0;
  // 5.5.3: the size chosen at the border; a manipulated value falls back to the default size.
  var MIN_WIDTH = 280, MIN_HEIGHT = 180;
  if (!(Number.isFinite(state.width) && state.width >= MIN_WIDTH)) delete state.width;
  if (!(Number.isFinite(state.height) && state.height >= MIN_HEIGHT)) delete state.height;
  var restored = false, scrollTimer;
  var initial = new URL(location.href);
  if (initial.searchParams.get("hilfe") === "offen") {
    state.opened = true;
    state.setting = root.dataset.setting;
    initial.searchParams.delete("hilfe"); initial.searchParams.delete("einstellung");
    history.replaceState(history.state, "", initial);
  }
  function question() { return content.querySelector("#help-question"); }
  function restoreDraft() {
    var input = question();
    if (input) input.value = state.draft;
  }
  function store(touch) {
    if (touch) state.expires = Math.min(expires, Date.now() + 86400000);
    try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (error) { blocked = true; }
  }
  function credentials(form) {
    var body = new URLSearchParams(new FormData(form));
    body.set("return_to", root.dataset.return);
    return body;
  }
  function json(url, body) {
    return fetch(url, {method: body ? "POST" : "GET", body: body, cache: "no-store", credentials: "same-origin",
      headers: {Accept: "application/json"}}).then(function (response) {
      if (response.status === 401 || response.status === 403) {
        stopped = true; state.opened = false; panel.hidden = true; content.textContent = ""; forget();
        throw new Error("Sitzung abgelaufen. Bitte erneut anmelden.");
      }
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || "Anfrage fehlgeschlagen. Bitte erneut versuchen.");
        return data;
      });
    });
  }
  function fallback() {
    saving = saving.catch(function () { /* A later explicit action may retry with fresh state. */ }).then(function () {
      return json("/api/hilfe/fenster").then(function (data) {
        var body = credentials(root.querySelector(".help-launch"));
        body.set("window_version", data.ui.version);
        body.set("window_action", state.opened ? "save" : "close");
        body.set("draft", state.draft); body.set("einstellung", state.setting);
        body.set("key", randomHexKey());
        var draft = state.draft;
        return json("/hilfe/fenster", body).then(function () { if (state.draft === draft) unsaved = false; });
      });
    });
    return saving;
  }
  function remember() {
    store(true);
    if (blocked) return fallback();
    return Promise.resolve();
  }
  // The height above the bottom navigation; a window never grows beyond it.
  function room() {
    var viewport = window.visualViewport;
    var bottom = document.querySelector("nav.tab-bar");
    return (viewport ? viewport.height : innerHeight) - bottom.getBoundingClientRect().height - 24;
  }
  function place(x, y) {
    var viewport = window.visualViewport;
    var available = room();
    // 5.5.3: a size chosen at the border wins over the default; a smaller screen limits it.
    if (state.height) {
      var height = Math.max(120, Math.min(state.height, available));
      panel.style.height = height + "px"; panel.style.maxHeight = height + "px";
    } else {
      panel.style.maxHeight = Math.max(120, Math.min(520, available * 0.78)) + "px";
    }
    if (state.width) panel.style.width = Math.min(state.width, innerWidth - 16) + "px";
    var box = panel.getBoundingClientRect();
    if (Number.isFinite(x) && Number.isFinite(y)) {
      state.x = Math.max(8, Math.min(x, innerWidth - box.width - 8));
      state.y = Math.max(8, Math.min(y, (viewport ? viewport.height : innerHeight) - box.height - 8));
      panel.style.left = state.x + "px"; panel.style.top = state.y + "px";
      panel.style.right = "auto"; panel.style.bottom = "auto";
    }
  }
  function show(focus) {
    panel.hidden = !state.opened;
    root.querySelector(".help-fab").setAttribute("aria-expanded", String(state.opened));
    restoreDraft(); place(state.x, state.y);
    if (focus && question()) question().focus({preventScroll: true});  // keep the reading position
  }
  function failure(error) { message.textContent = error.message; }
  function refresh(force) {
    if (stopped || busy || !state.opened || document.hidden) return Promise.resolve();
    if (state.expires <= Date.now()) {
      state.draft = ""; content.textContent = ""; stamp = ""; forget();
      state.expires = Math.min(expires, Date.now() + 86400000);
    }
    var current = ++sequence;
    return json("/api/hilfe/fenster?einstellung=" + encodeURIComponent(state.setting)).then(function (data) {
      if (current !== sequence || !state.opened) return;
      if (data.scope !== scope) {
        stopped = true; state.opened = false; panel.hidden = true; content.textContent = ""; forget(); return;
      }
      state.setting = data.setting;
      if (force || stamp !== data.stamp) {
        var input = question(), focused = document.activeElement === input;
        var start = input ? input.selectionStart : 0, end = input ? input.selectionEnd : 0;
        // After a page change the saved position counts; later a reader at the end follows
        // new content, a reader further up keeps the place.
        var following = restored && content.scrollTop + content.clientHeight >= content.scrollHeight - 4;
        var scroll = restored ? content.scrollTop : state.scroll;
        content.innerHTML = data.html;
        if (stamp) message.textContent = "Gespräch aktualisiert.";
        stamp = data.stamp;
        restoreDraft(); content.scrollTop = following ? content.scrollHeight : scroll;
        if (!content.hidden) { restored = true; state.scroll = content.scrollTop; }
        if (focused && question()) { question().focus({preventScroll: true}); question().setSelectionRange(start, end); }
      }
      show(false); store();
    }).catch(failure);
  }
  function open(link) {
    trigger = link; state.opened = true; restored = false;  // reopening returns to the reading position
    content.textContent = ""; doc.hidden = true; content.hidden = false;
    doc.querySelector(".help-document-text").textContent = "";
    var url = new URL(link.href || location.href, location.href);
    if (url.searchParams.has("einstellung")) state.setting = url.searchParams.get("einstellung");
    show(true); remember().catch(failure);
    refresh(true).then(function () {
      if (state.opened && (document.activeElement === document.body || document.activeElement === link)) show(true);
    });
  }
  content.addEventListener("input", function (event) {
    state.draft = event.target.value; unsaved = true; store(true);
    if (blocked) { clearTimeout(syncTimer); syncTimer = setTimeout(function () { fallback().catch(failure); }, 300); }
  });
  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href]");
    if (!link) return;
    var url = new URL(link.href, location.href);
    if (url.origin === location.origin && url.pathname === "/hilfe") {
      event.preventDefault(); open(link); return;
    }
    if (panel.contains(link) && url.origin === location.origin && url.pathname.startsWith("/hilfe/dokumentation")) {
      event.preventDefault();
      jsonDocument(url); return;
    }
    if (panel.contains(link) && url.origin === location.origin && url.pathname === "/einstellungen") {
      state.setting = ""; remember().catch(failure);
    }
    if (blocked && !event.defaultPrevented && url.origin === location.origin) {
      event.preventDefault();
      fallback().then(function () { location.assign(url); }).catch(failure);
    }
  });
  function jsonDocument(url) {
    var current = ++docSequence;
    fetch(url, {cache: "no-store", credentials: "same-origin"}).then(function (response) {
      if (!response.ok || response.redirected) throw new Error("Dokumentation nicht verfügbar. Bitte Anmeldung prüfen.");
      return response.text();
    }).then(function (html) {
      if (current !== docSequence) return;
      var parsed = new DOMParser().parseFromString(html, "text/html");
      var main = parsed.querySelector("main");
      doc.querySelector(".help-document-text").textContent = main.textContent;
      if (!content.hidden) { state.scroll = content.scrollTop; store(); }
      content.hidden = true; doc.hidden = false;
    }).catch(failure);
  }
  root.addEventListener("click", function (event) {
    if (event.target.closest("[data-help-back]")) {
      docSequence++; doc.hidden = true; content.hidden = false; content.scrollTop = state.scroll; restored = true;
    }
  });
  content.addEventListener("scroll", function () {
    // Emptying or rebuilding the content also scrolls; only a restored view is a reading position.
    if (!restored) return;
    state.scroll = content.scrollTop;
    clearTimeout(scrollTimer); scrollTimer = setTimeout(store, 150);
  }, {passive: true});
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!root.contains(form)) {
      if (form.hasAttribute("data-ends-session")) { forget(); return; }
      if (blocked && !form.dataset.helpSaved) {
        event.preventDefault(); var submitter = event.submitter;
        fallback().then(function () { form.dataset.helpSaved = "yes"; form.requestSubmit(submitter); }).catch(failure);
      }
      return;
    }
    event.preventDefault();
    if (form.action.endsWith("/hilfe/fenster")) {
      var action = event.submitter.value;
      if (action === "open") { open(event.submitter); return; }
      else { state.opened = false; sequence++; panel.hidden = true; if (trigger && trigger.isConnected) trigger.focus(); }
      remember().catch(failure); return;
    }
    if (busy) return;
    busy = true; message.textContent = "Anfrage wird gesendet …";
    var body = credentials(form), clear = form.action.endsWith("/hilfe/leeren");
    json(form.action, body).then(function (data) {
      state.draft = ""; content.innerHTML = data.html; stamp = "";
      if (clear) { doc.hidden = true; content.hidden = false; }
      // A cleared chat starts at the top; a sent question shows its pending notice at the end.
      content.scrollTop = clear ? 0 : content.scrollHeight; state.scroll = content.scrollTop;
      restoreDraft(); message.textContent = ""; remember().catch(failure);
    }).catch(failure).finally(function () { busy = false; });
  }, true);
  var drag = null, head = panel.querySelector(".help-window-head");
  head.addEventListener("pointerdown", function (event) {
    if (event.target.closest("button")) return;
    var box = panel.getBoundingClientRect(); drag = {x: event.clientX - box.x, y: event.clientY - box.y};
    head.setPointerCapture(event.pointerId);
  });
  head.addEventListener("pointermove", function (event) {
    if (drag) { place(event.clientX - drag.x, event.clientY - drag.y); store(true); }
  });
  head.addEventListener("pointerup", function () { drag = null; });
  // 5.5.3: resize at every border and corner; the opposite border stays where it is.
  function size(width, height, right, bottom, box) {
    state.width = Math.round(Math.max(Math.min(MIN_WIDTH, innerWidth - 16), Math.min(width, innerWidth - 16)));
    state.height = Math.round(Math.max(Math.min(MIN_HEIGHT, room()), Math.min(height, room())));
    place(right === null ? box.x : right - state.width, bottom === null ? box.y : bottom - state.height);
  }
  ["n", "s", "e", "w", "ne", "nw", "se", "sw"].forEach(function (edge) {
    var grip = document.createElement("div");
    grip.className = "help-resize help-resize-" + edge;
    grip.dataset.edge = edge; grip.setAttribute("aria-hidden", "true");
    panel.appendChild(grip);
  });
  var sizing = null;
  panel.addEventListener("pointerdown", function (event) {
    var grip = event.target.closest(".help-resize");
    if (!grip) return;
    event.preventDefault();
    sizing = {edge: grip.dataset.edge, x: event.clientX, y: event.clientY, box: panel.getBoundingClientRect()};
    grip.setPointerCapture(event.pointerId);
  });
  panel.addEventListener("pointermove", function (event) {
    if (!sizing) return;
    var edge = sizing.edge, box = sizing.box, width = box.width, height = box.height;
    var dx = event.clientX - sizing.x, dy = event.clientY - sizing.y;
    if (edge.indexOf("e") >= 0) width = box.width + dx;
    if (edge.indexOf("w") >= 0) width = box.width - dx;
    if (edge.indexOf("s") >= 0) height = box.height + dy;
    if (edge.indexOf("n") >= 0) height = box.height - dy;
    size(width, height, edge.indexOf("w") >= 0 ? box.right : null, edge.indexOf("n") >= 0 ? box.bottom : null, box);
    store(true);
  });
  panel.addEventListener("pointerup", function () { sizing = null; });
  // 5.5: without the arrow buttons the focusable title moves the window with the arrow keys;
  // with Shift they change its size (right/down larger, left/up smaller).
  var STEPS = {ArrowLeft: [-40, 0], ArrowRight: [40, 0], ArrowUp: [0, -40], ArrowDown: [0, 40]};
  head.querySelector("h2").addEventListener("keydown", function (event) {
    var step = STEPS[event.key];
    if (!step) return;
    event.preventDefault();
    var box = panel.getBoundingClientRect();
    if (event.shiftKey) size(box.width + step[0], box.height + step[1], null, null, box);
    else place(box.x + step[0], box.y + step[1]);
    store(true);
  });
  function resize() { place(state.x, state.y); }
  window.addEventListener("resize", resize);
  if (window.visualViewport) window.visualViewport.addEventListener("resize", resize);
  window.addEventListener("pagehide", function () {
    if (restored && !content.hidden) state.scroll = content.scrollTop;
    store(); panel.hidden = true; clearTimeout(timer);
  });
  window.addEventListener("beforeunload", function (event) {
    if (blocked && unsaved) { event.preventDefault(); event.returnValue = ""; }
  });
  window.addEventListener("pageshow", function (event) { if (event.persisted) { refresh(true); schedule(); } });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(false); });
  function schedule() { clearTimeout(timer); timer = setTimeout(function () { refresh(false); schedule(); }, 2000); }
  show(false); content.scrollTop = state.scroll; remember().catch(failure); refresh(false); schedule();
})();
