from __future__ import annotations

import httpx
import pytest
from unittest.mock import patch
from pydantic import ValidationError

from mailhelp.adapter import PermanentError, UncertainWriteError
from mailhelp.models import (ActionLedger, ActionLedgerEntry, MailState, Proposal,
                             ProposalStatus, RelevanceDialog, RelevanceDialogStatus)
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    Decision, DecisionAction,
    TelegramCallbackQuery,
    TelegramChatNotFoundError,
    TelegramClient,
    TelegramDialogController,
    TelegramMessage,
    TelegramUpdate,
    numbered_message_parts,
    format_proposal,
    validate_callback_data,
    validate_callback_markup,
)
from mailhelp.application import _state_directory
from mailhelp.config import Settings


def proposal(**changes):
    data = {"id": "p1", "version": 1, "kind": "task", "responsibility": "user", "certainty": "certain", "classification": "new", "title": "Aufgabe", "description": "Text", "evidence": "Beleg", "source_mail_id": "aaaaaaaaaaaaaaaaaaaaaaaa", "target": "inbox"}
    if "status" not in changes and (changes.get("open_questions") or changes.get("responsibility") not in {None, "user"}
                                    or changes.get("certainty") not in {None, "certain"}
                                    or changes.get("classification") not in {None, "new"}):
        data["status"] = "needs_clarification"
    data.update(changes)
    return Proposal.model_validate(data)


def message(update_id, text="Antwort", user=1, chat=2):
    return {"update_id": update_id, "message": {"message_id": update_id, "from": {"id": user}, "chat": {"id": chat}, "text": text}}


def callback(update_id, data, user=1, chat=2):
    return {"update_id": update_id, "callback_query": {"id": f"c{update_id}", "from": {"id": user, "is_bot": False, "first_name": "Ada"}, "chat_instance": "irrelevant", "message": {"message_id": 1, "from": {"id": 99, "is_bot": True, "first_name": "Mailhelp"}, "chat": {"id": chat, "type": "private"}, "date": 1_789_000_000, "text": "buttons", "reply_markup": {"inline_keyboard": []}}, "data": data}}


class Telegram:
    def __init__(self, updates=()):
        self.updates = list(updates); self.polls=[]; self.sent=[]; self.answered=[]
    def poll(self, offset): self.polls.append(offset); return self.updates
    def send(self, chat, text, reply_markup=None): self.sent.append((chat,text,reply_markup))
    def answer_callback(self, callback_id, text): self.answered.append((callback_id,text))


class Logger:
    def __init__(self): self.events=[]
    def event(self, *args, **fields): self.events.append((args,fields))


class RevisionService:
    def __init__(self): self.calls=[]
    def revise_proposal(self, item, question, answer):
        self.calls.append((item,question,answer))
        remaining=item.open_questions[1:]
        return "revision-call", Proposal.model_validate({**item.model_dump(),
            "version":item.version+1, "description":answer,
            "open_questions":remaining,
            "status":"needs_clarification" if remaining else "pending_confirmation"})


class FailingRevisionService:
    def revise_proposal(self, item, question, answer): raise ValueError("contradiction")


class OperationallyFailingRevisionService:
    def revise_proposal(self, item, question, answer): raise RuntimeError("provider unavailable")


