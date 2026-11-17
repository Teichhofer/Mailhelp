// Mailhelp web interface: dialogs, chart details, keyboard shortcuts, quick filters, lightbox
// and copying reply drafts. Loaded after open-list.js, whose state it reads.
"use strict";

(function () {
  var shared = window.MailhelpOpen, main = shared.main, desktop = shared.desktop;
  var announce = shared.announce, cards = shared.cards, select = shared.select, parse = shared.parse;
  var enhance = shared.enhance, openSource = shared.openSource;
  var shown = location.pathname + location.search;

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
    [["J / ↓", "Nächster Vorgang"], ["K / ↑", "Vorheriger Vorgang"], ["1 / A / C / Enter", "Bestätigen"],
     ["E", "Bearbeiten"], ["2 / X / D", "Verwerfen"], ["?", "Diese Hilfe"]].forEach(function (pair) {
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
    if (!shared.pane || !desktop.matches) return;
    var list = cards(), step = {j: 1, arrowdown: 1, k: -1, arrowup: -1}[key];
    if (step) {
      event.preventDefault();
      select(list[Math.min(list.length - 1, Math.max(0, list.indexOf(shared.selected) + step))]);
      return;
    }
    // 7.6.2: 1 and 2 decide with one hand next to the number row.
    var action = {1: "confirm", a: "confirm", c: "confirm", enter: "confirm", 2: "reject", x: "reject", d: "reject",
                  e: "edit"}[key];
    if (!action) return;
    event.preventDefault();
    var control = action === "edit" ? shared.pane.querySelector('a[href$="/bearbeiten"]')
      : shared.pane.querySelector('input[name="kind"][value="' + action + '"]');
    if (!control) {
      announce("Diese Aktion ist für den ausgewählten Vorgang nicht möglich.");
      return;
    }
    if (action === "edit") {
      control.click();
      return;
    }
    control.form.requestSubmit();
    // 7.6.2: a decision moves on to the next card, so a stack is decided key after key.
    var next = list[list.indexOf(shared.selected) + 1];
    if (next) select(next);
  });

  function filter(chip) {
    if (shared.pane && shared.pane.dataset.dirty === "yes") {
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
    var card = shared.pane && desktop.matches ? event.target.closest(".master-pane article.card") : null;
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

  // 7.3.2: the error report of a failed mail as a dialog in the failure list; the link itself
  // leads to the report on the mail page, so nothing is lost without JavaScript or on a failed read.
  document.addEventListener("click", function (event) {
    var link = event.target.closest("[data-error-report]");
    if (!link) return;
    event.preventDefault();
    fetch(link.getAttribute("href").split("#")[0], {credentials: "same-origin"}).then(function (answer) {
      if (!answer.ok) throw new Error("status");
      return answer.text();
    }).then(function (text) {
      var card = new DOMParser().parseFromString(text, "text/html").getElementById("fehlerbericht");
      if (!card) throw new Error("missing");
      card.removeAttribute("id");
      card.querySelector("details").open = true;
      // Opened from the failure list, its actions lead back to the list like the row buttons.
      card.querySelectorAll('form[action="/aktion"]').forEach(function (form) {
        var back = document.createElement("input");
        back.type = "hidden";
        back.name = "zurueck";
        back.value = "fehlerliste";
        form.appendChild(back);
      });
      modal("Fehlerbericht", [card]);
    }).catch(function () { location.href = link.href; });
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy-report]");
    if (!button) return;
    var box = button.closest(".report-box"), status = box.querySelector("[data-copy-status]");
    if (!navigator.clipboard) {
      status.textContent = "Bitte den Bericht markieren und manuell kopieren.";
      return;
    }
    navigator.clipboard.writeText(box.querySelector("textarea").value).then(function () {
      status.textContent = "Bericht kopiert.";
    }).catch(function () {
      status.textContent = "Kopieren nicht erlaubt. Bitte den Bericht manuell kopieren.";
    });
  });

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
})();
