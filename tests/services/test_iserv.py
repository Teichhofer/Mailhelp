"""IServ parent letters (3.3.7): sign-in, overview, letters, attachments and processing.

A simulated IServ server answers through httpx.MockTransport; all names and texts are synthetic.
"""
from __future__ import annotations

import email
import gzip
from datetime import UTC, datetime
from email.policy import default
from threading import Event

import httpx
import pytest
from pydantic import SecretStr

from mailhelp.config import ImapCredentials, IServAccountSettings
from mailhelp.iserv import (
    FOLDER,
    UIDVALIDITY,
    IServError,
    IServReader,
    IServRunService,
    IServSource,
    IServState,
    Letter,
    account_id,
    parse_html,
    state_name,
)
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult
from mailhelp.storage import JsonStore

SERVER = "https://schule.example"
INDEX = "/iserv/parentletter/parent/index"
LOGIN = """<form method="post" action="/iserv/auth/login">
<input type="hidden" name="_csrf" value="tok"><input type="text" name="_username">
<input type="password" name="_password"><button>Anmelden</button></form>"""


def row(ident: str, title: str, published: str, child: str = "Kim") -> str:
    return (f'<tr><td><a href="/iserv/parentletter/parent/show/{ident}/9">{title}</a></td>'
            f"<td>{published}</td><td>{child}</td></tr>")


def overview(*rows: str, footer: str = "") -> str:
    return f'<table id="crud-table"><tr><th>Titel</th></tr>{"".join(rows)}</table>{footer}'


LETTER = """<h2>Wandertag</h2><div class="parent-letter-body"><p>Am Freitag ist Wandertag.</p>
<p>Bitte Rucksack mitgeben.</p><script>tracking()</script></div>
<a href="/iserv/parentletter/attachment/77">Plan &amp; Liste.pdf</a>"""


class Server:
    """A synthetic IServ: a session cookie after a correct sign-in, then overview and letters."""

    def __init__(self):
        self.password = "geheim"
        self.index = overview(row("1", "Wandertag", "02.10.2026 08:00"), row("2", "Elternabend", "01.10.2026 19:30"))
        self.pages = {"/iserv/parentletter/parent/show/1/9": LETTER,
                      "/iserv/parentletter/parent/show/2/9": '<div class="parent-letter-body">Abend</div>'}
        self.files = {"/iserv/parentletter/attachment/77": (b"%PDF-1.4 synthetic", "application/pdf")}
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.overrides:
            return self.overrides[path]
        signed_in = request.headers.get("cookie") == "session=ok"
        if path == "/iserv/auth/login":
            form = dict(item.split("=", 1) for item in request.content.decode().split("&"))
            if form == {"_csrf": "tok", "_username": "eltern%40example.test", "_password": self.password}:
                return httpx.Response(302, headers={"Location": INDEX, "Set-Cookie": "session=ok; Path=/"})
            return httpx.Response(302, headers={"Location": INDEX})
        if not signed_in:
            return httpx.Response(200, html=LOGIN)
        if path == INDEX:
            return httpx.Response(200, html=self.index)
        if path in self.pages:
            return httpx.Response(200, html=self.pages[path])
        if path in self.files:
            data, kind = self.files[path]
            return httpx.Response(200, content=data, headers={"Content-Type": kind} if kind else {})
        return httpx.Response(404)


def account(**fields) -> IServAccountSettings:
    return IServAccountSettings(id=1, server=SERVER, **fields)


def reader(server: Server, max_bytes: int = 100_000) -> IServReader:
    credentials = ImapCredentials(username="eltern@example.test", password=SecretStr("geheim"))
    return IServReader(account(), credentials, "Europe/Berlin", max_bytes, transport=httpx.MockTransport(server))


def test_tree_tolerates_stray_and_void_tags_and_skips_scripts():
    page = parse_html(b'<div class="a b"><p>Eins<br>Zwei</span></p><input name="x"/>'
                      b"<style>x{}</style><script>y()</script> Drei </div>")
    div = page.find_all("div")[0]
    assert div.has_class("b") and not div.has_class("c")
    assert div.text("|") == "Eins|Zwei|Drei"
    assert page.find_all("input", name="x")[0].ancestor("div") is div
    assert div.ancestor("form") is None and page.find_all("p", id="none") == []
    assert parse_html("<b>text</b>").text() == "text"


