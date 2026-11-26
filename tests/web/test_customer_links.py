"""8.7.6 (AP4a): a customer session only ever sees links and forms it may use.

The audit follows every internal link of the reachable customer pages and fails for any link that
answers 403 ("Nur für den Betreiber") and for any form whose target a customer may not call.
"""
from __future__ import annotations

import re
from collections import defaultdict
from html import unescape
from urllib.parse import urlsplit

import pytest

from mailhelp.web.permissions import customer_may, customer_may_link
from tests.fakes.customer_mode import signed_in
from tests.fakes.shared_profiles import profiled  # noqa: F401  (fixture)
from tests.fakes.shared_setup import configured  # noqa: F401  (fixture)
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)

LINK = re.compile(r'<a\b[^>]*\bhref="([^"]*)"')
FORM = re.compile(r'<form\b([^>]*)>')
ATTRIBUTE = re.compile(r'\b(method|action)="([^"]*)"')
FORMACTION = re.compile(r'\bformaction="([^"]*)"')
START = ("/", "/mails", "/verlauf", "/themen", "/einstellungen", "/geraete", "/hilfe", "/verbrauch", "/lernen",
         "/einstellungen/postfaecher", "/einstellungen/postfaecher/1", "/einstellungen/zielprofile",
         "/einstellungen/absender", "/benachrichtigungen", "/einstellungen/web-passwort")


def internal(target: str) -> str | None:
    parts = urlsplit(unescape(target))
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or parts.path.startswith("/static/"):
        return None
    return parts.path + ("?" + parts.query if parts.query else "")


def audit(browser, start=START, limit=600, skip=("/hilfe/dokumentation/",)):
    """Pages visited and (page, method, target) of every link or form a customer cannot use."""
    seen: set[str] = set()
    queue, refused = list(start), set()
    referrers: dict[str, set[str]] = defaultdict(set)
    while queue and len(seen) < limit:
        path = queue.pop(0)
        if path in seen:
            continue
        seen.add(path)
        response = browser.request("GET", path)
        if response.status == 403:
            refused |= {(page, "GET", path) for page in referrers[path] or {"(start)"}}
            continue
        if response.status != 200 or not response.body.lstrip().startswith(b"<!doctype html>"):
            continue
        html = response.body.decode()
        for target in LINK.findall(html):
            link = internal(target)
            if link is not None and not customer_may_link(link):
                refused.add((path, "GET", link))  # even when the target page happens not to exist here
            elif link is not None:
                referrers[link].add(path)
                if link not in seen and not link.startswith(skip):
                    queue.append(link)
        for attributes in FORM.findall(html):
            values = dict(ATTRIBUTE.findall(attributes))
            action = internal(values.get("action") or path)
            method = values.get("method", "get").upper()
            if action is not None and not customer_may(method, urlsplit(action).path):
                refused.add((path, method, action))
        for target in FORMACTION.findall(html):
            action = internal(target)
            if action is not None and not customer_may("POST", urlsplit(action).path):
                refused.add((path, "POST", action))
    return sorted(refused), seen


@pytest.fixture
def customer(profiled):
    profiled.web.auth.enter_customer_mode("kunde-a")
    return profiled.web


def test_every_link_and_form_on_customer_pages_is_allowed_for_customers(customer):
    refused, seen = audit(signed_in(customer))
    assert refused == []
    assert {"/", "/einstellungen", "/verbrauch", "/einstellungen/postfaecher/1"} <= seen


@pytest.mark.parametrize("query", ["", "?bereich=zugangsdaten", "?suche=OPENROUTER", "?bereich=ki"])
def test_customers_get_their_own_settings_overview_whatever_the_address_asks_for(customer, query):
    browser = signed_in(customer)
    page = browser.request("GET", "/einstellungen" + query).body.decode()
    html = page[page.index("<main"):page.index("</main>")]  # the help chat only echoes its return address
    assert "Deine Bereiche." in html and 'href="/einstellungen/postfaecher"' in html
    assert "OPENROUTER" not in html and "zugangsdaten" not in html and "/einstellungen/speichern" not in html
    operator = signed_in(customer, "operator", "Support")
    assert "Deine Bereiche." not in operator.request("GET", "/einstellungen" + query).body.decode()


def test_operators_keep_the_full_navigation_and_their_links(customer):
    operator = signed_in(customer, "operator", "Support")
    html = operator.request("GET", "/einstellungen/postfaecher").body.decode()
    for href in ("/status", "/auswertung", "/berichte", "/abgleich", "/einstellungen/zugangsdaten"):
        assert f'href="{href}"' in html, href
    assert 'href="/verbrauch"' not in html  # the customer's page is not added to the operator navigation
    customer_html = signed_in(customer).request("GET", "/einstellungen/postfaecher").body.decode()
    assert 'href="/verbrauch"' in customer_html and 'href="/einstellungen/zugangsdaten"' not in customer_html


def test_the_frame_removes_customer_refused_links_and_their_separators():
    from mailhelp.web.pages import CUSTOMER_VIEW, customer_links, layout

    page = ('<p><a href="/diagnose">Diagnose</a> · <a href="/mails">Mails</a> · <a href="/status?x=1">S</a></p>'
            '<p><a href="/themen">T</a> · <a href="/dienst/neu-laden">N</a></p><a href="#x">Anker</a>'
            '<a href="/sprache?wert=en">English</a> <a href="https://example.test/">extern</a>'
            '<a class="b" href="/mail/000000000000000000000001?a=1&amp;b=2">M</a>')
    assert customer_links(page) == (
        '<p><a href="/mails">Mails</a></p><p><a href="/themen">T</a></p><a href="#x">Anker</a>'
        '<a href="/sprache?wert=en">English</a> <a href="https://example.test/">extern</a>'
        '<a class="b" href="/mail/000000000000000000000001?a=1&amp;b=2">M</a>')
    token = CUSTOMER_VIEW.set(True)
    try:
        assert 'href="/diagnose"' not in layout("T", page) and 'href="/diagnose"' in layout("T", page, signed_in=False)
    finally:
        CUSTOMER_VIEW.reset(token)
    assert 'href="/diagnose"' in layout("T", page) and 'href="/verbrauch"' not in layout("T", page)
