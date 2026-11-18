"""7.1 (D3, D4): "Demo starten" opens a private copy of the prepared dataset in the normal interface."""
from __future__ import annotations

import html
import json
import re
import shutil
from threading import Event
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
from tests.fakes.demo_questions import asked_dataset

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


@pytest.fixture
def asked(tmp_path, monkeypatch):
    """A demo whose dataset asks one question with a prepared answer (7.6: the shipped one asks none)."""
    dataset = asked_dataset(tmp_path / "dataset")
    monkeypatch.setattr(demo, "packaged", lambda: dataset)
    with JsonStore(tmp_path / "data" / "demo") as store:
        server, runtimes = demo.create_demo(tmp_path, store, WebSettings(enabled=True, allowed_hosts=[HOST]),
                                            "s" * 40, Log())
        yield SimpleNamespace(site=server.handler, runtimes=runtimes)
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


def test_visitor_runtimes_share_static_assets_without_sharing_routes_or_state(instance, monkeypatch):
    def forbid_read(name):
        raise AssertionError("Visitor creation must reuse the process assets")
    monkeypatch.setattr("mailhelp.web.app.static_file", forbid_read)
    one, first = start(instance.site)
    two, second = start(instance.site)
    assert one.status == two.status == 303
    assert instance.site(request("GET", "/", first)).status == 200
    assert instance.site(request("GET", "/", second)).status == 200
    assert len(instance.runtimes.runtimes) == 2
    assert len({runtime.store.directory for runtime in instance.runtimes.runtimes.values()}) == 2


def test_failed_runtime_construction_closes_the_partial_store(instance, monkeypatch):
    _response, jar = start(instance.site)
    session = instance.site.auth.authenticate(jar["mh_session"])
    area = instance.runtimes.visitors.area(session.id)
    def fail_load(path):
        raise OSError("snapshot unavailable")
    monkeypatch.setattr(demo.DemoRevisions, "load", fail_load)
    with pytest.raises(OSError, match="snapshot unavailable"):
        instance.runtimes.app(session.id)
    assert not instance.runtimes.runtimes
    with JsonStore(area) as reopened:
        assert reopened.names("mail-")


def test_concurrent_last_slot_never_revokes_the_winning_session(instance):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    instance.runtimes.visitors.max_visitors = instance.site.auth.max_sessions = 1
    arrivals = Barrier(2)
    def begin_client(number):
        jar = {}
        _page, csrf, key = open_login(instance.site, jar)
        arrivals.wait(timeout=5)
        response = instance.site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key}))
        return response, cookies_of(response, jar)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(begin_client, range(2)))
    assert sorted(response.status for response, jar in results) == [303, 429]
    winner = next(jar for response, jar in results if response.status == 303)
    assert instance.site.auth.authenticate(winner["mh_session"]) is not None
    assert instance.site(request("GET", "/", winner)).status == 200


def test_the_login_page_offers_only_the_demo_start(instance):
    page, _csrf, _key = open_login(instance.site, {})
    text = page.body.decode("utf-8")
    assert page.status == 200 and "<h1>Demo starten</h1>" in text and DEMO_NOTICE in text
    assert "Telegram senden" not in text and "--pair" not in text and 'type="password"' not in text


@pytest.mark.parametrize("payload", [[], {"code": "unchanged"}, {"message": 42}])
def test78_demo_response_preserves_non_message_payloads(payload):
    from mailhelp.web.demo_site import demo_response
    assert json.loads(demo_response(Response.json(200, payload)).body) == payload


def test78_limits_can_be_supplied_and_a_start_key_cannot_change_language(instance):
    from mailhelp.web.demo_site import DemoHooks, StartLimits
    site = instance.site
    hooks = DemoHooks(site.start, site.visitor_app, site.full, site.reset, site.dataset_locale, site.answers,
                      site.generation)
    limits = StartLimits()
    assert DemoSite(WebApp([HOST]), site.auth, site.logger, hooks, limits=limits).limits is limits
    jar = {}
    _page, csrf, key = open_login(site, jar)
    invalid = site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key, "locale": "fr"}))
    assert invalid.status == 400
    response = site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key, "locale": "en"}))
    assert response.status == 303
    cookies_of(response, jar)
    conflict = site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key, "locale": "de"}))
    assert conflict.status == 409


