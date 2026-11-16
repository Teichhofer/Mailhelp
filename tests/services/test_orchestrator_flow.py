"""The orchestrator: mail answers, routing, resumption and failure notices."""
from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mailhelp.config import TargetSettings, Topic
from mailhelp.domain.mail import ActionRoute
from mailhelp.domain.proposal import (
    Proposal,
)
from mailhelp.domain.relevance import RelevanceDialog
from mailhelp.llm.adapter import PermanentError
from mailhelp.llm.openrouter import RateLimitExceeded
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mime import MimeLimits
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.analysis import (
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationExceeded,
    LlmSchemaValidationFailed,
)
from mailhelp.processing.orchestrator import MailState, Orchestrator, ProcessingOutcome
from tests.fakes.shared_core import proposal
from tests.fakes.shared_services import (
    AnalyzerStub,
    Notify,
    _MailQuestionAnalyzer,
    _resolve_from_mail,
)


def test_orchestrator_resolves_mail_answer_before_telegram(tmp_path):
    class MailAnswerAnalyzer(AnalyzerStub):
        def extract_tasks(self, mail, *, expected_count):
            from mailhelp.domain.extraction import ExtractedTask
            from mailhelp.domain.mail import TaskExtraction
            return "t", TaskExtraction(tasks=[ExtractedTask(
                title="Unterlagen senden", description="", evidence="Bitte senden Sie",
                responsibility="unclear", certainty="certain", classification="new")])

        def answer_question_from_mail(self, mail, proposal, question):
            from mailhelp.domain.extraction import TelegramAnswerInterpretation
            assert mail["text"] == "Bitte senden Sie die Unterlagen selbst."
            assert question in proposal.open_questions
            return "mq", TelegramAnswerInterpretation(
                usable=True, normalized_answer="Die nutzende Person ist zuständig.",
                reason="Die Mail richtet die Bitte ausdrücklich an sie.")

        def revise_proposal(self, proposal, question, answer):
            from mailhelp.domain.proposal import Proposal
            assert answer == "Die nutzende Person ist zuständig."
            return "rev", Proposal.model_validate({**proposal.model_dump(mode="json"),
                "version": proposal.version + 1,
                "responsibility": "user",
                "open_questions": [],
                "status": "pending_confirmation",
            })

    notify = Notify()
    raw = (b"From: Beispiel <sender@example.test>\nSubject: Unterlagen\n"
           b"Message-ID: <mail-answer@example.test>\n\n"
           b"Bitte senden Sie die Unterlagen selbst.")
    with JsonStore(tmp_path / "mail-answer") as store:
        result = Orchestrator(
            MailAnswerAnalyzer("relevant"), store, notify, 1,
            [Topic(id="x", name="X", enabled=True, description="X")], 1000,
        ).process(FetchedMail("INBOX", 1, 95, raw))

    revised = result.state["proposals"][0]
    assert revised["version"] == 2
    assert revised["open_questions"] == []
    assert revised["status"] == "pending_confirmation"
    assert result.state["llm_call_ids"][-2:] == ["mq", "rev"]








def test_regression_mail_answer_with_clock_is_applied_deterministically(tmp_path):
    """Regression 2026-10-08 (B2): "13:00" from the mail was lost.

    The LLM revision returned no change without a trusted offset, yet the
    question was logged as resolved and the user was asked for the start again.
    """
    item = proposal(kind="event", status="needs_clarification",
                    open_questions=["Wann beginnt der Termin?", "Wann endet der Termin?"],
                    temporal_fact={"raw_text": "07.10.2026", "normalized_date": "2026-10-07",
                                   "year_source": "explicit_mail", "status": "resolved"})
    analyzer = _MailQuestionAnalyzer({"Wann beginnt der Termin?": "2026-10-07 13:00"})
    state, events = _resolve_from_mail(tmp_path, analyzer, item)
    revised = state.proposals[0]
    assert revised.start.isoformat() == "2026-10-07T13:00:00+02:00"
    assert revised.open_questions == ["Wann endet der Termin?"]
    assert analyzer.revisions == 0 and state.llm_call_ids == ["mq", "mq"]
    assert events == [
        ("mail_question_resolved", "Wann beginnt der Termin?", None),
        ("mail_question_unanswered", "Wann endet der Termin?", "not_answered_by_mail"),
    ]


def test_regression_mail_answer_with_date_keeps_known_start_time(tmp_path):
    """Regression 2026-10-08 (B2): the resolved "kommenden Freitag" was dropped."""
    question = "Welches konkrete Datum ist mit „kommenden Freitag“ gemeint?"
    item = proposal(kind="event", status="needs_clarification",
                    open_questions=[question, "Wann endet der Termin?"],
                    known_temporal_facts={"start_time": "08:00:00"})
    state, _ = _resolve_from_mail(tmp_path, _MailQuestionAnalyzer({question: "2026-10-02"}), item)
    revised = state.proposals[0]
    # Until the end is known, the start is kept as an application-owned fact.
    assert revised.known_temporal_facts.start.isoformat() == "2026-10-02T08:00:00+02:00"
    assert revised.temporal_fact.normalized_date == date(2026, 10, 2)
    assert revised.open_questions == ["Wann endet der Termin?"]


def test_mail_answer_revision_without_effect_keeps_the_question_open(tmp_path):
    item = proposal(open_questions=["Welcher Titel?"])

    def unchanged(previous):
        return Proposal.model_validate({**previous.model_dump(mode="json"),
                                        "version": previous.version + 1, "open_questions": []})

    analyzer = _MailQuestionAnalyzer({"Welcher Titel?": "Tun"}, unchanged)
    state, events = _resolve_from_mail(tmp_path, analyzer, item)
    assert state.proposals[0] == item
    assert state.llm_call_ids == ["mq", "rev"]
    assert events == [("mail_question_unanswered", "Welcher Titel?", "revision_without_effect")]


