// Mailhelp web interface: the help window of the settings shell.
"use strict";

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