@pytest.mark.parametrize("failure,status", [(OSError, 503), (ValueError, 409)])
def test78_failed_starts_release_their_new_session_without_revoking_another_visitor(instance, monkeypatch,
                                                                                  failure, status):
    instance.site.auth.max_sessions = instance.runtimes.visitors.max_visitors = 2
    _response, first = start(instance.site)
    old = instance.site.auth.authenticate(first["mh_session"])
    def failed(*args):
        raise failure("copy failed")
    with monkeypatch.context() as local:
        local.setattr(instance.site, "start", failed)
        assert start(instance.site)[0].status == status
    assert [session.id for session in instance.site.auth.sessions()] == [old.id]
    assert start(instance.site)[0].status == 303
    assert instance.site.auth.authenticate(first["mh_session"]) is not None
    assert instance.site(request("GET", "/", first)).status == 200


def test78_a_failed_start_keeps_an_existing_session_without_a_demo(instance, monkeypatch):
    token = instance.site.auth.demo_session("earlier start")
    jar = {"mh_session": token}
    _page, csrf, key = open_login(instance.site, jar)
    def failed(*args):
        raise OSError("copy failed")
    monkeypatch.setattr(instance.site, "start", failed)
    response = instance.site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key}))
    assert response.status == 503 and "start_failed" in instance.logger.events
    assert instance.site.auth.authenticate(token) is not None  # not created by this request, so not revoked


def test78_a_foreign_host_is_rejected_before_any_route(instance):
    _response, jar = start(instance.site)
    foreign = request("GET", "/", jar)
    foreign.headers["host"] = "attacker.example"
    assert instance.site(foreign).status in {400, 403, 421}


def test78_orphaned_sessions_are_cleaned_before_they_can_displace_a_visitor(instance):
    instance.site.auth.max_sessions = instance.runtimes.visitors.max_visitors = 2
    _response, first = start(instance.site)
    instance.site.auth.demo_session("old failed start")
    assert start(instance.site)[0].status == 429
    instance.runtimes.cleanup()
    assert start(instance.site)[0].status == 303
    assert instance.site.auth.authenticate(first["mh_session"]) is not None


@pytest.mark.parametrize("change", [
    {"locale": "fr"}, {"demo_generation": "0"}, {"extra": "one field too many"},
])
def test78_restart_rejects_invalid_locale_generation_and_oversized_forms(instance, change):
    _response, jar = start(instance.site)
    page = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page))
    assert instance.site(request("POST", "/demo/neu-starten", jar, {**fields, **change})).status == 400


def test78_malformed_private_posts_and_legacy_answer_snapshots(instance):
    _response, jar = start(instance.site)
    session = instance.site.auth.authenticate(jar["mh_session"])
    area = instance.runtimes.visitors.area(session.id)
    shutil.rmtree(area / ".demo")
    assert instance.runtimes.prepared(session.id) == instance.runtimes.revisions.prepared()
    assert instance.runtimes.prepared("not-a-session") == instance.runtimes.revisions.prepared()
    app = instance.runtimes.app(session.id)
    malformed = Request("POST", "/aktion", {"host": HOST, "cookie": f'mh_session={jar["mh_session"]}',
                                             "content-type": FORM}, body=b"\xff")
    assert app(malformed).status == 400
    assert instance.site(request("GET", "/", jar)).status == 200


def test78_missing_replacement_package_keeps_the_current_demo(instance):
    _response, jar = start(instance.site)
    assert instance.site(request("GET", "/", jar)).status == 200
    page = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page))
    instance.runtimes.visitors.dataset = instance.tmp / "missing-package"
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields)).status == 503
    assert instance.site(request("GET", "/", jar)).status == 200