@pytest.mark.parametrize(("answer", "failure", "error_class"), [
    ("Neu", LlmSchemaValidationFailed("proposal_revision"), "LlmSchemaValidationFailed"),
    ("2026-10-09 13:00", None, "ContradictoryRevision"),
])
def test_failed_mail_answer_revision_leaves_question_for_telegram(tmp_path, answer, failure,
                                                                  error_class):
    question = "Welcher Titel?" if failure is not None else "Wann beginnt der Termin?"
    item = (proposal(open_questions=[question]) if failure is not None else
            proposal(kind="event", status="needs_clarification", open_questions=[question],
                     temporal_fact={"raw_text": "07.10.2026", "normalized_date": "2026-10-07",
                                    "year_source": "explicit_mail", "status": "resolved"}))
    analyzer = _MailQuestionAnalyzer({question: answer}, failure or AssertionError("nie"))
    state, events = _resolve_from_mail(tmp_path, analyzer, item)
    assert state.proposals[0] == item
    assert events == [("mail_question_unanswered", question, "revision_failed")]


def test_transient_provider_failure_during_mail_answer_revision_is_retried_later(tmp_path):
    analyzer = _MailQuestionAnalyzer(
        {"Welcher Titel?": "Neu"}, LlmProviderResponseInvalid("proposal_revision", "timeout"))
    with pytest.raises(LlmProviderResponseInvalid):
        _resolve_from_mail(tmp_path, analyzer, proposal(open_questions=["Welcher Titel?"]))


def test_orchestrator_complete_notification_uses_validated_values(tmp_path):
    class CompleteAnalyzer(AnalyzerStub):
        def relevance(self, mail, topics):
            from mailhelp.domain.relevance import Relevance
            return "r", Relevance(decision="relevant", topic_ids=["billing"], reason="yes")
        def summary(self, mail):
            from mailhelp.domain.mail import Summary
            return "s", Summary(sentences=["Satz eins.", "Satz zwei."], deadlines=["31.12.2026"])
        def actions(self, mail):
            from mailhelp.domain.proposal import Actions
            return "a", Actions(proposals=[proposal(source_mail_id=mail["internal_id"])])
    topic=Topic(id="billing",name="Abrechnung",enabled=True,description="x")
    raw=b"From: Alice <alice@example.test>\nSubject: Rechnung\n\nBody"
    notify=Notify()
    with JsonStore(tmp_path) as store:
        Orchestrator(CompleteAnalyzer("relevant"),store,notify,1,[topic],1000,
                     targets=TargetSettings(todoist_project="inbox",google_calendar="primary")).process(FetchedMail("INBOX",1,91,raw))
    summary=notify.messages[0]
    # One compact mail line (sender name, subject), then the sentences.
    assert summary == "\n".join([
        "✉️ Alice · Rechnung",
        "• Satz eins.",
        "• Satz zwei.",
        "Fristen: 31.12.2026",
    ])
    assert "Mail-ID" not in summary


# B6: "unclear" without any candidate is stored as "none" and sends no hint;
# the hint for "unclear" with a candidate is covered by the tests below.
@pytest.mark.parametrize(("route", "stored", "expected_messages"),
                         [("none", "none", 1), ("unclear", "none", 1)])
def test_orchestrator_skips_extractor_for_none_and_business_clarification(tmp_path, route, stored,
                                                                          expected_messages):
    class RoutedAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute(action_state=route, task_count=0, event_count=0,
                                     reason="Art der Aktion ist fachlich unklar.")
        def actions(self, mail):
            raise AssertionError("Extractor darf nicht aufgerufen werden")
    topic=Topic(id="x",name="x",enabled=True,description="x")
    notify=Notify()
    with JsonStore(tmp_path / route) as store:
        result=Orchestrator(RoutedAnalyzer("relevant"),store,notify,1,[topic],1000).process(
            FetchedMail("INBOX",1,93,b"Subject: Router\n\nBody"))
    assert result.outcome is ProcessingOutcome.COMPLETED
    assert result["action_route"]["action_state"] == stored
    assert result["proposals"] == [] and result["error"] is None
    assert len(notify.messages) == expected_messages


def test_orchestrator_sends_event_candidate_even_when_route_is_unclear(tmp_path):
    class UnclearEventAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute(action_state="unclear", task_count=0, event_count=1,
                                     reason="Der Termin ist erkannt, die Einladung ist unklar.")

        def extract_events(self, mail, *, expected_count):
            from mailhelp.domain.extraction import ExtractedEvent
            from mailhelp.domain.mail import EventExtraction
            return "e", EventExtraction(events=[ExtractedEvent(
                title="Gemeinderatssitzung", evidence="Sitzung am 22.09.2026",
                date_text="22.09.2026", time_requirement="required_unknown", responsibility="unclear",
                certainty="certain", classification="new")])

        def extract_tasks(self, mail, *, expected_count):
            raise AssertionError("Ohne Aufgabenkandidat darf keine Aufgabenextraktion laufen")

    notify = Notify()
    topic = Topic(id="kommune", name="Kommune", enabled=True,
                  description="Gemeinderat")
    raw = (b"Date: Fri, 18 Sep 2026 17:24:41 +0000\n"
           b"Subject: GR-Sitzung am 22.09.2026\n\nWeitere Tagesordnungspunkte")
    with JsonStore(tmp_path / "unclear-event") as store:
        result = Orchestrator(UnclearEventAnalyzer("relevant"), store, notify, 1,
                              [topic], 1000, user_timezone="Europe/Berlin").process(
                                  FetchedMail("INBOX", 1, 94, raw))

    assert result.outcome is ProcessingOutcome.COMPLETED
    assert result["steps"]["task_extraction"] == "skipped"
    assert result["steps"]["event_extraction"] == "completed"
    assert result["event_extraction"]["events"][0]["title"] == "Gemeinderatssitzung"
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["kind"] == "event"
    assert result["proposals"][0]["status"] == "needs_clarification"
    assert "fachliche Klärung" in notify.messages[1]
    assert notify.messages[2] == result["proposals"][0]["id"]


