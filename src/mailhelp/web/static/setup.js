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
// 6.1: a check can take up to 15 seconds per service; say what is happening (app.js locks the form).
const checking = document.querySelector("[data-check-status]");
for (const form of document.querySelectorAll("form")) {
  form.addEventListener("submit", (event) => {
    if (checking && event.submitter && event.submitter.hasAttribute("data-check")) {
      checking.textContent = "Wird geprüft … das kann bis zu 15 Sekunden je Dienst dauern.";
    }
  });
}
// The result is announced and receives the focus, so keyboard users start reading there.
const result = document.getElementById("pruefergebnis");
if (result) result.focus();