def controller(store, updates=(), writers=None, test_mode=False, revision_service=None):
    transport=Telegram(updates); log=Logger()
    service=revision_service if revision_service is not None else RevisionService()
    return TelegramDialogController(store,transport,1,2,log,writers,test_mode,"UTC",service),transport,log


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
        def __init__(self, directory): super().__init__(directory); self.saved=[]
        def save(self, name, value): self.saved.append(name); super().save(name, value)

    mail_id="a"*24
    initial=proposal(source_mail_id=mail_id)
    with RecordingStore(tmp_path) as store:
        state=MailState(id=mail_id,config_fingerprint="f"*64,
                        imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},
                        proposals=[initial])
        store.save("mail-"+mail_id,state.model_dump(mode="json")); store.saved.clear()
        created=initial.model_copy(update={"status":ProposalStatus.CREATED,
                                           "external_id":"external-1",
                                           "external_link":"https://example.test/item"})
        dialog,_,_=controller(store); dialog.persist(created)
        assert store.saved == [f"proposal-{mail_id}-p1-v1", f"proposal-{mail_id}-p1",
                               f"mail-{mail_id}", "action-ledger"]

        # Simulate a crash between the second and third writes by restoring a
        # stale embedding.  Startup repairs it from the current proposal file.
        store.save("mail-"+mail_id,state.model_dump(mode="json"))
        restarted,_,_=controller(store); restarted.poll_once()
        repaired=store.load_model("mail-"+mail_id,MailState).proposals[0]
        assert repaired.status == ProposalStatus.CREATED
        assert repaired.external_id == "external-1"
        assert repaired.external_link == "https://example.test/item"


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
        dialog._decide("first", normal)
        assert writer.created == 0
        assert "erneute Freigabe" in telegram.answered[-1][1]
        assert "Bereits angelegt" in telegram.sent[-1][1]
        markup = telegram.sent[-1][2]
        repeat = Decision.parse(markup["inline_keyboard"][0][0]["callback_data"], store)
        assert repeat.action == DecisionAction.CONFIRM_DUPLICATE

        dialog._decide("second", repeat)
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
        dialog._decide("stale", decision)
        assert "veraltet" in telegram.answered[-1][1]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "pending_confirmation"


def test_action_ledger_rejects_duplicate_proposal_version():
    entry = ActionLedgerEntry(action_key="0" * 64, mail_id="a" * 24, proposal_id="p1",
                              proposal_version=1, kind="task", title="Aufgabe", target="inbox")
    with pytest.raises(ValidationError, match="doppelt verbucht"):
        ActionLedger(entries=[entry, entry])