def test_regression_unclear_route_without_candidate_sends_no_hint(tmp_path):
    """Regression 2026-10-08 (B6): a Teams access block became "unclear" 0/0.

    Without any candidate there is nothing to review; the generic hint
    "benötigt fachliche Klärung" was noise without a possible action.
    """
    route = {"action_state": "unclear", "task_count": 0, "event_count": 0,
             "reason": "Nur Zugangsdaten ohne Termin oder Einladung."}
    assert ActionRoute.model_validate(route).action_state == "none"
    assert ActionRoute(action_state="unclear", task_count=0, event_count=1,
                       reason="Möglicher Termin").action_state == "unclear"
    router = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))[
        "prompts"]["action_router"]["system_prompt"]
    assert 'Verwende "unclear" nur, wenn mindestens ein möglicher' in router

    class AccessDataAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute.model_validate(route)

    notify = Notify()
    raw = b"Subject: Teams-Besprechung\n\nBesprechungs-ID: 123 456\nPasscode: abc"
    with JsonStore(tmp_path / "access-data") as store:
        result = Orchestrator(AccessDataAnalyzer("relevant"), store, notify, 1,
                              [Topic(id="x", name="X", enabled=True, description="X")],
                              1000).process(FetchedMail("INBOX", 1, 96, raw))
    assert result.outcome is ProcessingOutcome.COMPLETED
    assert result["proposals"] == []
    assert not any("fachliche Klärung" in str(message) for message in notify.messages)


def test_orchestrator_sends_task_candidate_even_when_route_is_unclear(tmp_path):
    class UnclearTaskAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute(action_state="unclear", task_count=1, event_count=0,
                                     reason="Die freiwillige Buchung wurde erkannt.")

        def extract_tasks(self, mail, *, expected_count):
            from mailhelp.domain.extraction import ExtractedTask
            from mailhelp.domain.mail import TaskExtraction
            assert expected_count == 1
            return "t", TaskExtraction(tasks=[ExtractedTask(
                title="Optional ein Gespräch buchen",
                description="Freiwillige Buchung: https://booking.example.test/sunrise",
                evidence="Einen Termin können Sie hier direkt buchen",
                responsibility="user", certainty="certain", classification="new",
                due_text=None)])

        def extract_events(self, mail, *, expected_count):
            raise AssertionError("Ohne gebuchten Zeitpunkt darf keine Terminextraktion laufen")

    notify = Notify()
    topic = Topic(id="vertrieb", name="Vertrieb", enabled=True, description="Gespräche")
    with JsonStore(tmp_path / "unclear-task") as store:
        result = Orchestrator(UnclearTaskAnalyzer("relevant"), store, notify, 1,
                              [topic], 1000).process(FetchedMail(
                                  "INBOX", 1, 95,
                                  b"Subject: Gespraech\n\nTermin optional per Link buchen"))

    assert result.outcome is ProcessingOutcome.COMPLETED
    assert result["steps"]["task_extraction"] == "completed"
    assert result["steps"]["event_extraction"] == "skipped"
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["kind"] == "task"
    assert result["proposals"][0]["due"] is None
    assert result["proposals"][0]["status"] == "pending_confirmation"
    assert "https://booking.example.test/sunrise" in result["proposals"][0]["description"]


def test_proposal_boundary_builds_internal_identity_and_routing(tmp_path):
    topic=Topic(id="x",name="x",enabled=True,description="x")
    targets=TargetSettings(todoist_project="trusted-project", google_calendar="trusted-calendar")
    with JsonStore(tmp_path) as store:
        orchestrator=Orchestrator(AnalyzerStub("relevant"),store,Notify(),1,[topic],1000,targets=targets)
        state=MailState(id="a"*24,config_fingerprint="0"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1})
        from mailhelp.domain.extraction import ExtractedEvent, ExtractedTask
        from mailhelp.domain.mail import EventExtraction, TaskExtraction
        state.mail = {"date_context_status":"valid", "date_header_parsed":"2026-01-01T08:00:00Z",
                      "imap_received_at":"2026-01-01T08:00:00Z", "user_timezone":"UTC"}
        state.task_extraction = TaskExtraction(tasks=[ExtractedTask(title="t", description="", evidence="e",
            responsibility="user", certainty="certain", classification="new")])
        state.event_extraction = EventExtraction(events=[ExtractedEvent(title="e", evidence="e", date_text="2026-01-01", time_requirement="required_unknown",
            responsibility="user", certainty="certain", classification="new")])
        normalized=orchestrator.build_proposals(state)
        assert [item.target for item in normalized] == ["trusted-project","trusted-calendar"]
        assert all(item.id.startswith("p_") for item in normalized)