def test78_a_damaged_german_package_does_not_disable_the_english_demo(tmp_path, monkeypatch):
    broken = tmp_path / "broken-german-package"
    broken.mkdir()
    monkeypatch.setattr(demo, "packaged", lambda: broken)
    with JsonStore(tmp_path / "data" / "demo") as store:
        server, runtimes = demo.create_demo(tmp_path, store, WebSettings(enabled=True, allowed_hosts=[HOST]),
                                            "s" * 40, Log())
        try:
            response, english = start(server.handler, {"mailhelp_lang": "en"})
            assert response.status == 303
            assert server.handler(request("GET", "/", english)).status == 200
            failed, _german = start(server.handler)
            assert failed.status == 503
            assert server.handler(request("GET", "/", english)).status == 200
        finally:
            runtimes.close()


@pytest.mark.parametrize("language", ["de", "en"])
def test_demo_language_entry_works_before_start(instance, language):
    response = instance.site(Request("GET", f"/{language}/", {"host": HOST}))
    assert response.status == 303
    jar = cookies_of(response, {})
    assert jar["mailhelp_lang"] == language
    page = instance.site(request("GET", "/anmelden", jar))
    assert f'<html lang="{language}">' in page.body.decode()
    assert instance.runtimes.visitors._state().visitors == {}


def test_regular_language_switch_is_public_and_rejects_invalid_values(instance):
    response = instance.site(Request("GET", "/sprache", {"host": HOST}, query="wert=en"))
    assert cookies_of(response, {})["mailhelp_lang"] == "en"
    invalid = instance.site(Request("GET", "/sprache", {"host": HOST}, query="wert=fr"))
    assert invalid.status == 400 and invalid.cookies == []


@pytest.mark.parametrize(("path", "status", "message"), [("/missing", 404, "Not found."),
                                                          ("/../outside", 400, "Invalid path.")])
def test_web_errors_follow_language_before_route_dispatch(path, status, message):
    app = WebApp([HOST])
    result = app(Request("GET", path, {"host": HOST, "accept-language": "en"}))
    assert result.status == status and result.body.decode() == message


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


def test_pages_use_demo_wording_and_carry_the_notice_with_a_restart_link(instance):
    _response, jar = start(instance.site)
    page = instance.site(request("GET", "/status", jar)).body.decode("utf-8")
    assert DEMO_NOTICE in page and 'href="/demo/neu-starten"' in page
    assert "Demo – Einträge werden nur in der Demo angelegt" in page and "Testmodus" not in page
    overview = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    assert ">In der Demo anlegen<" in overview and ">Simulieren<" not in overview
    stylesheet = instance.site(request("GET", "/static/app.css", jar))
    assert stylesheet.body.startswith(b"/*")  # files other than pages and JSON pass unchanged


def test_every_replaced_test_mode_text_still_exists_in_the_code():
    """A changed wording in the normal interface must not silently escape the demo replacement."""
    from pathlib import Path

    import mailhelp
    from mailhelp.web.demo_site import DEMO_LABELS, DEMO_TEXTS
    code = "\n".join(path.read_text(encoding="utf-8") for path in Path(mailhelp.__file__).parent.rglob("*.py")
                     if path.name != "demo_site.py")
    assert [text for text in [*DEMO_TEXTS, *DEMO_LABELS] if text not in code] == []


def _answer_forms(page):
    return [form for form in re.findall(r'<form method="post" action="/aktion" class="stack">.*?</form>', page, re.S)
            if 'value="answer"' in form]


def test_the_shipped_demo_asks_nothing(instance):
    """7.6: every card of the shipped demo can be decided at once."""
    _response, jar = start(instance.site)
    page = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    assert "Offene Fragen" not in page and "Relevanz klären" not in page
    assert "In der Demo vorbereitet" not in page and page.count("In der Demo anlegen") >= 6


