"""Writing actions through the web: forms, command queue, results and Telegram consistency."""
from __future__ import annotations

import json
import re
from html import unescape

import pytest

from mailhelp.config import WebSettings
from mailhelp.domain.processing import ProposalClarificationState, ProposalRevisionStatus
from mailhelp.models import ActionLedger, ActionLedgerEntry, Proposal, TelegramDialogState
from mailhelp.review.commands import CommandKind
from mailhelp.review.inbox import MAX_QUEUED, CommandInbox, CommandStatus
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController
from mailhelp.telegram.dialog import STALE_BUTTON
from mailhelp.telegram.ledger import ActionLedgerService
from mailhelp.web import WebApp
from mailhelp.web.actions import proposal_actions
from mailhelp.web.auth import WebAuth
from mailhelp.web.site import MailhelpSite
from test_telegram_dialog import Logger, Telegram, Writer, callback
from test_web_auth import LOCAL, SECRET, Browser, code_from
from web_scenario import Revisions, mail_id, populate, proposal, save_mail

MAIL1 = mail_id(1)


class Web:
    """Web app, Mailhelp main thread (driven by run()) and a signed-in browser."""

    def __init__(self, store: JsonStore):
        self.store, self.telegram, self.writer = store, Telegram(), Writer()
        self.commands = CommandInbox(store)
        self.dialog = TelegramDialogController(
            store, self.telegram, 1, 2, Logger(), {"todoist": self.writer, "google_calendar": self.writer},
            False, "Europe/Berlin", Revisions(), commands=self.commands)
        messages = []
        self.auth = WebAuth(store, SECRET, 30, messages.append)
        self.dialog.review.web_authorizer = lambda actor: self.auth.active(actor.removeprefix("web:"))
        self.logger = Logger()
        self.app = WebApp([LOCAL])
        MailhelpSite(self.app, self.auth, WebSettings(), "Europe/Berlin", self.logger,
                     ReviewViews(store, "Europe/Berlin"), self.commands)
        self.browser = Browser(self.app)
        csrf = self.browser.csrf()
        self.browser.request("POST", "/anmelden/code", {"csrf": csrf})
        self.browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})

    def run(self):
        """One cycle of the main thread."""
        self.dialog.poll_once()

    def form(self, path: str, *, action: str = "/aktion", index: int = 0, **match: str) -> dict:
        """Fields of the index-th form for the given action whose hidden fields match."""
        html = self.browser.request("GET", path).body.decode()
        forms = []
        for block in re.findall(r'<form method="post" action="([^"]+)"[^>]*>(.*?)</form>', html, re.S):
            if block[0] != action:
                continue
            fields = {name: unescape(value) for name, value in
                      re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block[1])}
            if all(fields.get(name) == value for name, value in match.items()):
                forms.append(fields)
        return forms[index]

    def submit(self, fields: dict, **headers):
        return self.browser.request("POST", "/aktion", fields, **headers)


@pytest.fixture
def web(tmp_path, monkeypatch):
    # Without a running main thread, waiting for a quick result only slows tests down.
    monkeypatch.setattr("mailhelp.web.site.SETTLE_SECONDS", 0)
    with JsonStore(tmp_path) as store:
        populate(store)
        yield Web(store)


def test_confirm_in_the_web_writes_once_and_reports_progress(web):
    fields = web.form("/", kind="confirm", proposal_id="elternabend")
    assert fields["version"] == "1" and len(fields["key"]) == 32
    response = web.submit(fields)
    location = response.headers["Location"]
    assert response.status == 303 and location.startswith("/aktion/")
    running = web.browser.request("GET", location).body.decode()
    assert '<meta http-equiv="refresh" content="1">' in running and "Wird ausgeführt" in running
    web.run()
    # Done: the browser goes back to the overview, which shows the result on top.
    done = web.browser.request("GET", location)
    entry_id = location.rsplit("/", 1)[1]
    assert done.status == 303 and done.headers["Location"] == f"/?ergebnis={entry_id}"
    overview = web.browser.request("GET", done.headers["Location"]).body.decode()
    assert '<p class="notice notice-ok" role="status">Angelegt.</p>' in overview
    assert web.writer.created == 1
    assert web.store.load(f"proposal-{MAIL1}-elternabend")["status"] == "created"
    assert any("✅ Angelegt im Kalender" in text for _, text, _ in web.telegram.sent)


def test_a_browser_retry_with_the_same_key_never_writes_twice(web):
    """Regression: a timeout followed by a resend must not create a second entry."""
    fields = web.form("/", kind="confirm", proposal_id="formular")
    first = web.submit(fields, accept="application/json")
    assert first.status == 202 and json.loads(first.body)["status"] == "queued"
    second = web.submit(fields, accept="application/json")
    assert json.loads(second.body)["id"] == json.loads(first.body)["id"]
    web.run()
    third = web.submit(fields)
    # The proposal is decided now; the retry is answered from the queue or as stale.
    assert third.status in {303, 409}
    web.run()
    assert web.writer.created == 1


