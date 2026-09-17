"""Strict Telegram trust boundary and restart-safe proposal dialogs."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import (MailState, Proposal, ProposalKind, ProposalStatus, RelevanceDialog,
                     RelevanceDialogStatus, TelegramDialogState, TelegramOffset,
                     WriteAttemptReference)
from .integrations import ExternalWriter, execute_confirmed, proposal_is_writable
from .adapter import RetryPolicy, uncertain_write
from .storage import JsonStore
from .logging import EventLogger, NullLogger
from .analysis import validate_revision_successor
import time, traceback, uuid


class TelegramTransportModel(BaseModel):
    """Validated Telegram fields used by Mailhelp; API additions are discarded."""

    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)


class InternalTelegramModel(BaseModel):
    """Closed model for decisions that can affect Mailhelp's persisted state."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class TelegramUser(TelegramTransportModel):
    id: int


class TelegramChat(TelegramTransportModel):
    id: int


class TelegramMessage(TelegramTransportModel):
    message_id: int
    sender: TelegramUser = Field(alias="from")
    chat: TelegramChat
    text: str = Field(min_length=1, max_length=4096)


class TelegramCallbackQuery(TelegramTransportModel):
    id: str = Field(min_length=1, max_length=128)
    sender: TelegramUser = Field(alias="from")
    message: TelegramMessage
    data: str = Field(min_length=1, max_length=64)


class TelegramUpdate(TelegramTransportModel):
    update_id: int = Field(ge=0)
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "TelegramUpdate":
        if (self.message is None) == (self.callback_query is None):
            raise ValueError("Update muss genau eine Nachricht oder Callback-Query enthalten")
        return self


class TelegramUpdatesResponse(TelegramTransportModel):
    ok: bool
    result: list[TelegramUpdate]

    @model_validator(mode="after")
    def successful(self) -> "TelegramUpdatesResponse":
        if not self.ok: raise ValueError("Telegram meldet keinen Erfolg")
        return self


class TelegramWriteResult(TelegramTransportModel):
    message_id: int | None = None


class TelegramWriteResponse(TelegramTransportModel):
    ok: bool
    result: TelegramWriteResult | bool

    @model_validator(mode="after")
    def successful(self) -> "TelegramWriteResponse":
        if not self.ok: raise ValueError("Telegram meldet keinen Erfolg")
        return self


class DecisionAction(StrEnum):
    CONFIRM = "confirm"
    EDIT = "edit"
    REJECT = "reject"


class RelevanceDecision(InternalTelegramModel):
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    version: int = Field(ge=1)
    decision: str = Field(pattern=r"^(relevant|irrelevant)$")

    def encode(self) -> str:
        return f"relevance:{self.mail_id}:{self.version}:{self.decision}"

    @classmethod
    def parse(cls, value: str) -> "RelevanceDecision":
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "relevance" or not parts[2].isascii() or not parts[2].isdigit():
            raise ValueError("Ungültige Relevanzentscheidung")
        return cls(mail_id=parts[1], version=int(parts[2]), decision=parts[3])


class Decision(InternalTelegramModel):
    mail_id: str = Field(pattern=r"^[a-f0-9]{24}$")
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    version: int = Field(ge=1)
    action: DecisionAction

    def encode(self) -> str:
        return f"proposal:{self.mail_id}:{self.proposal_id}:{self.version}:{self.action.value}"

    @classmethod
    def parse(cls, value: str) -> "Decision":
        parts = value.split(":")
        if len(parts) != 5 or parts[0] != "proposal" or not parts[3].isascii() or not parts[3].isdigit():
            raise ValueError("Ungültige Aktion")
        return cls(mail_id=parts[1], proposal_id=parts[2], version=int(parts[3]), action=DecisionAction(parts[4]))


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
    if (decision.mail_id, decision.proposal_id, decision.version) != (proposal.source_mail_id, proposal.id, proposal.version):
        raise ValueError("Veraltete oder unpassende Bestätigung")
    if proposal.status != ProposalStatus.PENDING_CONFIRMATION:
        return proposal
    if decision.action == DecisionAction.CONFIRM:
        if not proposal_is_writable(proposal):
            raise ValueError("Dieser Vorschlag ist nur zur manuellen Prüfung bestimmt")
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


