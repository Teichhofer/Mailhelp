// Mailhelp web interface: collapsible sidebar, links to one setting and the live settings search.
"use strict";

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
    if (!row) return;
    if (row.classList.contains("setting-row")) {
      var details = row.querySelector("details");
      if (details) details.open = true;
    } else if (row.matches("input")) {
      row.focus();  // 8.5: a cell of the timeouts table
    } else if (row.classList.contains("setting-field")) {
      row.querySelector("input, select, textarea").focus();  // 8.5: a value of a section form
    }
  }
  window.addEventListener("hashchange", openTarget);
  // 8.5: after the load as well; the browser's own jump to the anchor would otherwise reset the focus.
  window.addEventListener("load", openTarget);
  openTarget();
})();

// 8.5: the save bar of a section counts changed values and warns before leaving with unsaved changes.
(function () {
  var forms = document.querySelectorAll("form[data-settings-form]");
  if (!forms.length) return;
  var submitting = false;
  function changed(control) {
    // A hidden input mirrors its value attribute, so it never differs from defaultValue.
    if (control.tagName === "SELECT") {
      return Array.prototype.some.call(control.options, function (option) {
        return option.selected !== option.defaultSelected;
      });
    }
    return control.value !== control.defaultValue;
  }
  function count(form) {
    return Array.prototype.filter.call(form.elements, function (control) {
      return /^setting:/.test(control.name) && changed(control);
    }).length;
  }
  function update(form) {
    var number = count(form);
    var bar = form.querySelector("[data-settings-savebar]");
    bar.classList.toggle("changed", number > 0);
    bar.querySelector("[data-settings-changes]").textContent =
      number === 0 ? "" : number === 1 ? mailhelpText("1 Änderung") : number + mailhelpText(" Änderungen");
  }
  Array.prototype.forEach.call(forms, function (form) {
    form.addEventListener("input", function () { update(form); });
    form.addEventListener("change", function () { update(form); });
    form.addEventListener("submit", function () { submitting = true; });
  });
  window.addEventListener("beforeunload", function (event) {
    if (submitting) return;
    var unsaved = Array.prototype.some.call(forms, function (form) { return count(form) > 0; });
    if (unsaved) event.preventDefault();
  });
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
    status.textContent = data.total === 0 ? mailhelpText("Keine Einstellung gefunden.") : data.total + " Treffer";
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
      status.textContent = mailhelpText("Die Sofortsuche ist gerade nicht verfügbar – „Suchen“ funktioniert weiterhin.");
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
