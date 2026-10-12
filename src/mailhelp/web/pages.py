"""Server-rendered HTML pages.

Every value from mails, LLM output or users is escaped with :func:`e`; links
from mails are shown as text.  Pages work without JavaScript; ``app.js`` only
adds the connection indicator and the automatic refresh.
"""

from __future__ import annotations

import html
from datetime import datetime

from ..formatting import format_datetime_local
from .auth import WebSession


def e(value: object) -> str:
    """Escape any value for HTML text and attribute positions."""
    return html.escape(str(value), quote=True)


NAVIGATION = (("/", "Offen"), ("/mails", "Mails"), ("/verlauf", "Verlauf"),
              ("/status", "Status"), ("/auswertung", "Auswertung"), ("/einstellungen", "Einstellungen"), ("/geraete", "Geräte"))


def layout(title: str, content: str, *, active: str | None = None, signed_in: bool = True,
           refresh: int | None = None, fingerprint: str | None = None,
           state_url: str | None = None, before: str = "", after: str = "") -> str:
    """Page frame; *refresh* adds a no-JavaScript reload for pending commands.

    *before* and *after* are further sections at the start and end of ``main``.
    """
    navigation = ""
    if signed_in:
        links = "".join(
            f'<a href="{href}"{" aria-current=\"page\"" if href == active else ""}>{label}</a>'
            for href, label in NAVIGATION)
        navigation = f'<nav class="nav" aria-label="Hauptnavigation">{links}</nav>'
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    data = f' data-fingerprint="{e(fingerprint)}"' if fingerprint else ""
    if state_url:
        # Pages with their own refresh signal (e.g. the status page).
        data += f' data-state-url="{e(state_url)}"'
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0b6b42">
{meta_refresh}<title>{e(title)} · Mailhelp</title>
<link rel="stylesheet" href="/static/app.css">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/static/icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Mailhelp">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<script src="/static/app.js" defer></script>
</head>
<body{data}>
<header class="top">
<a class="brand" href="/"><img src="/static/icon-192.png" alt="" width="28" height="28">Mailhelp</a>
<span class="connection" id="verbindung" role="status" aria-live="polite" hidden></span>
{navigation}
</header>
<main id="inhalt">{before}
{content}
{after}</main>
</body>
</html>
"""


def notice(text: str, kind: str = "info") -> str:
    role = "alert" if kind == "error" else "status"
    return f'<p class="notice notice-{kind}" role="{role}">{e(text)}</p>'


# Where pairing codes appear: the Telegram chat or, without Telegram (2.0), the PC console.
LOGIN_CHANNELS = {
    "telegram": {"sent": "Der Code wurde an deinen Telegram-Chat gesendet.", "label": "Code aus Telegram",
                 "intro": "Mailhelp sendet dir einen einmaligen Code in deinen Telegram-Chat.",
                 "button": "Code per Telegram senden", "again": "Neuen Code senden"},
    "console": {"sent": "Der Code steht im Konsolenfenster von Mailhelp auf dem PC "
                        "(bei Docker: <code>docker compose logs mailhelp</code>).",
                "label": "Code aus der Mailhelp-Konsole",
                "intro": "Mailhelp zeigt einen einmaligen Code im Konsolenfenster auf dem PC an.",
                "button": "Code in der Konsole anzeigen", "again": "Neuen Code anzeigen"},
}


def login_page(csrf: str, code_requested: bool, error: str | None = None,
               code: str = "", channel: str = "telegram") -> str:
    """Login; *code* pre-fills the field when the page was opened from the /web link."""
    message = notice(error, "error") if error else ""
    text = LOGIN_CHANNELS[channel]
    if code_requested or code:
        body = f"""<p>{text["sent"]} Er gilt 10 Minuten.</p>
<form method="post" action="/anmelden" class="stack">
<input type="hidden" name="csrf" value="{e(csrf)}">
<label for="code">{text["label"]}</label>
<input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{{4,5}}"
 maxlength="5" required autofocus value="{e(code)}">
<label for="geraet">Gerätename <span class="hint">(optional)</span></label>
<input id="geraet" name="geraet" maxlength="60" autocomplete="off" placeholder="z. B. iPhone">
<button class="button primary" type="submit">Gerät koppeln</button>
</form>
<form method="post" action="/anmelden/code" class="secondary-form">
<input type="hidden" name="csrf" value="{e(csrf)}">
<button class="button link" type="submit">{text["again"]}</button>
</form>"""
    else:
        body = f"""<p>Dieses Gerät ist noch nicht gekoppelt. {text["intro"]}</p>
<form method="post" action="/anmelden/code" class="stack">
<input type="hidden" name="csrf" value="{e(csrf)}">
<button class="button primary" type="submit">{text["button"]}</button>
</form>"""
    return layout("Anmelden", f"""<section class="card narrow">
<h1>Gerät koppeln</h1>
{message}{body}
</section>""", signed_in=False)


def _local(value: datetime, configured_timezone: str) -> str:
    return format_datetime_local(value, configured_timezone)


def devices_page(sessions: list[WebSession], current: WebSession, csrf: str,
                 configured_timezone: str, message: str | None = None) -> str:
    rows = []
    for session in sessions:
        label = " <span class=\"badge\">dieses Gerät</span>" if session.id == current.id else ""
        rows.append(f"""<li class="device">
<div><strong>{e(session.device)}</strong>{label}<br>
<span class="meta">Zuletzt aktiv: {e(_local(session.last_used_at, configured_timezone))} ·
gültig bis {e(_local(session.expires_at, configured_timezone))}</span></div>
<form method="post" action="/geraete/{e(session.id)}/abmelden">
<input type="hidden" name="csrf" value="{e(csrf)}">
<button class="button danger small" type="submit">Abmelden</button>
</form>
</li>""")
    content = f"""<h1>Gekoppelte Geräte</h1>
{notice(message) if message else ""}
<ul class="devices">{"".join(rows)}</ul>
<form method="post" action="/geraete/alle-abmelden" class="stack">
<input type="hidden" name="csrf" value="{e(csrf)}">
<button class="button danger" type="submit">Alle Geräte abmelden</button>
</form>
<p class="meta">Auch per Telegram: <code>/web_abmelden</code> meldet alle Geräte ab.</p>"""
    return layout("Geräte", content, active="/geraete")


def error_page(title: str, text: str, *, signed_in: bool = True) -> str:
    return layout(title, f"""<section class="card narrow">
<h1>{e(title)}</h1>
{notice(text, "error")}
<p><a class="button" href="/">Zur Übersicht</a></p>
</section>""", signed_in=signed_in)


__all__ = ["NAVIGATION", "devices_page", "e", "error_page", "layout", "login_page", "notice"]