def format_proposal(proposal: Proposal, configured_timezone: str) -> str:
    """Render every decision-relevant field in one stable, human-readable order."""
    missing = "—"
    questions = "\n".join(f"- {question}" for question in proposal.open_questions)
    questions_display = f"\n{questions}" if questions else " Keine"
    lines = [
        f"Vorschlagsversion: {proposal.version}",
        f"Typ: {'Aufgabe' if proposal.kind == ProposalKind.TASK else 'Termin'}",
        f"Zuständigkeit: {proposal.responsibility.value}",
        f"Sicherheit: {proposal.certainty.value}",
        f"Einordnung: {proposal.classification.value}",
        f"Extern anlegbar: {'Ja' if proposal_is_writable(proposal) else 'Nein – manuell prüfen'}",
        f"Titel: {proposal.title}",
        f"Beschreibung: {proposal.description or missing}",
        f"Belegstelle: {proposal.evidence}",
        f"Ursprungsmail: {proposal.source_mail_id}",
        f"Offene Fragen:{questions_display}",
        f"Ziel: {proposal.target}",
    ]
    if proposal.kind == ProposalKind.TASK:
        lines.append(f"Fälligkeit: {proposal.due.isoformat() if proposal.due else missing}")
    else:
        lines.extend([
            f"Beginn: {proposal.start.isoformat() if proposal.start else missing}",
            f"Ende: {proposal.end.isoformat() if proposal.end else missing}",
            f"Ganztägig: {'Ja' if proposal.all_day else 'Nein'}",
            f"Konfigurierte Zeitzone: {configured_timezone}",
            f"Ort: {proposal.location or missing}",
            f"Videolink: {proposal.video_link or missing}",
        ])
    return "\n".join(lines)


class TelegramClient:
    def __init__(self, token: str, timeout: float, transport: httpx.BaseTransport | None = None, poll_timeout: int = 30, policy: RetryPolicy | None = None, logger: EventLogger | None = None):
        self.poll_timeout = poll_timeout
        self.client = httpx.Client(base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]:
        call_id, started = str(uuid.uuid4()), time.perf_counter()
        self.logger.event("INFO", "telegram", "poll_started", call_id=call_id, offset=offset)
        def request() -> httpx.Response:
            response = self.client.get("/getUpdates", params={"offset": offset, "timeout": self.poll_timeout if timeout is None else timeout})
            response.raise_for_status(); return response
        try:
            response = self.policy.run(request, lambda attempt: self.logger.event("DEBUG", "telegram", "poll_attempt", call_id=call_id, attempt=attempt),
                                       lambda attempt, exc: self.logger.event("WARNING", "telegram", "poll_retry", call_id=call_id, attempt=attempt, error=exc))
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", call_id=call_id, error=exc, stacktrace=traceback.format_exc(), duration_ms=round((time.perf_counter()-started)*1000, 3))
            raise
        try: parsed = TelegramUpdatesResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"Telegram getUpdates: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}") from exc
        result = [item.model_dump(by_alias=True) for item in parsed.result]
        self.logger.event("INFO", "telegram", "poll_completed", call_id=call_id, count=len(result), status=response.status_code, duration_ms=round((time.perf_counter()-started)*1000, 3))
        return result

    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        call_id = str(uuid.uuid4())
        self.logger.event("INFO", "telegram", "send_started", call_id=call_id)
        parts = split_message(text)
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_markup is not None and index == len(parts) - 1:
                payload["reply_markup"] = reply_markup
            def request() -> httpx.Response:
                response = self.client.post("/sendMessage", json=payload); response.raise_for_status(); return response
            response = uncertain_write(request)
            self._validate_write(response, "sendMessage")
        self.logger.event("INFO", "telegram", "send_completed", call_id=call_id, parts=len(parts))

    def answer_callback(self, callback_id: str, text: str) -> None:
        def request() -> httpx.Response:
            response = self.client.post("/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text}); response.raise_for_status(); return response
        response = uncertain_write(request)
        self._validate_write(response, "answerCallbackQuery")

    @staticmethod
    def _validate_write(response: httpx.Response, operation: str) -> None:
        try: TelegramWriteResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"Telegram {operation}: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}") from exc

    def close(self) -> None:
        self.client.close()


class TelegramTransport(Protocol):
    def poll(self, offset: int) -> list[dict[str, Any]]: ...
    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...


class ProposalRevisionService(Protocol):
    def revise_proposal(self, proposal: Proposal, question: str, authorized_answer: str) -> tuple[str, Proposal]: ...


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: Any) -> None: ...