def test_orchestrator(tmp_path):
    raw=b"Subject: Test\n\nBody"
    mail=FetchedMail("INBOX",1,2,raw)
    topic=Topic(id="x",name="x",enabled=True,description="x")
    with JsonStore(tmp_path/"a") as store:
        class PlainNotify:
            def __init__(self): self.messages=[]
            def send(self,c,t): self.messages.append(t)
            def send_proposal(self,p): self.messages.append(p.id)
        n=PlainNotify()
        o=Orchestrator(AnalyzerStub("relevant"),store,n,1,[topic],1000)
        state=o.process(mail)
        assert state.outcome is ProcessingOutcome.COMPLETED and state["steps"]["completion"]=="completed" and n.messages
        assert o.process(mail)==state
    with JsonStore(tmp_path/"b") as store:
        state=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000).process(mail)
        assert state["steps"]=={"preparation":"completed","relevance":"completed","summary":"skipped","summary_notification":"skipped","action_detection":"skipped","action_router":"skipped","task_extraction":"skipped","event_extraction":"skipped","normalization":"skipped","proposal_building":"skipped","duplicate_precheck":"skipped","proposal_notification":"skipped","auto_draft":"skipped","completion":"completed"}
    with JsonStore(tmp_path/"blocked") as store:
        from mailhelp.domain.relevance import IrrelevantSenders
        sender_store = JsonStore(tmp_path / "config")
        sender_store.save("irrelevant-senders", IrrelevantSenders(
            domains=["example.test"]).model_dump())
        analyzer = AnalyzerStub("relevant")
        blocked_mail = FetchedMail("INBOX", 1, 3, b"From: News <bot@example.test>\nSubject: Sale\n\nBody")
        state = Orchestrator(
            analyzer, store, Notify(), 1, [topic], 1000, sender_store=sender_store
        ).process(blocked_mail)
        assert state["relevance"] == {
            "decision": "irrelevant", "topic_ids": [], "reason": "Absender-Vorfilter"
        }
        assert state["llm_call_ids"] == []
        assert not (store.directory / "irrelevant-senders.json").exists()
    with JsonStore(tmp_path/"c") as store:
        o=Orchestrator(AnalyzerStub("unclear"),store,Notify(),1,[topic],1000)
        state=o.process(mail)
        assert state.outcome is ProcessingOutcome.WAITING and state["awaiting_relevance"] and state["steps"]["completion"]=="pending"
        assert o.process(mail)==state
    with JsonStore(tmp_path/"d") as store:
        notify=Notify()
        oversized = FetchedMail("INBOX", 1, 2,
            b"From: safe@example.test\nSubject: Safe subject\n\n" + b"x" * 2_000)
        failed=Orchestrator(AnalyzerStub("relevant"),store,notify,1,[topic],1).process(oversized)
        assert failed.outcome is ProcessingOutcome.FAILED and "error" in failed
        assert notify.messages == [
            "✉️ safe@example.test · Safe subject\n⚠️ Schritt preparation: "
            "Mail wird nicht weiter versucht. Die Nachricht überschreitet ein Sicherheitslimit. Bitte Anhänge oder Nachrichtengröße reduzieren."
        ]
        assert failed["id"] not in notify.messages[0]
        assert failed["mail"] is None and failed["display_headers"] == {
            "sender": "safe@example.test", "subject": "Safe subject"}
    with JsonStore(tmp_path/"e") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000)
        count=[]
        def poll():
            count.append(1)
            o.stop()
            return [mail]
        o.run(poll,0,lambda _:None)
        assert count==[1]
    with JsonStore(tmp_path/"f") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000)
        waits=[]
        def wait(x):
            waits.append(x)
            o.stop()
        o.run(lambda: [mail],2,wait)
        assert waits==[2]

    class ProposalAnalyzer(AnalyzerStub):
        def actions(self,m):
            from mailhelp.domain.proposal import Actions
            return "a",Actions(proposals=[proposal(source_mail_id=m["internal_id"])])
    with JsonStore(tmp_path/"g") as store:
        notify=Notify()
        Orchestrator(ProposalAnalyzer("relevant"),store,notify,1,[topic],1000,
                                      targets=TargetSettings(todoist_project="inbox",google_calendar="primary")).process(mail)
        assert any(message.startswith("p_") for message in notify.messages)
    with JsonStore(tmp_path/"multiple") as store:
        analyzer=AnalyzerStub("irrelevant")
        orchestrator=Orchestrator(analyzer,store,Notify(),1,[topic],1000)
        first=orchestrator.process(mail)
        second=orchestrator.process(FetchedMail("INBOX",1,3,b"Subject: Other\n\nBody"))
        assert first["id"] != second["id"] and all(item["steps"]["completion"]=="completed" for item in (first,second))


def test_orchestrator_pins_fingerprint_across_restart(tmp_path):
    topic=Topic(id="x",name="x",enabled=True,description="x")
    mail=FetchedMail("INBOX",1,77,b"Subject: Restart\n\nBody")
    with JsonStore(tmp_path/"fingerprint") as store:
        first=Orchestrator(AnalyzerStub("unclear"),store,Notify(),1,[topic],1000,
                           config_fingerprint="a"*64).process(mail)
        changed=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000,
                             config_fingerprint="b"*64).process(mail)
        persisted=store.load_model("mail-"+first["id"],MailState)
        assert changed.outcome is ProcessingOutcome.WAITING
        assert changed["config_fingerprint"] == persisted.config_fingerprint == "a"*64
        assert changed["updated_at"] == first["updated_at"]