def test_a_prepared_answer_is_offered_and_replays_the_recorded_result(asked):
    instance = asked
    _response, jar = start(instance.site)
    page = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    prepared = [form for form in _answer_forms(page) if "In der Demo vorbereitet" in form]
    assert len(prepared) == 1
    form = prepared[0]
    assert "16:00 Uhr" in form
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form))
    fields["text"] = html.unescape(re.search(r"<textarea[^>]*>(.*?)</textarea>", form, re.S).group(1))
    instance.site(request("POST", "/aktion", jar, fields))
    for _ in range(6):
        instance.runtimes.work()
    area = instance.runtimes.visitors.area(instance.runtimes.auth.authenticate(jar["mh_session"]).id)
    revised = json.loads((area / f"proposal-{fields['mail_id']}-{fields['proposal_id']}.json").read_text("utf-8"))
    assert revised["version"] == 2 and "Wann beginnt der Termin?" not in revised["open_questions"]


def test_a_free_answer_meets_the_demo_limit_instead_of_a_model(asked):
    instance = asked
    _response, jar = start(instance.site)
    page = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    [form] = [item for item in _answer_forms(page) if "In der Demo vorbereitet" in item]
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form))
    fields["text"] = "Vielleicht, mal sehen."
    instance.site(request("POST", "/aktion", jar, fields))
    for _ in range(6):
        instance.runtimes.work()
    area = instance.runtimes.visitors.area(instance.runtimes.auth.authenticate(jar["mh_session"]).id)
    current = json.loads((area / f"proposal-{fields['mail_id']}-{fields['proposal_id']}.json").read_text("utf-8"))
    assert current["version"] == int(fields["version"])  # nothing invented, the question stays open


class NetworkUsed(AssertionError):
    pass


@pytest.fixture
def no_network(monkeypatch):
    """A trap: any name lookup or connection fails the test instead of leaving the host."""
    import socket

    def refuse(*args, **kwargs):
        raise NetworkUsed(f"Die Demo hat das Netz benutzt: {args!r}")
    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return refuse


def test_the_network_trap_catches_a_connection(no_network):
    import socket
    with pytest.raises(NetworkUsed):
        socket.create_connection(("example.org", 443))
    with socket.socket() as probe, pytest.raises(NetworkUsed):
        probe.connect(("192.0.2.1", 443))


def test_a_whole_visit_never_uses_the_network(instance, no_network):
    """Start, read, confirm, answer (prepared and free), background work, restart and cleanup."""
    _response, jar = start(instance.site)
    for path in ("/", "/mails", "/verlauf", "/status", "/einstellungen", "/termine", "/aufgaben"):
        assert instance.site(request("GET", path, jar)).status in (200, 303, 403, 404)
    page = instance.site(request("GET", "/", jar)).body.decode("utf-8")
    confirm = next(item for item in re.findall(r'<form method="post" action="/aktion"[^>]*>(.*?)</form>', page, re.S)
                   if 'value="confirm"' in item)
    fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', confirm))
    instance.site(request("POST", "/aktion", jar, {**fields, "kind": "confirm"}))
    for answer in _answer_forms(page)[:2]:
        fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', answer))
        text = html.unescape(re.search(r"<textarea[^>]*>(.*?)</textarea>", answer, re.S).group(1)) or "Weiß nicht."
        instance.site(request("POST", "/aktion", jar, {**fields, "text": text}))
        instance.site(request("POST", "/aktion", jar, {**fields, "text": "Eine freie Antwort."}))
    for _ in range(8):
        instance.runtimes.work()
    area = instance.runtimes.visitors.area(instance.runtimes.auth.authenticate(jar["mh_session"]).id)
    assert any('"status": "simulated"' in path.read_text(encoding="utf-8") for path in area.glob("proposal-*.json"))
    restart = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode("utf-8")
    csrf = re.search(r'name="csrf" value="([^"]+)"', restart).group(1)
    key = re.search(r'name="key" value="([^"]+)"', restart).group(1)
    assert instance.site(request("POST", "/demo/neu-starten", jar, {"csrf": csrf, "key": key})).status == 303
    instance.runtimes.cleanup()
    assert instance.site(request("GET", "/", jar)).status == 200


