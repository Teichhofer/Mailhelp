"""Controllable browser Push APIs; no external service is contacted."""

PUSH_STUB = """
window.__push = {permission: "granted", existing: null, subscribed: null, unsubscribed: 0,
  options: null, remove: true, subscribeError: false, registerError: false, hang: false};
const manager = {
  getSubscription: () => Promise.resolve(window.__push.existing),
  subscribe: (options) => {
    if (window.__push.subscribeError) return Promise.reject(new Error("synthetic"));
    window.__push.options = options;
    const value = window.__push.subscribed;
    value.options = options; window.__push.existing = value;
    return Promise.resolve(value);
  }
};
const listeners = [];
window.__pushMessage = data => listeners.forEach(listener => listener({data}));
const registration = {pushManager: manager, active: {postMessage: () =>
  window.__pushMessage({type:"mailhelp-worker-status", version:"synthetic-worker"})}};
window.__push.registration = registration;
Object.defineProperty(navigator, "serviceWorker", {configurable: true, value: {
  register: () => window.__push.registerError ? Promise.reject(new Error("synthetic")) :
    window.__push.hang ? new Promise(() => {}) : Promise.resolve(registration),
  ready: Promise.resolve(registration),
  addEventListener: (name, listener) => listeners.push(listener)}});
Object.defineProperty(Notification, "permission", {get: () => window.__push.permission});
Notification.requestPermission = () => Promise.resolve(window.__push.permission);
window.__subscription = json => ({options: {}, toJSON: () => json,
  unsubscribe: () => { window.__push.unsubscribed += 1;
    if (window.__push.remove) window.__push.existing = null;
    return Promise.resolve(window.__push.remove); }});
"""
