// Mailhelp web interface: the open decisions – split view, background refresh, card actions
// and the swipe gesture. Both share the card state and call each other, so they stay together.
"use strict";

// 2.0: split view, quick filters, shortcuts, undo, lightbox and Web-Push.
// Every form still posts to the server, which checks session, CSRF and version.
(function () {
  var main = document.getElementById("inhalt");
  var desktop = window.matchMedia("(min-width: 1024px)");
  var items = null, pane = null, selected = null, requestNumber = 0;
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
  // 6.2.8: on phones the search and sort controls of "Offen" start folded unless something is set,
  // so the first decision is on the first screen. Without JavaScript they simply stay open.
  var phone = window.matchMedia("(max-width: 899px)");
  function foldTools() {
    var tools = main.querySelector("details[data-open-more]");
    if (tools && phone.matches && !tools.hasAttribute("data-set")) tools.open = false;
  }
  function updateChips(reveal) {
    var row = main.querySelector(".open-toolbar .filter-chips");
    if (!row) return;
    var active = row.querySelector('a[aria-current="true"]');
    if (reveal && active) active.scrollIntoView({block: "nearest", inline: "nearest"});
    row.classList.toggle("chips-overflow", row.scrollLeft+row.clientWidth < row.scrollWidth-1);
  }
  document.addEventListener("scroll", function (event) {
    if (event.target.matches && event.target.matches(".filter-chips")) updateChips(false);
  }, true);
  window.addEventListener("resize", function () { updateChips(false); });
  // 6.2.10: long sections (the evaluation charts) also start folded on phones.
  if (phone.matches) document.querySelectorAll("details[data-fold-phone]").forEach(function (node) { node.open = false; });
  // From 900 px the summary is hidden, so the controls must never stay folded there.
  phone.addEventListener("change", function () {
    var tools = main.querySelector("details[data-open-more]");
    if (tools && !phone.matches) tools.open = true;
  });

  function enhance(previous) {
    foldTools();
    updateChips(true);
    items = main.querySelector(".open-items");
    pane = selected = null;
    if (!items) return;
    var split = document.createElement("div");
    pane = document.createElement("section");
    split.className = "split-view";
    pane.className = "detail-pane";
    pane.dataset.dirty = "no";
    pane.setAttribute("aria-label", "Ausgewählter Vorgang");
    items.classList.add("master-pane", "swipeable");
    items.setAttribute("aria-label", "Offene Vorgänge");
    showHint();
    items.before(split);
    split.append(items, pane);
    if (previous) pane.replaceChildren.apply(pane, Array.from(previous.childNodes));
    if (desktop.matches) restoreSelection();
  }

  // New data replaces the open items without reloading the page. A running
  // undo countdown or unsaved input in the pane waits for the next check.
  document.addEventListener("mailhelp:stale", function (event) {
    if (swipe || document.querySelector(".swipe-flying")) { event.preventDefault(); return; }
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
  function syncOverview(page) {
    var count = main.querySelector(".page-heading h1 .count"), freshCount = page.querySelector(".page-heading h1 .count");
    if (count && freshCount) count.textContent = freshCount.textContent;
    var links = page.querySelectorAll('nav a[href="/"]');
    document.querySelectorAll('nav a[href="/"]').forEach(function (link, index) {
      if (links[index]) link.replaceWith(links[index].cloneNode(true));
    });
    var oldDescription = document.getElementById("offen-zahl"), description = page.getElementById("offen-zahl");
    if (oldDescription) oldDescription.remove();
    if (description) document.body.appendChild(description);
    var oldEmpty = main.querySelector(".inbox-zero"), empty = page.querySelector(".inbox-zero");
    if (oldEmpty) oldEmpty.remove();
    // Above the list, else above "Zuletzt erledigt"; without either, insertBefore(…, null) appends it.
    if (empty) main.insertBefore(empty, main.querySelector(":scope > .split-view, :scope > h2:has(+ .recent)"));
  }
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
          return fetch(location.pathname + location.search, {credentials: "same-origin", cache: "no-store"})
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
              if (master) { clearFlight(master); master.replaceWith(updated); }
              syncOverview(page);
              // A decision also moves the item to "Zuletzt erledigt" on the same fresh overview.
              var recent = page.querySelector(".recent"), shown = main.querySelector(".recent");
              if (recent) {
                if (shown) shown.replaceWith(recent);
                else main.append(recent.previousElementSibling, recent);
              }
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
          statusText(marker, "Verbindung unterbrochen. Die Aktion wird nicht erneut gesendet; der Status wird weiter geprüft.");
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
    statusText(marker, "Wird verarbeitet …");
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
      var kind = fields.get("kind");
      if (kind === "retry_mail" || kind === "file_mail") {
        // 7.3.4: like without JavaScript, the action's page leads on to the mail or the failure list.
        location.assign("/aktion/" + id + (fields.get("zurueck") === "fehlerliste" ? "?zurueck=fehlerliste" : ""));
        return;
      }
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
            marker.setAttribute("role", "alert"); statusText(marker, result.error || "Die Aktion wurde nicht angenommen.");
            flyBack(card);
            (card || form).querySelectorAll("button, textarea").forEach(function (button) { button.disabled = false; });
            delete form.dataset.sending;
            return;
          }
          admitted(result.id);
        });
      }).catch(function () {
        statusText(marker, "Antwort unterbrochen. Der Annahmestatus wird geprüft; es wird nichts erneut gesendet.");
        pollCard(marker);
      });
  }, true);
  observeCards();

  // 6.9: the browser arbitrates pan-y; once accepted, the grip follows both axes exactly.
  var SWIPE = {start: 10, edge: 24, share: 0.4, most: 160, tilt: 10, tiltHeight: 400,
               fling: 0.9, flingShare: 0.5, window: 100};
  var ACCEPT = 'input[name="kind"][value="confirm"], input[name="decision"][value="relevant"]';
  var REJECT = 'input[name="kind"][value="reject"], input[name="decision"][value="irrelevant"]';
  var BLOCKED = "Diese Aktion ist für diesen Vorgang nicht möglich.", TYPED = "Erst die Antwort senden oder das Feld leeren.";
  var coarse = window.matchMedia("(pointer: coarse)"), reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var HINT = "mailhelp-swipe-hint", swipe = null, suppressClick = null, flights = new WeakMap();
  var demoTimer = null, demo = null, candidate = null, demoSeen = false, staleHint = false;

  document.addEventListener("click", function (event) {
    if (!suppressClick || !suppressClick.contains(event.target) || event.detail === 0) return;
    suppressClick = null;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  function remembered() {
    try { return localStorage.getItem(HINT) === "1"; } catch (error) { return false; }
  }
  function dismissHint() {
    window.clearTimeout(demoTimer);
    candidate = null;
    main.querySelectorAll("[data-swipe-hint]").forEach(function (node) { node.hidden = true; });
    try { localStorage.setItem(HINT, "1"); } catch (error) { return; }
  }
  function formOf(card, selector) {
    var input = card.querySelector(selector);
    return input ? input.form : null;
  }
  function showHint() {
    var first = items.querySelector(REJECT), tip = main.querySelector("[data-swipe-hint]");
    if (!coarse.matches || desktop.matches || !first || remembered()) return;
    var card = first.closest("article.card");
    tip.querySelector("span").textContent = card.querySelector('input[name="decision"]')
      ? "Nach rechts wischen: relevant · nach links: irrelevant"
      : "Nach rechts wischen: anlegen · nach links: verwerfen";
    card.after(tip);
    tip.hidden = false;
    candidate = cards().find(function (item) {
      return formOf(item, ACCEPT) && formOf(item, REJECT) && !item.querySelector("button:disabled");
    });
    quiet();
  }
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-swipe-hint-close]")) dismissHint();
  });

  function scrollsSideways(node, card) {
    for (; node !== card; node = node.parentElement) {
      if (node.scrollWidth > node.clientWidth && /auto|scroll/.test(getComputedStyle(node).overflowX)) return true;
    }
    return false;
  }
  function prepare(card, x, y) {
    var box = card.getBoundingClientRect();
    return {card: card, width: box.width, height: box.height, offsetX: x-box.left, offsetY: y-box.top,
            inline: card.style.cssText, forms: {accept: formOf(card, ACCEPT), reject: formOf(card, REJECT)},
            backdrop: null, dx: 0, dy: 0, vx: 0, vy: 0, armed: false, pulsed: false, reason: "", samples: []};
  }
  function begin(state) {
    var card = state.card, backdrop = document.createElement("div"), bar = card.querySelector("[data-swipe-blocked]");
    state.limit = Math.min(state.width * SWIPE.share, SWIPE.most);
    state.why = bar ? bar.dataset.swipeBlocked : BLOCKED;
    state.typed = Array.from(card.querySelectorAll("textarea")).some(function (box) { return box.value.trim(); });
    backdrop.setAttribute("aria-hidden", "true");
    backdrop.innerHTML = '<span class="swipe-label"><span class="swipe-symbol"></span><span class="swipe-text"></span></span>';
    backdrop.style.cssText = "top:" + card.offsetTop + "px;left:" + card.offsetLeft + "px;width:" +
      state.width + "px;height:" + state.height + "px";
    backdrop.firstChild.style.width = state.limit + "px";
    card.before(backdrop);
    card.style.transformOrigin = state.offsetX + "px " + state.offsetY + "px";
    card.classList.add("swipe-card", "swiping");
    state.backdrop = backdrop;
  }
  function follow(state, dx, dy) {
    var side = dx > 0 ? "accept" : "reject", form = state.forms[side], size = Math.abs(dx);
    var reason = state.typed ? TYPED : form ? "" : state.why;
    var labelChanged = state.side !== side || state.reason !== reason;
    var offset = reason ? 32 * (1-Math.exp(-size/80)) * Math.sign(dx) : dx;
    var maximum = SWIPE.tilt * Math.min(1, SWIPE.tiltHeight/state.height);
    var angle = reason || reduced.matches ? 0 :
      Math.max(-maximum, Math.min(maximum, dx/state.width*SWIPE.tilt)) * (state.offsetY < state.height/2 ? 1 : -1);
    var progress = Math.min(1, size/state.limit), armed = !reason && size >= state.limit;
    if (armed && !state.pulsed) {
      state.pulsed = true;
      if (navigator.vibrate) navigator.vibrate(10);
    }
    state.side = side; state.armed = armed; state.reason = reason; state.angle = angle;
    state.dx = dx; state.dy = dy;
    state.card.style.transform = "translate(" + offset + "px," + dy + "px) rotate(" + angle + "deg)";
    state.backdrop.style.setProperty("--swipe-progress", progress);
    var classes = "swipe-backdrop swipe-" + side + (reason ? " swipe-blocked" : armed ? " swipe-armed" : "") +
      (state.pulsed ? " swipe-pulsed" : "");
    if (state.backdrop.className !== classes) state.backdrop.className = classes;
    if (labelChanged) {
      state.backdrop.querySelector(".swipe-symbol").textContent = reason ? "🔒" : dx > 0 ? "✓" : "✕";
      state.backdrop.querySelector(".swipe-text").textContent = reason ? "" : form.querySelector("button").textContent;
    }
  }
  function dispose(state) {
    window.clearTimeout(state.timer);
    state.card.style.cssText = state.inline;
    state.card.classList.remove("swiping", "swipe-card", "swipe-flying");
    state.card.hidden = false;
    state.backdrop.remove();
  }
  function springBack(state) {
    state.card.classList.remove("swiping");
    var duration = reduced.matches ? 100 : state.demonstration ? 250 :
      Math.min(300, Math.max(150, Math.hypot(state.dx, state.dy)));
    state.card.style.transition = "transform " + duration + "ms " +
      (reduced.matches ? "linear" : "cubic-bezier(.2,1.3,.4,1)");
    state.card.style.transform = "";
    state.timer = window.setTimeout(function () { dispose(state); if (demo === state) demo = null; }, duration);
  }
  function clearFlight(card) {
    var state = flights.get(card);
    if (!state) return;
    state.strip.remove();
    flights.delete(card);
    dispose(state);
  }
  function flyBack(card) {
    var state = flights.get(card);
    if (!state) return;
    card.hidden = false;
    state.strip.style.height = state.height + "px";
    card.style.transition = "transform 200ms ease-out, opacity 100ms linear";
    requestAnimationFrame(function () { card.style.transform = ""; card.style.opacity = "1"; });
    state.timer = window.setTimeout(function () { clearFlight(card); }, 200);
  }
  function statusText(marker, text) {
    marker.textContent = text;
    var card = marker.closest("article.card"), state = flights.get(card);
    if (state) state.strip.textContent = state.label + " – " + text;
  }
  function flyOut(state) {
    var card = state.card, strip = document.createElement("div");
    state.label = (state.side === "accept" ? "✓ " : "✕ ") + state.forms[state.side].querySelector("button").textContent;
    strip.className = "swipe-result swipe-" + state.side;
    strip.setAttribute("role", "status");
    strip.textContent = state.label + " – wird verarbeitet …";
    strip.style.height = state.height + "px";
    state.strip = strip;
    var top = card.offsetTop, left = card.offsetLeft;
    card.before(strip);
    card.style.position = "absolute"; card.style.top = top + "px";
    card.style.left = left + "px"; card.style.width = state.width + "px";
    card.classList.remove("swiping"); card.classList.add("swipe-flying");
    flights.set(card, state);
    var duration = reduced.matches ? 100 : Math.min(240, Math.max(180, 220 - Math.abs(state.vx)*20));
    card.style.transition = reduced.matches ? "opacity 100ms linear" : "transform " + duration + "ms cubic-bezier(.2,.6,.4,1)";
    if (reduced.matches) card.style.opacity = "0";
    else {
      var end = (state.side === "accept" ? 1 : -1) * (innerWidth + state.width);
      var y = state.dy + state.vy*duration;
      card.style.transform = "translate(" + end + "px," + y + "px) rotate(" + state.angle*1.5 + "deg)";
    }
    state.timer = window.setTimeout(function () {
      card.hidden = true;
      state.backdrop.hidden = true;
      strip.style.height = "56px";
      state.forms[state.side].requestSubmit();
    }, duration);
  }
  function cancelDemo() {
    if (!demo) return;
    dispose(demo); demo = null;
  }
  function quiet() {
    window.clearTimeout(demoTimer);
    if (!candidate || demoSeen || staleHint || !coarse.matches || desktop.matches || reduced.matches || swipe || document.hidden) return;
    demoTimer = window.setTimeout(function () {
      var box = candidate.getBoundingClientRect();
      if (box.top < document.querySelector("header").getBoundingClientRect().bottom ||
          box.bottom > innerHeight-document.querySelector(".tab-bar").getBoundingClientRect().height ||
          candidate.querySelector("textarea:focus, input:focus")) { quiet(); return; }
      demoSeen = true;
      demo = prepare(candidate, box.left+box.width/2, box.top+box.height/4);
      demo.demonstration = true;
      begin(demo);
      demo.card.classList.remove("swiping");
      demo.card.style.transition = "transform 250ms ease-out";
      follow(demo, Math.min(110, box.width/3), 0);
      demo.timer = window.setTimeout(function () { springBack(demo); }, 250);
    }, 600);
  }
  function activity() { cancelDemo(); quiet(); }
  ["pointerdown", "pointermove", "keydown", "input", "scroll"].forEach(function (type) {
    document.addEventListener(type, activity, true);
  });
  document.addEventListener("visibilitychange", activity);
  window.addEventListener("resize", activity);
  document.addEventListener("mailhelp:stale", function () {
    staleHint = true; window.clearTimeout(demoTimer); cancelDemo();
  });
  window.addEventListener("pagehide", function () { window.clearTimeout(demoTimer); cancelDemo(); });

  document.addEventListener("pointerdown", function (event) {
    suppressClick = null;
    if (swipe) { var cancelled = finish(); if (cancelled.backdrop) springBack(cancelled); return; }
    var card = event.target.closest(".open-items article.card");
    if (!card || desktop.matches || event.pointerType === "mouse" ||
        event.target.closest("input, textarea, select") ||
        event.clientX < SWIPE.edge || event.clientX > window.innerWidth-SWIPE.edge ||
        String(window.getSelection()) || card.querySelector("[data-card-command-status], [data-command-result]") ||
        flights.has(card) || scrollsSideways(event.target, card)) return;
    if (!formOf(card, REJECT)) return;
    swipe = prepare(card, event.clientX, event.clientY);
    swipe.id = event.pointerId; swipe.x = event.clientX; swipe.y = event.clientY;
    swipe.samples.push({x: event.clientX, y: event.clientY, t: event.timeStamp});
  });
  // The browser scrolls moves steeper than 45° (pan-y) and then cancels the pointer. Starting earlier
  // only made the card twitch for a frame while the list scrolled; a flatter move is always the card's.
  function startable(dx, dy) { return Math.abs(dx) >= SWIPE.start && Math.abs(dx) >= Math.abs(dy); }
  // WebKit must receive the horizontal decision before its native scroller takes over.
  // Vertical moves and a second finger remain native scrolling / pinch zoom.
  document.addEventListener("touchmove", function (event) {
    if (!swipe || event.touches.length !== 1) return;
    var point = event.touches[0];
    if (swipe.backdrop || startable(point.clientX-swipe.x, point.clientY-swipe.y)) event.preventDefault();
  }, {passive: false});
  document.addEventListener("pointermove", function (event) {
    if (!swipe || event.pointerId !== swipe.id) return;
    var state = swipe, samples = event.getCoalescedEvents ? event.getCoalescedEvents() : [];
    if (!samples.length) samples = [event];
    samples.forEach(function (point) {
      state.samples.push({x: point.clientX, y: point.clientY, t: point.timeStamp});
      while (state.samples.length > 2 && state.samples[0].t < point.timeStamp-SWIPE.window) state.samples.shift();
    });
    state.latest = samples[samples.length-1];
    if (state.frame) return;
    state.frame = requestAnimationFrame(function () {
      state.frame = null;
      var dx = state.latest.clientX-state.x, dy = state.latest.clientY-state.y;
      if (!state.backdrop) {
        if (!startable(dx, dy)) return;
        begin(state);
        try { state.card.setPointerCapture(state.id); } catch (error) { /* cancelled native pointer */ }
      }
      follow(state, dx, dy);
    });
  });
  function finish() {
    var state = swipe;
    swipe = null;
    if (state.frame) cancelAnimationFrame(state.frame);
    if (!state.backdrop) return state;
    suppressClick = state.card;
    return state;
  }
  function release(event) {
    if (!swipe || event.pointerId !== swipe.id) return;
    // The final finger position need not have been delivered in a pointermove (or a frame) yet.
    if (event.type === "pointerup") {
      swipe.latest = event;
      var previous = swipe.samples[swipe.samples.length-1];
      if (event.clientX !== previous.x || event.clientY !== previous.y) {
        swipe.samples.push({x: event.clientX, y: event.clientY, t: event.timeStamp});
      }
    }
    if ((swipe.frame || event.type === "pointerup") && swipe.latest &&
        (swipe.backdrop || startable(swipe.latest.clientX-swipe.x, swipe.latest.clientY-swipe.y))) {
      if (!swipe.backdrop) begin(swipe);
      follow(swipe, swipe.latest.clientX-swipe.x, swipe.latest.clientY-swipe.y);
    }
    var state = finish();
    if (!state.backdrop) return;
    var samples = state.samples.filter(function (sample) { return event.timeStamp-sample.t <= SWIPE.window; });
    if (samples.length > 1) {
      var first = samples[0], last = samples[samples.length-1], elapsed = Math.max(1, last.t-first.t);
      state.vx = (last.x-first.x)/elapsed; state.vy = (last.y-first.y)/elapsed;
    }
    var fling = Math.abs(state.vx) >= SWIPE.fling && state.vx*state.dx > 0 &&
      Math.abs(state.dx) >= state.limit*SWIPE.flingShare;
    if (event.type === "pointerup" && !state.reason && (state.armed || fling)) {
      dismissHint(); flyOut(state);
    } else {
      if (event.type === "pointerup" && state.reason) announce(state.reason);
      springBack(state); quiet();
    }
  }
  document.addEventListener("pointerup", release);
  document.addEventListener("pointercancel", release);

  // dialogs.js (loaded next) uses these; pane and selection change at runtime.
  window.MailhelpOpen = {
    main: main, desktop: desktop, announce: announce, cards: cards, select: select, parse: parse,
    enhance: enhance, openSource: openSource,
    get pane() { return pane; },
    get selected() { return selected; }
  };
})();
