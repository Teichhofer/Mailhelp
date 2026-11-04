"use strict";
// Browser time zone is only a suggestion; manual choices survive back navigation.
const zone = document.querySelector('input[name="timezone"]');
if (zone && !sessionStorage.getItem("mailhelp-initial-zone")) {
  zone.value = Intl.DateTimeFormat().resolvedOptions().timeZone;
  sessionStorage.setItem("mailhelp-initial-zone", "shown");
}
for (const button of document.querySelectorAll("[data-copy-code]")) {
  button.addEventListener("click", () => navigator.clipboard.writeText(button.dataset.copyCode));
}
