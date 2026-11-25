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
        # Topics and sender rules. Learning (/lernen, /themen/lernen) and reports (/berichte) still show
        # budgets and estimates in money; they follow once they show points (Planung 8.7, AP4).
        ("GET", r"/themen|/themen/(?:relevant|ausschluss)/[a-z0-9_-]{1,64}|/themen/entwurf/[a-f0-9]{64}"),
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
        # Own devices, password and sign-out
        ("GET POST", r"/geraete(?:/.*)?|/einstellungen/web-passwort"),
        ("POST", r"/abmelden"),
        # Help: product documentation and the help chat (its calls count as usage)
        ("GET POST", r"/hilfe(?:/.*)?"),
        ("GET", r"/api/hilfe/(?:fenster|auftrag/[a-f0-9]{32})"),
        # Usage in points
        ("GET", r"/verbrauch"),
    )
)


def customer_may(method: str, path: str) -> bool:
    """Whether a customer session may call ``method path`` at all."""
    return any(method in methods and pattern.fullmatch(path) for methods, pattern in CUSTOMER_ROUTES)


__all__ = ["CUSTOMER_ROUTES", "customer_may"]
