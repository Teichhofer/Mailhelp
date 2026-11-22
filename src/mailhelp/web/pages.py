"""Server-rendered HTML pages.

Every value from mails, LLM output or users is escaped with :func:`e`; links
from mails are shown as text.  Pages work without JavaScript; ``app.js`` only
adds the connection indicator and the automatic refresh.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from datetime import datetime
from types import MappingProxyType

from ..formatting import format_datetime_local
from ..i18n import Locale, current, heading, msg, stored, tr
from .auth import WebSession
from .js_texts import messages


def e(value: object) -> str:
    """Escape any value for HTML text and attribute positions."""
    return html.escape(str(value), quote=True)


NAVIGATION = (
    ("/", "Offen"),
    ("/mails", "Mails"),
    ("/verlauf", msg("Verlauf")),
    ("/status", "Status"),
    ("/auswertung", msg("Auswertung")),
    ("/berichte", msg("Berichte")),
    ("/einstellungen", msg("Einstellungen")),
    ("/geraete", msg("Geräte")),
    ("/abgleich", msg("Vorschlagsabgleich")),
    ("/lernen", msg("Lernen")),
)

NAVIGATION_GROUPS = (
    (msg("Arbeitsbereich"), ("/", "/mails", "/abgleich")),
    (msg("Einblicke"), ("/verlauf", "/berichte", "/auswertung", "/status")),
    (msg("Verwaltung"), ("/einstellungen", "/lernen", "/geraete")),
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
# 6.2.8 (E3): the reconciliation is daily work and takes the place of the status page.
TAB_BAR = ("/", "/mails", "/abgleich", "/verlauf")
# Labels that would not fit a fifth of a 320 px phone bar.
TAB_LABELS = {"/abgleich": msg("Abgleich")}
MORE_ICON = "M5 12h.01 M12 12h.01 M19 12h.01"

# Open decisions of the current request, set once by the session guard (5.0.1).
OPEN_DECISIONS: ContextVar[int] = ContextVar("open_decisions", default=0)
ASSET_URLS: ContextVar[Mapping[str, str]] = ContextVar("asset_urls", default=MappingProxyType({}))
# 7.0.12: the page scripts by area; deferred, so they run in this order after parsing.
PAGE_SCRIPTS = ("app.js", "open-list.js", "dialogs.js", "push.js", "settings.js", "help.js")
# 5.3.12: whether the current request shows the floating help chat button (settings pages).
HELP_BUTTON: ContextVar[bool] = ContextVar("help_button", default=False)
HELP_WINDOW: ContextVar[Callable[[], str] | None] = ContextVar("help_window", default=None)
HELP_ICON = "M4 5h16v11H9l-5 4z M8 9h8 M8 12h5"


def shows_help_button(path: str) -> bool:
    """The settings area: every page below /einstellungen and the topics page."""
    return (path in {"/themen", "/lernen", "/einrichtung", "/diagnose", "/geraete", "/benachrichtigungen",
                     "/hilfe/frage", "/hilfe/leeren", "/hilfe/fenster"}
            or path.startswith(("/einstellungen/", "/themen/", "/lernen/", "/dienst/", "/einrichtung/", "/aktion/"))
            or path == "/einstellungen")


def _help_button() -> str:
    return (f'<a class="help-fab" href="/hilfe" aria-label="{tr("Hilfschat öffnen")}" title="{tr("Hilfschat öffnen")}">'
            + _icon(HELP_ICON) + "</a>")


def _icon(path: str) -> str:
    return (f'<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            f'<path d="{path}"/></svg>')


def _link(href: str, active: str | None, open_count: int, *, tab: bool = False) -> str:
    current = ' aria-current="page"' if href == active else ""
    badge = ""
    if href == "/" and open_count:
        current += msg(' aria-describedby="offen-zahl"')
        badge = f'<span class="nav-count" aria-hidden="true">{open_count}</span>'
    label = heading(TAB_LABELS.get(href, dict(NAVIGATION)[href]) if tab else dict(NAVIGATION)[href])
    return f'<a href="{href}"{current}>{_icon(NAVIGATION_ICONS[href])}<span class="nav-label">{label}</span>{badge}</a>'


def _navigation(active: str | None) -> tuple[str, str]:
    """Sidebar (from 900 px), phone bar with "Mehr" (below 900 px); both work without JavaScript."""
    open_count = OPEN_DECISIONS.get()
    groups = []
    for title, routes in NAVIGATION_GROUPS:
        links = "".join(_link(href, active, open_count) for href in routes)
        groups.append(f'<div class="nav-section"><p class="nav-section-label">{tr(title)}</p>{links}</div>')
    described = ""
    if open_count:
        noun = tr("offene Entscheidung") if open_count == 1 else tr("offene Entscheidungen")
        described = f'<span id="offen-zahl" hidden>{open_count} {noun}</span>'
    tabs = "".join(_link(href, active, open_count, tab=True) for href in TAB_BAR)
    others = "".join(_link(href, active, open_count) for href, _label in NAVIGATION if href not in TAB_BAR)
    current = " has-current" if active is not None and active not in TAB_BAR else ""
    more = (f'<details class="tab-more{current}"><summary>{_icon(MORE_ICON)}<span class="nav-label">{tr("Mehr")}</span>'
            f'</summary><div class="tab-menu">{others}{_language_switch()}</div></details>')
    return (described + f'<nav class="nav" aria-label="{tr("Hauptnavigation")}">' + "".join(groups)
            + _language_switch() + "</nav>",
            f'<nav class="tab-bar" aria-label="{tr("Schnellnavigation")}">{tabs}{more}</nav>')


def _language_switch() -> str:
    """7.5: the other language as a link; it keeps the page and works without JavaScript."""
    other, name = (Locale.DE, "Deutsch") if current() == Locale.EN else (Locale.EN, "English")
    return (f'<p class="nav-language"><a href="/sprache?wert={other.value}" lang="{other.value}" '
            f'hreflang="{other.value}">{tr(name)}</a></p>')


def page_head(title: str, section: str, intro: str = "", *, count: str = "",
              back: tuple[str, str] | None = None) -> str:
    """6.2.2: the one page head – where (*section*), what (*title*), why (*intro*).

    *count* is trusted markup shown after the title; tool rows and filters follow the head.
    """
    link = f'<p class="page-back"><a href="{e(back[0])}">← {e(back[1])}</a></p>' if back else ""
    return (f'<div class="page-heading">{link}<p class="eyebrow">{e(section)}</p><h1>{e(title)}{count}</h1>'
            + (f'<p class="page-intro">{e(intro)}</p>' if intro else "") + "</div>")


def _scripts() -> str:
    urls = ASSET_URLS.get()
    return "\n".join(f'<script src="{urls.get(name, "/static/" + name)}" defer></script>' for name in PAGE_SCRIPTS)


def layout(title: str, content: str, *, active: str | None = None, signed_in: bool = True,
           refresh: int | None = None, fingerprint: str | None = None,
           state_url: str | None = None, before: str = "", after: str = "", wide: bool = False) -> str:
    """Page frame; *refresh* adds a no-JavaScript reload for pending commands.

    *before* and *after* are further sections at the start and end of ``main``; *wide* selects the
    second of the two page widths (6.2.2) for tables and side-by-side comparisons.
    """
    navigation = tab_bar = ""
    if signed_in:
        navigation, tab_bar = _navigation(active)
    else:
        navigation = _language_switch()
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    data = f' data-ui-texts="{e(messages(current()))}"'
    data += f' data-fingerprint="{e(fingerprint)}"' if fingerprint else ""
    if state_url:
        # Pages with their own refresh signal (e.g. the status page).
        data += f' data-state-url="{e(state_url)}"'
    window = HELP_WINDOW.get()
    widget = window() if signed_in and window is not None else ""
    return f"""<!doctype html>
