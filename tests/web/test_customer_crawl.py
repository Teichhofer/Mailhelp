"""8.8.6 (Planung 8.8 AP7, Abnahme 11): every page a customer session reaches, in German and English.

No rendered link leads to 403 or 404, every form posts to a customer route, and no page shows operator
details (prices, exchange rates, credential files, model provider keys). Synthetic configuration only.
"""
from __future__ import annotations

import html
import re

import pytest

from mailhelp.web.factory import WebComponents
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import signed_in

INTERNALS = ("USD", "Wechselkurs", "exchange rate", ".env", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN",
             "Aufschlag", "markup")
START = ("/", "/einstellungen", "/einstellungen/postfaecher", "/einstellungen/zielprofile", "/verbrauch",
         "/lernen", "/themen", "/hilfe")


@pytest.fixture
def customer(profiled):
    web = profiled.web
    web.auth.enter_customer_mode("kunde-a")
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    profiled.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    # As in the composition: the connection flows and the learning run are part of the running site.
    from types import SimpleNamespace

    from mailhelp.app.browser_accounts import attach_accounts
    profiled.app.services = SimpleNamespace()
    attach_accounts(profiled.app, web.site, profiled.tmp_path)
    from contextlib import nullcontext

    from mailhelp.runtime.learning_worker import LearningWorker
    from mailhelp.web.learning_site import LearningSite
    LearningSite(web.site, LearningWorker(profiled.app, web.site, None, lambda *_: nullcontext()))
    return profiled


@pytest.mark.parametrize("language", ["de", "en"])
def test_acceptance_11_customer_pages_link_only_to_reachable_pages(customer, language):
    web = customer.web
    browser = signed_in(web)
    browser.cookies["mailhelp_lang"] = language
    seen, todo, broken = set(), list(START), []
    while todo and len(seen) < 400:
        href = todo.pop()
        if href in seen:
            continue
        seen.add(href)
        response = browser.request("GET", href)
        if response.status in (403, 404):
            broken.append((href, response.status))
            continue
        if not response.content_type.startswith("text/html"):
            continue
        body = response.body.decode("utf-8", "replace")
        assert not any(word in body for word in INTERNALS), (href, [word for word in INTERNALS if word in body])
        for action in re.findall(r'<form method="post" action="([^"]+)"', body):
            if not customer_may("POST", html.unescape(action)):
                broken.append(("form " + href, action))
        for link in re.findall(r'<a\b[^>]*?href="(/[^"#]*)', body):
            link = html.unescape(link)
            if not link.startswith(("/static", "/sprache")) and link not in seen:
                todo.append(link)
    assert len(seen) > 40 and broken == []
