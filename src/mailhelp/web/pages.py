"""Server-rendered HTML pages.

Every value from mails, LLM output or users is escaped with :func:`e`; links
from mails are shown as text.  Pages work without JavaScript; ``app.js`` only
adds the connection indicator and the automatic refresh.
"""

from __future__ import annotations

import html
from contextvars import ContextVar
from datetime import datetime

from ..formatting import format_datetime_local
from .auth import WebSession


def e(value: object) -> str:
    """Escape any value for HTML text and attribute positions."""
    return html.escape(str(value), quote=True)


NAVIGATION = (("/", "Offen"), ("/mails", "Mails"), ("/verlauf", "Verlauf"),
              ("/status", "Status"), ("/auswertung", "Auswertung"), ("/berichte", "Berichte"),
              ("/einstellungen", "Einstellungen"), ("/geraete", "Geräte"), ("/abgleich", "Vorschlagsabgleich"),
              ("/lernen", "Lernen"))

NAVIGATION_GROUPS = (
    ("Arbeitsbereich", ("/", "/mails", "/abgleich")),
    ("Einblicke", ("/verlauf", "/berichte", "/auswertung", "/status")),
    ("Verwaltung", ("/einstellungen", "/lernen", "/geraete")),
)
NAVIGATION_ICONS = {
    "/": "M4 4h16v16H4z M8 12l3 3 5-6",
    "/mails": "M3 6h18v12H3z M3 6l9 7 9-7",
    "/abgleich": "M4 7h14l-3-3 M20 17H6l3 3 M18 7l-3 3 M6 17l3-3",
    "/verlauf": "M12 7v5l3 2 M4 4v5h5 M4 9a8 8 0 1 1 1 8",
    "/berichte": "M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6",
    "/auswertung": "M4 3v17h17 M8 16v-5 M13 16V6 M18 16v-8",
    "/status": "M3 12h4l3-7 4 14 3-7h4",
    "/einstellungen": "M4 7h16 M4 17h16 M9 4v6 M15 14v6",
    "/geraete": "M7 2h10v20H7z M10 18h4",
    "/lernen": "M3 5h8v15H3z M13 5h8v15h-8z M5 9h4 M15 9h4",
}


# 5.0.1: the phone bar at the bottom shows these routes; the others are under "Mehr".
TAB_BAR = ("/", "/mails", "/verlauf", "/status")
MORE_ICON = "M5 12h.01 M12 12h.01 M19 12h.01"

# Open decisions of the current request, set once by the session guard (5.0.1).
OPEN_DECISIONS: ContextVar[int] = ContextVar("open_decisions", default=0)
# 5.3.12: whether the current request shows the floating help chat button (settings pages).
HELP_BUTTON: ContextVar[bool] = ContextVar("help_button", default=False)
HELP_ICON = "M4 5h16v11H9l-5 4z M8 9h8 M8 12h5"


def shows_help_button(path: str) -> bool:
    """The settings area: every page below /einstellungen and the topics page."""
    return path == "/themen" or path == "/einstellungen" or path.startswith("/einstellungen/")


def _help_button() -> str:
    return ('<a class="help-fab" href="/hilfe" aria-label="Hilfschat öffnen" title="Hilfschat öffnen">'
            + _icon(HELP_ICON) + "</a>")


