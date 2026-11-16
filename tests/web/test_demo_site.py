"""7.1 (D3, D4): "Demo starten" opens a private copy of the prepared dataset in the normal interface."""
from __future__ import annotations

import re
import shutil
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from mailhelp.app import demo
from mailhelp.config import WebSettings
from mailhelp.persistence.storage import JsonStore
from mailhelp.runtime.demo_dataset import packaged
from mailhelp.runtime.standalone import DisabledTelegram
from mailhelp.web.app import WebApp
from mailhelp.web.auth import WebAuth
from mailhelp.web.demo_site import DEMO_NOTICE, SESSION_SECONDS, DemoSite
from mailhelp.web.http import Request, Response

HOST = "localhost:8765"
FORM = "application/x-www-form-urlencoded"


class Log:
    def __init__(self):
        self.events = []

    def event(self, level, area, name, **fields):
        self.events.append(name)


@pytest.fixture
def instance(tmp_path):
    shutil.copytree(packaged(), tmp_path / "dataset")
    with JsonStore(tmp_path / "data" / "demo") as store:
        settings = WebSettings(enabled=True, allowed_hosts=[HOST])
        logger = Log()
        server, runtimes = demo.create_demo(tmp_path, store, settings, "s" * 40, logger)
        runtimes.visitors.dataset = tmp_path / "dataset"
        yield SimpleNamespace(site=server.handler, runtimes=runtimes, logger=logger, store=store, tmp=tmp_path)
        runtimes.close()


def request(method, path, cookies=None, form=None):
    headers = {"host": HOST}
    if cookies:
        headers["cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
    body = b""
    if form is not None:
        headers["content-type"] = FORM
        body = urlencode(form).encode("utf-8")
    return Request(method, path, headers, body=body)


def cookies_of(response, jar):
    for header in response.cookies:
        name, _, rest = header.partition("=")
        jar[name] = rest.split(";", 1)[0]
    return jar


def open_login(site, jar):
    page = site(request("GET", "/anmelden", jar))
    cookies_of(page, jar)
    text = page.body.decode("utf-8")
    return page, re.search(r'name="csrf" value="([^"]+)"', text).group(1), re.search(r'name="key" value="([^"]+)"',
                                                                                    text).group(1)


def start(site, jar=None):
    jar = {} if jar is None else jar
    _page, csrf, key = open_login(site, jar)
    response = site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key}))
    cookies_of(response, jar)
    return response, jar


def test_the_login_page_offers_only_the_demo_start(instance):
    page, _csrf, _key = open_login(instance.site, {})
    text = page.body.decode("utf-8")
    assert page.status == 200 and "Gerät koppeln" in text and DEMO_NOTICE in text and "Demo starten" in text
    assert "Telegram senden" not in text and "--pair" not in text and 'type="password"' not in text


def test_a_start_opens_the_own_copy_and_keeps_it(instance):
    response, jar = start(instance.site)
    assert response.status == 303 and response.headers["Location"] == "/"
    assert f"Max-Age={SESSION_SECONDS}" in next(item for item in response.cookies if item.startswith("mh_session="))
    overview = instance.site(request("GET", "/", jar))
    assert overview.status == 200 and "Elternabend" in overview.body.decode("utf-8")
    area = next((instance.tmp / "data" / "visitors").iterdir())
    _page, csrf, key = open_login(instance.site, {"mh_pair": jar["mh_pair"]})
    again = instance.site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key}))
    assert again.status == 303 and list((instance.tmp / "data" / "visitors").iterdir()) == [area]
    assert instance.site(request("GET", "/anmelden", jar)).headers["Location"] == "/"
    assert "visitor_started" in instance.logger.events


def test_two_visitors_get_separate_copies(instance):
    _first, one = start(instance.site)
    _second, two = start(instance.site)
    assert one["mh_session"] != two["mh_session"]
    assert len(list((instance.tmp / "data" / "visitors").iterdir())) == 2


def test_a_wrong_start_request_is_refused(instance):
    jar = {}
    _page, csrf, key = open_login(instance.site, jar)
    broken = Request("POST", "/demo/starten", {"host": HOST, "content-type": FORM,
                                                "cookie": f"mh_pair={jar['mh_pair']}"}, body=b"\xff")
    assert instance.site(broken).status == 400
    for cookies, form in (({}, {"csrf": csrf, "key": key}), (jar, {"csrf": "falsch", "key": key}),
                          (jar, {"csrf": csrf, "key": "kurz"})):
        assert instance.site(request("POST", "/demo/starten", cookies, form)).status == 403
    assert "start_rejected" in instance.logger.events
    assert not (instance.tmp / "data" / "visitors").exists()


