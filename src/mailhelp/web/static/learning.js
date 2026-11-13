(function () {
  "use strict";
  // 5.7.3 / 6.0.4: the action bar of the rule review counts the proposals to accept and to reject
  // as they are chosen. The script is only included together with that bar.
  var count = document.querySelector("[data-rule-count]");
  var choices = Array.from(document.querySelectorAll("[data-rule-decision]"));
  function update() {
    var picked = choices.filter(function (choice) { return choice.checked; });
    var accepted = picked.filter(function (choice) { return choice.value === "accept"; }).length;
    var rejected = picked.filter(function (choice) { return choice.value === "reject"; }).length;
    count.textContent = accepted + " zur Übernahme ausgewählt · " + rejected + " zum Verwerfen markiert.";
  }
  choices.forEach(function (choice) { choice.addEventListener("change", update); });
  update();
}());
