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
