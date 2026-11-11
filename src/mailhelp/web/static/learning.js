(function () {
  "use strict";
  // 5.7.3: the action bar of the rule review counts the selected proposals as they are ticked.
  // The script is only included together with that bar.
  var count = document.querySelector("[data-rule-count]");
  var boxes = Array.from(document.querySelectorAll("[data-rule-select]"));
  function update() {
    var selected = boxes.filter(function (box) { return box.checked; }).length;
    count.textContent = selected + " von " + boxes.length + " Vorschlägen ausgewählt.";
  }
  boxes.forEach(function (box) { box.addEventListener("change", update); });
  update();
}());
