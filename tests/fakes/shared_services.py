"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

import httpx
from shared_core import proposal

from mailhelp.config import Topic
from mailhelp.models import (
    ActionRoute,
    Relevance,
    TaskExtraction,
)
from mailhelp.orchestrator import MailState, Orchestrator
from mailhelp.storage import JsonStore


def mock_response(status=200, data=None):
    return lambda request: httpx.Response(status, json={} if data is None else data, request=request)

class FakeCompleter:
    def __init__(self, values):
        self.values=iter(values)
        self.calls=0
    def complete(self, *args, **kwargs):
        self.calls+=1
        return str(self.calls), next(self.values)

class RetrySequence:
    """Synthetic provider recording every logical provider invocation."""
    def __init__(self, values):
        self.values=iter(values)
        self.payloads=[]
        self.systems=[]
        self.parameters=[]
        self.call_ids=[]

    def complete(self, _model, parameters, system, payload, **_metadata):
        self.payloads.append(payload)
        self.systems.append(system)
        self.parameters.append(parameters)
        call_id=f"provider-call-{len(self.payloads)}"
        self.call_ids.append(call_id)
        value=next(self.values)
        if isinstance(value, Exception):
            raise value
        return call_id,value

class Writer:
    def __init__(self, found=None, error=None):
        self.found=found
        self.error=error
        self.created=0
    def reconcile(self,key): return self.found
    def create(self,p,key):
        self.created += 1
        if self.error: raise self.error
        return {"id":"1"}

class AnalyzerStub:
    last_relevance_source = "test"

    def __init__(self, decision): self.decision=decision
    def relevance(self,m,t):
        return "r",Relevance(decision=self.decision,topic_ids=[],reason="why")
    def summary(self,m):
        from mailhelp.models import Summary
        return "s",Summary(sentences=["eins","zwei"])
    def action_route(self,m):
        return "ar",ActionRoute(action_state="task",task_count=1,event_count=0,reason="synthetic")
    def actions(self,m):
        from mailhelp.models import Actions
        return "a",Actions()
    def extract_tasks(self,m, *, expected_count):
        from mailhelp.models import ExtractedTask
        return "t",TaskExtraction(tasks=[ExtractedTask(title="Aufgabe",description="",evidence="Body",responsibility="user",certainty="certain",classification="new")])
    def extract_events(self,m, *, expected_count):
        from mailhelp.models import EventExtraction
        return "e",EventExtraction(events=[])
    def answer_question_from_mail(self, mail, proposal, question):
        from mailhelp.models import TelegramAnswerInterpretation
        return "mq", TelegramAnswerInterpretation(
            usable=False, reason="Synthetische Mail beantwortet die Frage nicht")

class Notify:
    def __init__(self): self.messages=[]
    def send(self,c,t): self.messages.append(t)
    def send_proposal(self,p): self.messages.append(p.id)
    def send_relevance(self,d,sender,subject): self.messages.append((d.mail_id,sender,subject))

_NO_LLM_REVISION = AssertionError("LLM-Revision darf nicht laufen")


class _MailQuestionAnalyzer(AnalyzerStub):
    """Answers selected questions from the mail; the revision is configurable."""

    def __init__(self, answers, revision=_NO_LLM_REVISION):
        super().__init__("relevant")
        self.answers, self.revision, self.revisions = answers, revision, 0

    def answer_question_from_mail(self, mail, proposal, question):
        from mailhelp.models import TelegramAnswerInterpretation
        answer = self.answers.get(question)
        if answer is None:
            return "mq", TelegramAnswerInterpretation(usable=False, reason="Nicht in der Mail")
        return "mq", TelegramAnswerInterpretation(usable=True, normalized_answer=answer,
                                                  reason="In der Mail belegt")

    def revise_proposal(self, proposal, question, answer):
        self.revisions += 1
        if isinstance(self.revision, BaseException):
            raise self.revision
        return "rev", self.revision(proposal)

class _EventLog:
    def __init__(self): self.events = []
    def event(self, level, module, event, **fields): self.events.append((event, fields))

def _resolve_from_mail(tmp_path, analyzer, item):
    state = MailState(id="a" * 24, config_fingerprint="f" * 64,
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
                      mail={"text": "synthetische Mail", "user_timezone": "Europe/Berlin"},
                      proposals=[item])
    log = _EventLog()
    with JsonStore(tmp_path) as store:
        Orchestrator(analyzer, store, Notify(), 1,
                     [Topic(id="x", name="X", enabled=True, description="X")], 1000,
                     logger=log).questions.resolve("mail-" + "a" * 24, state)
    return state, [(event, fields.get("question"), fields.get("reason"))
                   for event, fields in log.events if event.startswith("mail_question_")]
