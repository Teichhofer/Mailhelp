"""7.1: the public pages of the demo instance; nothing here reaches a mailbox, Telegram or a model."""
from __future__ import annotations

from typing import Any

from ..persistence.storage import JsonStore
from .app import WebApp
from .http import Request, Response
from .pages import layout, notice

DEMO_NOTICE = "Demo – Beispieldaten. Es werden keine echten Termine oder Aufgaben angelegt."


def demo_login_page() -> str:
    body = (notice(DEMO_NOTICE, "info")
            + "<p>Diese Instanz zeigt Mailhelp mit vorbereiteten Beispielmails. Es wird kein Postfach, "
              "kein Telegram und kein Kalender verbunden.</p>"
            + '<p role="status">Der Beispielbestand wird in einer der nächsten Versionen ergänzt; bis dahin '
              "lässt sich die Demo noch nicht starten.</p>")
    return layout("Demo", f'<section class="card narrow">\n<h1>Gerät koppeln</h1>\n{body}\n</section>',
                  signed_in=False)


class DemoSite:
    def __init__(self, app: WebApp, store: JsonStore, secret: str, logger: Any) -> None:
        self.app, self.store, self.secret, self.logger = app, store, secret, logger
        app.route("GET", "/", lambda request: Response.redirect("/anmelden"))
        app.route("GET", "/anmelden", self.login)

    def login(self, request: Request) -> Response:
        return Response.html(200, demo_login_page())