class TelegramDialogController:
    """Validate updates, persist offsets, and enforce version-bound decisions."""

    def __init__(self, store: JsonStore, telegram: TelegramTransport, user_id: int, chat_id: int, logger: EventLogger, writers: dict[str, ExternalWriter] | None = None, test_mode: bool = False, configured_timezone: str = "UTC", revision_service: ProposalRevisionService | None = None):
        self.store, self.telegram, self.user_id, self.chat_id, self.logger = store, telegram, user_id, chat_id, logger
        self.writers, self.test_mode = writers or {}, test_mode
        self.configured_timezone = configured_timezone
        self.revision_service = revision_service
        self.relevance_handler: Any = None

    def send_relevance(self, dialog: RelevanceDialog) -> None:
        buttons = [[
            {"text": "Relevant", "callback_data": RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision="relevant").encode()},
            {"text": "Irrelevant", "callback_data": RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision="irrelevant").encode()},
        ]]
        self.telegram.send(self.chat_id, f"Relevanz für Mail {dialog.mail_id} auswählen:", {"inline_keyboard": buttons})

    @staticmethod
    def _proposal_name(mail_id: str, proposal_id: str) -> str:
        return f"proposal-{mail_id}-{proposal_id}"

    @staticmethod
    def _version_name(mail_id: str, proposal_id: str, version: int) -> str:
        return f"proposal-{mail_id}-{proposal_id}-v{version}"

    def persist(self, proposal: Proposal) -> None:
        value = proposal.model_dump(mode="json")
        version_name = self._version_name(proposal.source_mail_id, proposal.id, proposal.version)
        if self.store.load(version_name) is None:
            self.store.save(version_name, value)
        self.store.save(self._proposal_name(proposal.source_mail_id, proposal.id), value)
        if proposal.status in {ProposalStatus.WRITING, ProposalStatus.CREATED,
                               ProposalStatus.FAILED, ProposalStatus.UNCERTAIN}:
            mail_name = f"mail-{proposal.source_mail_id}"
            state = self.store.load_model(mail_name, MailState) if hasattr(self.store, "load_model") else None
            if isinstance(state, MailState):
                service = "todoist" if proposal.kind.value == "task" else "google_calendar"
                reference = WriteAttemptReference(
                    mail_id=proposal.source_mail_id,
                    proposal_id=proposal.id, proposal_version=proposal.version, service=service,
                    idempotency_key=f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}",
                )
                state.write_attempts = [item for item in state.write_attempts
                                        if (item.proposal_id, item.proposal_version, item.service) !=
                                        (reference.proposal_id, reference.proposal_version, reference.service)]
                state.write_attempts.append(reference)
                state.updated_at = datetime.now(timezone.utc)
                self.store.save(mail_name, state.model_dump(mode="json"))

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError("Nachrichten dürfen nur an den konfigurierten Chat gesendet werden")
        self.telegram.send(chat_id, text)

    def send_proposal(self, proposal: Proposal) -> None:
        """Persist first, then expose controls for precisely that immutable version."""
        if ((proposal.open_questions or proposal.responsibility.value == "unclear" or
             proposal.certainty.value != "certain") and
                proposal.status == ProposalStatus.PENDING_CONFIRMATION):
            proposal = proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
        self.persist(proposal)
        text = format_proposal(proposal, self.configured_timezone)
        parts = numbered_message_parts(proposal.source_mail_id, proposal.id, text)
        for part in parts[:-1]:
            self.telegram.send(self.chat_id, part)
        if not proposal_is_writable(proposal):
            buttons = [[
                {"text": "Manuell prüfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode()},
                {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode()},
            ]]
        elif proposal.open_questions:
            buttons = [[
                {"text": "Klären", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode()},
                {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode()},
            ]]
        else:
            buttons = [[
                {"text": "Bestätigen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.CONFIRM).encode()},
                {"text": "Ändern", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode()},
                {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode()},
            ]]
        self.telegram.send(self.chat_id, parts[-1], {"inline_keyboard": buttons})

    def poll_once(self) -> None:
        self._resume_writes()
        offset_state = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset())
        assert isinstance(offset_state, TelegramOffset)
        offset = max(offset_state.offset, self._durable_dialog_offset())
        for raw in self.telegram.poll(offset):
            raw_id = raw.get("update_id") if isinstance(raw, dict) else None
            if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id < offset:
                self.logger.event("WARNING", "telegram", "invalid_update")
                if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id < offset:
                    self._reject_duplicate_relevance(raw)
                continue
            try:
                update = TelegramUpdate.model_validate(raw)
                self._handle(update)
            except ValidationError:
                self.logger.event("WARNING", "telegram", "invalid_update", update_id=raw_id)
                self.telegram.send(self.chat_id, "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.")
            finally:
                offset = raw_id + 1
                self.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())

    def _reject_duplicate_relevance(self, raw: dict[str, Any]) -> None:
        """Make a replayed relevance answer visible without trusting raw fields."""
        try:
            update = TelegramUpdate.model_validate(raw)
        except ValidationError:
            return
        callback = update.callback_query
        if callback is not None and callback.data.startswith("relevance:") and self._authorized(callback.sender.id, callback.message.chat.id):
            self.telegram.answer_callback(callback.id, "Diese Relevanzantwort wurde bereits verarbeitet.")
            return
        message = update.message
        if message is not None and message.text.strip().lower() in {"relevant", "irrelevant"} and self._authorized(message.sender.id, message.chat.id):
            self.telegram.send(self.chat_id, "Diese Relevanzantwort wurde bereits verarbeitet.")

    def _handle(self, update: TelegramUpdate) -> None:
        if update.callback_query is not None:
            callback = update.callback_query
            if not self._authorized(callback.sender.id, callback.message.chat.id):
                self.telegram.answer_callback(callback.id, "Nicht autorisierte Aktion.")
                return
            if callback.data.startswith("relevance:"):
                try:
                    relevance = RelevanceDecision.parse(callback.data)
                except (ValueError, ValidationError):
                    self.telegram.answer_callback(callback.id, "Relevanzantwort ist syntaktisch ungültig.")
                    return
                self._decide_relevance(callback.id, relevance, update.update_id + 1)
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
        normalized = message.text.strip().lower()
        if normalized in {"relevant", "irrelevant"}:
            dialogs = self._open_relevance_dialogs()
            if len(dialogs) != 1:
                self.telegram.send(self.chat_id, "Freitext ist nicht eindeutig zuordenbar; bitte die Schaltfläche der gewünschten Mail verwenden.")
                return
            dialog = dialogs[0]
            self._decide_relevance(None, RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision=normalized), update.update_id + 1)
            return
        self._answer(message.text)

    def _all_relevance_dialogs(self) -> list[RelevanceDialog]:
        result = []
        for name in self.store.names("mail-") if hasattr(self.store, "names") else []:
            state = self.store.load_model(name, MailState)
            if isinstance(state, MailState) and state.relevance_dialog is not None:
                result.append(state.relevance_dialog)
        return result

    def _open_relevance_dialogs(self) -> list[RelevanceDialog]:
        return [item for item in self._all_relevance_dialogs() if item.status == RelevanceDialogStatus.OPEN]

    def _durable_dialog_offset(self) -> int:
        return max((item.telegram_offset or 0 for item in self._all_relevance_dialogs()), default=0)

    def _decide_relevance(self, callback_id: str | None, decision: RelevanceDecision, offset: int) -> None:
        try:
            if self.relevance_handler is None:
                raise ValueError("Relevanzverarbeitung ist nicht verfügbar")
            state = self.relevance_handler.resolve_relevance(decision.mail_id, decision.version, decision.decision, offset)
        except ValueError as exc:
            if callback_id is None:
                self.telegram.send(self.chat_id, str(exc))
            else:
                self.telegram.answer_callback(callback_id, str(exc))
            return
        text = f"Mail als {decision.decision} eingestuft."
        if callback_id is None:
            self.telegram.send(self.chat_id, text)
        else:
            self.telegram.answer_callback(callback_id, text)
        if decision.decision == "relevant":
            self.relevance_handler.resume_mail(state)

    def _authorized(self, user_id: int, chat_id: int) -> bool:
        return (user_id, chat_id) == (self.user_id, self.chat_id)

    def _decide(self, callback_id: str, decision: Decision) -> None:
        proposal = self.store.load_model(self._proposal_name(decision.mail_id, decision.proposal_id), Proposal)
        if proposal is None:
            self.telegram.answer_callback(callback_id, "Vorschlag wurde nicht gefunden.")
            return
        assert isinstance(proposal, Proposal)
        if proposal.version != decision.version or proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
            self.telegram.answer_callback(callback_id, "Diese Schaltfläche ist veraltet; der Status blieb unverändert.")
            return
        if decision.action == DecisionAction.EDIT:
            changed = proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})
            self.persist(changed)
            self.store.save("telegram-dialog", TelegramDialogState(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version).model_dump())
            prompt = proposal.open_questions[0] if proposal.open_questions else "Welche Änderung soll übernommen werden?"
            self.telegram.answer_callback(callback_id, "Änderung ausgewählt.")
            self.telegram.send(self.chat_id, prompt)
            return
        if decision.action == DecisionAction.CONFIRM and proposal.status != ProposalStatus.PENDING_CONFIRMATION:
            self.telegram.answer_callback(callback_id, "Zuerst müssen die offenen Fragen beantwortet werden.")
            return
        if decision.action == DecisionAction.CONFIRM and not proposal_is_writable(proposal):
            self.telegram.answer_callback(callback_id, "Dieser Fall ist nur zur manuellen Prüfung bestimmt und wird nicht angelegt.")
            return
        changed = (proposal.model_copy(update={"status": ProposalStatus.REJECTED})
                   if decision.action == DecisionAction.REJECT else
                   apply_decision(proposal, decision, self.user_id, self.chat_id, self.user_id, self.chat_id))
        self.persist(changed)
        response = "Vorschlag bestätigt." if changed.status == ProposalStatus.CONFIRMED else "Vorschlag verworfen."
        self.telegram.answer_callback(callback_id, response)
        if changed.status == ProposalStatus.CONFIRMED:
            self._execute(changed)

    def _writer(self, proposal: Proposal) -> ExternalWriter | None:
        return self.writers.get("todoist" if proposal.kind.value == "task" else "google_calendar")

    def _execute(self, proposal: Proposal) -> None:
        if not proposal_is_writable(proposal):
            return
        if proposal.status == ProposalStatus.SIMULATED and proposal.simulation_notified:
            return
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
            if changed.uncertain_notified:
                return
            text = f"Unklarer Schreiberfolg bei „{proposal.title}“; wird weiter abgeglichen und nicht automatisch wiederholt."
        else:
            text = f"Erstellen von „{proposal.title}“ fehlgeschlagen."
        self.telegram.send(self.chat_id, text)
        if changed.status == ProposalStatus.UNCERTAIN:
            self.persist(changed.model_copy(update={"uncertain_notified": True}))
        elif changed.status == ProposalStatus.SIMULATED:
            self.persist(changed.model_copy(update={"simulation_notified": True}))

    def _resume_writes(self) -> None:
        names = getattr(self.store, "names", None)
        if names is None:
            return
        for name in names("proposal-"):
            if "-v" in name:
                continue
            proposal = self.store.load_model(name, Proposal)
            assert isinstance(proposal, Proposal)
            if proposal.status in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING,
                                   ProposalStatus.UNCERTAIN, ProposalStatus.SIMULATED}:
                self._execute(proposal)

    def _answer(self, answer: str) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.telegram.send(self.chat_id, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen.")
            return
        assert dialog.mail_id is not None
        proposal = self.store.load_model(self._proposal_name(dialog.mail_id, dialog.proposal_id), Proposal)
        if proposal is None:
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(self.chat_id, "Der zugehörige Vorschlag wurde nicht gefunden.")
            return
        assert isinstance(proposal, Proposal)
        if proposal.version != dialog.version or proposal.status != ProposalStatus.NEEDS_CLARIFICATION:
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(self.chat_id, "Die Rückfrage ist veraltet; es wurde nichts geändert.")
            return
        question = proposal.open_questions[0] if proposal.open_questions else "Welche Änderung soll übernommen werden?"
        if self.revision_service is None:
            self.telegram.send(self.chat_id, "Die Überarbeitung ist derzeit nicht verfügbar; der Vorschlag blieb unverändert.")
            return
        try:
            _, candidate = self.revision_service.revise_proposal(proposal, question, answer)
            revised = validate_revision_successor(proposal, candidate)
        except (ValueError, ValidationError):
            self.telegram.send(self.chat_id, "Die Antwort konnte nicht widerspruchsfrei übernommen werden; der Vorschlag und die Rückfrage blieben unverändert.")
            return
        # send_proposal persists the immutable version before exposing it.
        self.send_proposal(revised)
        self.store.save("telegram-dialog", TelegramDialogState().model_dump())


def _validation_path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(part) for part in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
