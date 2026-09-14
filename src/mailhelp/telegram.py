"""Strict Telegram trust boundary and restart-safe proposal dialogs."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import Proposal, ProposalStatus
from .integrations import ExternalWriter, execute_confirmed
from .storage import JsonStore


class TelegramModel(BaseModel):
    """Telegram fields used by Mailhelp; everything else is rejected."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class TelegramUser(TelegramModel):
    id: int


class TelegramChat(TelegramModel):
    id: int


class TelegramMessage(TelegramModel):
    message_id: int
    sender: TelegramUser = Field(alias="from")
    chat: TelegramChat
    text: str = Field(min_length=1, max_length=4096)


class TelegramCallbackQuery(TelegramModel):
    id: str = Field(min_length=1, max_length=128)
    sender: TelegramUser = Field(alias="from")
    message: TelegramMessage
    data: str = Field(min_length=1, max_length=64)


class TelegramUpdate(TelegramModel):
    update_id: int = Field(ge=0)
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "TelegramUpdate":
        if (self.message is None) == (self.callback_query is None):
            raise ValueError("Update muss genau eine Nachricht oder Callback-Query enthalten")
        return self


class DecisionAction(StrEnum):
    CONFIRM = "confirm"
    EDIT = "edit"
    REJECT = "reject"


class Decision(TelegramModel):
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    version: int = Field(ge=1)
    action: DecisionAction

    def encode(self) -> str:
        return f"proposal:{self.proposal_id}:{self.version}:{self.action.value}"

    @classmethod
    def parse(cls, value: str) -> "Decision":
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "proposal" or not parts[2].isascii() or not parts[2].isdigit():
            raise ValueError("Ungültige Aktion")
        return cls(proposal_id=parts[1], version=int(parts[2]), action=DecisionAction(parts[3]))


def apply_decision(
    proposal: Proposal,
    decision: Decision,
    user_id: int,
    chat_id: int,
    allowed_user: int,
    allowed_chat: int,
) -> Proposal:
    if (user_id, chat_id) != (allowed_user, allowed_chat):
        raise PermissionError("Nicht autorisierte Telegram-Anfrage")
    if decision.proposal_id != proposal.id or decision.version != proposal.version:
        raise ValueError("Veraltete oder unpassende Bestätigung")
    if proposal.status != ProposalStatus.PENDING_CONFIRMATION:
        return proposal
    if decision.action == DecisionAction.CONFIRM:
        if proposal.open_questions:
            raise ValueError("Offene Fragen verhindern die Bestätigung")
        return proposal.model_copy(update={"status": ProposalStatus.CONFIRMED})
    if decision.action == DecisionAction.REJECT:
        return proposal.model_copy(update={"status": ProposalStatus.REJECTED})
    return proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or [""]


def numbered_message_parts(mail_id: str, proposal_id: str, text: str, limit: int = 4000) -> list[str]:
    """Split text while putting a stable identity and ordering on every part."""
    if not mail_id or not proposal_id:
        raise ValueError("Mail- und Vorschlags-ID werden benötigt")
    if limit < 32:
        raise ValueError("limit ist zu klein für eine sichere Zuordnung")
    count = 1
    while True:
        prefix = f"[Mail {mail_id} · Vorschlag {proposal_id} · Teil {count}/{count}]\n"
        chunks = split_message(text, limit - len(prefix))
        if len(chunks) == count:
            break
        count = len(chunks)
    return [f"[Mail {mail_id} · Vorschlag {proposal_id} · Teil {index}/{count}]\n{part}" for index, part in enumerate(chunks, 1)]