def test_orchestrator_resolves_versioned_relevance_both_ways(tmp_path):
    topic=Topic(id="x",name="x",enabled=True,description="x")
    for uid,decision in ((31,"irrelevant"),(32,"relevant")):
        with JsonStore(tmp_path/decision) as store:
            notify=Notify()
            orchestrator=Orchestrator(AnalyzerStub("unclear"),store,notify,1,[topic],1000)
            waiting=orchestrator.process(FetchedMail("INBOX",1,uid,b"From: Alice <alice@example.test>\nSubject: Private\n\nSecret"))
            mail_id=waiting["id"]
            assert notify.messages == [(mail_id,"Alice <alice@example.test>","Private")]
            with pytest.raises(ValueError,match="nicht gefunden"): orchestrator.resolve_relevance("f"*24,1,decision,10)
            with pytest.raises(ValueError,match="veraltet"): orchestrator.resolve_relevance(mail_id,2,decision,10)
            with pytest.raises(ValueError,match="Ungültige"): orchestrator.resolve_relevance(mail_id,1,"maybe",10)
            resolved=orchestrator.resolve_relevance(mail_id,1,decision,10)
            assert resolved.relevance_dialog.telegram_offset==10
            with pytest.raises(ValueError,match="bereits"): orchestrator.resolve_relevance(mail_id,1,decision,11)
            if decision == "irrelevant":
                assert resolved.steps.model_dump()=={"preparation":"completed","relevance":"completed","summary":"skipped","summary_notification":"skipped","action_detection":"skipped","action_router":"skipped","task_extraction":"skipped","event_extraction":"skipped","normalization":"skipped","proposal_building":"skipped","duplicate_precheck":"skipped","proposal_notification":"skipped","auto_draft":"skipped","completion":"completed"}
            else:
                completed=orchestrator.resume_mail(resolved)
                assert completed.outcome is ProcessingOutcome.COMPLETED
                assert completed["steps"]["summary"]==completed["steps"]["action_detection"]=="completed"
                assert notify.messages[1] == "\n".join([
                    "✉️ Alice · Private",
                    "• eins",
                    "• zwei",
                ])
                assert len(notify.messages) == 2


def test_relevance_dialog_schema_consistency():
    with pytest.raises(ValidationError): RelevanceDialog(mail_id="a"*24,decision="relevant")
    with pytest.raises(Exception,match="gehört nicht"):
        MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},awaiting_relevance=True,relevance_dialog=RelevanceDialog(mail_id="b"*24))
    with pytest.raises(Exception,match="benötigt"):
        MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},awaiting_relevance=True)
    with pytest.raises(Exception,match="widersprechen"):
        MailState(id="a"*24,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},relevance_dialog=RelevanceDialog(mail_id="a"*24))


@pytest.mark.slow
def test_orchestrator_resumes_each_persisted_analysis_step(tmp_path):
    raw=b"Subject: Restart\n\nBody"
    mail=FetchedMail("INBOX",1,9,raw)
    topic=Topic(id="x",name="x",enabled=True,description="x")
    class CountingAnalyzer(AnalyzerStub):
        def __init__(self):
            super().__init__("relevant")
            self.calls=[]
        def relevance(self,m,t):
            self.calls.append("relevance")
            return super().relevance(m,t)
        def summary(self,m):
            self.calls.append("summary")
            return super().summary(m)
        def action_route(self,m):
            self.calls.append("action_router")
            return super().action_route(m)
        def extract_tasks(self,m, *, expected_count):
            self.calls.append("task_extraction")
            return super().extract_tasks(m, expected_count=expected_count)
    from tests.fakes.store_fakes import InterruptingStore
    # Every durable boundary, including normalization, proposal construction and
    # both sides of the per-version Telegram delivery marker, is interrupted.
    with JsonStore(tmp_path/"boundaries") as disk:
        counting = InterruptingStore(disk, 1000000)
        Orchestrator(CountingAnalyzer(), counting, Notify(), 1, [topic], 1000).process(mail)
        boundary_count = counting.count
    for fail_at in range(2, boundary_count + 1):
        with JsonStore(tmp_path/str(fail_at)) as disk:
            first=CountingAnalyzer()
            notify = Notify()
            with pytest.raises(RuntimeError,match="power loss"):
                Orchestrator(first,InterruptingStore(disk,fail_at),notify,1,[topic],1000).process(mail)
            second=CountingAnalyzer()
            import time
            result=Orchestrator(second,disk,notify,1,[topic],1000,clock=lambda: time.time() + 65).process(mail)
            assert result["steps"]["completion"]=="completed"
            assert second.calls == [step for step in ("relevance", "summary", "action_router", "task_extraction") if step in second.calls]
            assert len(second.calls) == len(set(second.calls))
            assert notify.messages.count(result["proposals"][0]["id"]) == 1
            assert result["proposal_notifications"][0]["status"] in {"sending", "completed"}

    with JsonStore(tmp_path/"invalid") as store:
        store.save("mail-"+"a"*24,{"schema_version":3,"id":"bad","imap":{},"steps":{}})
        with pytest.raises(ValidationError): MailState.model_validate(store.load("mail-"+"a"*24))