class Writer:
    def __init__(self, found=None, error=None): self.found=found; self.error=error; self.created=0; self.reconciled=0; self.versions=[]
    def reconcile(self,key): self.reconciled+=1; return self.found
    def create(self,p,key):
        self.created+=1; self.versions.append(p.version)
        if self.error: raise self.error
        return {"id":"external-1","url":"https://example.test/item"}


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
        with patch("mailhelp.telegram.secrets.token_hex", side_effect=["1" * 32, "2" * 32]):
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
    ({}, ["Bestätigen", "Ändern", "Verwerfen"],
     [DecisionAction.CONFIRM, DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"open_questions": ["Bitte klären"]}, ["Klären", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
    ({"classification": "unsupported"}, ["Manuell prüfen", "Verwerfen"],
     [DecisionAction.EDIT, DecisionAction.REJECT]),
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


def test_numbered_parts():
    parts=numbered_message_parts("sender@example.test","Ein Betreff","x"*150,100)
    assert len(parts)>1 and all(
        f"[Absender: sender@example.test · Teil {i}/{len(parts)}]\nBetreff: Ein Betreff\n" in part
        for i,part in enumerate(parts,1))
    with pytest.raises(ValueError): numbered_message_parts("","p","x")
    with pytest.raises(ValueError): numbered_message_parts("m","","x")
    with pytest.raises(ValueError): numbered_message_parts("m","p","x",31)


@pytest.mark.parametrize(("item", "expected"), [
    (proposal(description="", due=None), ["Typ: Aufgabe", "Beschreibung: —", "Fälligkeit: —"]),
    (proposal(kind="event", start="2026-05-10T10:00:00+02:00", end="2026-05-10T11:00:00+02:00", location="Raum 1", video_link="https://video.example.test/abc"),
     ["Typ: Termin", "Beginn: 2026-05-10T10:00:00+02:00", "Ganztägig: Nein", "Konfigurierte Zeitzone: Europe/Berlin", "Ort: Raum 1", "Videolink: https://video.example.test/abc"]),
    (proposal(kind="event", all_day=True, start="2026-05-10", end="2026-05-11", location=None),
     ["Ende: 2026-05-11", "Ganztägig: Ja", "Ort: —", "Videolink: —"]),
])
def test_central_proposal_formatting_for_tasks_and_events(item, expected):
    text = format_proposal(item, "Europe/Berlin")
    assert all(value in text for value in expected)
    assert [line.split(":", 1)[0] for line in text.splitlines() if not line.startswith("-")] [:8] == [
        "Vorschlagsversion", "Typ", "Zuständigkeit", "Sicherheit", "Einordnung",
        "Extern anlegbar", "Titel", "Beschreibung",
    ]


def test_persist_before_buttons_and_authorized_flow(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        p=proposal(title="t"*500, description="x"*4000)
        c.send_proposal(p)
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["version"]==1
        assert all("[Absender: — · Teil " in message for _, message, _ in t.sent)
        assert "Vorschlag p1" not in t.sent[-1][1] and "Ursprungsmail:" not in t.sent[-1][1]
        value=t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        assert len(t.sent)>=2 and value.startswith("decision:") and len(value.encode("utf-8")) <= 64
        assert Decision.parse(value, store) == Decision(mail_id="a"*24, proposal_id="p1", version=1, action=DecisionAction.CONFIRM)
        c.send(2,"ok")
        with pytest.raises(PermissionError): c.send(3,"x")

        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed" and "bestätigt" in t.answered[-1][1]
        # Duplicate update is ignored by the persisted offset after restart.
        c2,t2,_=controller(store,t.updates); c2.poll_once()
        assert t2.polls==[5] and not t2.answered
        # A replay with a fresh update id still cannot mutate the terminal state.
        t2.updates=[callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:reject")]; c2.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed" and "veraltet" in t2.answered[-1][1]


def test_proposal_notification_uses_persisted_sender_and_subject(tmp_path):
    mail_id = "a" * 24
    with JsonStore(tmp_path) as store:
        state = MailState(
            id=mail_id, config_fingerprint="f" * 64,
            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
            display_headers={"sender": "Ada <ada@example.test>", "subject": "Besprechung"},
        )
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog, transport, _ = controller(store)
        dialog.send_proposal(proposal(source_mail_id=mail_id))
        text = transport.sent[-1][1]
        assert text.startswith("[Absender: Ada <ada@example.test> · Teil 1/1]\nBetreff: Besprechung\n")
        assert mail_id not in text and "Vorschlag p1" not in text


def test_only_exactly_displayed_version_is_written(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        c.send_proposal(proposal(version=1))
        c.send_proposal(proposal(version=2, title="Neue Fassung"))
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"),callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:confirm")]
        c.poll_once()
        assert "veraltet" in t.answered[0][1]
        assert writer.versions == [2]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["title"] == "Neue Fassung"


def test_deadline_clarification_blocks_every_external_request(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        item=proposal(due="2026-10-01", status="needs_clarification",
                      open_questions=["Welcher Datumskontext soll verwendet werden?"])
        c.send_proposal(item)
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert writer.reconciled == 0 and writer.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "needs_clarification"


def test_identical_proposals_have_isolated_confirmation_and_external_results(tmp_path):
    common=dict(timezone="UTC",poll_interval_seconds=5,data_directory=tmp_path/"state",
                imap={"host":"h","port":993,"folders":["INBOX"]},telegram={"user_id":1,"chat_id":2},
                targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},
                retries={"provider_retry":0,"json_repair":0,"schema_repair":0},timeouts={**{name:{"timeout_seconds":30,"retries":0,"initial_backoff_seconds":0,"max_backoff_seconds":1} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},
                logging={"directory":str(tmp_path/"logs"),"console":{"enabled":False},"file":{"filename":"application.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30},"llm":{"filename":"llm/requests.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30}})
    test_settings=Settings(test_mode=True,**common)
    production_settings=Settings(test_mode=False,**common)
    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        test_dialog,_,_=controller(test_store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":Writer()},True)
        test_dialog.persist(proposal()); test_dialog.poll_once()
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2

    writer=Writer()
    with JsonStore(_state_directory(production_settings,tmp_path)) as production_store:
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1") is None
        assert production_store.load("telegram-offset") is None
        production_dialog,_,_=controller(production_store,[callback(7,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer})
        production_dialog.persist(proposal()); production_dialog.poll_once()
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["external_id"]=="external-1"
        assert production_store.load("telegram-offset")["offset"]==8
        assert writer.created==1

    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2


def test_same_llm_id_from_two_mails_survives_restart_and_writes_separately(tmp_path):
    first_mail, second_mail = "a" * 24, "b" * 24
    first_writer, second_writer = Writer(), Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":first_writer})
        c.persist(proposal(source_mail_id=first_mail))
        c.persist(proposal(source_mail_id=second_mail))
        assert store.load(f"proposal-{first_mail}-p1")["source_mail_id"] == first_mail
        assert store.load(f"proposal-{second_mail}-p1")["source_mail_id"] == second_mail
        t.updates=[callback(1,f"proposal:{first_mail}:p1:1:confirm")]
        c.poll_once()
        assert first_writer.created == 1

        restarted,t2,_=controller(store,[callback(2,f"proposal:{second_mail}:p1:1:confirm")],
                                  {"todoist":second_writer})
        restarted.poll_once()
        assert second_writer.created == 0
        repeat_data = t2.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        t2.updates = [callback(3, repeat_data)]
        restarted.poll_once()
        assert second_writer.created == 1
        assert store.load(f"proposal-{first_mail}-p1")["external_id"] == "external-1"
        assert store.load(f"proposal-{second_mail}-p1")["external_id"] == "external-1"

        # A fresh Telegram update cannot execute the already-created first proposal again.
        t2.updates=[callback(4,f"proposal:{first_mail}:p1:1:confirm")]
        restarted.poll_once()
        assert first_writer.created == 1 and second_writer.created == 1
        assert "veraltet" in t2.answered[-1][1]

def test_edit_question_answer_new_version_then_reject(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_proposal(proposal(open_questions=["Wann?", "Wo?"]))
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="needs_clarification"
        labels=[button["text"] for button in t.sent[-1][2]["inline_keyboard"][0]]
        assert labels == ["Klären", "Verwerfen"] and "Bestätigen" not in labels
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"), callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:edit")]
        c.poll_once()
        assert "Zuerst" in t.answered[0][1] and store.load("telegram-dialog")["proposal_id"]=="p1"
        t.updates=[message(3,"Morgen")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["open_questions"]==["Wo?"]
        # Select edit and answer the remaining question, producing a confirmable v3.
        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:edit"),message(5,"Berlin")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==3 and store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="pending_confirmation"
        t.updates=[callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:3:reject")]; c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="rejected" and "verworfen" in t.answered[-1][1]


def test_invalid_unauthorized_missing_and_stale_dialogs(tmp_path):
    with JsonStore(tmp_path) as store:
        bad=[{"not":"an update"}, {"update_id":1,"message":{"private":"do not log"}}, message(2,user=9), message(3,chat=9), callback(4,"bad"), callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:missing:1:confirm"), callback(6,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm",user=9)]
        c,t,log=controller(store,bad); c.poll_once()
        assert store.load("telegram-offset")["offset"]==7
        assert any("syntaktisch" in item[1] for item in t.sent)
        assert any("Nicht autorisierte" in text for _,text in t.answered)
        assert "private" not in repr(log.events)

        c.persist(proposal(version=2))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        t.updates=[message(7)]; c.poll_once(); assert "veraltet" in t.sent[-1][1]
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"gone","version":1})
        t.updates=[message(8)]; c.poll_once(); assert "nicht gefunden" in t.sent[-1][1]
        t.updates=[message(9)]; c.poll_once(); assert "Keine offene" in t.sent[-1][1]

        c.revision_service=FailingRevisionService()
        c.persist(proposal(version=2, description="x"*3995, status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":2})
        t.updates=[message(10,"zu lang")]; c.poll_once()
        assert "widerspruchsfrei" in t.sent[-1][1] and store.load("telegram-dialog")["version"]==2


def test_revision_unavailable_preserves_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        transport=Telegram([message(1,"Neuer Titel")]); log=Logger()
        c=TelegramDialogController(store,transport,1,2,log)
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog",{"mail_id":"a"*24,"proposal_id":"p1","version":1})
        c.poll_once()
        assert "nicht verfügbar" in transport.sent[-1][1]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["version"]==1
        assert store.load("telegram-dialog")["proposal_id"]=="p1"


def test_operational_reply_failure_is_logged_and_not_acknowledged(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [message(4, "Neuer Titel")],
                           revision_service=OperationallyFailingRevisionService())
        c.persist(proposal(status="needs_clarification"))
        store.save("telegram-dialog", {"mail_id":"a"*24,"proposal_id":"p1","version":1})
        with pytest.raises(RuntimeError, match="provider unavailable"):
            c.poll_once()
        assert store.load("telegram-offset") is None
        assert store.load("telegram-dialog")["proposal_id"] == "p1"
        event = next(item for item in log.events if item[0][2] == "update_processing_failed")
        assert event[1]["update_id"] == 4
        assert "provider unavailable" in str(event[1]["error"])


def test_unrelated_telegram_update_does_not_block_following_reply(tmp_path):
    unrelated = {"update_id": 1, "my_chat_member": {"private": "not logged"}}
    with JsonStore(tmp_path) as store:
        c,t,log=controller(store, [unrelated, message(2)])
        c.poll_once()
        assert store.load("telegram-offset")["offset"] == 3
        assert "Keine offene" in t.sent[-1][1]
        assert "private" not in repr(log.events)


def test_telegram_client_validation_and_callback():
    requests=[]
    def handler(request):
        requests.append(request)
        data={"ok":True,"result":[]} if request.url.path.endswith("getUpdates") else {"ok":True,"result":True}
        return httpx.Response(200,json=data,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    assert client.poll(0)==[]
    client.send(2,"x",{"inline_keyboard":[]}); client.answer_callback("c","ok"); client.close()
    assert len(requests)==3
    assert requests[0].url.params["allowed_updates"] == '["message","callback_query"]'
    invalid=TelegramClient("secret",1,httpx.MockTransport(lambda r:httpx.Response(200,json={"ok":True,"result":{}},request=r)))
    with pytest.raises(ValueError): invalid.poll(0)
    invalid.close()


def test_started_chats_ignores_unrelated_update_kind():
    payload = {"ok": True, "result": [
        {"update_id": 1, "my_chat_member": {"status": "member"}},
        message(2, "/start", user=1, chat=7),
    ]}
    client = TelegramClient("secret", 1, httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)))
    assert client.started_chats(1) == [7]
    client.close()


def test_telegram_client_preserves_documented_api_error_description():
    def rejected(request):
        return httpx.Response(400,json={"ok":False,"error_code":400,"description":"Bad Request: chat not found"},request=request)
    client=TelegramClient("top-secret",1,httpx.MockTransport(rejected))
    with pytest.raises(PermanentError) as error:
        client.send(2,"x")
    assert str(error.value) == (
        "Permanente Adapterantwort: Telegram sendMessage: Chat nicht erreichbar. "
        "Bitte den Bot im Zielchat zuerst mit /start starten, die numerische "
        "telegram.chat_id prüfen und bei Gruppen sicherstellen, dass der Bot Mitglied ist"
    )
    assert "top-secret" not in str(error.value)
    client.close()


def test_telegram_client_finds_only_configured_users_start_chats():
    payload = {"ok": True, "result": [
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": 42},
         "chat": {"id": 42}, "text": "/start"}},
        {"update_id": 2, "message": {"message_id": 2, "from": {"id": 42},
         "chat": {"id": -100}, "text": "/start@mailhelp_bot"}},
        {"update_id": 3, "message": {"message_id": 3, "from": {"id": 7},
         "chat": {"id": 7}, "text": "/start"}},
        {"update_id": 4, "message": {"message_id": 4, "from": {"id": 42},
         "chat": {"id": 42}, "text": "hello"}},
    ]}
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload, request=request)
    client = TelegramClient("secret", 1, httpx.MockTransport(handler))

    assert client.started_chats(42) == [-100, 42]
    assert seen[0].url.params["timeout"] == "0"
    assert seen[0].url.params["allowed_updates"] == '["message"]'
    client.close()


def test_telegram_started_chat_diagnostic_validates_api_response():
    for status, payload, error in (
        (200, {"wrong": True}, ValueError),
        (200, {"ok": False, "result": []}, ValueError),
        (400, {"ok": False, "description": "Bad Request: chat not found"},
         TelegramChatNotFoundError),
    ):
        client = TelegramClient(
            "secret", 1,
            httpx.MockTransport(lambda request, s=status, p=payload:
                                httpx.Response(s, json=p, request=request)),
        )
        with pytest.raises(error):
            client.started_chats(42)
        client.close()


def test_telegram_client_preserves_retryable_and_http_success_api_errors():
    responses=iter([
        (500,{"ok":False,"description":"Internal Server Error: try later"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: message is too long"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: chat not found"}),
    ])
    def rejected(request):
        status_code,payload=next(responses)
        return httpx.Response(status_code,json=payload,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(rejected))
    with pytest.raises(UncertainWriteError,match="Telegram sendMessage: Internal Server Error: try later"):
        client.send(2,"x")
    with pytest.raises(PermanentError,match="Telegram sendMessage: Bad Request: message is too long"):
        client.send(2,"x")
    with pytest.raises(PermanentError, match="Chat nicht erreichbar"):
        client.send(2,"x")
    client.close()


def test_telegram_error_description_boundary_rejects_unusable_fields():
    request=httpx.Request("POST","https://example.test")
    invalid_json=httpx.Response(400,content=b"not-json",request=request)
    list_json=httpx.Response(400,json=["description"],request=request)
    wrong_description=httpx.Response(400,json={"ok":False,"description":42},request=request)
    assert TelegramClient._description(invalid_json) is None
    assert TelegramClient._description(list_json) is None
    assert TelegramClient._description(wrong_description) is None
    with pytest.raises(httpx.HTTPStatusError) as error:
        TelegramClient._raise_for_status(wrong_description,"sendMessage")
    assert not hasattr(error.value,"safe_detail")
    TelegramClient._raise_api_error(invalid_json,"sendMessage")
    TelegramClient._raise_api_error(list_json,"sendMessage")
    TelegramClient._raise_api_error(wrong_description,"sendMessage")


def test_telegram_client_sends_calendar_document_and_validates_filename():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={"ok":True,"result":{"message_id":7}},request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    client.send_document(2,"termin.ics",b"BEGIN:VCALENDAR\r\n",caption="Import")
    client.send_document(2,"termin-ohne-text.ics",b"BEGIN:VCALENDAR\r\n")
    assert requests[0].url.path.endswith("/sendDocument")
    assert b'text/calendar' in requests[0].content and b'termin.ics' in requests[0].content
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"../termin.ics",b"x")
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"",b"x")
    client.close()


