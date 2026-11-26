"""8.7: what a customer session may reach in customer mode – everything else is operator only.

The list is explicit and deny-by-default: a route that is not named here (including every route added
later) is refused for customers before its handler runs, for GET and POST alike. Operator functions
keep their routes; they are simply not reachable with a customer session. Fields inside the settings
forms are limited separately (``config.customer_fields``), and queued commands are checked again
when they run.
"""

from __future__ import annotations

import re

_ID = r"[a-f0-9]{24}"
_PROPOSAL = r"/vorschlag/" + _ID + r"/[A-Za-z0-9_-]{1,64}(?:/.*)?"
_REPORT = r"/berichte/[a-f0-9]{32}"

# (methods, path) – matched against the full request path.
CUSTOMER_ROUTES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = tuple(
    (frozenset(methods.split()), re.compile(path)) for methods, path in (
        # Own mails, proposals, decisions and their history
        ("GET", r"/|/offen|/mails|/verlauf|/briefing|/api/stand"),
        ("GET POST", _PROPOSAL),
        ("GET", r"/mail/" + _ID + r"(?:/(?:anhang|original)/[0-9]{1,5})?"),
        ("POST", r"/mail/" + _ID + r"/(?:absender-ignorieren|absender-vip|absender-zulassen|domain-ignorieren"
                 r"|entwurf|nachanalyse(?:/[a-f0-9]{32}/(?:abbrechen|uebernehmen))?)"),
        ("GET POST", r"/mails/fehler/alle"),
        ("POST", r"/aktion"),
        ("GET", r"/(?:api/)?aktion/[a-f0-9]{32}"),
        ("POST", r"/aktion/[a-f0-9]{32}/gesehen"),
        ("GET", r"/status/(?:vorschlaege|relevanzfragen|web-aktionen)"),
        ("GET POST", r"/serie/.+"),
        # Topics and sender rules
        ("GET", r"/themen|/themen/(?:relevant|ausschluss)/[a-z0-9_-]{1,64}|/themen/entwurf/[a-f0-9]{64}"),
        # 8.7.7: activity reports of the instance's mailboxes, estimates in points only
        ("GET", r"/berichte|/berichte/neu|" + _REPORT + r"(?:/export\.xlsx)?"),
        ("POST", r"/berichte|" + _REPORT + r"/aktion"),
        ("GET POST", _REPORT + r"/mail/[0-9]{1,6}"),
        ("POST", r"/themen/(?:pruefen|speichern)"),
        ("GET POST", r"/einstellungen/(?:absender|ignorierte-absender)(?:/.*)?"),
        # Notifications and push
        ("GET POST", r"/(?:einstellungen/)?benachrichtigungen|/push/kanaele"),
        ("GET POST", r"/api/push/(?:public-key|status|subscribe|unsubscribe|test)"),
        # Own mailboxes and targets, with their connection flows (no generic credential editor)
        ("GET POST", r"/einstellungen/postfaecher(?:/.*)?"),
        ("GET POST", r"/einstellungen/zielprofile(?:/.*)?"),
        ("GET POST", r"/auth/(?:google|microsoft|notion)(?:/.*)?"),
        ("GET POST", r"/einrichtung/(?:google|microsoft|notion)(?:/.*)?"),
        # 8.7.7 (operator decision 26.11.2026): Notion data source and property mapping of own profiles
        ("GET POST", r"/notion/(?:datenquelle|zuordnung)"),
        # Own devices, password and sign-out
        ("GET POST", r"/geraete(?:/.*)?|/einstellungen/web-passwort"),
        ("POST", r"/abmelden"),
        # Help: product documentation and the help chat (its calls count as usage)
        ("GET POST", r"/hilfe(?:/.*)?"),
        ("GET", r"/api/hilfe/(?:fenster|auftrag/[a-f0-9]{32})"),
        # Usage in points; 8.7.6: the customer's own settings overview (only customer areas)
        ("GET", r"/verbrauch|/einstellungen"),
        # 8.7.4: learning shows points only; adoptions change only topics, sender rules and folders
        ("GET POST", r"/lernen|/lernen/postfach|/lernen/entscheidungen|/themen/lernen"),
        ("GET", r"/api/lernen|/api/lernen/uebersicht|/lernen/vorschlaege|/lernen/absender-hinweis"),
        ("POST", r"/lernen/absender-hinweis/(?:uebernehmen|nicht-mehr-vorschlagen|wieder-zulassen)"
                 r"|/lernen/hinweis-ausblenden"),
    )
)


# Routes without a session (language switch, sign-in); links to them work for everyone.
PUBLIC_LINKS = re.compile(r"/sprache|/(?:de|en)/|/anmelden(?:/.*)?")


def customer_may(method: str, path: str) -> bool:
    """Whether a customer session may call ``method path`` at all."""
    return any(method in methods and pattern.fullmatch(path) for methods, pattern in CUSTOMER_ROUTES)


def customer_may_link(href: str) -> bool:
    """Whether a local link (path with optional query or fragment) works in a customer session."""
    path = href.split("#", 1)[0].split("?", 1)[0]
    return bool(PUBLIC_LINKS.fullmatch(path)) or customer_may("GET", path)


__all__ = ["CUSTOMER_ROUTES", "PUBLIC_LINKS", "customer_may", "customer_may_link"]
