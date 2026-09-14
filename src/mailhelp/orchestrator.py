"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
from enum import StrEnum
from threading import Event
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .analysis import Analyzer
from .config import Topic
from .imap import FetchedMail
from .mime import prepare
from .models import Proposal, Relevance, Summary
from .storage import JsonStore


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class ProcessingSteps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preparation: StepStatus = StepStatus.PENDING
    relevance: StepStatus = StepStatus.PENDING
    summary: StepStatus = StepStatus.PENDING
    action_detection: StepStatus = StepStatus.PENDING
    notification: StepStatus = StepStatus.PENDING
    completion: StepStatus = StepStatus.PENDING


class MailState(BaseModel):
    """Persisted mail schema; every read and checkpoint crosses this boundary."""

    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=2, ge=2, le=2)
    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    imap: dict[str, Any]
    steps: ProcessingSteps = Field(default_factory=ProcessingSteps)
    mail: dict[str, Any] | None = None
    relevance: Relevance | None = None
    summary: Summary | None = None
    proposals: list[Proposal] = Field(default_factory=list)
    llm_call_ids: list[str] = Field(default_factory=list)
    awaiting_relevance: bool = False
    error: dict[str, str] | None = None


class Orchestrator:
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, max_mail_bytes
        self.stop_event = Event()

    def stop(self) -> None: self.stop_event.set()

    def _save(self, name: str, state: MailState) -> None:
        self.store.save(name, state.model_dump(mode="json"))

    def process(self, fetched: FetchedMail) -> dict[str, Any]:
        identity = f"{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        name = f"mail-{internal_id}"
        existing = self.store.load(name)
        state = MailState.model_validate(existing) if existing is not None else MailState(
            id=internal_id,
            imap={"folder": fetched.folder, "uidvalidity": fetched.uidvalidity, "uid": fetched.uid},
        )
        if state.steps.completion == StepStatus.COMPLETED:
            return state.model_dump(mode="json")
        try:
            if state.steps.preparation == StepStatus.PENDING:
                state.mail = prepare(fetched.raw, self.max_bytes)
                state.mail["internal_id"] = internal_id
                state.steps.preparation = StepStatus.COMPLETED
                self._save(name, state)
            assert state.mail is not None
            if state.steps.relevance == StepStatus.PENDING:
                call, relevance = self.analyzer.relevance(state.mail, self.topics)
                state.relevance = relevance
                state.llm_call_ids.append(call)
                state.steps.relevance = StepStatus.COMPLETED
                self._save(name, state)
            assert state.relevance is not None
            if state.relevance.decision == "irrelevant":
                state.steps.summary = StepStatus.SKIPPED
                state.steps.action_detection = StepStatus.SKIPPED
                state.steps.notification = StepStatus.SKIPPED
            elif state.relevance.decision == "unclear":
                if state.steps.notification == StepStatus.PENDING:
                    self.notifier.send(self.chat_id, f"Unklare Relevanz: {state.mail['subject']}")
                    state.steps.notification = StepStatus.COMPLETED
                    state.awaiting_relevance = True
                    self._save(name, state)
                return state.model_dump(mode="json")
            else:
                if state.steps.summary == StepStatus.PENDING:
                    call, summary = self.analyzer.summary(state.mail)
                    state.summary = summary
                    state.llm_call_ids.append(call)
                    state.steps.summary = StepStatus.COMPLETED
                    self._save(name, state)
                if state.steps.action_detection == StepStatus.PENDING:
                    call, actions = self.analyzer.actions(state.mail)
                    state.proposals = actions.proposals
                    state.llm_call_ids.append(call)
                    state.steps.action_detection = StepStatus.COMPLETED
                    self._save(name, state)
                if state.steps.notification == StepStatus.PENDING:
                    assert state.summary is not None
                    self.notifier.send(self.chat_id, f"{state.mail['subject']}\n" + " ".join(state.summary.sentences))
                    for proposal in state.proposals:
                        self.notifier.send_proposal(proposal)
                    state.steps.notification = StepStatus.COMPLETED
                    self._save(name, state)
            state.steps.completion = StepStatus.COMPLETED
            state.error = None
            self._save(name, state)
        except Exception as exc:
            state.error = {"type": type(exc).__name__, "message": str(exc)}
            self._save(name, state)
        return state.model_dump(mode="json")

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
