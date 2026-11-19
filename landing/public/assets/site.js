"use strict";
document.querySelectorAll("form[data-interest]").forEach(function (form) {
  var button = form.querySelector("button[type=submit]"), output = form.querySelector("[role=status]");
  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    output.textContent = form.dataset.loading;
    output.className = "form-status";
    try {
      var response = await fetch(form.action, {
        method: "POST", credentials: "same-origin", headers: {"Accept": "application/json"},
        body: new URLSearchParams(new FormData(form))
      });
      var result = await response.json().catch(function () { return null; });
      if (!response.ok || !result || result.ok !== true || typeof result.message !== "string") {
        output.textContent = result && typeof result.message === "string" ? result.message : form.dataset.error;
        output.classList.add("error");
        return;
      }
      output.textContent = result.message;
      output.classList.add("success");
      form.reset();
    } catch (error) {
      output.textContent = form.dataset.error;
      output.classList.add("error");
    } finally {
      button.disabled = false;
      form.removeAttribute("aria-busy");
    }
  });
});