<html lang="{current().value}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#047857">
{meta_refresh}<title>{e(title)} · Mailhelp</title>
<link rel="stylesheet" href="{ASSET_URLS.get().get("app.css", "/static/app.css")}">
<link rel="manifest" href="/manifest{"-en" if current() == Locale.EN else ""}.webmanifest">
<link rel="icon" href="/static/icon-192.png" type="image/png">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Mailhelp">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
{_scripts()}
</head>
<body class="{"app-shell" if signed_in else "guest-shell"}"{data}>
<a class="skip-link" href="#inhalt">{tr("Zum Inhalt springen")}</a>
<header class="top">
<a class="brand" href="/"><img src="/static/icon-192.png" alt="" width="28" height="28">Mailhelp</a>
<span class="connection" id="verbindung" role="status" aria-live="polite" hidden></span>
{navigation}
</header>
<main id="inhalt"{' class="page-wide"' if wide else ""}>{before}
{content}
{after}</main>
{tab_bar}
{widget or (_help_button() if signed_in and HELP_BUTTON.get() else "")}
</body>
</html>
"""


def notice(text: str, kind: str = "info") -> str:
    role = "alert" if kind == "error" else "status"
    # 7.5.4: result messages are stored in German and shown in the reader's language.
    return f'<p class="notice notice-{kind}" role="{role}">{e(stored(text))}</p>'


# Where pairing codes appear: the Telegram chat or, without Telegram (2.0), the PC console.
LOGIN_CHANNELS = {
    "telegram": {
        "sent": msg("Der Code wurde an deinen Telegram-Chat gesendet."),
        "label": msg("Code aus Telegram"),
        "intro": msg("Mailhelp sendet dir einen einmaligen Code in deinen Telegram-Chat."),
        "button": msg("Code per Telegram senden"),
        "again": msg("Neuen Code senden"),
    },
    "console": {
        "sent": msg(
            "Der Code steht im aufrufenden Terminal von <code>mailhelp --pair</code> "
            "(bei Docker: <code>docker compose exec mailhelp mailhelp --pair "
            "--config-directory /config</code>)."
        ),
        "label": msg("Code aus der Mailhelp-Konsole"),
        "intro": msg("Am lokalen Host mailhelp --pair starten und den Einmalcode hier eingeben."),
        "button": msg("Code in der Konsole anzeigen"),
        "again": msg("Neuen Code anzeigen"),
    },
}


def login_page(csrf: str, code_requested: bool, error: str | None = None,
               code: str = "", channel: str = "telegram", password_available: bool = False) -> str:
    """Login; *code* pre-fills the field when the page was opened from the /web link."""
    message = notice(error, "error") if error else ""
    text = LOGIN_CHANNELS[channel]
    if code_requested or code:
        body = tr(
            (
                '<p>{p0} Er gilt 10 Minuten.</p>\n<form method="post" action="/anmelden" '
                'class="stack">\n<input type="hidden" name="csrf" value="{p1}">\n<label '
                'for="code">{p2}</label>\n<input id="code" name="code" inputmode="numeric" '
                'autocomplete="one-time-code" pattern="[0-9 ]{{4,5}}"\n maxlength="5" '
                'required autofocus value="{p3}">\n<label for="geraet">Gerätename <span '
                'class="hint">(optional)</span></label>\n<input id="geraet" name="geraet" '
                'maxlength="60" autocomplete="off" placeholder="z. B. iPhone">\n<button '
                'class="button primary" type="submit">Gerät koppeln</button>\n</form>\n<form '
                'method="post" action="/anmelden/code" class="secondary-form">\n<input '
                'type="hidden" name="csrf" value="{p4}">\n<button class="button link" '
                'type="submit">{p5}</button>\n</form>'
            ),
            p0=f"{text['sent']}",
            p1=f"{e(csrf)}",
            p2=f"{text['label']}",
            p3=f"{e(code)}",
            p4=f"{e(csrf)}",
            p5=f"{text['again']}",
        )
    else:
        body = tr(
            (
                '<p>Dieses Gerät ist noch nicht gekoppelt. {p0}</p>\n<form method="post" '
                'action="/anmelden/code" class="stack">\n<input type="hidden" name="csrf" '
                'value="{p1}">\n<button class="button primary" type="submit">{p2}</button>\n</form>'
            ),
            p0=f"{text['intro']}",
            p1=f"{e(csrf)}",
            p2=f"{text['button']}",
        )
    body += tr(
        
            "<details><summary>Code aus dem Terminal verwenden</summary><p>Am Host "
            "<code>mailhelp --pair</code> ausführen; bei Docker <code>docker compose "
            "exec mailhelp mailhelp --pair --config-directory /config</code>. Der Code "
            "funktioniert auch ohne Telegram.</p></details>"
        
    )
    if password_available:
        body += tr(
            (
                '<form method="post" action="/anmelden/passwort" class="stack"><input '
                'type="hidden" name="csrf" value="{p0}"><label '
                'for="password">Web-Passwort</label><input id="password" type="password" '
                'name="password" maxlength="1024" autocomplete="current-password" '
                'required><button type="submit">Anmelden</button></form>'
            ),
            p0=f"{e(csrf)}",
        )
    return layout(
        tr("Anmelden"),
        tr(
            '<section class="card narrow">\n<h1>Gerät koppeln</h1>\n{p0}{p1}\n</section>', p0=f"{message}", p1=f"{body}"
        ),
        signed_in=False,
    )


def _local(value: datetime, configured_timezone: str) -> str:
    return format_datetime_local(value, configured_timezone)


def devices_page(sessions: list[WebSession], current: WebSession, csrf: str,
                 configured_timezone: str, message: str | None = None) -> str:
    rows = []
    for session in sessions:
        own = session.id == current.id
        label = tr(' <span class="badge">dieses Gerät</span>') if own else ""
        # 5.4.1: forms that end this browser's session also erase its local help draft.
        ends = " data-ends-session" if own else ""
        rows.append(
            tr(
                (
                    '<li class="device">\n<div><strong>{p0}</strong>{p1}<br>\n<span '
                    'class="meta">Zuletzt aktiv: {p2} ·\ngültig bis {p3}</span></div>\n<form '
                    'method="post" action="/geraete/{p4}/abmelden"{p5}>\n<input type="hidden" '
                    'name="csrf" value="{p6}">\n<button class="button danger small" '
                    'type="submit">Abmelden</button>\n</form>\n</li>'
                ),
                p0=f"{e(session.device)}",
                p1=f"{label}",
                p2=f"{e(_local(session.last_used_at, configured_timezone))}",
                p3=f"{e(_local(session.expires_at, configured_timezone))}",
                p4=f"{e(session.id)}",
                p5=f"{ends}",
                p6=f"{e(csrf)}",
            )
        )
    content = page_head(msg("Geräte"), msg("Verwaltung"), msg("Browser, die mit Mailhelp gekoppelt sind.")) + tr(
        (
            '\n{p0}\n<ul class="devices">{p1}</ul>\n<form method="post" '
            'action="/geraete/alle-abmelden" class="stack" data-ends-session>\n<input '
            'type="hidden" name="csrf" value="{p2}">\n<button class="button danger" '
            'type="submit">Alle Geräte abmelden</button>\n</form>\n<p class="meta">Auch '
            "per Telegram: <code>/web_abmelden</code> meldet alle Geräte ab.</p>"
        ),
        p0=f"{(notice(message) if message else '')}",
        p1=f"{''.join(rows)}",
        p2=f"{e(csrf)}",
    )
    content += tr('<p><a href="/einstellungen/web-passwort">Web-Passwort festlegen oder ändern</a></p>')
    return layout(msg("Geräte"), content, active="/geraete")


def error_page(title: str, text: str, *, signed_in: bool = True) -> str:
    return layout(
        title,
        tr(
            (
                '<section class="card narrow">\n<h1>{p0}</h1>\n{p1}\n<p><a class="button" '
                'href="/">Zur Übersicht</a></p>\n</section>'
            ),
            p0=f"{e(title)}",
            p1=f"{notice(text, 'error')}",
        ),
        signed_in=signed_in,
    )


__all__ = ["HELP_BUTTON", "NAVIGATION", "OPEN_DECISIONS", "TAB_BAR", "devices_page", "e", "error_page", "layout",
           "login_page", "notice", "page_head"]