def test_gemeinderat_action_failure_preserves_summary_and_retries_only_actions(tmp_path):
    class CouncilAnalyzer(AnalyzerStub):
        def __init__(self):
            super().__init__("relevant")
            self.calls = []
            self.fail_actions = True
        def relevance(self, mail, topics):
            self.calls.append("relevance")
            return super().relevance(mail, topics)
        def summary(self, mail):
            self.calls.append("summary")
            return super().summary(mail)
        def action_route(self, mail):
            self.calls.append("action_router")
            return "ar", ActionRoute(action_state="event", task_count=0, event_count=1,
                                     reason="Eine Gemeinderatssitzung ist ein Termin.")
        def extract_events(self, mail, *, expected_count):
            self.calls.append("events")
            if self.fail_actions:
                raise LlmSchemaValidationExceeded("event_extraction")
            from mailhelp.domain.extraction import ExtractedEvent
            from mailhelp.domain.mail import EventExtraction
            return "e", EventExtraction(events=[ExtractedEvent(
                title="Gemeinderatssitzung", evidence="Sitzung am 22.09.2026",
                date_text="22.09.2026", time_text=None, end_time_text=None,
                location=None, video_link=None, time_requirement="required_unknown", responsibility="unclear",
                certainty="uncertain", classification="new")])

    raw = (b"From: Gemeinderat <rat@example.test>\nSubject: Sitzung\n\n"
           b"Synthetische Einladung zur Gemeinderatssitzung")
    mail = FetchedMail("INBOX", 1, 92, raw)
    topic = Topic(id="kommune", name="Kommune", enabled=True, description="Gemeinderat")
    analyzer, notify = CouncilAnalyzer(), Notify()
    with JsonStore(tmp_path / "gemeinderat") as store:
        orchestrator = Orchestrator(analyzer, store, notify, 1, [topic], 1000)
        partial = orchestrator.process(mail)
        assert partial.outcome is ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR
        assert partial["steps"]["summary"] == "completed"
        assert partial["steps"]["summary_notification"] == "completed"
        assert partial["steps"]["action_detection"] == "failed"
        assert partial["action_route"] == {
            "action_state": "event", "task_count": 0, "event_count": 1,
            "reason": "Eine Gemeinderatssitzung ist ein Termin.",
            "reply_needed": False, "reply_reason": None,  # 4.8: stored with their defaults
        }
        assert partial["steps"]["completion"] == "completed"
        assert "• " in notify.messages[0]
        assert not any("Schritt event_extraction:" in message for message in notify.messages)

        analyzer.fail_actions = False
        import time
        orchestrator.clock = lambda: time.time() + 65
        resumed = orchestrator.resume_mail(store.load_model("mail-" + partial["id"], MailState))
        assert resumed.outcome is ProcessingOutcome.COMPLETED
        assert analyzer.calls == ["relevance", "summary", "action_router", "events", "events"]
        assert resumed["event_extraction"]["events"][0]["date_text"] == "22.09.2026"
        assert resumed["event_extraction"]["events"][0]["responsibility"] == "unclear"
        assert resumed["event_extraction"]["events"][0]["time_text"] is None
        assert len([message for message in notify.messages if "\n• " in message]) == 1
        assert not any("Schritt event_extraction:" in message for message in notify.messages)
        assert resumed["error"] is None


def test_task_and_event_partial_success_resumes_only_failed_event(tmp_path):
    class BothAnalyzer(AnalyzerStub):
        def __init__(self):
            super().__init__("relevant")
            self.calls = []
            self.fail_event = True
        def relevance(self, mail, topics):
            self.calls.append("relevance-call")
            return super().relevance(mail, topics)
        def summary(self, mail):
            self.calls.append("summary-call")
            return super().summary(mail)
        def action_route(self, mail):
            self.calls.append("router-call")
            return "router-id", ActionRoute(action_state="task_and_event", task_count=1,
                                             event_count=1, reason="Beides")
        def extract_tasks(self, mail, *, expected_count):
            self.calls.append("task-call")
            return super().extract_tasks(mail, expected_count=expected_count)
        def extract_events(self, mail, *, expected_count):
            self.calls.append("event-call")
            if self.fail_event:
                raise LlmSchemaValidationExceeded("event_extraction")
            from mailhelp.domain.extraction import ExtractedEvent
            from mailhelp.domain.mail import EventExtraction
            return "event-id", EventExtraction(events=[ExtractedEvent(
                title="Termin", evidence="Termin", time_requirement="required_unknown", responsibility="other",
                certainty="certain", classification="new")])

    analyzer, notify = BothAnalyzer(), Notify()
    fetched = FetchedMail("INBOX", 1, 193, b"Subject: Beides\n\nAufgabe und Termin")
    topic = Topic(id="x", name="x", enabled=True, description="x")
    with JsonStore(tmp_path / "both") as store:
        orchestrator = Orchestrator(analyzer, store, notify, 1, [topic], 1000)
        partial = orchestrator.process(fetched)
        stable_ids = list(partial["llm_call_ids"])
        assert partial["steps"]["task_extraction"] == "completed"
        assert partial["steps"]["event_extraction"] == "failed"
        assert stable_ids == ["r", "s", "router-id", "t"]
        analyzer.fail_event = False
        import time
        resumed = Orchestrator(analyzer, store, notify, 1, [topic], 1000, clock=lambda: time.time() + 65).process(fetched)
    assert analyzer.calls == ["relevance-call", "summary-call", "router-call", "task-call",
                              "event-call", "event-call"]
    assert resumed["llm_call_ids"][:4] == stable_ids
    assert resumed["llm_call_ids"] == stable_ids + ["event-id", "mq"]
    assert resumed["steps"]["normalization"] == "completed"
    assert resumed["steps"]["proposal_building"] == "completed"
    assert resumed["steps"]["summary_notification"] == "completed"
    assert len([message for message in notify.messages if "\n• " in message]) == 1