def test_confirmation_executes_and_reports_all_results(tmp_path):
    cases=[
        (Writer(),False,"created","Erstellt"),
        (Writer(error=httpx.ReadTimeout("timeout")),False,"uncertain","Unklarer"),
        (Writer(error=httpx.HTTPStatusError("bad",request=httpx.Request("POST","https://x"),response=httpx.Response(400))),False,"failed","fehlgeschlagen"),
        (Writer(),True,"simulated","Testmodus"),
    ]
    for index,(writer,test_mode,status,text) in enumerate(cases):
        with JsonStore(tmp_path/str(index)) as store:
            c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer},test_mode)
            c.persist(proposal()); c.poll_once()
            saved=store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")
            assert saved["status"]==status and text in t.sent[-1][1]
            if status=="created": assert saved["external_id"]=="external-1" and saved["external_link"]=="https://example.test/item"


def test_restart_reconciles_before_retry_and_duplicate_update_is_safe(tmp_path):
    with JsonStore(tmp_path) as store:
        first=Writer(error=httpx.ReadTimeout("timeout"))
        c,t,_=controller(store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":first})
        c.persist(proposal()); c.poll_once()
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
        c.persist(proposal(status="writing")); c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="uncertain"
        assert interrupted.reconciled == 1 and interrupted.created == 0

    class MinimalStore:
        def __init__(self): self.values={}
        def load(self,name,default=None): return self.values.get(name,default)
        def save(self,name,value): self.values[name]=value
        def load_model(self,name,model,default=None):
            value=self.load(name)
            return default if value is None else model.model_validate(value)
    minimal=MinimalStore(); c,_,_=controller(minimal); c.poll_once()


def test_uncertain_write_is_only_reconciled_across_restarts(tmp_path):
    with JsonStore(tmp_path) as store:
        failed=Writer(error=httpx.ConnectError("lost"))
        initial,telegram,_=controller(
            store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":failed})
        initial.persist(proposal()); initial.poll_once()
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
        assert "Erstellt" in messages.sent[-1][1]


class RelevanceHandler:
    def __init__(self, store): self.store=store; self.resumed=[]
    def resolve_relevance(self, mail_id, version, decision, offset):
        state=self.store.load_model("mail-"+mail_id,MailState)
        dialog=state.relevance_dialog
        if dialog is None or dialog.version != version or dialog.status.value != "open":
            raise ValueError("Die Relevanzfrage ist veraltet oder bereits beantwortet")
        state.relevance_dialog=dialog.model_copy(update={"status":RelevanceDialogStatus.DECIDED,"decision":decision,"telegram_offset":offset})
        state.awaiting_relevance=False
        self.store.save("mail-"+mail_id,state.model_dump(mode="json")); return state
    def resume_mail(self,state): self.resumed.append(state.id)


def relevance_state(mail_id, version=1):
    return MailState(id=mail_id,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},awaiting_relevance=True,relevance_dialog=RelevanceDialog(mail_id=mail_id,version=version))


def test_relevance_dialog_authorization_stale_restart_and_duplicate(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        updates=[callback(1,f"relevance:{mail_id}:1:relevant",user=9),callback(2,f"relevance:{mail_id}:2:relevant"),callback(3,f"relevance:{mail_id}:1:relevant")]
        c,t,_=controller(store,updates); handler=RelevanceHandler(store); c.relevance_handler=handler
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
        assert "Nicht autorisierte" in t.answered[0][1] and "veraltet" in t.answered[1][1]
        assert handler.resumed==[mail_id] and store.load("mail-"+mail_id)["relevance_dialog"]["telegram_offset"]==4
        restarted,t2,_=controller(store,[callback(3,f"relevance:{mail_id}:1:irrelevant")]); restarted.relevance_handler=handler
        restarted.poll_once(); assert t2.polls==[4] and "bereits verarbeitet" in t2.answered[-1][1]
        t2.updates=[callback(4,f"relevance:{mail_id}:1:irrelevant")]; restarted.poll_once()
        assert "bereits beantwortet" in t2.answered[-1][1]


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
        c,t,_=controller(store,[message(1,"relevant")]); c.relevance_handler=RelevanceHandler(store); c.poll_once()
        assert "nicht eindeutig" in t.sent[-1][1]
        state=store.load_model("mail-"+ids[1],MailState); state.relevance_dialog=None; state.awaiting_relevance=False
        store.save("mail-"+ids[1],state.model_dump(mode="json"))
        t.updates=[message(2,"irrelevant")]; c.poll_once()
        assert store.load("mail-"+ids[0])["relevance_dialog"]["decision"]=="irrelevant"


def test_invalid_relevance_callbacks_and_unavailable_handler(tmp_path):
    mail_id="a"*24
    with JsonStore(tmp_path) as store:
        store.save("mail-"+mail_id,relevance_state(mail_id).model_dump(mode="json"))
        c,t,_=controller(store,[callback(1,"relevance:bad"),callback(2,f"relevance:{mail_id}:1:relevant"),message(3,"irrelevant")])
        c.poll_once()
        assert "syntaktisch" in t.answered[0][1] and "nicht verfügbar" in t.answered[1][1]
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
        assert "Extern anlegbar: Nein – manuell prüfen" in transport.sent[-1][1]
        transport.updates = [callback(1, Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                                                   version=item.version, action=DecisionAction.CONFIRM).encode())]
        dialog.poll_once()
        assert writer.created == 0 and writer.reconciled == 0
        assert "offenen Fragen" in transport.answered[-1][1]
        dialog._execute(item.model_copy(update={"status": ProposalStatus.CONFIRMED}))
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
        from mailhelp.integrations import execute_confirmed
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
