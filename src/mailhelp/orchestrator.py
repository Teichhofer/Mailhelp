"""Zentrale, schema-validierte und wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from threading import Event
from typing import Any, Protocol

from .analysis import Analyzer
from .config import Topic
from .imap import FetchedMail
from .mime import prepare
from .models import MailState, Proposal
from .storage import JsonStore
from .openrouter import RateLimitExceeded


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...


class Orchestrator:
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int, logger: Any = None, clock: Any = time.time):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, max_mail_bytes
        self.stop_event = Event()
        self.logger = logger
        self.clock = clock

    def stop(self) -> None: self.stop_event.set()

    def _save(self, name: str, state: MailState) -> None:
        self.store.save(name, state.model_dump(mode="json"))

    def process(self, fetched: FetchedMail) -> dict[str, Any]:
        identity = f"{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        name = f"mail-{internal_id}"
        existing = self.store.load_model(name, MailState) if hasattr(self.store, "load_model") else self.store.load(name)
        state = existing if isinstance(existing, MailState) else MailState.model_validate(existing) if existing is not None else MailState(
            id=internal_id,
            imap={"folder": fetched.folder, "uidvalidity": fetched.uidvalidity, "uid": fetched.uid},
        )
        if state.deferred_until is not None and state.deferred_until.timestamp() > self.clock():
            return state.model_dump(mode="json")
        state.deferred_until = None
        if state.steps.completion == "completed":
            return state.model_dump(mode="json")
        try:
            if state.steps.preparation == "pending":
                state.mail = prepare(fetched.raw, self.max_bytes)
                state.mail["internal_id"] = internal_id
                state.steps.preparation = "completed"
                self._save(name, state)
            assert state.mail is not None
            if state.steps.relevance == "pending":
                call, relevance = self.analyzer.relevance(state.mail, self.topics)
                state.relevance = relevance
                state.llm_call_ids.append(call)
                state.steps.relevance = "completed"
                self._save(name, state)
            assert state.relevance is not None
            if state.relevance.decision == "irrelevant":
                state.steps.summary = "skipped"
                state.steps.action_detection = "skipped"
                state.steps.notification = "skipped"
            elif state.relevance.decision == "unclear":
                if state.steps.notification == "pending":
                    self.notifier.send(self.chat_id, f"Unklare Relevanz: {state.mail['subject']}")
                    state.steps.notification = "completed"
                    state.awaiting_relevance = True
                    self._save(name, state)
                return state.model_dump(mode="json")
            else:
                if state.steps.summary == "pending":
                    call, summary = self.analyzer.summary(state.mail)
                    state.summary = summary
                    state.llm_call_ids.append(call)
                    state.steps.summary = "completed"
                    self._save(name, state)
                if state.steps.action_detection == "pending":
                    call, actions = self.analyzer.actions(state.mail)
                    state.proposals = actions.proposals
                    state.llm_call_ids.append(call)
                    state.steps.action_detection = "completed"
                    self._save(name, state)
                if state.steps.notification == "pending":
                    assert state.summary is not None
                    self.notifier.send(self.chat_id, f"{state.mail['subject']}\n" + " ".join(state.summary.sentences))
                    for proposal in state.proposals:
                        self.notifier.send_proposal(proposal)
                    state.steps.notification = "completed"
                    self._save(name, state)
            state.steps.completion = "completed"
            state.error = None
            self._save(name, state)
        except RateLimitExceeded as exc:
            state.deferred_until = datetime.fromtimestamp(exc.next_allowed_at, timezone.utc)
            state.error = {"type": type(exc).__name__, "message": str(exc)}
            self._save(name, state)
            message = f"LLM-Limit erreicht; Mail bis {state.deferred_until.isoformat()} zurueckgestellt."
            self.notifier.send(self.chat_id, message)
            if self.logger is not None:
                self.logger.event("WARNING", "orchestrator", "llm_rate_limited", mail_id=state.id, next_allowed_at=state.deferred_until.isoformat())
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