@pytest.mark.parametrize(("kind", "expected_stage"), [
    ("task", "task_extraction"), ("event", "event_extraction"),
])
def test_router_count_mismatch_is_assigned_to_its_extractor(tmp_path, kind, expected_stage):
    class MismatchAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute(action_state=kind,
                task_count=1 if kind == "task" else 0,
                event_count=1 if kind == "event" else 0, reason="Fund")
        def extract_tasks(self, mail, *, expected_count):
            from mailhelp.domain.mail import TaskExtraction
            return "t", TaskExtraction(tasks=[])
        def extract_events(self, mail, *, expected_count):
            from mailhelp.domain.mail import EventExtraction
            return "e", EventExtraction(events=[])

    with JsonStore(tmp_path / kind) as store:
        result = Orchestrator(MismatchAnalyzer("relevant"), store, Notify(), 1,
            [Topic(id="x", name="x", enabled=True, description="x")], 1000).process(
                FetchedMail("INBOX", 1, 120 if kind == "task" else 121,
                            b"Subject: Inkonsistent\n\nBody"))
    assert result.outcome is ProcessingOutcome.COMPLETED
    assert result["error"] is None
    assert result["steps"][expected_stage] == "completed"
    assert result["steps"]["action_detection"] == "completed"
    assert result["steps"]["normalization"] == "completed"
    assert result["proposals"] == []
    assert result["extraction_count_conflicts"][0] | {
        "notification_marked_at": None
    } == {
        "schema_version": 1, "category": kind, "expected_count": 1,
        "actual_count": 0, "router_call_id": "ar",
        "extractor_call_id": "t" if kind == "task" else "e",
        "notification_marked_at": None,
    }
    state = MailState.model_validate(result.state)
    before = len(state.extraction_count_conflicts)
    Orchestrator(MismatchAnalyzer("relevant"), store, Notify(), 1,
        [Topic(id="x", name="x", enabled=True, description="x")], 1000
    ).record_count_conflict("unused", state, kind, 1, 0, "ar",
                             "t" if kind == "task" else "e")
    assert len(state.extraction_count_conflicts) == before
    state.steps.completion = "pending"
    state.steps.proposal_notification = "pending"
    # Simulate a historical pre-fix state that had already aggregated actions;
    # its durable conflict must still be notified exactly once.
    state.steps.action_detection = "completed"
    store.save("mail-" + state.id, state.model_dump(mode="json"))
    restarted_notifier = Notify()
    Orchestrator(MismatchAnalyzer("relevant"), store, restarted_notifier, 1,
        [Topic(id="x", name="x", enabled=True, description="x")], 1000
    ).process(FetchedMail("INBOX", 1, 120 if kind == "task" else 121,
                          b"Subject: Inkonsistent\n\nBody"))
    assert not any("Zählerabweichung" in message for message in restarted_notifier.messages)
    state = store.load_model("mail-" + state.id, MailState)
    state.steps.completion = "pending"
    state.steps.proposal_notification = "pending"
    store.save("mail-" + state.id, state.model_dump(mode="json"))
    again = Notify()
    Orchestrator(MismatchAnalyzer("relevant"), store, again, 1,
        [Topic(id="x", name="x", enabled=True, description="x")], 1000
    ).process(FetchedMail("INBOX", 1, 120 if kind == "task" else 121,
                          b"Subject: Inkonsistent\n\nBody"))
    assert not any("Zählerabweichung" in message for message in again.messages)


def test_resume_after_extractor_and_after_action_aggregation(tmp_path):
    class EventAnalyzer(AnalyzerStub):
        def action_route(self, mail):
            return "ar", ActionRoute(action_state="event", task_count=0, event_count=1, reason="Termin")
        def extract_events(self, mail, *, expected_count):
            from mailhelp.domain.extraction import ExtractedEvent
            from mailhelp.domain.mail import EventExtraction
            return "e", EventExtraction(events=[ExtractedEvent(
                title="Termin", evidence="Termin", time_requirement="required_unknown", responsibility="other",
                certainty="certain", classification="new")])

    fetched = FetchedMail("INBOX", 1, 122, b"Subject: Neustart\n\nTermin")
    topic = Topic(id="x", name="x", enabled=True, description="x")
    with JsonStore(tmp_path / "resume") as store:
        orchestrator = Orchestrator(EventAnalyzer("relevant"), store, Notify(), 1, [topic], 1000)
        completed = orchestrator.process(fetched)
        name = "mail-" + completed["id"]
        state = store.load_model(name, MailState)
        state.steps.action_detection = "pending"
        state.steps.proposal_notification = "pending"
        state.steps.completion = "pending"
        store.save(name, state.model_dump(mode="json"))
        assert orchestrator.process(fetched).outcome is ProcessingOutcome.COMPLETED

        state = store.load_model(name, MailState)
        state.steps.action_detection = "completed"
        state.steps.proposal_notification = "completed"
        state.steps.completion = "pending"
        store.save(name, state.model_dump(mode="json"))
        assert orchestrator.process(fetched).outcome is ProcessingOutcome.COMPLETED

def test_orchestrator_defers_rate_limit_and_reports(tmp_path):
    class Limited:
        def relevance(self, mail, topics):
            raise RateLimitExceeded(120.0)
    from tests.fakes.log_fakes import RecordingLogger as Log
    with JsonStore(tmp_path/"limited") as store:
        notify=Notify()
        log=Log()
        topic=Topic(id="x",name="x",enabled=True,description="x")
        mail=FetchedMail("INBOX",1,20,b"Subject: Limit\n\nBody")
        state=Orchestrator(Limited(),store,notify,1,[topic],1000,log).process(mail)
        assert state.outcome is ProcessingOutcome.WAITING
        assert state["deferred_until"].startswith("1970-01-01T00:02:00")
        assert "LLM-Limit" in notify.messages[0] and any(item[0][2] == "llm_rate_limited" for item in log.events)
        second=Orchestrator(Limited(),store,notify,1,[topic],1000,log,lambda:100)
        assert second.process(mail)["deferred_until"] == state["deferred_until"]
    with JsonStore(tmp_path/"limited-no-log") as store:
        Orchestrator(Limited(),store,Notify(),1,[topic],1000).process(mail)