def test_signs_in_lists_letters_oldest_first_and_reuses_the_session():
    server = Server()
    server.index = overview(row("1", "Wandertag", "02.10.2026 08:00"), row("2", "  Eltern-\nabend ", "01.10.2026 19:30"),
                            row("1", "Wandertag", "02.10.2026 08:00"), "<tr><td>ohne Link</td></tr>",
                            footer="<p>1 bis 2 von 2 Einträgen</p>")
    client = reader(server)
    letters = client.letters()
    assert [(letter.key, letter.title, letter.child) for letter in letters] == [
        ("2_9", "Eltern- abend", "Kim"), ("1_9", "Wandertag", "Kim")]
    assert letters[1].published == datetime(2026, 10, 2, 6, 0, tzinfo=UTC)
    assert letters[1].uid == Letter("1_9", "x", "", letters[1].published, "u").uid > 0
    sign_ins = [request for request in server.requests if request.method == "POST"]
    assert len(sign_ins) == 1 and b"_password=geheim" in sign_ins[0].content
    client.check_access()
    assert len([request for request in server.requests if request.method == "POST"]) == 1
    client.close()


def test_account_id_is_stable_and_separate_from_imap_accounts():
    from mailhelp.imap import account_id as imap_account_id
    assert account_id(SERVER, " Eltern@Example.test ") == account_id(SERVER, "eltern@example.test")
    assert account_id(SERVER, "a") != imap_account_id("schule.example", 993, "a")


@pytest.mark.parametrize(("page", "message"), [
    (LOGIN.replace("geheim", ""), "Anmeldung fehlgeschlagen"),
    ('<input type="password" name="p">', "Unbekanntes IServ-Anmeldeformular"),
    ('<form><input type="password" name="p"></form>', "Unbekanntes IServ-Anmeldeformular"),
    ('<form><input name="_username"><input type="password"></form>', "Unbekanntes IServ-Anmeldeformular"),
])
def test_rejected_or_unknown_sign_in_is_reported(page, message):
    server = Server()
    server.password = "anders"
    if page != LOGIN.replace("geheim", ""):
        server.overrides[INDEX] = httpx.Response(200, html=page)
    with pytest.raises(IServError, match=message):
        reader(server).letters()


@pytest.mark.parametrize(("index", "message"), [
    ("<p>Keine Berechtigung</p>", "Kein Elternbrief-Postfach"),
    (overview('<tr><td><a href="/iserv/parentletter/parent/show/1/9">X</a></td><td>bald</td></tr>'),
     "Veröffentlichungsdatum"),
    (overview(row("1", "A", "02.10.2026 08:00"), footer="1 bis 1 von 1.020 Einträgen"), "mehrere Seiten"),
])
def test_unexpected_overviews_stop_instead_of_processing_a_part(index, message):
    server = Server()
    server.index = index
    with pytest.raises(IServError, match=message):
        reader(server).letters()


def test_letter_becomes_a_mime_message_with_text_and_attachments():
    server = Server()
    server.files["/iserv/parentletter/attachment/78"] = (b"plain", "text/plain; charset=utf-8")
    server.files["/iserv/parentletter/attachment/79"] = (b"raw", "")
    server.pages["/iserv/parentletter/parent/show/1/9"] = LETTER + (
        '<a href="/iserv/parentletter/attachment/78">Notiz.txt</a>'
        '<a href="/iserv/parentletter/attachment/79"> </a>')
    client = reader(server)
    letter = client.letters()[1]
    fetched = client.fetch(letter)
    assert (fetched.folder, fetched.uidvalidity, fetched.uid, fetched.account_id) == (
        FOLDER, UIDVALIDITY, letter.uid, client.account_id)
    assert fetched.received_at == letter.published
    message = email.message_from_bytes(fetched.raw, policy=default)
    assert message["Subject"] == "Wandertag" and message["From"] == "Elternbriefe <elternbriefe@schule.example>"
    assert message["Message-ID"] == "<1_9.parentletter@schule.example>"
    body = message.get_body(("plain",)).get_content().replace("\r\n", "\n")
    assert body.startswith("Elternbrief vom 02.10.2026 08:00\nKind: Kim\n\nAm Freitag ist Wandertag.\nBitte Rucksack")
    assert "tracking" not in body
    parts = [(part.get_filename(), part.get_content_type(), part.get_content())
             for part in message.iter_attachments()]
    assert parts == [("Plan & Liste.pdf", "application/pdf", b"%PDF-1.4 synthetic"),
                     ("Notiz.txt", "application/octet-stream", b"plain"),
                     ("anhang-3", "application/octet-stream", b"raw")]


