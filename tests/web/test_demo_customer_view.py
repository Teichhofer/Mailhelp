"""8.8.5 (Planung 8.8 AP5/AP6, Abnahme 9–11): the demo shows the customer interface, deny by default.

Regression: until 8.8.4 a visitor got the operator frame and reached /status, /abgleich and /auswertung,
the settings overview linked operator areas, and the demo blocked routes from a list of exceptions, so a
new route (e.g. /einstellungen/allgemein in 8.8.2) was open until someone added it. Synthetic dataset only.
"""
from __future__ import annotations

import html
import re
import shutil

import pytest

from mailhelp.app import demo
from mailhelp.config import WebSettings
from mailhelp.persistence.storage import JsonStore
from mailhelp.runtime.demo_dataset import packaged
from mailhelp.web.http import Request
from mailhelp.web.permissions import customer_may
from tests.fakes.demo_web import HOST, Log, start

OPERATOR = ("/status", "/abgleich", "/auswertung", "/einrichtung", "/diagnose", "/einstellungen/zugangsdaten")
INTERNALS = ("USD", "Wechselkurs", ".env", "OPENROUTER", "Aufschlag", "markup")


@pytest.fixture
def instance(tmp_path):
    shutil.copytree(packaged(), tmp_path / "dataset")
    with JsonStore(tmp_path / "data" / "demo") as store:
        server, runtimes = demo.create_demo(tmp_path, store, WebSettings(enabled=True, allowed_hosts=[HOST]),
                                            "s" * 40, Log())
        runtimes.visitors.dataset = tmp_path / "dataset"
        yield server.handler, runtimes, store, tmp_path
        runtimes.close()


def get(site, href, jar, method="GET"):
    path, _, query = href.partition("?")
    headers = {"host": HOST, "cookie": "; ".join(f"{name}={value}" for name, value in jar.items())}
    return site(Request(method, path, headers, query=query))


def visitor(site, language):
    _response, jar = start(site, {"mailhelp_lang": language} if language == "en" else None)
    return jar


def test_regression_visitors_are_customers_with_the_customer_frame(instance):
    site, runtimes, _store, _tmp = instance
    jar = visitor(site, "de")
    session = runtimes.auth.authenticate(jar["mh_session"])
    assert session.role == "customer" and session.instance == "demo"
    home = get(site, "/", jar).body.decode()
    assert 'href="/verbrauch"' in home  # customer navigation
    assert not any(f'href="{path}"' in home for path in OPERATOR)
    for path in OPERATOR:
        refused = get(site, path, jar)
        assert refused.status == 403 and "In der Demo nicht verfügbar" in refused.body.decode(), path
        assert not any(f'href="{other}"' in refused.body.decode() for other in OPERATOR)


@pytest.mark.parametrize(("language", "hint"), [
    ("de", "In deiner eigenen Mailhelp-Instanz verfügbar – in der Demo deaktiviert."),
    ("en", "Available in your own Mailhelp instance – disabled in the demo.")])
def test_acceptance_9_settings_show_info_cards_without_links_to_closed_areas(instance, language, hint):
    site, *_rest = instance
    jar = visitor(site, language)
    page = get(site, "/einstellungen", jar).body.decode()
    assert page.count(hint) >= 6  # mailboxes, targets, topics, senders, notifications, devices, password, …
    assert 'href="/lernen"' in page and 'href="/verbrauch"' in page
    for closed in ("/einstellungen/postfaecher", "/einstellungen/zielprofile", "/einstellungen/allgemein",
                   "/geraete", "/einstellungen/web-passwort", "/benachrichtigungen"):
        assert f'href="{closed}"' not in page, closed
    assert "help-window" not in page and "/hilfe/frage" not in page  # no help chat in the demo