@pytest.mark.parametrize(("failure", "code", "retryable"), [
    (LlmSchemaValidationExceeded("relevance"), "schema_validation_failed", True),
    (LlmProviderResponseInvalid("relevance", "message_content_null"), "provider_response_invalid", True),
    (LlmInvalidJson("summary"), "invalid_json", True),
    (PermanentError("password=not-for-telegram"), "permanent_adapter_error", False),
    (RuntimeError("Subject: secret; token=not-for-state"), "internal_error", None),
])
def test_safe_failures_are_structured_and_notified_once_after_restart(tmp_path, failure, code, retryable):
    class Failing:
        def relevance(self, mail, topics):
            raise failure
    topic=Topic(id="x",name="x",enabled=True,description="x")
    mail=FetchedMail("INBOX",1,41,b"From: sender@example.test\nSubject: Classified\n\nPrivate body")
    notify=Notify()
    with JsonStore(tmp_path/code) as store:
        import time
        now = time.time()
        first=Orchestrator(Failing(),store,notify,1,[topic],1000).process(mail)
        if retryable is not False:
            assert len(notify.messages) == 0
            for _ in range(4):
                now += 7500
                second=Orchestrator(Failing(),store,notify,1,[topic],1000,clock=lambda: now).process(mail)
        else:
            second=Orchestrator(Failing(),store,notify,1,[topic],1000).process(mail)
        assert first.outcome is second.outcome is ProcessingOutcome.FAILED
        assert first["error"]["code"] == code
        assert first["error"]["stage"] == "relevance"
        assert first["error"]["retryable"] is retryable
        if code == "provider_response_invalid":
            assert first["validation_errors"] == []
            assert first["error"]["code"] not in {
                "schema_validation_failed", "llm_schema_validation_exhausted"}
        assert first["error"]["occurred_at"] == second["error"]["occurred_at"]
        assert len(notify.messages) == 1
        message=notify.messages[0]
        assert "✉️ sender@example.test · Classified" in message and "relevance" in message
        assert first["id"] not in message
        assert "Private body" not in message and "not-for" not in message


def test_permanent_adapter_safe_detail_is_included_in_notification(tmp_path):
    class Failing:
        def relevance(self, mail, topics):
            raise PermanentError(
                "Permanente Adapterantwort",
                safe_detail=("OpenRouter: Authentifizierungsfehler "
                             "(OPENROUTER_API_KEY wurde abgelehnt)"),
            )

    topic = Topic(id="x", name="x", enabled=True, description="x")
    mail = FetchedMail("INBOX", 1, 42, b"Subject: Test\n\nBody")
    notify = Notify()
    with JsonStore(tmp_path / "safe-detail") as store:
        result = Orchestrator(Failing(), store, notify, 1, [topic], 1000).process(mail)

    assert result.outcome is ProcessingOutcome.FAILED
    assert "OpenRouter: Authentifizierungsfehler" in notify.messages[0]
    assert "OPENROUTER_API_KEY wurde abgelehnt" in notify.messages[0]


@pytest.mark.parametrize("limit_name", ["max_mime_parts", "max_decoded_text_bytes"])
def test_mime_limit_uses_persisted_display_headers_once_after_restart(tmp_path, limit_name):
    message = EmailMessage()
    message["From"] = "bounded@example.test"
    message["Subject"] = "Visible safely"
    if limit_name == "max_mime_parts":
        message.make_mixed()
        for text in ("one", "two"):
            part = EmailMessage()
            part.set_content(text)
            message.attach(part)
    else:
        message.set_content("decoded text is too long")
    limits = MimeLimits(
        max_mail_bytes=100_000,
        max_mime_parts=1 if limit_name == "max_mime_parts" else 20,
        max_decoded_text_bytes=4 if limit_name == "max_decoded_text_bytes" else 10_000,
    )
    fetched = FetchedMail("INBOX", 1, 99, message.as_bytes())
    topic = Topic(id="x", name="x", enabled=True, description="x")
    notify = Notify()
    from tests.fakes.log_fakes import RecordingLogger as Log
    log = Log()
    directory = tmp_path / limit_name
    with JsonStore(directory) as store:
        first = Orchestrator(AnalyzerStub("irrelevant"), store, notify, 1, [topic],
                             100_000, logger=log, mime_limits=limits).process(fetched)
        assert first.outcome is ProcessingOutcome.FAILED
        assert first["mail"] is None
        assert first["display_headers"] == {
            "sender": "bounded@example.test", "subject": "Visible safely"}
    with JsonStore(directory) as store:
        second = Orchestrator(AnalyzerStub("irrelevant"), store, notify, 1, [topic],
                              100_000, logger=log, mime_limits=limits).process(fetched)
    assert second["error"]["occurred_at"] == first["error"]["occurred_at"]
    assert notify.messages == [
        "✉️ bounded@example.test · Visible safely\n⚠️ Schritt preparation: "
        "Mail wird nicht weiter versucht. Die Nachricht überschreitet ein Sicherheitslimit. Bitte Anhänge oder Nachrichtengröße reduzieren."
    ]
    exceeded = [kwargs for args, kwargs in log.events if args[2] == "mime_limit_exceeded"]
    assert [event["limit"] for event in exceeded] == [limit_name]