def test_letter_without_child_and_by_its_stand_in_uid():
    server = Server()
    server.index = overview('<tr><td><a href="/iserv/parentletter/parent/show/2/9">Abend</a></td>'
                            "<td>01.10.2026 19:30</td></tr>")
    client = reader(server)
    letter = client.letters()[0]
    fetched = client.fetch_uid(FOLDER, letter.uid, UIDVALIDITY)
    body = email.message_from_bytes(fetched.raw, policy=default).get_body(("plain",)).get_content()
    body = body.replace("\r\n", "\n")
    assert body == "Elternbrief vom 01.10.2026 19:30\n\nAbend\n"
    for args in ((FOLDER, letter.uid + 1, UIDVALIDITY), ("INBOX", letter.uid, UIDVALIDITY),
                 (FOLDER, letter.uid, 2)):
        with pytest.raises(IServError, match="nicht mehr vorhanden"):
            client.fetch_uid(*args)


@pytest.mark.parametrize(("change", "message"), [
    ({"/iserv/parentletter/parent/show/1/9": httpx.Response(200, html=LOGIN)}, "Sitzung abgelaufen"),
    ({"/iserv/parentletter/parent/show/1/9": httpx.Response(200, html="<p>leer</p>")}, "Inhaltsbereich"),
    ({"/iserv/parentletter/attachment/77": httpx.Response(200, html="<p>Fehler</p>")}, "HTML-Seite"),
])
def test_broken_letters_are_errors(change, message):
    server = Server()
    client = reader(server, max_bytes=5000)
    letter = client.letters()[1]
    server.overrides.update(change)
    with pytest.raises(IServError, match=message):
        client.fetch(letter)


@pytest.mark.parametrize("size", [4900, 6000, 5_000_000, 5_000_001])
def test_attachment_limits_are_separate_from_the_letter_body_limit(size):
    server = Server()
    client = reader(server, max_bytes=5000)
    server.files["/iserv/parentletter/attachment/77"] = (b"x" * size, "application/pdf")
    fetched = client.fetch(client.letters()[1])
    attachments = list(email.message_from_bytes(fetched.raw, policy=default).iter_attachments())
    if size > 5_000_000:
        assert attachments == []
        assert fetched.oversized_attachments == (("Plan & Liste.pdf", "application/pdf", 5_000_001),)
    else:
        assert attachments[0].get_payload(decode=True) == b"x" * size
        assert fetched.oversized_attachments == ()


def test_the_html_response_size_limit_still_applies():
    server = Server()
    server.overrides[INDEX] = httpx.Response(200, content=b"x" * 5001)
    with pytest.raises(IServError, match="Antwort überschreitet"):
        reader(server, max_bytes=5000).letters()


def test_compressed_attachment_is_decoded_once_and_uses_the_decoded_size():
    server = Server()
    payload = b"synthetic text " * 100
    server.overrides["/iserv/parentletter/attachment/77"] = httpx.Response(
        200, content=gzip.compress(payload), headers={"Content-Encoding": "gzip", "Content-Type": "text/plain"})
    client = reader(server)
    fetched = client.fetch(client.letters()[1])
    attachment, = email.message_from_bytes(fetched.raw, policy=default).iter_attachments()
    assert attachment.get_payload(decode=True) == payload
    client.max_attachment_bytes = 1024
    fetched = client.fetch(client.letters()[1])
    assert fetched.oversized_attachments[0][2] == 1025


def test_oversized_unnamed_attachment_has_safe_metadata_and_no_cached_original():
    server = Server()
    server.pages["/iserv/parentletter/parent/show/1/9"] = LETTER.replace("Plan &amp; Liste.pdf", " ")
    server.files["/iserv/parentletter/attachment/77"] = (b"x" * 1025, "")
    client = reader(server)
    client.max_attachment_bytes = 1024
    fetched = client.fetch(client.letters()[1])
    assert fetched.oversized_attachments == (("anhang-1", "application/octet-stream", 1025),)
    assert list(email.message_from_bytes(fetched.raw, policy=default).iter_attachments()) == []


def test_oversized_letter_does_not_stop_later_letters_or_repeat_after_restart(tmp_path):
    server = Server()
    server.pages["/iserv/parentletter/parent/show/2/9"] = LETTER
    server.files["/iserv/parentletter/attachment/77"] = (b"x" * 5_000_001, "application/pdf")
    process = Results()
    run, store, source = service(tmp_path, server, process)
    assert len(run.poll()) == 2
    assert process.seen == ["Elternabend", "Wandertag"]
    restarted = IServRunService(store, Log(), [source], process, Event())
    assert restarted.poll() == []
    assert len(process.seen) == 2


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(302, headers={"Location": "https://andere.example/x"}), "anderen Server"),
    (httpx.Response(302, headers={"Location": "https://user:pw@schule.example/x"}), "anderen Server"),
    (httpx.Response(302, headers={"Location": INDEX}), "Zu viele Weiterleitungen"),
    (httpx.Response(500), "HTTP-Status 500"),
])
def test_redirects_leave_the_school_never_and_errors_carry_no_addresses(response, message):
    server = Server()
    server.overrides[INDEX] = response
    with pytest.raises(IServError, match=message) as raised:
        reader(server).letters()
    assert "http" not in str(raised.value)


