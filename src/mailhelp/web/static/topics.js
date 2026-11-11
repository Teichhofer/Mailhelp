(function () {
  "use strict";
  function normalize(value) {
    return value.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue")
      .replace(/ß/g, "ss").trim().replace(/\s+/g, " ");
  }
  var list = document.getElementById("topic-filter");
  if (list) {
    var query = document.getElementById("topic-query");
    var status = document.getElementById("topic-status");
    var rows = Array.from(document.querySelectorAll("[data-topic-row]"));
    function filter() {
    var words = normalize(query.value).split(" ").filter(Boolean);
    var count = 0;
    rows.forEach(function (row) {
      var selected = status.value === "alle" || (status.value === "aktiv") === (row.dataset.enabled === "true");
      var found = words.every(function (word) { return row.dataset.topicSearch.indexOf(word) !== -1; });
      row.hidden = !(selected && found);
      if (!row.hidden) count += 1;
    });
    document.getElementById("topic-count").textContent = count + " von " + rows.length + " Themen angezeigt.";
    document.getElementById("topic-empty").hidden = count !== 0;
    }
    query.addEventListener("input", filter);
    status.addEventListener("change", filter);
  }
  var name = document.getElementById("topic-name");
  var identity = document.getElementById("topic-id");
  if (name && identity) {
    var manual = Boolean(identity.value);
    function suggest() {
      if (!manual) identity.value = normalize(name.value).replace(/[^a-z0-9_-]+/g, "-")
        .replace(/^[-_]+|[-_]+$/g, "").slice(0, 64).replace(/[-_]+$/g, "") || "thema";
    }
    name.addEventListener("input", suggest);
    identity.addEventListener("input", function () { manual = identity.value !== ""; });
    suggest();
  }
}());