@pytest.mark.parametrize("language", ["de", "en"])
def test_acceptance_11_every_link_and_form_of_the_demo_works(instance, language):
    from mailhelp.web.demo_site import demo_may
    site, *_rest = instance
    jar = visitor(site, language)
    seen, todo, broken = set(), ["/", "/einstellungen", "/status"], []
    while todo and len(seen) < 400:
        href = todo.pop()
        if href in seen:
            continue
        seen.add(href)
        response = get(site, href, jar)
        if response.status >= 400 and href != "/status":
            broken.append((href, response.status))
            continue
        body = response.body.decode("utf-8", "replace")
        if response.content_type.startswith("text/html"):
            assert not any(word in body for word in INTERNALS), href
        for action in re.findall(r'<form method="post" action="([^"]+)"', body):
            action = html.unescape(action)
            if action != "/demo/neu-starten" and not demo_may("POST", action):
                broken.append(("form " + href.split("?")[0], action))
        todo += [html.unescape(link) for link in re.findall(r'<a\b[^>]*?href="(/[^"#]*)', body)
                 if not link.startswith("/static") and html.unescape(link) not in seen]
    assert len(seen) > 50 and broken == []


def test_demo_routes_are_a_subset_of_the_customer_routes(instance):
    from mailhelp.web.demo_site import DEMO_INSTANCE, demo_may, demo_may_link
    assert DEMO_INSTANCE == "demo"
    site, runtimes, *_rest = instance
    jar = visitor(site, "de")
    app = runtimes.app(runtimes.auth.authenticate(jar["mh_session"]).id)
    assert app is not None
    samples = {r"(?P<number>[1-9][0-9]?)": "1", r"(?P<mail_id>[a-f0-9]{24})": "a" * 24}
    checked = 0
    for method, path in (("GET", "/"), ("GET", "/mails"), ("POST", "/aktion"), ("GET", "/lernen"),
                         ("GET", "/verbrauch"), ("GET", "/einstellungen")):
        assert demo_may(method, path) and customer_may(method, path)
    for method, pattern in (("GET", r"/einstellungen/allgemein"), ("POST", r"/einstellungen/allgemein"),
                            ("GET", r"/google/verbinden"), ("GET", r"/einstellungen/neustarten"),
                            ("POST", r"/einstellungen/verbindungen/pruefen"), ("POST", r"/themen/speichern"),
                            ("GET", r"/hilfe"), ("POST", r"/lernen"), ("GET", "/status")):
        for regex, value in samples.items():
            pattern = pattern.replace(regex, value)
        checked += 1
        assert not demo_may(method, pattern), pattern
    assert checked == 9
    # Every route the demo allows is also a customer route (the demo only removes, never adds).
    for path in ("/", "/offen", "/mails", "/verlauf", "/briefing", "/lernen", "/verbrauch", "/einstellungen",
                 "/api/stand", "/lernen/vorschlaege"):
        assert not demo_may("GET", path) or customer_may("GET", path), path
    assert demo_may_link("/sprache?wert=en") and demo_may_link("/demo/neu-starten#x")
    assert not demo_may_link("/geraete")


def test_an_earlier_visitor_session_without_a_role_ends_at_the_next_start(tmp_path):
    shutil.copytree(packaged(), tmp_path / "dataset")
    with JsonStore(tmp_path / "data" / "demo") as store:
        from mailhelp.web.auth import WebAuth
        old = WebAuth(store, "s" * 40, 1, lambda text: None).demo_session("Demo")  # as written by 8.8.4
        server, runtimes = demo.create_demo(tmp_path, store, WebSettings(enabled=True, allowed_hosts=[HOST]),
                                            "s" * 40, Log())
        try:
            assert runtimes.auth.authenticate(old) is None
            assert get(server.handler, "/mails", {"mh_session": old}).headers["Location"] == "/anmelden"
        finally:
            runtimes.close()


def test_acceptance_9_the_demo_usage_is_a_fixed_example_in_points(instance):
    """8.8.6: until 8.8.5 the demo said that usage recording was not set up."""
    site, *_rest = instance
    pages = {}
    for language in ("de", "en"):
        body = get(site, "/verbrauch", visitor(site, language)).body.decode()
        assert not any(word in body for word in ("USD", "EUR", "Wechselkurs", "exchange rate", "nicht eingerichtet"))
        pages[language] = re.findall(r"<td>([^<]+)</td>", body)
    assert "Beispielwerte der Demo" in get(site, "/verbrauch", visitor(site, "de")).body.decode()
    assert pages["de"][0] == "54,00 Punkte" and len(pages["de"]) == len(pages["en"]) == 8
    assert [value.replace(",", ".").split()[0] for value in pages["de"]] == [value.split()[0] for value in pages["en"]]