def test_permanent_redirects_keep_the_form_and_refresh_pages_are_followed():
    server = Server()
    server.overrides["/iserv/auth/start"] = httpx.Response(307, headers={"Location": "/iserv/auth/login"})
    server.overrides["/iserv/wait"] = httpx.Response(
        200, html="<meta charset='utf-8'><meta http-equiv='Refresh' content=\"0; URL='/iserv/parentletter/parent/index'\">")
    server.overrides["/iserv/odd"] = httpx.Response(200, html='<meta http-equiv="refresh" content="5">ok')
    client = reader(server)
    response = client._request("POST", "/iserv/auth/start", {"_csrf": "tok", "_username": "eltern@example.test",
                                                              "_password": "geheim"})
    assert response.headers["content-type"].startswith("text/html")
    assert [request.method for request in server.requests[-3:]] == ["POST", "POST", "GET"]
    assert client._request("GET", "/iserv/wait").url.path == INDEX
    assert client._request("GET", "/iserv/odd").text.endswith("ok")


class Results:
    """Synthetic processing: per letter title an outcome, recorded in order."""

    def __init__(self, outcomes: dict[str, ProcessingOutcome] | None = None, stop: Event | None = None):
        self.outcomes, self.stop, self.seen = outcomes or {}, stop, []

    def __call__(self, mail):
        subject = email.message_from_bytes(mail.raw, policy=default)["Subject"]
        self.seen.append(subject)
        if self.stop is not None:
            self.stop.set()
        return ProcessingResult(self.outcomes.get(subject, ProcessingOutcome.COMPLETED), {"id": "m" + subject})


class Log:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **context):
        self.events.append((level, event, context))


def service(tmp_path, server, process, *, start=None, stop=None, extra=()):
    store = JsonStore(tmp_path / "state")
    source = IServSource(account(), reader(server), start)
    return IServRunService(store, Log(), [source, *extra], process, stop or Event()), store, source


def test_new_letters_are_processed_oldest_first_once(tmp_path):
    process = Results()
    run, store, source = service(tmp_path, Server(), process)
    assert [result.state["id"] for result in run.poll()] == ["mElternabend", "mWandertag"]
    assert store.load_model(state_name(source.reader.account_id), IServState).processed == ["2_9", "1_9"]
    assert run.poll() == [] and process.seen == ["Elternabend", "Wandertag"]
    assert run.readers() == {source.reader.account_id: source.reader}
    assert ("INFO", "letters_listed", {"account": 1, "count": 2}) in run.logger.events


def test_letters_before_the_start_and_beyond_the_limit_wait(tmp_path):
    process = Results()
    run, store, source = service(tmp_path, Server(), process,
                                 start=datetime(2026, 10, 2, tzinfo=UTC))
    assert run.poll(limit=0) == []
    assert [result.state["id"] for result in run.poll(limit=1)] == ["mWandertag"]
    assert process.seen == ["Wandertag"]


def test_a_failed_letter_is_retried_and_others_continue(tmp_path):
    process = Results({"Elternabend": ProcessingOutcome.FAILED, "Wandertag": ProcessingOutcome.WAITING})
    run, store, source = service(tmp_path, Server(), process)
    run.poll()
    assert store.load_model(state_name(source.reader.account_id), IServState).processed == ["1_9"]
    assert ("ERROR", "letter_failed", {"account": 1, "mail_id": "mElternabend"}) in run.logger.events
    run.poll()
    assert process.seen == ["Elternabend", "Wandertag", "Elternabend"]


def test_stop_ends_the_round_between_letters(tmp_path):
    stop = Event()
    run, store, _ = service(tmp_path, Server(), Results(stop=stop), stop=stop)
    assert len(run.poll()) == 1
    assert run.poll() == []


def test_one_failing_school_does_not_stop_the_others(tmp_path):
    broken, unreachable = Server(), Server()
    broken.overrides[INDEX] = httpx.Response(500)

    def offline(request):
        raise httpx.ConnectError("down")

    other = IServSource(account(), IServReader(account(), ImapCredentials(username="b", password=SecretStr("c")),
                                                "UTC", 1000, transport=httpx.MockTransport(offline)), None)
    working = IServSource(account(), reader(Server()), None)
    run, _, _ = service(tmp_path, broken, Results(), extra=(other, working))
    assert len(run.poll()) == 2
    assert [context for _, event, context in run.logger.events if event == "poll_failed"] == [
        {"account": 1, "error": "IServ antwortete mit HTTP-Status 500"}, {"account": 1, "error": "ConnectError"}]
    assert run.poll(limit=2) == []
    del unreachable