class TelegramClient:
    def __init__(self, token: str, timeout: float, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport)

    def poll(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        response = self.client.get("/getUpdates", params={"offset": offset, "timeout": timeout})
        response.raise_for_status()
        result = response.json().get("result")
        if not isinstance(result, list):
            raise ValueError("Telegram-Antwort enthält keine Update-Liste")
        return result

    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        parts = split_message(text)
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_markup is not None and index == len(parts) - 1:
                payload["reply_markup"] = reply_markup
            response = self.client.post("/sendMessage", json=payload)
            response.raise_for_status()

    def answer_callback(self, callback_id: str, text: str) -> None:
        response = self.client.post("/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})
        response.raise_for_status()

    def close(self) -> None:
        self.client.close()


class TelegramTransport(Protocol):
    def poll(self, offset: int) -> list[dict[str, Any]]: ...
    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: Any) -> None: ...


class TelegramDialogController:
    """Validate updates, persist offsets, and enforce version-bound decisions."""

    def __init__(self, store: JsonStore, telegram: TelegramTransport, user_id: int, chat_id: int, logger: EventLogger, writers: dict[str, ExternalWriter] | None = None, test_mode: bool = False):
        self.store, self.telegram, self.user_id, self.chat_id, self.logger = store, telegram, user_id, chat_id, logger
        self.writers, self.test_mode = writers or {}, test_mode

    @staticmethod
    def _proposal_name(proposal_id: str) -> str:
        return f"proposal-{proposal_id}"

    @staticmethod
    def _version_name(proposal_id: str, version: int) -> str:
        return f"proposal-{proposal_id}-v{version}"

    def persist(self, proposal: Proposal) -> None:
        value = proposal.model_dump(mode="json")
        self.store.save(self._version_name(proposal.id, proposal.version), value)
        self.store.save(self._proposal_name(proposal.id), value)

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError("Nachrichten dürfen nur an den konfigurierten Chat gesendet werden")
        self.telegram.send(chat_id, text)

    def send_proposal(self, proposal: Proposal) -> None:
        """Persist first, then expose controls for precisely that immutable version."""
        if proposal.open_questions and proposal.status == ProposalStatus.PENDING_CONFIRMATION:
            proposal = proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
        self.persist(proposal)
        text = f"{proposal.title}\n{proposal.description}".rstrip()
        parts = numbered_message_parts(proposal.source_mail_id, proposal.id, text)
        for part in parts[:-1]:
            self.telegram.send(self.chat_id, part)
        buttons = [[
            {"text": "Bestätigen", "callback_data": Decision(proposal_id=proposal.id, version=proposal.version, action=DecisionAction.CONFIRM).encode()},
            {"text": "Ändern", "callback_data": Decision(proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode()},
            {"text": "Verwerfen", "callback_data": Decision(proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode()},
        ]]
        self.telegram.send(self.chat_id, parts[-1], {"inline_keyboard": buttons})

    def poll_once(self) -> None:
        self._resume_writes()
        offset = self.store.load("telegram-offset", {"offset": 0})["offset"]
        for raw in self.telegram.poll(offset):
            raw_id = raw.get("update_id") if isinstance(raw, dict) else None
            if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id < offset:
                self.logger.event("WARNING", "telegram", "invalid_update")
                continue
            try:
                update = TelegramUpdate.model_validate(raw)
                self._handle(update)
            except ValidationError:
                self.logger.event("WARNING", "telegram", "invalid_update", update_id=raw_id)
                self.telegram.send(self.chat_id, "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.")
            finally:
                offset = raw_id + 1
                self.store.save("telegram-offset", {"offset": offset})

    def _handle(self, update: TelegramUpdate) -> None:
        if update.callback_query is not None:
            callback = update.callback_query
            if not self._authorized(callback.sender.id, callback.message.chat.id):
                self.telegram.answer_callback(callback.id, "Nicht autorisierte Aktion.")
                return
            try:
                decision = Decision.parse(callback.data)
            except (ValueError, ValidationError):
                self.telegram.answer_callback(callback.id, "Aktion ist syntaktisch ungültig.")
                return
            self._decide(callback.id, decision)
            return
        message = update.message
        assert message is not None
        if not self._authorized(message.sender.id, message.chat.id):
            self.logger.event("WARNING", "telegram", "unauthorized_update", update_id=update.update_id)
            return
        self._answer(message.text)

    def _authorized(self, user_id: int, chat_id: int) -> bool:
        return (user_id, chat_id) == (self.user_id, self.chat_id)

    def _decide(self, callback_id: str, decision: Decision) -> None:
        value = self.store.load(self._proposal_name(decision.proposal_id))
        if value is None:
            self.telegram.answer_callback(callback_id, "Vorschlag wurde nicht gefunden.")
            return
        proposal = Proposal.model_validate(value)
        if proposal.version != decision.version or proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
            self.telegram.answer_callback(callback_id, "Diese Schaltfläche ist veraltet; der Status blieb unverändert.")
            return
        if decision.action == DecisionAction.EDIT:
            changed = proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
            self.persist(changed)
            self.store.save("telegram-dialog", {"proposal_id": proposal.id, "version": proposal.version})
            prompt = proposal.open_questions[0] if proposal.open_questions else "Welche Änderung soll übernommen werden?"
            self.telegram.answer_callback(callback_id, "Änderung ausgewählt.")
            self.telegram.send(self.chat_id, prompt)
            return
        if proposal.status != ProposalStatus.PENDING_CONFIRMATION:
            self.telegram.answer_callback(callback_id, "Zuerst müssen die offenen Fragen beantwortet werden.")
            return
        changed = apply_decision(proposal, decision, self.user_id, self.chat_id, self.user_id, self.chat_id)
        self.persist(changed)
        response = "Vorschlag bestätigt." if changed.status == ProposalStatus.CONFIRMED else "Vorschlag verworfen."
        self.telegram.answer_callback(callback_id, response)
        if changed.status == ProposalStatus.CONFIRMED:
            self._execute(changed)

    def _writer(self, proposal: Proposal) -> ExternalWriter | None:
        return self.writers.get("todoist" if proposal.kind.value == "task" else "google_calendar")

    def _execute(self, proposal: Proposal) -> None:
        writer = self._writer(proposal)
        if writer is None:
            return
        changed, result = execute_confirmed(proposal, writer, self.persist, self.test_mode)
        if result.get("simulation"):
            text = f"Testmodus: „{proposal.title}“ wurde nur simuliert."
        elif changed.status == ProposalStatus.CREATED:
            details = f" (ID: {changed.external_id})" if changed.external_id else ""
            link = f" {changed.external_link}" if changed.external_link else ""
            text = f"Erstellt: „{proposal.title}“{details}.{link}"
        elif changed.status == ProposalStatus.UNCERTAIN:
            text = f"Unklarer Schreiberfolg bei „{proposal.title}“; vor einem neuen Versuch wird abgeglichen."
        else:
            text = f"Erstellen von „{proposal.title}“ fehlgeschlagen."
        self.telegram.send(self.chat_id, text)

    def _resume_writes(self) -> None:
        names = getattr(self.store, "names", None)
        if names is None:
            return
        for name in names("proposal-"):
            if "-v" in name:
                continue
            proposal = Proposal.model_validate(self.store.load(name))
            if proposal.status in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN}:
                self._execute(proposal)

    def _answer(self, answer: str) -> None:
        dialog = self.store.load("telegram-dialog")
        if not dialog:
            self.telegram.send(self.chat_id, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen.")
            return
        value = self.store.load(self._proposal_name(dialog["proposal_id"]))
        if value is None:
            self.store.save("telegram-dialog", {})
            self.telegram.send(self.chat_id, "Der zugehörige Vorschlag wurde nicht gefunden.")
            return
        proposal = Proposal.model_validate(value)
        if proposal.version != dialog["version"] or proposal.status != ProposalStatus.NEEDS_CLARIFICATION:
            self.store.save("telegram-dialog", {})
            self.telegram.send(self.chat_id, "Die Rückfrage ist veraltet; es wurde nichts geändert.")
            return
        remaining = proposal.open_questions[1:]
        description = f"{proposal.description}\nAntwort: {answer}".strip()
        if len(description) > 4000:
            self.telegram.send(self.chat_id, "Die Antwort ist zu lang und wurde nicht übernommen.")
            return
        revised = Proposal.model_validate({**proposal.model_dump(), **{
            "version": proposal.version + 1,
            "description": description,
            "open_questions": remaining,
            "status": ProposalStatus.NEEDS_CLARIFICATION if remaining else ProposalStatus.PENDING_CONFIRMATION,
        }})
        self.store.save("telegram-dialog", {})
        self.send_proposal(revised)