def test_simultaneous_confirmation_in_telegram_and_web_writes_once(web):
    """Regression: the same version confirmed through both channels has one effect."""
    location = web.submit(web.form("/", kind="confirm", proposal_id="elternabend")).headers["Location"]
    item = Proposal.model_validate(web.store.load(f"proposal-{MAIL1}-elternabend"))
    token = web.dialog.presenter.present(item).reply_markup["inline_keyboard"][0][0]["callback_data"]
    web.telegram.updates = [callback(1, token)]
    web.run()
    # Telegram input of the cycle runs first; the queued web command then finds
    # the version decided and is refused instead of writing a second time.
    assert web.writer.created == 1
    result = web.commands.get(location.rsplit("/", 1)[1]).result
    assert result.status.value == "stale"
    back = web.browser.request("GET", location).headers["Location"]
    assert "notice-warn" in web.browser.request("GET", back).body.decode()
    assert "geändert oder entschieden" in web.browser.request("GET", back).body.decode()


def test_a_telegram_button_after_a_web_decision_is_reported_as_stale(web):
    item = Proposal.model_validate(web.store.load(f"proposal-{MAIL1}-formular"))
    token = web.dialog.presenter.present(item).reply_markup["inline_keyboard"][0][0]["callback_data"]
    web.submit(web.form("/", kind="reject", proposal_id="formular"))
    web.run()
    assert web.telegram.sent[-1][1] == "🌐 Im Web: Vorschlag verworfen."
    web.telegram.updates = [callback(2, token)]
    web.run()
    assert web.telegram.sent[-1][1] == STALE_BUTTON and web.telegram.removed
    assert web.writer.created == 0


def test_an_answer_in_the_web_creates_a_version_that_needs_confirmation(web):
    fields = web.form("/", kind="answer", proposal_id="zahnarzt")
    web.submit({**fields, "text": "10 Uhr"})
    web.run()
    # The start is known now; the end is asked next.
    follow_up = web.store.load(f"proposal-{mail_id(2)}-zahnarzt")
    assert follow_up["open_questions"] == ["Wann endet der Termin?"]
    web.submit({**web.form("/", kind="answer", proposal_id="zahnarzt"), "text": "10:30"})
    web.run()
    current = web.store.load(f"proposal-{mail_id(2)}-zahnarzt")
    assert (current["version"], current["status"]) == (3, "pending_confirmation")
    assert web.writer.created == 0
    # The old version is stale; the new one has its own confirm button.
    stale = web.submit({**web.form("/", kind="reject", proposal_id="zahnarzt"), "version": "1"})
    assert stale.status == 409 and "Version 3" in stale.body.decode()
    web.submit(web.form("/", kind="confirm", proposal_id="zahnarzt"))
    web.run()
    assert web.writer.versions == [3]


def test_yes_no_quick_answers_and_relevance(web):
    yes = web.form("/", kind="answer", proposal_id="fest", text="ja")
    assert web.form("/", kind="answer", proposal_id="fest", text="nein")
    web.submit(yes)
    relevance = web.form("/", kind="relevance", decision="irrelevant")
    web.dialog.relevance_handler = type("H", (), {
        "resolve_relevance": lambda self, *args: __import__(
            "test_telegram_dialog").RelevanceHandler(web.store).resolve_relevance(*args),
        "resume_mail": lambda self, state: None})()
    web.submit(relevance)
    web.run()
    assert web.store.load(f"proposal-{mail_id(3)}-fest")["version"] == 2
    assert web.store.load(f"mail-{mail_id(7)}")["relevance_dialog"]["decision"] == "irrelevant"
    assert "🌐 Im Web: Mail als irrelevant eingestuft." in [text for _, text, _ in web.telegram.sent]
    again = web.submit(relevance)
    assert again.status == 409 and "Relevanzfrage" in again.body.decode()


def test_duplicate_confirmation_is_offered_on_the_result_page(web):
    earlier = proposal(9, "alt", title="Einverständniserklärung Klassenfahrt zurückgeben",
                       due="2026-10-17", evidence="Bitte die Erklärung bis Freitag, 17.10., zurückgeben.")
    web.store.save("action-ledger", ActionLedger(entries=[ActionLedgerEntry(
        action_key=ActionLedgerService.action_key(earlier.model_copy(update={"source_mail_id": MAIL1, "id": "formular"})),
        action_key_version=2, mail_id=mail_id(9), proposal_id="alt", proposal_version=1, kind="task",
        title=earlier.title, target="Inbox")]).model_dump(mode="json"))
    location = web.submit(web.form("/", kind="confirm", proposal_id="formular")).headers["Location"]
    web.run()
    page = web.browser.request("GET", location).body.decode()
    assert "bereits früher angelegt" in page and "Erneut anlegen" in page
    web.submit(web.form(location, kind="confirm_duplicate"))
    web.run()
    assert web.writer.created == 1


