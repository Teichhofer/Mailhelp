"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from mailhelp.models import (
    MailState,
    Proposal,
    RelevanceDialog,
    RelevanceDialogStatus,
)
from mailhelp.telegram import (
    TelegramDialogController,
)


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
        self.updates = list(updates)
        self.polls=[]
        self.sent=[]
        self.answered=[]
        self.documents=[]
        self.removed=[]
    def poll(self, offset, timeout=None):
        self.polls.append(offset)
        return self.updates
    def send(self, chat, text, reply_markup=None): self.sent.append((chat,text,reply_markup))
    def answer_callback(self, callback_id, text): self.answered.append((callback_id,text))
    def remove_inline_keyboard(self, chat_id, message_id): self.removed.append((chat_id,message_id))
    def send_document(self, chat_id, filename, content, caption=None):
        self.documents.append((chat_id, filename, content, caption))

from log_fakes import RecordingLogger as Logger


class RevisionService:
    def __init__(self): self.calls=[]
    def interpret_telegram_answer(self, item, question, answer):
        self.calls.append(("interpret", item, question, answer))
        return "interpret-call", type("Interpretation", (), {
            "usable": True, "normalized_answer": answer, "reason": "passt"})()
    def clarify_telegram_answer(self, question, answer, reason, *, current_date=None):
        self.calls.append(("clarify", question, answer, reason, current_date))
        return "clarify-call", type("Clarification", (), {
            "message": f"Bitte konkreter beantworten: {question}"})()
    def revise_proposal(self, item, question, answer):
        self.calls.append((item,question,answer))
        remaining=item.open_questions[1:]
        return "revision-call", Proposal.model_validate({**item.model_dump(),
            "version":item.version+1, "description":answer,
            "open_questions":remaining,
            "status":"needs_clarification" if remaining else "pending_confirmation"})

class FailingRevisionService(RevisionService):
    def revise_proposal(self, item, question, answer): raise ValueError("contradiction")

class OperationallyFailingRevisionService(RevisionService):
    def revise_proposal(self, item, question, answer): raise RuntimeError("provider unavailable")

class UnusableAnswerService(RevisionService):
    def interpret_telegram_answer(self, item, question, answer):
        self.calls.append(("interpret", item, question, answer))
        return "interpret-call", type("Interpretation", (), {
            "usable": False, "normalized_answer": None, "reason": "Datum fehlt"})()

class InterpretationErrorService(RevisionService):
    def __init__(self, error):
        super().__init__()
        self.error = error
    def interpret_telegram_answer(self, item, question, answer):
        raise self.error

def controller(store, updates=(), writers=None, test_mode=False, revision_service=None):
    transport=Telegram(updates)
    log=Logger()
    service=revision_service if revision_service is not None else RevisionService()
    return TelegramDialogController(store,transport,1,2,log,writers,test_mode,"UTC",service),transport,log

class Writer:
    def __init__(self, found=None, error=None):
        self.found=found
        self.error=error
        self.created=0
        self.reconciled=0
        self.versions=[]
    def reconcile(self,key):
        self.reconciled+=1
        return self.found
    def create(self,p,key):
        self.created+=1
        self.versions.append(p.version)
        if self.error: raise self.error
        return {"id":"external-1","url":"https://example.test/item"}

class RelevanceHandler:
    def __init__(self, store):
        self.store=store
        self.resumed=[]
    def resolve_relevance(self, mail_id, version, decision, offset):
        state=self.store.load_model("mail-"+mail_id,MailState)
        dialog=state.relevance_dialog
        if dialog is None or dialog.version != version or dialog.status.value != "open":
            raise ValueError("Die Relevanzfrage ist veraltet oder bereits beantwortet")
        state.relevance_dialog=dialog.model_copy(update={"status":RelevanceDialogStatus.DECIDED,"decision":decision,"telegram_offset":offset})
        state.awaiting_relevance=False
        self.store.save("mail-"+mail_id,state.model_dump(mode="json"))
        return state
    def resume_mail(self,state): self.resumed.append(state.id)

def relevance_state(mail_id, version=1):
    return MailState(id=mail_id,config_fingerprint="0"*64,imap={"account_id":"0"*24,"folder":"INBOX","uidvalidity":1,"uid":1},awaiting_relevance=True,relevance_dialog=RelevanceDialog(mail_id=mail_id,version=version))