def test_the_restart_confirms_and_replaces_only_the_own_area(instance):
    _response, jar = start(instance.site)
    _other, other = start(instance.site)
    auth, visitors = instance.runtimes.auth, instance.runtimes.visitors
    own, foreign = (visitors.area(auth.authenticate(item["mh_session"]).id) for item in (jar, other))
    instance.site(request("GET", "/", jar))  # builds the runtime of the own area
    confirm = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode("utf-8")
    assert "Demo jetzt neu starten" in confirm and DEMO_NOTICE in confirm
    csrf = re.search(r'name="csrf" value="([^"]+)"', confirm).group(1)
    key = re.search(r'name="key" value="([^"]+)"', confirm).group(1)
    broken = Request("POST", "/demo/neu-starten", {"host": HOST, "content-type": FORM,
                                                    "cookie": f"mh_session={jar['mh_session']}"}, body=b"\xff")
    assert instance.site(broken).status == 400
    assert instance.site(request("POST", "/demo/neu-starten", jar, {"csrf": "falsch", "key": key})).status == 403
    done = instance.site(request("POST", "/demo/neu-starten", jar, {"csrf": csrf, "key": key}))
    fresh = visitors.area(auth.authenticate(jar["mh_session"]).id)
    assert done.headers["Location"] == "/" and fresh != own and not own.exists() and foreign.is_dir()
    assert "visitor_reset" in instance.logger.events and own not in instance.runtimes.runtimes


def test_starts_are_limited_per_client_and_in_total(monkeypatch):
    from mailhelp.web import demo_site
    now = [0.0]
    limits = demo_site.StartLimits(clock=lambda: now[0])
    assert all(limits.allow("a") for _ in range(demo_site.STARTS_PER_CLIENT)) and not limits.allow("a")
    assert limits.allow("b")
    monkeypatch.setattr(demo_site, "STARTS_TOTAL", 6)
    assert not limits.allow("c")
    now[0] = demo_site.START_WINDOW
    assert limits.allow("a") and limits.allow("c")


