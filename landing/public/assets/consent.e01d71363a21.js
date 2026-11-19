"use strict";
(function () {
  var cookieName = "inboxstride_consent", revision = "2026-11-16-v1", lifetime = 15552000;
  var measurementId = "G-ZQP60GV6NS", loaded = false, current = null, channel = null;
  var panel = document.querySelector("[data-consent-panel]");
  if (!panel) return;
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window["ga-disable-" + measurementId] = true;
  window.gtag("consent", "default", {
    analytics_storage: "denied", ad_storage: "denied", ad_user_data: "denied",
    ad_personalization: "denied", personalization_storage: "denied",
    functionality_storage: "granted", security_storage: "granted"
  });
  window.gtag("set", {
    allow_google_signals: false, allow_ad_personalization_signals: false,
    allow_enhanced_conversions: false, user_data: {}, ads_data_redaction: true,
    url_passthrough: false, cookie_expires: lifetime, cookie_update: false,
    page_location: location.origin + location.pathname,
    page_referrer: cleanReferrer(document.referrer)
  });

  function cleanReferrer(value) {
    try { var url = new URL(value); return url.origin + url.pathname; }
    catch (error) { return ""; }
  }
  function read() {
    try {
      var item = document.cookie.split("; ").find(function (part) { return part.startsWith(cookieName + "="); });
      if (!item) return null;
      var value = JSON.parse(decodeURIComponent(item.slice(cookieName.length + 1)));
      if (value.revision !== revision || !["analytics", "necessary"].includes(value.choice) ||
          typeof value.at !== "number" || value.at > Date.now() || Date.now() - value.at >= lifetime * 1000) return null;
      return value;
    } catch (error) { return null; }
  }
  function save(choice) {
    current = {revision: revision, choice: choice, at: Date.now()};
    try {
      document.cookie = cookieName + "=" + encodeURIComponent(JSON.stringify(current)) +
        "; Path=/; Max-Age=" + lifetime + "; SameSite=Lax" + (location.protocol === "https:" ? "; Secure" : "");
    } catch (error) { /* The explicit choice applies to this page even if storage is blocked. */ }
    if (channel) channel.postMessage(choice);
  }
  function clearAnalyticsCookies() {
    var cookies;
    try { cookies = document.cookie; } catch (error) { return; }
    cookies.split(";").forEach(function (item) {
      var name = item.split("=")[0].trim();
      if (!/^(_ga(?:_|$)|_gid$|_gat(?:_|$))/.test(name)) return;
      ["", location.hostname, "." + location.hostname, ".inboxstride.de"].forEach(function (domain) {
        document.cookie = name + "=; Path=/; Max-Age=0; SameSite=Lax" +
          (domain ? "; Domain=" + domain : "") + (location.protocol === "https:" ? "; Secure" : "");
      });
    });
  }
  function startAnalytics() {
    if (loaded) return;
    loaded = true;
    window["ga-disable-" + measurementId] = false;
    window.gtag("consent", "update", {analytics_storage: "granted", ad_storage: "denied",
      ad_user_data: "denied", ad_personalization: "denied"});
    window.gtag("js", new Date());
    window.dataLayer.push({"gtm.start": Date.now(), event: "gtm.js"});
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://www.googletagmanager.com/gtm.js?id=GTM-55C4ZT5N";
    document.head.appendChild(script);
  }
  function show() {
    panel.hidden = false;
    panel.querySelector("[data-consent-close]").hidden = !current;
    var status = panel.querySelector("[data-consent-status]");
    status.textContent = !current ? "" : panel.dataset[current.choice === "analytics" ? "accepted" : "rejected"];
  }
  function revoke() {
    window["ga-disable-" + measurementId] = true;
    clearAnalyticsCookies();
    // Reload removes the already executed third-party code. Do not send a denied-consent ping.
    if (loaded) location.reload();
  }
  function sync() {
    var choice = read();
    if (loaded && (!choice || choice.choice !== "analytics")) { revoke(); return; }
    current = choice;
    if (!choice) show();
    else if (choice.choice === "analytics") startAnalytics();
  }
  panel.querySelector("[data-consent-accept]").addEventListener("click", function () {
    save("analytics"); panel.hidden = true; startAnalytics();
  });
  panel.querySelector("[data-consent-reject]").addEventListener("click", function () {
    save("necessary"); panel.hidden = true; revoke();
  });
  panel.querySelector("[data-consent-close]").addEventListener("click", function () { panel.hidden = true; });
  document.querySelectorAll("[data-consent-settings]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () { show(); panel.querySelector("[data-consent-reject]").focus(); });
  });
  try { channel = new BroadcastChannel("inboxstride-consent"); channel.onmessage = sync; }
  catch (error) { /* Cookie/focus synchronization still works without BroadcastChannel. */ }
  window.addEventListener("focus", sync);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) sync(); });
  window.setInterval(sync, 60000);
  current = read();
  if (!current) show();
  else if (current.choice === "analytics") startAnalytics();
  else clearAnalyticsCookies();
})();
