"""7.9.2: the warning area for sign-in problems above the open decisions and the mail list.

It names service, affected mailbox or target profile, the effect, the time of the last failed
check and the setup page that fixes it. It only shows the stored status; it never signs in,
changes configuration or calls a provider, and it exists only behind the web sign-in.
"""
from __future__ import annotations

from collections.abc import Iterable
from zoneinfo import ZoneInfo

from ..i18n import msg, tr
from ..i18n.formatting import day_time
from ..support.connection_health import OAUTH, WRITERS, ConnectionProblem
from .pages import e

_TASKS = {"todoist", "google_tasks", "caldav_tasks", "apple_reminders", "microsoft_todo", "notion"}
_SIGN_IN_EFFECT = msg("Abgleich und Änderungen der damit verbundenen Kalender und Aufgabenlisten sind derzeit "
                      "nicht möglich.")
_CALENDAR_EFFECT = msg("Kalenderabgleich und Kalenderänderungen sind derzeit nicht möglich.")
_TASK_EFFECT = msg("Abgleich und Anlage von Aufgaben sind derzeit nicht möglich.")
_MAIL_EFFECT = msg("Neue Mails dieses Postfachs werden derzeit nicht abgerufen.")
_ISERV_EFFECT = msg("Neue Elternbriefe werden derzeit nicht abgerufen.")
# A refused renewal or sign-in is named as such; whether a token expired or was revoked is not known.
_CODES = {"refresh_denied": msg("Anmeldung fehlgeschlagen."), "login_rejected": msg("Anmeldung abgelehnt."),
          "permission_denied": msg("Zugriff verweigert – eine nötige Berechtigung fehlt.")}


def _service(problem: ConnectionProblem) -> tuple[str, str, str]:
    """(name, effect, setup page) of the connection."""
    if problem.service == "imap":
        name = tr("Postfach {number}", number=problem.number) if problem.number else tr("Postfach")
        return name, str(_MAIL_EFFECT), "/einstellungen/postfaecher"
    if problem.service == "iserv":
        return tr("IServ-Konto {number}", number=problem.number), str(_ISERV_EFFECT), "/einstellungen/iserv"
    if problem.service in OAUTH:
        return tr(OAUTH[problem.service]), str(_SIGN_IN_EFFECT), "/einstellungen/zielprofile"
    name = tr(WRITERS[problem.service])
    if problem.number is not None and problem.number > 1:
        name = tr("{service} (Zielprofil {number})", service=name, number=problem.number)
    effect = _TASK_EFFECT if problem.service in _TASKS else _CALENDAR_EFFECT
    return name, str(effect), "/einstellungen/zielprofile"


def connection_warnings(problems: Iterable[ConnectionProblem], timezone: str, *, hosted_google: bool = False,
                        mailbox_auth: dict[int, str] | None = None) -> str:
    """One warning per affected connection; nothing at all while every used connection signs in.

    8.0: with the hosted Google sign-in, a Google problem leads straight to "Google erneut verbinden".
    """
    items = []
    zone = ZoneInfo(timezone)
    for problem in problems:
        name, effect, link = _service(problem)
        action = tr("Verbindung prüfen")
        if hosted_google and problem.service in {"google_oauth", "google_calendar"}:
            link, action = f"/google/verbinden?profile={problem.number or 1}", tr("Google erneut verbinden")
        if hosted_google and problem.service in {"microsoft_oauth", "outlook_calendar", "microsoft_todo"}:
            link, action = f"/microsoft/verbinden?profile={problem.number or 1}", tr("Microsoft erneut verbinden")
        if hosted_google and problem.service == "notion":
            link, action = f"/notion/verbinden?profile={problem.number or 1}", tr("Notion erneut verbinden")
        method = (mailbox_auth or {}).get(problem.number or 0)
        if problem.service == "imap" and method in {"gmail", "microsoft"}:
            link = f"/postfach/oauth?provider={method}&mailbox={problem.number}"
            action = tr("Postfach erneut verbinden")
        when = tr("Zuletzt fehlgeschlagen: {when}.", when=day_time(problem.last_seen.astimezone(zone)))
        items.append(
            f'<li class="connection-warning"><span class="icon" aria-hidden="true">⚠️</span> '
            f"<strong>{e(name)}: {e(_CODES[problem.code])}</strong> {e(effect)} {e(when)} "
            f'<a href="{e(link)}">{action}</a></li>')
    if not items:
        return ""
    heading = tr("Verbindungsprobleme")
    return (f'<section class="connection-warnings notice notice-warn" aria-labelledby="verbindungsprobleme">'
            f'<h2 id="verbindungsprobleme">{heading}</h2><ul>{"".join(items)}</ul></section>')


__all__ = ["connection_warnings"]
