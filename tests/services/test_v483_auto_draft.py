"""4.8, step 19.4: a reply draft without a click, only where the mailbox allows it."""
from contextlib import contextmanager
from email import message_from_bytes, policy
from types import SimpleNamespace

import pytest

from mailhelp import state_names
from mailhelp.config import PromptStep
from mailhelp.models import ActionRoute, MailState
from mailhelp.notifications.drafts import AUTO_KEY, DraftService, ReplyDraft
from mailhelp.processing.analysis import Analyzer
from mailhelp.processing.mail_pipeline import MailPipeline, ProcessingRun
from mailhelp.storage import JsonStore
from tests.fakes.shared_core import prompt_config
from tests.scenarios.web_scenario import mail_id, save_mail

MAIL = mail_id(70)


class Imap:
    def __init__(self, found=False):
        self.found, self.appended, self.searches = found, [], 0

    def select(self, folder, readonly):
        return "OK", []

    def uid(self, *args):
        self.searches += 1
        return "OK", [b"1" if self.found else b""]

    def append(self, folder, flags, date, content):
        self.appended.append((folder, flags, content))
        return "OK", []


class Writer:
    def __init__(self):
        self.calls = []

    def draft_reply(self, mail, intent, personal_info, reason=None):
        self.calls.append((intent, personal_info, reason))
        return "call-1", ReplyDraft(text="Vielen Dank für Ihre Anfrage. [Termin vorschlagen]\n\nGrüße")


def service(store, imap, *, auto=True, smart=True, test_mode=False, policy=True):
    @contextmanager
    def connection():
        yield imap

    drafts = DraftService(store, lambda actor: False, connection, "Ich <ich@example.test>", "Drafts", test_mode,
                          Writer(), lambda: "Global", mailbox_policy=(lambda account: (smart, "Postfach-Signatur"))
                          if policy else None)
    drafts.auto_policy = lambda account: auto
    return drafts


@pytest.fixture
def store(tmp_path):
    with JsonStore(tmp_path / "data") as opened:
        save_mail(opened, 70, "Kundin <kundin@example.test>", "AW: Hofführung", text="Wann haben Sie Zeit?")
        yield opened


def test_an_enabled_mailbox_gets_the_draft_in_its_drafts_folder(store):
    imap = Imap()
    drafts = service(store, imap)
    assert drafts.auto_draft(MAIL, "Zeitvorschlag für die Hofführung") == "saved"
    assert drafts.analyzer.calls == [("reply", "Postfach-Signatur", "Zeitvorschlag für die Hofführung")]
    ((folder, flags, content),) = imap.appended
    assert folder == "Drafts" and flags == r"(\Draft \Seen)"
    sent = message_from_bytes(content, policy=policy.default)
    assert sent["Subject"] == "Re: Hofführung" and sent["To"] == "kundin@example.test"
    assert sent["Message-ID"] == f"<mailhelp-{MAIL}-v1@draft.local>"
    stored = drafts.get(MAIL)
    assert (stored["auto"], stored["status"], stored["intent"], stored["version"]) == (True, "saved", "reply", 1)
    assert AUTO_KEY in stored["operations"]


@pytest.mark.parametrize("settings", [dict(auto=False), dict(smart=False)])
def test_without_both_settings_nothing_is_generated(store, settings):
    imap = Imap()
    drafts = service(store, imap, **settings)
    assert drafts.auto_draft(MAIL, None) == "skipped"
    assert drafts.analyzer.calls == [] and imap.appended == [] and drafts.get(MAIL) is None


def test_a_draft_the_user_started_is_never_replaced(store):
    store.save(state_names.draft(MAIL), {"version": 2, "text": "Mein Text", "status": "editing", "operations": {}})
    drafts = service(store, Imap())
    assert drafts.auto_draft(MAIL, None) == "skipped" and drafts.analyzer.calls == []
    assert drafts.get(MAIL)["text"] == "Mein Text"


def test_an_unclear_automatic_draft_is_reconciled_and_not_written_again(store):
    store.save(state_names.draft(MAIL), {"version": 1, "text": "Entwurf", "status": "uncertain", "operations": {},
                                         "auto": True})
    imap = Imap(found=True)
    drafts = service(store, imap)
    assert drafts.auto_draft(MAIL, None) == "saved"
    assert drafts.analyzer.calls == [] and imap.appended == [] and imap.searches == 1