def test_change_request_cancel_and_card_variants(web):
    fields = web.form("/", kind="answer", proposal_id="formular")
    assert "Ändern</summary>" in web.browser.request("GET", "/").body.decode()
    web.store.save("telegram-dialog", TelegramDialogState(
        mail_id=MAIL1, proposal_id="formular", version=1).model_dump(mode="json"))
    cancel = web.form("/", kind="cancel", proposal_id="formular")
    web.submit(cancel)
    web.run()
    assert web.store.load("telegram-dialog")["proposal_id"] is None
    assert fields["version"] == "1"
    detail = web.browser.request("GET", f"/vorschlag/{MAIL1}/formular").body.decode()
    assert 'action="/aktion"' in detail


def test_saved_and_paused_answers_show_no_buttons(web):
    views = {view.proposal_id: view for view in ReviewViews(web.store, "UTC").overview().open}
    render = proposal_actions("csrf")
    saved = views["zahnarzt"].__class__(**{**views["zahnarzt"].__dict__, "answer_saved": True})
    paused = views["zahnarzt"].__class__(**{**views["zahnarzt"].__dict__, "paused": True})
    closed = views["zahnarzt"].__class__(**{**views["zahnarzt"].__dict__, "actions": frozenset()})
    assert "Antwort gespeichert" in render(saved) and "<form" not in render(saved)
    assert "pausiert" in render(paused) and render(closed) == ""


@pytest.mark.parametrize("change", [
    {"kind": "unbekannt"}, {"version": "x"}, {"key": "kurz"}, {"mail_id": "zz"},
    {"kind": "answer", "text": ""},
])
def test_invalid_actions_are_refused(web, change):
    fields = web.form("/", kind="confirm", proposal_id="elternabend")
    response = web.submit({**fields, **change})
    assert response.status == 422
    assert web.submit({**fields, **change}, accept="application/json").status == 422


def test_stale_json_conflicts_and_a_full_queue(web, monkeypatch):
    fields = web.form("/", kind="confirm", proposal_id="elternabend")
    stale = web.submit({**fields, "version": "7"}, accept="application/json")
    assert stale.status == 409 and json.loads(stale.body)["current_version"] == 1
    missing = web.submit({**fields, "proposal_id": "weg"})
    assert missing.status == 409 and "Aktueller Stand" not in missing.body.decode()
    web.submit(fields)
    conflict = web.submit({**fields, "kind": "reject"})
    assert conflict.status == 422 and "anderen Angaben" in conflict.body.decode()
    monkeypatch.setattr("mailhelp.review.inbox.MAX_QUEUED", 1)
    full = web.submit(web.form("/", kind="reject", proposal_id="formular"))
    assert full.status == 503


def test_progress_is_private_to_the_session_and_available_as_json(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"]
    status = json.loads(web.browser.request("GET", location, accept="application/json").body)
    assert status["status"] == "queued" and status["result"] is None
    web.run()
    status = json.loads(web.browser.request("GET", location, accept="application/json").body)
    assert status["result"]["status"] == "done"
    other = Browser(web.app)
    csrf = other.csrf()
    other.request("POST", "/anmelden/code", {"csrf": csrf})
    messages = []
    web.auth.notify = messages.append
    other.request("POST", "/anmelden/code", {"csrf": csrf})
    other.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})
    assert other.request("GET", location).status == 404
    assert web.browser.request("GET", "/aktion/" + "0" * 32).status == 404


def test_rejected_and_failed_results_and_a_revoked_session(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"]
    web.auth.revoke_all()
    web.run()
    entry = web.commands.get(location.rsplit("/", 1)[1])
    assert entry.status == CommandStatus.REJECTED and entry.result.status.value == "unauthorized"
    assert web.store.load(f"proposal-{MAIL1}-formular")["status"] == "pending_confirmation"


def test_a_failing_telegram_notice_does_not_affect_the_result(web, monkeypatch):
    location = web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"]

    def down(*_args, **_kwargs):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(web.telegram, "send", down)
    web.run()
    assert web.commands.get(location.rsplit("/", 1)[1]).status == CommandStatus.DONE
    assert any(args[2] == "web_notice_failed" for args, _ in web.dialog.logger.events)


def test_paused_revision_offers_no_action(web):
    web.store.save(f"clarification-{mail_id(2)}-zahnarzt-v1", ProposalClarificationState(
        mail_id=mail_id(2), proposal_id="zahnarzt", version=1, question="Wann beginnt der Termin?",
        authorized_answer="10", answer_status="valid", question_status="answered",
        normalized_answer="10", interpretation_status="completed",
        proposal_revision_status=ProposalRevisionStatus.PAUSED).model_dump(mode="json"))
    html = web.browser.request("GET", f"/vorschlag/{mail_id(2)}/zahnarzt").body.decode()
    assert "pausiert" in html and 'value="answer"' not in html
    assert MAX_QUEUED == 50 and CommandKind.ANSWER.value == "answer"
    save_mail(web.store, 20, "x <x@x.test>", "x", [])
