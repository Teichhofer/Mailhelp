from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.models import Proposal, ProposalStatus
from mailhelp.storage import JsonStore
from mailhelp.telegram import (
    Decision,
    TelegramCallbackQuery,
    TelegramClient,
    TelegramDialogController,
    TelegramMessage,
    TelegramUpdate,
    numbered_message_parts,
)


def proposal(**changes):
    data = {"id": "p1", "version": 1, "kind": "task", "title": "Aufgabe", "description": "Text", "evidence": "Beleg", "source_mail_id": "m1", "target": "inbox"}
    data.update(changes)
    return Proposal.model_validate(data)


def message(update_id, text="Antwort", user=1, chat=2):
    return {"update_id": update_id, "message": {"message_id": update_id, "from": {"id": user}, "chat": {"id": chat}, "text": text}}


def callback(update_id, data, user=1, chat=2):
    return {"update_id": update_id, "callback_query": {"id": f"c{update_id}", "from": {"id": user}, "message": {"message_id": 1, "from": {"id": 1}, "chat": {"id": chat}, "text": "buttons"}, "data": data}}


class Telegram:
    def __init__(self, updates=()):
        self.updates = list(updates); self.polls=[]; self.sent=[]; self.answered=[]
    def poll(self, offset): self.polls.append(offset); return self.updates
    def send(self, chat, text, reply_markup=None): self.sent.append((chat,text,reply_markup))
    def answer_callback(self, callback_id, text): self.answered.append((callback_id,text))


class Logger:
    def __init__(self): self.events=[]
    def event(self, *args, **fields): self.events.append((args,fields))


def controller(store, updates=()):
    transport=Telegram(updates); log=Logger()
    return TelegramDialogController(store,transport,1,2,log),transport,log


def test_strict_schemas_and_decisions():
    parsed=Decision.parse("proposal:p1:3:confirm")
    assert parsed.encode()=="proposal:p1:3:confirm"
    for bad in ("x", "proposal:p1:x:confirm", "proposal:p1:٣:confirm", "proposal:p1:1:bad"):
        with pytest.raises((ValueError,ValidationError)): Decision.parse(bad)
    with pytest.raises(ValidationError): TelegramMessage.model_validate({"message_id":1,"from":{"id":1},"chat":{"id":2},"text":"x","unknown":True})
    with pytest.raises(ValidationError): TelegramCallbackQuery.model_validate({"id":"c","from":{"id":1},"message":message(1)["message"],"data":"x","unknown":1})
    with pytest.raises(ValidationError): TelegramUpdate(update_id=1)
    with pytest.raises(ValidationError): TelegramUpdate.model_validate({**message(1),"callback_query":callback(1,"x")["callback_query"]})


def test_numbered_parts():
    parts=numbered_message_parts("mail","proposal","x"*150,64)
    assert len(parts)>1 and all(f"Teil {i}/{len(parts)}" in part for i,part in enumerate(parts,1))
    with pytest.raises(ValueError): numbered_message_parts("","p","x")
    with pytest.raises(ValueError): numbered_message_parts("m","p","x",31)


def test_persist_before_buttons_and_authorized_flow(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        p=proposal(title="t"*500, description="x"*4000)
        c.send_proposal(p)
        assert store.load("proposal-p1-v1")["version"]==1
        assert len(t.sent)>=2 and t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]=="proposal:p1:1:confirm"
        c.send(2,"ok")
        with pytest.raises(PermissionError): c.send(3,"x")

        t.updates=[callback(4,"proposal:p1:1:confirm")]
        c.poll_once()
        assert store.load("proposal-p1")["status"]=="confirmed" and "bestätigt" in t.answered[-1][1]
        # Duplicate update is ignored by the persisted offset after restart.
        c2,t2,_=controller(store,t.updates); c2.poll_once()
        assert t2.polls==[5] and not t2.answered
        # A replay with a fresh update id still cannot mutate the terminal state.
        t2.updates=[callback(5,"proposal:p1:1:reject")]; c2.poll_once()
        assert store.load("proposal-p1")["status"]=="confirmed" and "veraltet" in t2.answered[-1][1]


def test_edit_question_answer_new_version_then_reject(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        c.send_proposal(proposal(open_questions=["Wann?", "Wo?"]))
        assert store.load("proposal-p1")["status"]=="needs_clarification"
        t.updates=[callback(1,"proposal:p1:1:confirm"), callback(2,"proposal:p1:1:edit")]
        c.poll_once()
        assert "Zuerst" in t.answered[0][1] and store.load("telegram-dialog")["proposal_id"]=="p1"
        t.updates=[message(3,"Morgen")]; c.poll_once()
        assert store.load("proposal-p1-v2")["open_questions"]==["Wo?"]
        # Select edit and answer the remaining question, producing a confirmable v3.
        t.updates=[callback(4,"proposal:p1:2:edit"),message(5,"Berlin")]; c.poll_once()
        assert store.load("proposal-p1")["version"]==3 and store.load("proposal-p1")["status"]=="pending_confirmation"
        t.updates=[callback(6,"proposal:p1:3:reject")]; c.poll_once()
        assert store.load("proposal-p1")["status"]=="rejected" and "verworfen" in t.answered[-1][1]


def test_invalid_unauthorized_missing_and_stale_dialogs(tmp_path):
    with JsonStore(tmp_path) as store:
        bad=[{"not":"an update"}, {"update_id":1,"message":{"private":"do not log"}}, message(2,user=9), message(3,chat=9), callback(4,"bad"), callback(5,"proposal:missing:1:confirm"), callback(6,"proposal:p1:1:confirm",user=9)]
        c,t,log=controller(store,bad); c.poll_once()
        assert store.load("telegram-offset")=={"offset":7}
        assert any("syntaktisch" in item[1] for item in t.sent)
        assert any("Nicht autorisierte" in text for _,text in t.answered)
        assert "private" not in repr(log.events)

        c.persist(proposal(version=2))
        store.save("telegram-dialog",{"proposal_id":"p1","version":1})
        t.updates=[message(7)]; c.poll_once(); assert "veraltet" in t.sent[-1][1]
        store.save("telegram-dialog",{"proposal_id":"gone","version":1})
        t.updates=[message(8)]; c.poll_once(); assert "nicht gefunden" in t.sent[-1][1]
        t.updates=[message(9)]; c.poll_once(); assert "Keine offene" in t.sent[-1][1]

        c.persist(proposal(version=2, description="x"*3995, status="needs_clarification"))
        store.save("telegram-dialog",{"proposal_id":"p1","version":2})
        t.updates=[message(10,"zu lang")]; c.poll_once()
        assert "zu lang" in t.sent[-1][1] and store.load("telegram-dialog")["version"]==2


def test_telegram_client_validation_and_callback():
    requests=[]
    def handler(request):
        requests.append(request)
        data={"result":[]} if request.url.path.endswith("getUpdates") else {}
        return httpx.Response(200,json=data,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    assert client.poll(0)==[]
    client.send(2,"x",{"inline_keyboard":[]}); client.answer_callback("c","ok"); client.close()
    assert len(requests)==3
    invalid=TelegramClient("secret",1,httpx.MockTransport(lambda r:httpx.Response(200,json={"result":{}},request=r)))
    with pytest.raises(ValueError): invalid.poll(0)
    invalid.close()