def test_a_finished_automatic_draft_is_not_written_twice(store):
    imap = Imap()
    drafts = service(store, imap)
    drafts.auto_draft(MAIL, None)
    assert drafts.auto_draft(MAIL, None) == "skipped" and len(imap.appended) == 1


def test_test_mode_simulates_without_the_mailbox(store):
    imap = Imap()
    drafts = service(store, imap, test_mode=True)
    assert drafts.auto_draft(MAIL, None) == "simulated" and imap.appended == []


def test_without_a_mailbox_policy_the_global_signature_is_used(store):
    drafts = service(store, Imap(), policy=False)
    drafts.auto_draft(MAIL, None)
    assert drafts.analyzer.calls == [("reply", "Global", None)]


def test_a_mail_without_content_gets_no_draft(store):
    state = store.load_model(state_names.mail(MAIL), MailState)
    store.save(state_names.mail(MAIL), state.model_copy(update={"mail": None}).model_dump(mode="json"))
    assert service(store, Imap()).auto_draft(MAIL, None) == "skipped"
    assert service(store, Imap()).auto_draft(mail_id(71), None) == "skipped"  # unknown mail


class Recorder:
    def __init__(self):
        self.events = []

    def event(self, level, module, name, **context):
        self.events.append((level, name, context))


def pipeline_step(store, *, route, drafts):
    state = store.load_model(state_names.mail(MAIL), MailState).model_copy(update={"action_route": route})
    owner = SimpleNamespace(drafts=drafts, logger=Recorder(), save=lambda name, value: None)
    run = ProcessingRun(state_names.mail(MAIL), state, None, 0.0)
    MailPipeline(owner)._auto_draft(run)
    return run.state.steps.auto_draft, owner.logger.events


ROUTE = ActionRoute(action_state="none", task_count=0, event_count=0, reason="x", reply_needed=True,
                    reply_reason="Antwort auf die Anfrage")


def test_the_pipeline_drafts_only_where_a_reply_is_needed(store):
    imap = Imap()
    step, events = pipeline_step(store, route=ROUTE, drafts=service(store, imap))
    assert step == "completed" and len(imap.appended) == 1
    assert events == [("INFO", "auto_draft_completed", {"mail_id": MAIL, "outcome": "saved"})]
    for route, drafts in ((ROUTE.model_copy(update={"reply_needed": False}), service(store, Imap())),
                          (ROUTE, None), (None, service(store, Imap()))):
        assert pipeline_step(store, route=route, drafts=drafts)[0] == "skipped"
    assert pipeline_step(store, route=ROUTE, drafts=service(store, Imap(), auto=False))[0] == "skipped"


def test_a_failing_draft_never_stops_the_mail(store):
    class Broken:
        def auto_draft(self, mail_id, reason):
            raise ConnectionError("synthetic")

    step, events = pipeline_step(store, route=ROUTE, drafts=Broken())
    assert step == "failed" and events == [("WARNING", "auto_draft_failed",
                                            {"mail_id": MAIL, "error": "ConnectionError"})]


def test_a_step_that_already_ran_is_not_repeated(store):
    state = store.load_model(state_names.mail(MAIL), MailState)
    state.steps.auto_draft = "completed"
    owner = SimpleNamespace(drafts=None, logger=Recorder(), save=lambda name, value: None)
    run = ProcessingRun(state_names.mail(MAIL), state.model_copy(update={"action_route": ROUTE}), None, 0.0)
    MailPipeline(owner)._auto_draft(run)
    assert run.state.steps.auto_draft == "completed" and owner.logger.events == []


class Completer:
    def __init__(self):
        self.payloads = []

    def complete(self, model, parameters, system, payload, **metadata):
        self.payloads.append(payload)
        return "call", {"text": "Danke."}


def test_the_reason_reaches_the_draft_prompt_only_for_automatic_drafts():
    client = Completer()
    prompts = prompt_config()
    prompts.prompts["draft_reply"] = PromptStep(system_prompt="Draft")
    analyzer = Analyzer(client, prompts, 0)
    analyzer.draft_reply({"headers": {"from": "a@b.test"}, "text": "x"}, "reply", "Sig", reason="Zeit nennen")
    analyzer.draft_reply({"headers": {"from": "a@b.test"}, "text": "x"}, "accept", "Sig")
    assert client.payloads[0]["reply_reason"] == "Zeit nennen" and "reply_reason" not in client.payloads[1]
