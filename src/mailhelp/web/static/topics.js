(function () {
  "use strict";
  var query = document.getElementById("topic-query");
  var status = document.getElementById("topic-status");
  var rows = Array.from(document.querySelectorAll("[data-topic-row]"));
  function normalize(value) {
    return value.toLowerCase().replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue")
      .replace(/ß/g, "ss").trim().replace(/\s+/g, " ");
  }
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
}());