def test_too_many_starts_are_refused_and_a_proxy_is_trusted_only_when_configured(instance, monkeypatch):
    site = instance.site
    assert site.client(Request("GET", "/", {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, client="10.0.0.1")) == \
        "10.0.0.1"
    monkeypatch.setattr(site, "trust_proxy", True)
    assert site.client(Request("GET", "/", {"x-forwarded-for": "203.0.113.9"}, client="10.0.0.1")) == "203.0.113.9"
    # The proxy appends the address it saw; earlier entries come from the visitor, who could otherwise
    # pass the start limit with a new invented address on every request.
    assert site.client(Request("GET", "/", {"x-forwarded-for": "198.51.100.7, 203.0.113.9"},
                               client="10.0.0.1")) == "203.0.113.9"
    assert site.client(Request("GET", "/", {}, client="10.0.0.1")) == "10.0.0.1"
    monkeypatch.setattr(site.limits, "allow", lambda client: False)
    refused, _ = start(site)
    assert refused.status == 429 and "Zu viele Demo-Starts" in refused.body.decode("utf-8")


def test_cleanup_removes_expired_visitors_and_closes_their_runtimes(instance):
    _response, jar = start(instance.site)
    _other, other = start(instance.site)
    instance.site(request("GET", "/", jar))
    auth = instance.runtimes.auth
    expired = auth.authenticate(jar["mh_session"]).id
    area = instance.runtimes.visitors.area(expired)
    auth.revoke(expired)
    assert instance.runtimes.cleanup() == 1
    assert not area.exists() and area not in instance.runtimes.runtimes
    assert instance.runtimes.visitors.area(auth.authenticate(other["mh_session"]).id).is_dir()


def test_the_worker_cleans_up_once_a_minute(monkeypatch):
    stopped, calls, now = Event(), [], [0.0]

    def work():
        calls.append("work")
        now[0] += 30
        if now[0] >= 120:
            stopped.set()
    runtimes = SimpleNamespace(work=work, cleanup=lambda: calls.append("cleanup"))
    demo._work(runtimes, stopped, clock=lambda: now[0])
    assert calls == ["work", "work", "cleanup", "work", "work", "cleanup"]


def test_the_demo_revisions_replay_only_recorded_calls():
    from mailhelp.domain.proposal import Proposal
    from mailhelp.domain.revision_errors import TechnicalRevisionError
    from mailhelp.runtime.demo_answers import DEMO_ONLY, DemoRevisions
    base = json.loads(next((packaged() / "state").glob("proposal-*-p_*[0-9a-f].json")).read_text("utf-8"))
    item = Proposal.model_validate(base)
    revised = {**base, "version": item.version + 1}
    revisions = DemoRevisions([
        {"method": "interpret_telegram_answer", "proposal": [item.source_mail_id, item.id, item.version],
         "arguments": ["Frage?", "Antwort"], "result": {"usable": True, "normalized_answer": "Antwort", "reason": "ok"}},
        {"method": "revise_proposal", "proposal": [item.source_mail_id, item.id, item.version],
         "arguments": ["Frage?", "Antwort"], "result": revised},
        {"method": "clarify_telegram_answer", "proposal": None, "arguments": ["Frage?", "x", "y"],
         "result": {"message": "egal"}}])
    assert revisions.prepared() == {(item.source_mail_id, item.id, item.version): "Antwort"}
    assert revisions.interpret_telegram_answer(item, "Frage?", "Antwort")[1].usable
    assert revisions.interpret_telegram_answer(item, "Frage?", "anders")[1].reason == DEMO_ONLY
    assert revisions.revise_proposal(item, "Frage?", "Antwort")[1].version == item.version + 1
    with pytest.raises(TechnicalRevisionError, match="vorbereiteten"):
        revisions.revise_proposal(item, "Frage?", "anders")
    assert "vorbereitete Beispielantwort" in revisions.clarify_telegram_answer("Frage?", "x", DEMO_ONLY)[1].message


def test_json_answers_get_demo_wording_and_odd_forms_stay_unchanged():
    from mailhelp.web.demo_site import _prefill, demo_response
    answer = Response(200, b'{"message": "Simuliert (Testmodus)"}', "application/json")
    assert demo_response(answer).body == b'{"message": "In der Demo angelegt"}'
    odd = ('<form method="post" action="/aktion" class="stack"><input type="hidden" name="kind" value="answer">'
           '<input type="hidden" name="version" value="x"><textarea name="text"></textarea></form>')
    assert _prefill(odd, {("a", "b", 1): "Antwort"}) == odd


def test_demo_decoration_preserves_mail_content_and_translates_only_owned_messages():
    from mailhelp.i18n import Locale, use_locale
    from mailhelp.web.demo_site import demo_response
    with use_locale(Locale.EN):
        page = demo_response(Response.html(200, '<main id="inhalt"><p>Simuliert (Testmodus)</p></main>'))
        assert '<p>Simuliert (Testmodus)</p>' in page.body.decode()
        assert "Demo – sample data" in page.body.decode()
        answer = demo_response(Response(200, b'{"message":"Simuliert (Testmodus)","subject":"Simuliert (Testmodus)"}',
                                        "application/json"))
        assert json.loads(answer.body) == {"message": "Created in demo", "subject": "Simuliert (Testmodus)"}


def test_demo_login_english_has_no_german_pairing_heading(instance):
    page = instance.site(Request("GET", "/anmelden", {"host": "localhost:8765", "accept-language": "en"}))
    assert '<h1>Start demo</h1>' in page.body.decode() and 'eigene Kopie' not in page.body.decode()


def test_demo_english_start_and_ui_switch_preserve_the_dataset(instance):
    _response, jar = start(instance.site, {"mailhelp_lang": "en"})
    session = instance.runtimes.auth.authenticate(jar["mh_session"])
    visitors = instance.runtimes.visitors
    area = visitors.area(session.id)
    assert visitors.entry(session.id).dataset_locale == "en"
    page = instance.site(request("GET", "/", jar)).body.decode()
    assert 'lang="en"' in page and "Class 4B parent meeting" in page and "Create in demo" in page
    jar["mailhelp_lang"] = "de"
    switched = instance.site(request("GET", "/", jar)).body.decode()
    assert "Die Beispieldaten bleiben in ihrer bisherigen Sprache" in switched
    assert "Class 4B parent meeting" in switched and visitors.area(session.id) == area


def test_confirmed_restart_binds_language_and_rejects_previous_generation(instance):
    _response, jar = start(instance.site)
    session = instance.runtimes.auth.authenticate(jar["mh_session"])
    old_app = instance.runtimes.app(session.id)
    old_page = instance.site(request("GET", "/", jar)).body.decode()
    jar["mailhelp_lang"] = "en"
    confirm = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', confirm))
    assert fields["locale"] == "en"
    jar["mailhelp_lang"] = "de"
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields)).status == 303
    assert instance.runtimes.visitors.entry(session.id).dataset_locale == "en"
    assert old_app(request("GET", "/", jar)).status == 409
    stale_fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', old_page))
    assert instance.site(request("POST", "/aktion", jar, stale_fields)).status == 409
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields)).status == 303
    assert instance.runtimes.visitors.entry(session.id).generation == 2


