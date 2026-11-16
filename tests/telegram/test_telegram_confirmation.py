"""Telegram confirmation, relevance dialogs and writable classifications."""
from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import (
    TelegramDialogState,
)
from mailhelp.domain.proposal import (
    Proposal,
    ProposalStatus,
)
from mailhelp.domain.relevance import RelevanceDialog, RelevanceDialogStatus
from mailhelp.persistence.storage import JsonStore
from mailhelp.telegram import (
    Decision,
    DecisionAction,
)
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)
from tests.fakes.shared_telegram_dialog import (
    RelevanceHandler,
    RevisionService,
    Writer,
    callback,
    controller,
    message,
    proposal,
    relevance_state,
)


def test_confirmation_executes_and_reports_all_results(tmp_path):
    cases=[
        (Writer(),False,"created","✅ Angelegt als Aufgabe"),
        (Writer(error=httpx.ReadTimeout("timeout")),False,"uncertain","Unklarer"),
        (Writer(error=httpx.HTTPStatusError("bad",request=httpx.Request("POST","https://x"),response=httpx.Response(400))),False,"failed","fehlgeschlagen"),
        (Writer(),True,"simulated","Testmodus"),
    ]
    for index,(writer,test_mode,status,text) in enumerate(cases):
        with JsonStore(tmp_path/str(index)) as store:
            c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer},test_mode)
            c.persist(proposal())
            c.poll_once()
            saved=store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")
            assert saved["status"]==status
            assert any(text in message for _,message,_ in t.sent)
            callback_message = t.sent[-1][1]
            # Created and simulated results are reported once, by the write message.
            if status == "simulated":
                assert callback_message.startswith("🧪 Testmodus: Aufgabe „Aufgabe“ bestätigt")
            elif status == "created":
                assert callback_message == "✅ Angelegt als Aufgabe: „Aufgabe“\nhttps://example.test/item"
            if status=="created": assert saved["external_id"]=="external-1" and saved["external_link"]=="https://example.test/item"


def test_restart_reconciles_before_retry_and_duplicate_update_is_safe(tmp_path):
    with JsonStore(tmp_path) as store:
        first=Writer(error=httpx.ReadTimeout("timeout"))
        c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":first})
        c.persist(proposal())
        c.poll_once()
        assert first.created==1 and store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="uncertain"
        recovered=Writer(found={"id":"external-existing","html_url":"https://example.test/existing"})
        restarted,t2,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":recovered})
        restarted.poll_once()
        assert recovered.reconciled==1 and recovered.created==0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["external_id"]=="external-existing"
        assert t2.polls==[2]

    with JsonStore(tmp_path/"writing") as store:
        interrupted=Writer()
        c,t,_=controller(store,(),{"todoist":interrupted})
        c.persist(proposal(status="writing"))
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="uncertain"
        assert interrupted.reconciled == 1 and interrupted.created == 0