def _icon(path: str) -> str:
    return (f'<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f'<path d="{path}"/></svg>')


def _link(href: str, active: str | None, open_count: int) -> str:
    current = ' aria-current="page"' if href == active else ""
    badge = ""
    if href == "/" and open_count:
        current += ' aria-describedby="offen-zahl"'
        badge = f'<span class="nav-count" aria-hidden="true">{open_count}</span>'
    label = dict(NAVIGATION)[href]
    return f'<a href="{href}"{current}>{_icon(NAVIGATION_ICONS[href])}<span class="nav-label">{label}</span>{badge}</a>'


def _navigation(active: str | None) -> str:
    """Sidebar (from 900 px), phone bar with "Mehr" (below 900 px); both work without JavaScript."""
    open_count = OPEN_DECISIONS.get()
    groups = []
    for title, routes in NAVIGATION_GROUPS:
        links = "".join(_link(href, active, open_count) for href in routes)
        groups.append(f'<div class="nav-section"><p class="nav-section-label">{title}</p>{links}</div>')
    described = ""
    if open_count:
        noun = "offene Entscheidung" if open_count == 1 else "offene Entscheidungen"
        described = f'<span id="offen-zahl" hidden>{open_count} {noun}</span>'
    tabs = "".join(_link(href, active, open_count) for href in TAB_BAR)
    others = "".join(_link(href, active, open_count) for href, _label in NAVIGATION if href not in TAB_BAR)
    current = " has-current" if active is not None and active not in TAB_BAR else ""
    more = (f'<details class="tab-more{current}"><summary>{_icon(MORE_ICON)}<span class="nav-label">Mehr</span>'
            f'</summary><div class="tab-menu">{others}</div></details>')
    return (described + '<nav class="nav" aria-label="Hauptnavigation">' + "".join(groups) + "</nav>"
            + f'<nav class="tab-bar" aria-label="Schnellnavigation">{tabs}{more}</nav>')


def layout(title: str, content: str, *, active: str | None = None, signed_in: bool = True,
           refresh: int | None = None, fingerprint: str | None = None,
           state_url: str | None = None, before: str = "", after: str = "") -> str:
    """Page frame; *refresh* adds a no-JavaScript reload for pending commands.

    *before* and *after* are further sections at the start and end of ``main``.
    """
    navigation = ""
    if signed_in:
        navigation = _navigation(active)
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
<meta name="theme-color" content="#047857">
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
<body class="{"app-shell" if signed_in else "guest-shell"}"{data}>
<a class="skip-link" href="#inhalt">Zum Inhalt springen</a>
<header class="top">
<a class="brand" href="/"><img src="/static/icon-192.png" alt="" width="28" height="28">Mailhelp</a>
<span class="connection" id="verbindung" role="status" aria-live="polite" hidden></span>
{navigation}
</header>
<main id="inhalt">{before}
{content}
{after}</main>
{_help_button() if signed_in and HELP_BUTTON.get() else ""}
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
    "console": {"sent": "Der Code steht im aufrufenden Terminal von <code>mailhelp --pair</code> "
                        "(bei Docker: <code>docker compose exec mailhelp mailhelp --pair "
                        "--config-directory /config</code>).",
                "label": "Code aus der Mailhelp-Konsole",
                "intro": "Am lokalen Host mailhelp --pair starten und den Einmalcode hier eingeben.",
                "button": "Code in der Konsole anzeigen", "again": "Neuen Code anzeigen"},
}


def login_page(csrf: str, code_requested: bool, error: str | None = None,
               code: str = "", channel: str = "telegram", password_available: bool = False) -> str:
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
    body += ('<details><summary>Code aus dem Terminal verwenden</summary>'
             '<p>Am Host <code>mailhelp --pair</code> ausführen; bei Docker '
             '<code>docker compose exec mailhelp mailhelp --pair --config-directory /config</code>. '
             'Der Code funktioniert auch ohne Telegram.</p></details>')
    if password_available:
        body += (f'<form method="post" action="/anmelden/passwort" class="stack">'
                 f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                 '<label for="password">Web-Passwort</label>'
                 '<input id="password" type="password" name="password" maxlength="1024" '
                 'autocomplete="current-password" required><button type="submit">Anmelden</button></form>')
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
    content += '<p><a href="/einstellungen/web-passwort">Web-Passwort festlegen oder ändern</a></p>'
    return layout("Geräte", content, active="/geraete")


def error_page(title: str, text: str, *, signed_in: bool = True) -> str:
    return layout(title, f"""<section class="card narrow">
<h1>{e(title)}</h1>
{notice(text, "error")}
<p><a class="button" href="/">Zur Übersicht</a></p>
</section>""", signed_in=signed_in)


__all__ = ["HELP_BUTTON", "NAVIGATION", "OPEN_DECISIONS", "TAB_BAR", "devices_page", "e", "error_page", "layout",
           "login_page", "notice"]