def test_a_restart_confirmation_from_an_older_generation_is_refused(instance):
    _response, jar = start(instance.site)
    first = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    second = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    fields = lambda page: dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page))
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields(second))).status == 303
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields(first))).status == 409
    session = instance.runtimes.auth.authenticate(jar["mh_session"])
    assert instance.runtimes.visitors.entry(session.id).generation == 2


def test_a_failed_restart_preserves_the_open_runtime_and_decisions(instance, monkeypatch):
    from mailhelp.runtime import demo_visitors
    _response, jar = start(instance.site)
    session = instance.runtimes.auth.authenticate(jar["mh_session"])
    old_app = instance.runtimes.app(session.id)
    confirm = instance.site(request("GET", "/demo/neu-starten", jar)).body.decode()
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', confirm))
    def fail(*args):
        raise OSError("synthetic copy failure")
    monkeypatch.setattr(demo_visitors, "install", fail)
    assert instance.site(request("POST", "/demo/neu-starten", jar, fields)).status == 503
    assert instance.runtimes.app(session.id) is old_app
    assert old_app(request("GET", "/", jar)).status == 200


def test_the_open_list_names_the_keys_and_the_finished_list_offers_a_new_round():
    """7.6.2: the quick flow – keys above the open list, a new round once everything is decided."""
    from mailhelp.web.demo_site import AGAIN, KEYS_HINT, demo_response
    page = ('<main id="inhalt"><div class="swipe-hint" data-swipe-hint hidden></div>'
            '<section class="card inbox-zero"><h2 id="inbox-zero">Alles erledigt!</h2><p>Heute</p></section></main>')
    shown = demo_response(Response.html(200, page)).body.decode("utf-8")
    assert shown.count(KEYS_HINT) == 1 and shown.index(KEYS_HINT) < shown.index("data-swipe-hint")
    assert shown.count(AGAIN) == 1 and shown.index("</h2>") < shown.index(AGAIN) < shown.index("<p>Heute")
    plain = demo_response(Response.html(200, '<main id="inhalt"><h1>Mails</h1></main>')).body.decode("utf-8")
    assert KEYS_HINT not in plain and AGAIN not in plain


def test_the_shipped_demo_shows_the_key_hint_on_the_open_decisions(instance):
    from mailhelp.web.demo_site import KEYS_HINT
    _response, jar = start(instance.site)
    assert KEYS_HINT in instance.site(request("GET", "/", jar)).body.decode("utf-8")