def test_uncertain_write_is_only_reconciled_across_restarts(tmp_path):
    with JsonStore(tmp_path) as store:
        failed=Writer(error=httpx.ConnectError("lost"))
        initial,telegram,_=controller(
            store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":failed})
        initial.persist(proposal())
        initial.poll_once()
        assert failed.created == 1
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "uncertain"
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["uncertain_notified"] is True
        assert len([text for _,text,_ in telegram.sent if "Unklarer" in text]) == 1

        unresolved=Writer()
        for _ in range(3):
            restarted,messages,_=controller(store,(),{"todoist":unresolved})
            restarted.poll_once()
            assert not messages.sent
        assert unresolved.reconciled == 3
        assert unresolved.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "uncertain"

        unresolved.found={"id":"eventual","url":"https://example.test/eventual"}
        recovered,messages,_=controller(store,(),{"todoist":unresolved})
        recovered.poll_once()
        assert unresolved.reconciled == 4
        assert unresolved.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "created"
        assert "✅ Angelegt" in messages.sent[-1][1]






def test_relevance_dialog_authorization_stale_restart_and_duplicate(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        updates=[callback(1,f"relevance:{mail_id}:1:relevant",user=9),callback(2,f"relevance:{mail_id}:2:relevant"),callback(3,f"relevance:{mail_id}:1:relevant")]
        c,t,_=controller(store,updates)
        handler=RelevanceHandler(store)
        c.relevance_handler=handler
        assert c.awaiting_relevance_decision()
        c.send_relevance(RelevanceDialog(mail_id=mail_id), "Alice <alice@example.test>", "Rechnung")
        visible=t.sent[-1][1]
        callbacks=t.sent[-1][2]["inline_keyboard"][0]
        assert visible == "Absender: Alice <alice@example.test>\nBetreff: Rechnung\nRelevanz bitte bestätigen:"
        assert mail_id not in visible
        assert [button["callback_data"] for button in callbacks] == [
            f"relevance:{mail_id}:1:relevant",
            f"relevance:{mail_id}:1:irrelevant",
        ]
        c.poll_once()
        assert not c.awaiting_relevance_decision()
        assert all(text == "Aktion wird verarbeitet …" for _, text in t.answered[:3])
        assert any("Nicht autorisierte" in text for _, text, _ in t.sent)
        assert any("Schaltfläche ist veraltet" in text for _, text, _ in t.sent)
        assert handler.resumed==[mail_id] and store.load("mail-"+mail_id)["relevance_dialog"]["telegram_offset"]==4
        restarted,t2,_=controller(store,[callback(3,f"relevance:{mail_id}:1:irrelevant")])
        restarted.relevance_handler=handler
        restarted.poll_once()
        assert t2.polls==[4] and "bereits verarbeitet" in t2.answered[-1][1]
        t2.updates=[callback(4,f"relevance:{mail_id}:1:irrelevant")]
        restarted.poll_once()
        assert "Schaltfläche ist veraltet" in t2.sent[-1][1]


def test_relevance_dialog_displays_missing_headers_without_exposing_mail_id(tmp_path):
    mail_id="b"*24
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_relevance(RelevanceDialog(mail_id=mail_id,version=3), "—", "—")
        assert t.sent[-1][1] == "Absender: —\nBetreff: —\nRelevanz bitte bestätigen:"
        assert mail_id not in t.sent[-1][1]
        assert [button["callback_data"] for button in t.sent[-1][2]["inline_keyboard"][0]] == [
            f"relevance:{mail_id}:3:relevant",
            f"relevance:{mail_id}:3:irrelevant",
        ]


def test_relevance_free_text_requires_unique_open_dialog(tmp_path):
    ids=["a"*24,"b"*24]
    with JsonStore(tmp_path) as store:
        for mail_id in ids: store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        c,t,_=controller(store,[message(1,"relevant")])
        c.relevance_handler=RelevanceHandler(store)
        c.poll_once()
        assert "nicht eindeutig" in t.sent[-1][1]
        state=store.load_model("mail-"+ids[1],MailState)
        state.relevance_dialog=None
        state.awaiting_relevance=False
        store.save("mail-"+ids[1],state.model_dump(mode="json"))
        t.updates=[message(2,"irrelevant")]
        c.poll_once()
        assert store.load("mail-"+ids[0])["relevance_dialog"]["decision"]=="irrelevant"


def test_invalid_relevance_callbacks_and_unavailable_handler(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        c,t,_=controller(store,[callback(1,"relevance:bad"),callback(2,f"relevance:{mail_id}:1:relevant"),message(3,"irrelevant")])
        c.poll_once()
        assert all(text == "Aktion wird verarbeitet …" for _, text in t.answered)
        assert any("syntaktisch" in text for _, text, _ in t.sent)
        assert "nicht verfügbar" in t.sent[-1][1]


def test_duplicate_free_text_is_visible_only_to_authorized_chat(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        state=relevance_state(mail_id)
        state.relevance_dialog=state.relevance_dialog.model_copy(update={"status":RelevanceDialogStatus.DECIDED,"decision":"relevant","telegram_offset":3})
        state.awaiting_relevance=False
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        c,t,_=controller(store,[message(2,"relevant"),message(2,"relevant",user=9)])
        c.poll_once()
        assert t.polls==[3]
        assert [text for _,text,_ in t.sent]==["Diese Relevanzantwort wurde bereits verarbeitet."]

        # Even a replay is schema-validated before any raw Telegram fields are used.
        t.updates=[{"update_id":2,"message":{"private":"not trusted"}}]
        c.poll_once()
        assert [text for _,text,_ in t.sent]==["Diese Relevanzantwort wurde bereits verarbeitet."]

@pytest.mark.parametrize("classification", [
    "non_binding", "already_completed", "change", "cancellation", "recurring", "unsupported",
])
def test_non_creatable_classifications_stay_manual_after_telegram_interaction(tmp_path, classification):
    writer = Writer()
    with JsonStore(tmp_path / classification) as store:
        dialog, transport, _ = controller(store, writers={"todoist": writer})
        item = proposal(classification=classification)
        dialog.send_proposal(item)
        markup = transport.sent[-1][2]["inline_keyboard"]
        assert [button["text"] for button in markup[0]] == ["Manuell prüfen", "Verwerfen"]
        assert "⚠️ Kann nicht automatisch angelegt werden" in transport.sent[-1][1]
        transport.updates = [callback(1, Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                                                   version=item.version, action=DecisionAction.CONFIRM).encode())]
        dialog.poll_once()
        assert writer.created == 0 and writer.reconciled == 0
        assert transport.answered[-1][1] == "Aktion wird verarbeitet …"
        assert "konnte nicht verarbeitet" in transport.sent[-1][1]
        dialog.write_executor.execute(item.model_copy(update={"status": ProposalStatus.CONFIRMED}))
        assert writer.created == 0 and writer.reconciled == 0


@pytest.mark.parametrize(("changes", "expected_status"), [
    ({"responsibility": "other"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"responsibility": "unclear"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"certainty": "uncertain"}, ProposalStatus.NEEDS_CLARIFICATION),
    ({"certainty": "contradictory"}, ProposalStatus.NEEDS_CLARIFICATION),
])
def test_responsibility_and_uncertainty_are_not_writable(changes, expected_status):
    item = proposal(**changes)
    assert item.status == expected_status
    writer = Writer()
    with pytest.raises(ValueError, match="neue, sichere und eigene"):
        from mailhelp.proposals.integrations import execute_confirmed
        execute_confirmed(item.model_copy(update={"status": ProposalStatus.CONFIRMED}), writer, lambda _: None)
    assert writer.created == 0 and writer.reconciled == 0
    decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=item.version, action=DecisionAction.CONFIRM)
    if expected_status == ProposalStatus.PENDING_CONFIRMATION:
        with pytest.raises(ValueError, match="manuellen Prüfung"):
            from mailhelp.telegram import apply_decision
            apply_decision(item, decision, 1, 2, 1, 2)


def test_classification_fields_are_required_and_closed():
    raw = proposal().model_dump()
    for field in ("responsibility", "certainty", "classification"):
        missing = {**raw}
        missing.pop(field)
        with pytest.raises(ValidationError):
            Proposal.model_validate(missing)
    for field in ("responsibility", "certainty", "classification"):
        with pytest.raises(ValidationError):
            Proposal.model_validate({**raw, field: "invalid"})


def test_calendar_duplicate_outcomes_are_reported_without_claiming_creation(tmp_path):
    class DuplicateWriter(Writer):
        def __init__(self, operation):
            super().__init__()
            self.operation=operation
        def create(self,p,key):
            self.created += 1
            return {"id":"existing", "operation":self.operation}
    for index,(operation,phrase) in enumerate([
        ("duplicate_updated","fehlende Informationen wurden ergänzt"),
        ("duplicate_skipped","Kein neuer Termin wurde angelegt"),
    ]):
        with JsonStore(tmp_path/str(index)) as store:
            item=proposal(kind="event",start="2026-05-10T10:00:00+00:00",
                          end="2026-05-10T11:00:00+00:00")
            decision=f"proposal:{item.source_mail_id}:{item.id}:1:confirm"
            dialog,telegram,_=controller(store,[callback(1,decision)],
                                          {"google_calendar":DuplicateWriter(operation)})
            dialog.persist(item)
            dialog.poll_once()
            assert any(phrase in text for _,text,_ in telegram.sent)
            assert not any(text.startswith("Erstellt:") for _,text,_ in telegram.sent)


def test_regression_messages_after_open_question_are_held_until_resolved(tmp_path):
    """Bug: every new notification was sent while a question was still open."""
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        c.send_proposal(proposal(title="Frage A", open_questions=["Welches Datum?"]))
        c.send_proposal(proposal(source_mail_id="b" * 24, title="Aufgabe B"))
        c.send(2, "Zusammenfassung C")
        assert any("Frage A" in text for _, text, _ in t.sent)
        assert not any("Aufgabe B" in text or text == "Zusammenfassung C"
                       for _, text, _ in t.sent)
        t.updates = [callback(1, "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:reject")]
        c.poll_once()
        assert any("Aufgabe B" in text for _, text, _ in t.sent)
        assert not any(text == "Zusammenfassung C" for _, text, _ in t.sent)
        t.updates = [callback(2, "proposal:bbbbbbbbbbbbbbbbbbbbbbbb:p1:1:reject")]
        c.poll_once()
        later = [text for _, text, _ in t.sent]
        assert later.index("Zusammenfassung C") > max(
            i for i, text in enumerate(later) if "Aufgabe B" in text)


def test_contradictory_end_without_validated_date_gets_a_question(tmp_path):
    # Regression: an event without validated date facts (e.g. from an invitation) made
    # the contradiction message compute None + 1 day for an "Ende" question and crash.
    service = RevisionService()
    with JsonStore(tmp_path) as store:
        item = proposal(
            kind="event", status="needs_clarification",
            open_questions=["Wann endet der Termin?"],
            start="2026-09-23T18:00:00+02:00", end="2026-09-23T19:00:00+02:00",
        )
        assert item.known_temporal_facts is None and item.temporal_fact is None
        c, transport, _ = controller(store, revision_service=service)
        c.revisions.configured_timezone = "Europe/Berlin"
        c.persist(item)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=item.source_mail_id, proposal_id=item.id,
            version=item.version).model_dump(mode="json"))

        c.revisions.answer("2026-09-23 17 Uhr")

        assert service.calls == []
        state = store.load("clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")
        assert state["answer_status"] == "invalid"
        assert "Bitte" in transport.sent[-1][1]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"] == 1
