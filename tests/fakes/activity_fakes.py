"""Doubles for activity reports: a read-only mailbox and a language model per step."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from shared_core import prompt_config

from mailhelp.activity.models import ReportDefinition
from mailhelp.config import PromptStep
from mailhelp.imap import FetchedMail, FolderNotReadable, ListedMailbox, MailCandidate


def raw_mail(subject: str, body: str, *, sender: str = "Schule <info@schule.test>",
             to: str = "Ich <ich@example.test>", message_id: str | None = None,
             headers: dict[str, str] | None = None) -> bytes:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message["Date"] = format_datetime(datetime(2026, 1, 10, 9, 0, tzinfo=UTC))
    if message_id:
        message["Message-ID"] = message_id
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(body)
    return message.as_bytes()


class Mailbox:
    """IMAP double: folders with roles, metadata listing and body fetching; it records every call."""

    def __init__(self, folders: dict[str, tuple[str | None, list[tuple[int, datetime, bytes]]]]):
        self.folders = folders
        self.last_uidvalidity: int | None = None
        self.calls: list[tuple[Any, ...]] = []
        self.fetch_errors: list[Exception] = []

    def list_folders(self) -> list[ListedMailbox]:
        return [ListedMailbox(name, frozenset(), role) for name, (role, _) in self.folders.items()]

    def discover_since(self, folder, after_uid, expected, ranges, max_count, historical_start=None):
        self.calls.append(("discover", folder, historical_start))
        if folder not in self.folders:
            raise FolderNotReadable(folder)
        self.last_uidvalidity = 7
        return [MailCandidate(folder, 7, uid, "0" * 24, received)
                for uid, received, _ in self.folders[folder][1] if received >= historical_start]

    def fetch_uid(self, folder, uid, uidvalidity):
        self.calls.append(("fetch", folder, uid, uidvalidity))
        if self.fetch_errors:
            raise self.fetch_errors.pop(0)
        received, raw = next((received, raw) for item_uid, received, raw in self.folders[folder][1]
                             if item_uid == uid)
        return FetchedMail(folder, uidvalidity, uid, raw, "0" * 24, received)

    @contextmanager
    def connection(self):
        self.calls.append(("open",))
        yield self


class Model:
    """Completer double: one answer function per prompt step; records each request."""

    def __init__(self, **answers: Any):
        self.answers, self.requests = answers, []
        self.service_name = "Fake"

    def complete(self, model, parameters, system, payload, *, stage, **kwargs):
        self.requests.append((stage, payload))
        answer = self.answers[stage]
        value = answer(payload) if callable(answer) else answer
        if isinstance(value, Exception):
            raise value
        return f"call-{len(self.requests)}", value


def activity_prompts():
    prompts = prompt_config()
    prompts.prompts["activity_relevance"] = PromptStep(system_prompt="Relevanz", parameters={"max_tokens": 200})
    prompts.prompts["activity_events"] = PromptStep(system_prompt="Termine", parameters={"max_tokens": 200})
    prompts.suspicious_link_phrases = ["konto bestätigen"]
    prompts.suspicious_link_hosts = ["bit.ly"]
    return prompts


def definition(**changes: Any) -> ReportDefinition:
    values = dict(title="Elternbeirat", topic="Termine und Aufgaben des Elternbeirats der Klasse 4b",
                  since=date(2026, 1, 1), until=date(2026, 1, 31), folders=["INBOX"])
    return ReportDefinition(**(values | changes))


__all__ = ["Mailbox", "Model", "activity_prompts", "definition", "raw_mail"]