def test_a_full_demo_and_a_failed_start_explain_themselves(instance, monkeypatch):
    monkeypatch.setattr(instance.runtimes.visitors, "max_visitors", 0)
    full, _ = start(instance.site)
    assert full.status == 429 and "alle Demo-Plätze belegt" in full.body.decode("utf-8")
    monkeypatch.setattr(instance.runtimes.visitors, "max_visitors", 5)
    (instance.tmp / "dataset" / "manifest.json").write_text("{}", encoding="utf-8")
    failed, _ = start(instance.site)
    assert failed.status == 503 and "konnte nicht gestartet werden" in failed.body.decode("utf-8")
    assert "start_failed" in instance.logger.events


def test_requests_without_a_demo_are_sent_to_the_start(instance):
    assert instance.site(request("GET", "/")).headers["Location"] == "/anmelden"
    assert instance.site(request("POST", "/aktion")).status == 403
    assert instance.site(request("GET", "/health")).status == 200
    token = instance.runtimes.auth.demo_session("Demo")  # a session whose area was never created
    assert instance.site(request("GET", "/mails", {"mh_session": token})).headers["Location"] == "/anmelden"


@pytest.mark.parametrize(("method", "path"), [
    ("GET", "/einrichtung"), ("GET", "/einstellungen/zugangsdaten"), ("POST", "/einstellungen/postfaecher/aktivieren"),
    ("GET", "/geraete"), ("POST", "/api/push/subscribe"), ("GET", "/hilfe"), ("GET", "/api/hilfe/fenster"),
    ("GET", "/berichte/neu"), ("GET", "/lernen/entscheidungen"), ("POST", "/lernen"), ("GET", "/diagnose"),
    ("POST", f"/mail/{'a' * 24}/entwurf"), ("GET", "/einstellungen/neustarten"),
])
def test_setup_connections_and_model_calls_are_blocked_also_when_called_directly(instance, method, path):
    _response, jar = start(instance.site)
    blocked = instance.site(request(method, path, jar, {} if method == "POST" else None))
    assert blocked.status == 403 and "In der Demo nicht verfügbar" in blocked.body.decode("utf-8")


def test_reading_pages_stay_available(instance):
    _response, jar = start(instance.site)
    for path in ("/lernen", "/mails", "/verlauf", "/status", "/auswertung"):
        assert instance.site(request("GET", path, jar)).status == 200, path


def test_a_confirmed_proposal_is_simulated_in_the_own_copy_only(instance):
    _response, jar = start(instance.site)
    _other, other = start(instance.site)
    page = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    form = next(item for item in re.findall(r'<form method="post" action="/aktion"[^>]*>(.*?)</form>', page, re.S)
                if 'value="confirm"' in item)
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form))
    fields["kind"] = "confirm"
    queued = instance.site(request("POST", "/aktion", jar, fields))
    assert queued.status in (200, 202, 303)
    instance.runtimes.work()
    instance.runtimes.work()
    name = f"proposal-{fields['mail_id']}-{fields['proposal_id']}.json"
    sessions = {instance.runtimes.auth.authenticate(jar["mh_session"]).id: "own",
                instance.runtimes.auth.authenticate(other["mh_session"]).id: "other"}
    states = {label: (instance.runtimes.visitors.area(session_id) / name).read_text(encoding="utf-8")
              for session_id, label in sessions.items()}
    assert '"status": "simulated"' in states["own"] and '"status": "simulated"' not in states["other"]


def test_the_disabled_telegram_transport_ignores_keyboard_removal():
    assert DisabledTelegram().remove_inline_keyboard(1, 2) is None


def test_more_demo_sessions_than_devices_of_one_person(tmp_path):
    with JsonStore(tmp_path) as store:
        auth = WebAuth(store, "s" * 40, 1, lambda text: None)
        auth.max_sessions = 30
        tokens = [auth.demo_session("Demo") for _ in range(25)]
        assert all(auth.authenticate(token) for token in tokens) and len(auth.sessions()) == 25


def test_the_visitor_app_is_built_once_per_area(instance):
    _response, jar = start(instance.site)
    session = instance.runtimes.auth.authenticate(jar["mh_session"])
    app = instance.runtimes.app(session.id)
    assert instance.runtimes.app(session.id) is app and isinstance(app(request("GET", "/health")), Response)
    assert isinstance(instance.site, DemoSite) and isinstance(instance.site.public, WebApp)


@pytest.mark.parametrize("call", [lambda t: t.reconcile("k"), lambda t: t.create(None, "k"),
                                  lambda t: t.remove(None, "k"), lambda t: t.reconcile_remove(None, "k")])
def test_the_demo_target_refuses_every_real_write(call):
    with pytest.raises(RuntimeError, match="schreibt nie"):
        call(demo.DemoTarget())
