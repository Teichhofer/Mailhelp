"""Zentrale, wiederaufnehmbare Ablaufsteuerung."""
from __future__ import annotations
import hashlib
from threading import Event
from typing import Any, Protocol
from .analysis import Analyzer
from .config import Topic
from .imap import FetchedMail
from .mime import prepare
from .storage import JsonStore


class Notifier(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def send_proposal(self, proposal: Any) -> None: ...


class Orchestrator:
    def __init__(self, analyzer: Analyzer, store: JsonStore, notifier: Notifier, chat_id: int, topics: list[Topic], max_mail_bytes: int):
        self.analyzer, self.store, self.notifier, self.chat_id, self.topics, self.max_bytes = analyzer, store, notifier, chat_id, topics, max_mail_bytes
        self.stop_event = Event()

    def stop(self) -> None: self.stop_event.set()

    def process(self, fetched: FetchedMail) -> dict[str, Any]:
        identity = f"{fetched.folder}:{fetched.uidvalidity}:{fetched.uid}"
        internal_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        existing = self.store.load(f"mail-{internal_id}")
        if existing and existing.get("completed"): return existing
        state: dict[str, Any] = existing or {"schema_version": 1, "id": internal_id, "imap": {"folder": fetched.folder, "uidvalidity": fetched.uidvalidity, "uid": fetched.uid}, "completed": False}
        try:
            mail = prepare(fetched.raw, self.max_bytes); mail["internal_id"] = internal_id; state["mail"] = mail; self.store.save(f"mail-{internal_id}", state)
            call, relevance = self.analyzer.relevance(mail, self.topics); state["relevance"] = relevance.model_dump(); state.setdefault("llm_call_ids", []).append(call)
            if relevance.decision == "irrelevant": state["completed"] = True
            elif relevance.decision == "unclear": self.notifier.send(self.chat_id, f"Unklare Relevanz: {mail['subject']}"); state["awaiting_relevance"] = True
            else:
                call, summary = self.analyzer.summary(mail); state["summary"] = summary.model_dump(); state["llm_call_ids"].append(call)
                call, actions = self.analyzer.actions(mail); state["proposals"] = [x.model_dump(mode="json") for x in actions.proposals]; state["llm_call_ids"].append(call)
                self.notifier.send(self.chat_id, f"{mail['subject']}\n" + " ".join(summary.sentences))
                send_proposal = getattr(self.notifier, "send_proposal", None)
                if send_proposal is not None:
                    for proposal in actions.proposals:
                        send_proposal(proposal)
                state["completed"] = True
        except Exception as exc:
            state["error"] = {"type": type(exc).__name__, "message": str(exc)}
        self.store.save(f"mail-{internal_id}", state); return state

    def run(self, poll: Any, interval: float, wait: Any = None) -> None:
        waiter = wait or self.stop_event.wait
        while not self.stop_event.is_set():
            for mail in poll():
                if self.stop_event.is_set(): break
                self.process(mail)
            waiter(interval)
