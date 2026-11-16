"""Telegram decisions: persistence, ledger, callback tokens, buttons and pauses."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import (
    AnswerStatus,
    ProposalClarificationState,
    ProposalNotification,
    ProposalRevisionStatus,
    QuestionStatus,
)
from mailhelp.domain.proposal import (
    ActionLedger,
    ActionLedgerEntry,
    Proposal,
    ProposalStatus,
)
from mailhelp.persistence.proposals import proposal_version_name
from mailhelp.persistence.storage import JsonStore
from mailhelp.telegram import (
    Decision,
    DecisionAction,
    TelegramCallbackQuery,
    TelegramDialogController,
    TelegramMessage,
    TelegramUpdate,
    validate_callback_data,
    validate_callback_markup,
)
from tests.fakes.log_fakes import RecordingLogger as Logger
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)
from tests.fakes.shared_telegram_dialog import (
    RevisionService,
    Telegram,
    Writer,
    callback,
    controller,
    message,
    proposal,
)


def test_validation_failure_log_contains_safe_structured_details(tmp_path):
    with JsonStore(tmp_path) as store:
        c, _, log = controller(store)
        with pytest.raises(ValidationError) as caught:
            Proposal.model_validate({})
        c.revisions._log_revision_failure("a" * 24, "p1", 1, caught.value,
                                ProposalRevisionStatus.RETRY_REQUIRED)
        fields = log.events[-1][1]
        assert fields["validation_errors"][0]["location"] == ["id"]
        assert fields["validation_errors"][0]["type"] == "missing"
        assert "input" not in repr(fields["validation_errors"])






def test_write_attempt_references_are_linked_to_mail(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path/"references") as store:
        state=MailState(id=mail_id,config_fingerprint="f"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1})
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        dialog,_,_=controller(store)
        task=proposal(source_mail_id=mail_id,status="writing")
        dialog.persist(task)
        dialog.persist(task)
        dialog.persist(proposal(id="event",kind="event",source_mail_id=mail_id,status="uncertain",
                                start="2026-01-01T10:00:00Z",end="2026-01-01T11:00:00Z"))
        loaded=store.load_model("mail-"+mail_id,MailState)
        assert [(item.proposal_id,item.service,item.idempotency_key) for item in loaded.write_attempts] == [
            ("p1","todoist",f"mailhelp:{mail_id}:p1:v1"),
            ("event","google_calendar",f"mailhelp:{mail_id}:event:v1"),
        ]


@pytest.mark.parametrize(("status", "has_attempt"), [
    (ProposalStatus.REJECTED, False),
    (ProposalStatus.CREATED, True),
    (ProposalStatus.SIMULATED, False),
    (ProposalStatus.FAILED, True),
    (ProposalStatus.UNCERTAIN, True),
])
def test_persist_synchronizes_every_terminal_result_with_mail_state(tmp_path, status, has_attempt):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id)
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[original], created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    changes = {"version": 2, "status": status}
    if status == ProposalStatus.CREATED:
        changes.update(external_id="external-1", external_link="https://example.test/item")
    current = original.model_copy(update=changes)
    with JsonStore(tmp_path / status.value) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog,_,_=controller(store)
        dialog.persist(current)
        dialog.persist(current)
        loaded=store.load_model("mail-" + mail_id, MailState)
        assert loaded.proposals[0] == current
        assert loaded.updated_at > state.updated_at
        assert len(loaded.write_attempts) == int(has_attempt)
        if status == ProposalStatus.CREATED:
            assert loaded.proposals[0].external_id == "external-1"
            assert loaded.proposals[0].external_link == "https://example.test/item"


def test_persist_order_and_restart_repair_use_current_proposal(tmp_path):
    class RecordingStore(JsonStore):
        def __init__(self, directory):
            super().__init__(directory)
            self.saved=[]
        def save(self, name, value):
            self.saved.append(name)
            super().save(name, value)

    mail_id="a"*24
    initial=proposal(source_mail_id=mail_id)
    with RecordingStore(tmp_path) as store:
        state=MailState(id=mail_id,config_fingerprint="f"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
                        proposals=[initial])
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        store.saved.clear()
        created=initial.model_copy(update={"status":ProposalStatus.CREATED,
                                           "external_id":"external-1",
                                           "external_link":"https://example.test/item"})
        dialog,_,_=controller(store)
        dialog.persist(created)
        assert store.saved == [f"proposal-{mail_id}-p1-v1", f"history-{mail_id}",
                               f"proposal-{mail_id}-p1", f"mail-{mail_id}", "action-ledger"]

        # Simulate a crash between the second and third writes by restoring a
        # stale embedding.  Startup repairs it from the current proposal file.
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        restarted,_,_=controller(store)
        restarted.poll_once()
        repaired=store.load_model("mail-"+mail_id,MailState).proposals[0]
        assert repaired.status == ProposalStatus.CREATED
        assert repaired.external_id == "external-1"
        assert repaired.external_link == "https://example.test/item"


def test_revision_replaces_notification_version_and_validates_mail_state(tmp_path):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id, status="needs_clarification",
                        open_questions=["Welches Datum?"])
    unrelated = proposal(id="p2", source_mail_id=mail_id)
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[unrelated, original],
        proposal_notifications=[ProposalNotification(
            proposal_id=original.id, proposal_version=1, status="completed")],
    )
    revised = proposal(source_mail_id=mail_id, version=2)
    with JsonStore(tmp_path) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog, transport, _ = controller(store)

        dialog.persist(revised)

        saved = store.load_model("mail-" + mail_id, MailState)
        assert saved.proposals == [unrelated, revised]
        assert saved.proposal_notifications == [ProposalNotification(
            proposal_id=revised.id, proposal_version=2, status="pending")]
        dialog.send_proposal(revised)
        delivered = store.load_model("mail-" + mail_id, MailState)
        assert delivered.proposal_notifications[0].status == "completed"
        assert len(transport.sent) == 1


def test_restart_delivers_persisted_revision_before_marking_it_completed(tmp_path):
    mail_id = "a" * 24
    original = proposal(source_mail_id=mail_id, status="needs_clarification",
                        open_questions=["Welches Datum?"])
    state = MailState(
        id=mail_id, config_fingerprint="f" * 64,
        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
        proposals=[original],
        proposal_notifications=[ProposalNotification(
            proposal_id=original.id, proposal_version=1, status="completed")],
    )
    answered = ProposalClarificationState(
        mail_id=mail_id, proposal_id=original.id, version=1,
        question="Welches Datum?", question_status=QuestionStatus.ANSWERED,
        answer_status=AnswerStatus.VALID, normalized_answer="2026-10-21",
        proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED)
    name = "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1"
    with JsonStore(tmp_path) as store:
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        first, _, _ = controller(store)
        first.persist(proposal(source_mail_id=mail_id, version=2))
        store.save(name, answered.model_dump(mode="json"))

        restarted, transport, _ = controller(store)
        mail = store.load_model("mail-" + mail_id, MailState)
        mail.proposal_notifications[0].status = "sending"
        store.save("mail-" + mail_id, mail.model_dump(mode="json"))
        restarted.revisions._revise_answered(answered)
        assert not transport.sent
        assert store.load(name)["proposal_revision_status"] == "retry_required"
        mail.proposal_notifications[0].status = "pending"
        store.save("mail-" + mail_id, mail.model_dump(mode="json"))
        restarted.revisions._revise_answered(answered)

        assert len(transport.sent) == 1
        assert store.load_model("mail-" + mail_id, MailState).proposal_notifications[0].status == "completed"
        assert store.load(name)["proposal_revision_status"] == "completed"
        restarted.revisions._revise_answered(answered)
        assert len(transport.sent) == 1


def test_created_action_is_booked_and_duplicate_needs_second_confirmation(tmp_path):
    first_mail, second_mail = "a" * 24, "b" * 24
    with JsonStore(tmp_path) as store:
        writer = Writer()
        dialog, telegram, _ = controller(store, writers={"todoist": writer})
        already_created = proposal(source_mail_id=first_mail, status="created",
                                   external_id="old-external")
        dialog.persist(already_created)
        dialog.persist(already_created)  # bookkeeping is idempotent
        candidate = proposal(source_mail_id=second_mail)
        dialog.persist(candidate)

        normal = Decision(mail_id=second_mail, proposal_id="p1", version=1,
                          action=DecisionAction.CONFIRM)
        assert "Doppelanlage" in dialog.decision_service.decide(normal, dialog.user_id, dialog.chat_id)
        assert writer.created == 0
        assert "Bereits angelegt" in telegram.sent[-1][1]
        markup = telegram.sent[-1][2]
        repeat = Decision.parse(markup["inline_keyboard"][0][0]["callback_data"], store)
        assert repeat.action == DecisionAction.CONFIRM_DUPLICATE

        # The write result message reports the creation; no second confirmation.
        assert dialog.decision_service.decide(repeat, dialog.user_id, dialog.chat_id) == ""
        assert telegram.sent[-1][1].startswith("✅ Angelegt")
        assert writer.created == 1
        assert store.load("proposal-" + second_mail + "-p1")["status"] == "created"
        ledger = store.load_model("action-ledger", ActionLedger)
        assert len(ledger.entries) == 2
        assert {item.external_id for item in ledger.entries} == {"old-external", "external-1"}


def test_duplicate_override_is_rejected_when_ledger_no_longer_matches(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = controller(store, writers={"todoist": Writer()})
        item = proposal()
        dialog.persist(item)
        decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=1,
                            action=DecisionAction.CONFIRM_DUPLICATE)
        with pytest.raises(ValueError, match="veraltet"):
            dialog.decision_service.decide(decision, dialog.user_id, dialog.chat_id)
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "pending_confirmation"


def test_action_ledger_rejects_duplicate_proposal_version():
    entry = ActionLedgerEntry(action_key="0" * 64, mail_id="a" * 24, proposal_id="p1",
                              proposal_version=1, kind="task", title="Aufgabe", target="inbox")
    with pytest.raises(ValidationError, match="doppelt verbucht"):
        ActionLedger(entries=[entry, entry])




def test_direct_decision_persists_confirmation_before_write(tmp_path):
    events=[]
    class OrderedStore(JsonStore):
        def save(self, name, value):
            super().save(name, value)
            if name == "proposal-aaaaaaaaaaaaaaaaaaaaaaaa-event" and value["status"] == "confirmed":
                events.append("confirmation persisted")
    class SlowWriter(Writer):
        def create(self, item, key):
            assert events == ["confirmation persisted"]
            events.append("external write")
            return super().create(item, key)

    with OrderedStore(tmp_path) as store:
        transport=Telegram()
        dialog=TelegramDialogController(store,transport,1,2,Logger(),
                                        {"google_calendar":SlowWriter()},False,"UTC",
                                        RevisionService())
        item=proposal(id="event",kind="event",status="pending_confirmation",
                      start="2026-01-01T10:00:00Z",end="2026-01-01T11:00:00Z")
        dialog.persist(item)
        dialog.decision_service.decide(Decision(mail_id=item.source_mail_id,
                       proposal_id=item.id,version=item.version,
                       action=DecisionAction.CONFIRM), dialog.user_id, dialog.chat_id)

    assert events[:2] == ["confirmation persisted", "external write"]


@pytest.mark.parametrize(("start", "end", "all_day", "expected"), [
    ("2026-05-10T22:30:00+00:00", "2026-05-10T23:30:00+00:00",
     False, " · 11.05.2026, 00:30 Uhr"),
    ("2026-05-10", "2026-05-11", True, " · 10.05.2026, ganztägig"),
])
def test_created_calendar_notification_includes_local_date_and_time(
    tmp_path, start, end, all_day, expected
):
    with JsonStore(tmp_path) as store:
        writer = Writer()
        transport = Telegram()
        dialog = TelegramDialogController(
            store, transport, 1, 2, Logger(), {"google_calendar": writer},
            False, "Europe/Berlin", RevisionService()
        )
        item = proposal(kind="event", start=start, end=end, all_day=all_day)
        dialog.persist(item)

        dialog.decision_service.decide(Decision(mail_id=item.source_mail_id,
                                proposal_id=item.id, version=item.version,
                                action=DecisionAction.CONFIRM), dialog.user_id, dialog.chat_id)

        created_message = next(
            text for _, text, _ in transport.sent if text.startswith("✅ Angelegt im Kalender")
        )
        assert expected in created_message


def test_strict_schemas_and_decisions():
    parsed=Decision.parse("proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:confirm")
    assert parsed.encode()=="proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:confirm"
    for bad in ("x", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:x:confirm", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:٣:confirm", "proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:bad"):
        with pytest.raises((ValueError,ValidationError)): Decision.parse(bad)
    transport=TelegramMessage.model_validate({"message_id":1,"from":{"id":1,"first_name":"Ada","is_bot":False},"chat":{"id":2,"type":"private"},"date":1_789_000_000,"text":"x","unknown":True})
    assert transport.model_dump(by_alias=True)=={"message_id":1,"from":{"id":1},"chat":{"id":2},"text":"x"}
    callback_model=TelegramCallbackQuery.model_validate({**callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")["callback_query"],"unknown":1})
    assert "unknown" not in callback_model.model_dump() and callback_model.sender.id == 1
    with pytest.raises(ValidationError): Decision.model_validate({"proposal_id":"p1","version":1,"action":"confirm","unknown":True})
    with pytest.raises(ValidationError): TelegramUpdate(update_id=1)
    with pytest.raises(ValidationError): TelegramUpdate.model_validate({**message(1),"callback_query":callback(1,"x")["callback_query"]})


def test_durable_callback_tokens_bound_every_field_and_survive_restart(tmp_path):
    item = Decision(mail_id="a" * 24, proposal_id="Z_" * 16, version=123456789,
                    action=DecisionAction.CONFIRM)
    with JsonStore(tmp_path) as store:
        encoded = item.encode(store)
        assert len(encoded.encode("utf-8")) <= 64
        assert Decision.parse(encoded, store) == item
    with JsonStore(tmp_path) as restarted:
        assert Decision.parse(encoded, restarted) == item
        for bad in ("decision:" + "0" * 32, encoded[:-1] + "g", "decision:short"):
            with pytest.raises((ValueError, ValidationError)):
                Decision.parse(bad, restarted)
        with pytest.raises(ValueError, match="Unbekannter"):
            Decision.parse(encoded)


def test_callback_token_collision_and_invalid_persisted_record(tmp_path):
    item = Decision(mail_id="a" * 24, proposal_id="p1", version=12,
                    action=DecisionAction.EDIT)
    with JsonStore(tmp_path) as store:
        store.save("telegram-callback-" + "1" * 32, item.model_dump(mode="json"))
        with patch("mailhelp.telegram.callbacks.secrets.token_hex", side_effect=["1" * 32, "2" * 32]):
            value = item.encode(store)
        assert value == "decision:" + "2" * 32
        for token, record in (("3" * 32, ["broken"]),
                              ("4" * 32, {"action": 1})):
            store.save("telegram-callback-" + token, record)
            with pytest.raises(ValueError, match="Callback-Datensatz"):
                Decision.parse("decision:" + token, store)


def test_callback_data_byte_validation_and_legacy_limit():
    validate_callback_markup(None)
    validate_callback_markup({"inline_keyboard": [[{"text": "URL"}]]})
    validate_callback_data("x" * 64)
    for value in ("", "x" * 65, "ü" * 33):
        with pytest.raises(ValueError, match="1 bis 64 UTF-8-Bytes"):
            validate_callback_data(value)
    with pytest.raises(ValueError, match="Zeichenkette"):
        validate_callback_markup({"inline_keyboard": [[{"callback_data": 1}]]})
    too_long_legacy = "proposal:" + "a" * 24 + ":" + "p" * 32 + ":12:confirm"
    with pytest.raises(ValueError, match="UTF-8-Bytes"):
        Decision.parse(too_long_legacy)


@pytest.mark.parametrize(("changes", "labels", "actions"), [
    ({}, ["Als Aufgabe anlegen", "Ändern", "Verwerfen"],
     [DecisionAction.CONFIRM, DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"open_questions": ["Bitte klären"]}, ["Klären", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"classification": "unsupported"}, ["Manuell prüfen", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"kind": "event", "start": "2026-05-10T10:00:00+02:00", "end": "2026-05-10T11:00:00+02:00"},
     ["Im Kalender anlegen", "Ändern", "Verwerfen"], [DecisionAction.CONFIRM, DecisionAction.EDIT, DecisionAction.REJECT]),
])
def test_all_proposal_buttons_use_short_exactly_bound_tokens(tmp_path, changes, labels, actions):
    item = proposal(id="P_" * 16, version=123456789, **changes)
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store)
        dialog.send_proposal(item)
        buttons = transport.sent[-1][2]["inline_keyboard"][0]
        assert [button["text"] for button in buttons] == labels
        for button, action in zip(buttons, actions, strict=True):
            value = button["callback_data"]
            assert 1 <= len(value.encode("utf-8")) <= 64
            assert Decision.parse(value, store) == Decision(
                mail_id=item.source_mail_id, proposal_id=item.id,
                version=item.version, action=action)


def test_pending_event_pauses_until_anlegen_or_verwerfen(tmp_path):
    item = proposal(kind="event", start="2026-05-10T10:00:00+02:00",
                    end="2026-05-10T11:00:00+02:00")
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store)
        dialog.send_proposal(item)

        assert dialog.awaiting_decision()
        buttons = transport.sent[-1][2]["inline_keyboard"][0]
        assert [button["text"] for button in buttons] == ["Im Kalender anlegen", "Ändern", "Verwerfen"]

        transport.updates = [callback(1, buttons[2]["callback_data"])]
        dialog.poll_once()
        assert not dialog.awaiting_decision()


def test_awaiting_decision_ignores_version_snapshots_but_not_open_relevance(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        item = proposal()
        store.save(proposal_version_name(item.source_mail_id, item.id, item.version),
                   item.model_dump(mode="json"))
        assert not dialog.awaiting_decision()
        dialog._open_relevance_dialogs = lambda: [object()]
        assert dialog.awaiting_decision()


def test_paused_answer_is_operator_block_not_open_user_decision(tmp_path):
    item = proposal(status="needs_clarification", open_questions=["Wann?"])
    state = ProposalClarificationState(
        mail_id=item.source_mail_id, proposal_id=item.id, version=item.version,
        question="Wann?", question_status=QuestionStatus.ANSWERED,
        answer_status=AnswerStatus.VALID, authorized_answer="Antwort",
        normalized_answer="Antwort",
        proposal_revision_status=ProposalRevisionStatus.PAUSED,
    )
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        dialog.persist(item)
        store.save(
            "clarification-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1",
            state.model_dump(mode="json"),
        )

        assert not dialog.awaiting_decision()
        assert dialog.processing_blocked()
