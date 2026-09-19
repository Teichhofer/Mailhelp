"""Strict Telegram trust boundary and restart-safe proposal dialogs."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
import hashlib
import json
import secrets
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import (ActionLedger, ActionLedgerEntry, MailState, Proposal, ProposalKind, ProposalStatus, RelevanceDialog,
                     RelevanceDialogStatus, TelegramDialogState, TelegramOffset,
                     WriteAttemptReference)
from .integrations import ExternalWriter, execute_confirmed, proposal_is_writable
from .adapter import PermanentError, RetryPolicy, uncertain_write
from .storage import JsonStore
from .logging import EventLogger, NullLogger
from .analysis import validate_revision_successor
import time, traceback, uuid


class TelegramChatNotFoundError(PermanentError):
    """The configured Telegram chat cannot be addressed by this bot."""


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
    # Telegram may return update kinds this application does not subscribe to
    # (in particular updates queued before allowed_updates was changed).  Keep
    # the envelope strict, but validate each update independently in the dialog
    # controller so one unrelated update cannot block every later reply.
    result: list[TelegramUpdate | dict[str, Any]]

    @model_validator(mode="after")
    def successful(self) -> "TelegramUpdatesResponse":
        if not self.ok: raise ValueError("Telegram meldet keinen Erfolg")
        if any(isinstance(item, dict) and ({"message", "callback_query"} & item.keys())
               for item in self.result):
            raise ValueError("Telegram-Update mit unterstütztem Typ ist ungültig")
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


class TelegramBot(TelegramTransportModel):
    id: int
    is_bot: bool
    username: str | None = None


class TelegramBotResponse(TelegramTransportModel):
    ok: bool
    result: TelegramBot

    @model_validator(mode="after")
    def successful(self) -> "TelegramBotResponse":
        if not self.ok or not self.result.is_bot:
            raise ValueError("Telegram meldet keinen gültigen Bot")
        return self


class DecisionAction(StrEnum):
    CONFIRM = "confirm"
    CONFIRM_DUPLICATE = "confirm_duplicate"
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

    def encode(self, store: JsonStore | None = None) -> str:
        """Encode a decision, preferably as an opaque, durable callback token.

        The store-less form is retained solely for short, already-issued legacy
        callbacks and deliberately refuses values Telegram could not transport.
        """
        if store is None:
            value = f"proposal:{self.mail_id}:{self.proposal_id}:{self.version}:{self.action.value}"
            validate_callback_data(value)
            return value
        while True:
            token = secrets.token_hex(16)
            name = f"telegram-callback-{token}"
            if store.load(name) is None:
                store.save(name, self.model_dump(mode="json"))
                return f"decision:{token}"

    @classmethod
    def parse(cls, value: str, store: JsonStore | None = None) -> "Decision":
        validate_callback_data(value)
        if value.startswith("decision:"):
            token = value.removeprefix("decision:")
            if len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
                raise ValueError("Ungültiger Callback-Token")
            record = store.load(f"telegram-callback-{token}") if store is not None else None
            if record is None:
                raise ValueError("Unbekannter Callback-Token")
            if (not isinstance(record, dict) or
                    not isinstance(record.get("action"), str)):
                raise ValueError("Ungültiger Callback-Datensatz")
            return cls.model_validate({**record, "action": DecisionAction(record["action"])})
        parts = value.split(":")
        if len(parts) != 5 or parts[0] != "proposal" or not parts[3].isascii() or not parts[3].isdigit():
            raise ValueError("Ungültige Aktion")
        return cls(mail_id=parts[1], proposal_id=parts[2], version=int(parts[3]), action=DecisionAction(parts[4]))


def validate_callback_data(value: str) -> None:
    """Enforce Telegram's documented callback_data UTF-8 byte boundary locally."""
    size = len(value.encode("utf-8"))
    if not 1 <= size <= 64:
        raise ValueError(f"Telegram callback_data muss 1 bis 64 UTF-8-Bytes lang sein (ist {size})")


def validate_callback_markup(reply_markup: dict[str, Any] | None) -> None:
    if reply_markup is None:
        return
    for row in reply_markup.get("inline_keyboard", []):
        for button in row:
            if "callback_data" in button:
                value = button["callback_data"]
                if not isinstance(value, str):
                    raise ValueError("Telegram callback_data muss eine Zeichenkette sein")
                validate_callback_data(value)


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
        return proposal.model_copy(update={"status": ProposalStatus.CONFIRMED})
    if decision.action == DecisionAction.REJECT:
        return proposal.model_copy(update={"status": ProposalStatus.REJECTED})
    return proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION})


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or [""]


def numbered_message_parts(sender: str, subject: str, text: str, limit: int = 4000) -> list[str]:
    """Split text while repeating its human-readable mail context on every part."""
    if not sender or not subject:
        raise ValueError("Absender und Betreff werden benötigt")
    if limit < 32:
        raise ValueError("limit ist zu klein für eine sichere Zuordnung")
    count = 1
    while True:
        prefix = f"[Absender: {sender} · Teil {count}/{count}]\nBetreff: {subject}\n"
        chunks = split_message(text, limit - len(prefix))
        if len(chunks) == count:
            break
        count = len(chunks)
    return [f"[Absender: {sender} · Teil {index}/{count}]\nBetreff: {subject}\n{part}"
            for index, part in enumerate(chunks, 1)]


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
    _CHAT_NOT_FOUND_HELP = (
        "Telegram {operation}: Chat nicht erreichbar. Bitte den Bot im Zielchat "
        "zuerst mit /start starten, die numerische telegram.chat_id prüfen und "
        "bei Gruppen sicherstellen, dass der Bot Mitglied ist"
    )

    def __init__(self, token: str, timeout: float, transport: httpx.BaseTransport | None = None, poll_timeout: int = 30, policy: RetryPolicy | None = None, logger: EventLogger | None = None):
        self.poll_timeout = poll_timeout
        self.client = httpx.Client(base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def check_access(self) -> None:
        """Validate the bot token without reading updates."""
        response = self.policy.run(lambda: self.client.get("/getMe"))
        self._raise_for_status(response, "getMe")
        self._raise_api_error(response, "getMe")
        try:
            TelegramBotResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram getMe: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc

    def started_chats(self, user_id: int) -> list[int]:
        """Return chats in which the configured user most recently sent /start.

        This is used only after an access check failed.  Filtering locally by the
        configured user prevents diagnostics from disclosing unrelated bot users.
        """
        response = self.policy.run(lambda: self.client.get(
            "/getUpdates", params={"timeout": 0, "allowed_updates": '["message"]'},
        ))
        self._raise_for_status(response, "getUpdates")
        self._raise_api_error(response, "getUpdates")
        try:
            parsed = TelegramUpdatesResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram getUpdates: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc
        chats = set()
        for item in parsed.result:
            if not isinstance(item, TelegramUpdate):
                continue
            if (item.message is not None
                    and item.message.sender.id == user_id
                    and item.message.text.partition("@")[0] == "/start"):
                chats.add(item.message.chat.id)
        return sorted(chats)

    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]:
        call_id, started = str(uuid.uuid4()), time.perf_counter()
        self.logger.event("INFO", "telegram", "poll_started", call_id=call_id, offset=offset)
        def request() -> httpx.Response:
            response = self.client.get("/getUpdates", params={
                "offset": offset,
                "timeout": self.poll_timeout if timeout is None else timeout,
                "allowed_updates": '["message","callback_query"]',
            })
            self._raise_for_status(response, "getUpdates"); return response
        try:
            response = self.policy.run(request, lambda attempt: self.logger.event("DEBUG", "telegram", "poll_attempt", call_id=call_id, attempt=attempt),
                                       lambda attempt, exc: self.logger.event("WARNING", "telegram", "poll_retry", call_id=call_id, attempt=attempt, error=exc))
        except Exception as exc:
            self.logger.event("ERROR", "telegram", "poll_failed", call_id=call_id, error=exc, stacktrace=traceback.format_exc(), duration_ms=round((time.perf_counter()-started)*1000, 3))
            raise
        self._raise_api_error(response, "getUpdates")
        try: parsed = TelegramUpdatesResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"Telegram getUpdates: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}") from exc
        result = [item.model_dump(by_alias=True) if isinstance(item, TelegramUpdate) else item
                  for item in parsed.result]
        self.logger.event("INFO", "telegram", "poll_completed", call_id=call_id, count=len(result), status=response.status_code, duration_ms=round((time.perf_counter()-started)*1000, 3))
        return result

    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        validate_callback_markup(reply_markup)
        call_id = str(uuid.uuid4())
        self.logger.event("INFO", "telegram", "send_started", call_id=call_id)
        parts = split_message(text)
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_markup is not None and index == len(parts) - 1:
                payload["reply_markup"] = reply_markup
            def request() -> httpx.Response:
                response = self.client.post("/sendMessage", json=payload); self._raise_for_status(response, "sendMessage"); return response
            response = uncertain_write(request)
            self._validate_write(response, "sendMessage")
        self.logger.event("INFO", "telegram", "send_completed", call_id=call_id, parts=len(parts))

    def send_document(self, chat_id: int, filename: str, content: bytes,
                      caption: str | None = None) -> None:
        """Send a generated file without ever placing its contents in a log."""
        if not filename or any(character in filename for character in ("/", "\\", "\x00")):
            raise ValueError("Telegram-Dateiname ist ungültig")
        call_id = str(uuid.uuid4())
        self.logger.event("INFO", "telegram", "document_send_started", call_id=call_id,
                          filename=filename, size=len(content))

        def request() -> httpx.Response:
            data: dict[str, Any] = {"chat_id": str(chat_id)}
            if caption is not None:
                data["caption"] = caption
            response = self.client.post(
                "/sendDocument", data=data,
                files={"document": (filename, content, "text/calendar; charset=utf-8")},
            )
            self._raise_for_status(response, "sendDocument")
            return response

        response = uncertain_write(request)
        self._validate_write(response, "sendDocument")
        self.logger.event("INFO", "telegram", "document_send_completed", call_id=call_id,
                          filename=filename, size=len(content))

    def answer_callback(self, callback_id: str, text: str) -> None:
        def request() -> httpx.Response:
            response = self.client.post("/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text}); self._raise_for_status(response, "answerCallbackQuery"); return response
        response = uncertain_write(request)
        self._validate_write(response, "answerCallbackQuery")

    @staticmethod
    def _validate_write(response: httpx.Response, operation: str) -> None:
        TelegramClient._raise_api_error(response, operation)
        try: TelegramWriteResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"Telegram {operation}: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}") from exc

    @staticmethod
    def _description(response: httpx.Response) -> str | None:
        """Read only Telegram's documented human-readable error field."""
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        description = payload.get("description")
        return description if isinstance(description, str) and description else None

    @staticmethod
    def _error_detail(response: httpx.Response, operation: str) -> str | None:
        """Turn Telegram's safe description into an actionable diagnostic."""
        description = TelegramClient._description(response)
        if description is None:
            return None
        if description.casefold() == "bad request: chat not found":
            return TelegramClient._CHAT_NOT_FOUND_HELP.format(operation=operation)
        return f"Telegram {operation}: {description}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = TelegramClient._error_detail(response, operation)
            if detail is not None:
                # Retry code consumes this explicit safe field instead of rendering
                # the exception URL, because that URL contains the bot token.
                exc.safe_detail = detail
                if detail == TelegramClient._CHAT_NOT_FOUND_HELP.format(operation=operation):
                    raise TelegramChatNotFoundError(
                        f"Permanente Adapterantwort: {detail}"
                    ) from exc
            raise

    @staticmethod
    def _raise_api_error(response: httpx.Response, operation: str) -> None:
        try:
            payload = response.json()
        except ValueError:
            return
        if isinstance(payload, dict) and payload.get("ok") is False:
            detail = TelegramClient._error_detail(response, operation)
            if detail is not None:
                if detail == TelegramClient._CHAT_NOT_FOUND_HELP.format(operation=operation):
                    raise TelegramChatNotFoundError(
                        f"Permanente Adapterantwort: {detail}"
                    )
                raise PermanentError(f"Permanente Adapterantwort: {detail}")

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

    def send_relevance(self, dialog: RelevanceDialog, sender: str, subject: str) -> None:
        buttons = [[
            {"text": "Relevant", "callback_data": RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision="relevant").encode()},
            {"text": "Irrelevant", "callback_data": RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision="irrelevant").encode()},
        ]]
        text = "\n".join([
            f"Absender: {sender}",
            f"Betreff: {subject}",
            "Relevanz bitte bestätigen:",
        ])
        validate_callback_markup({"inline_keyboard": buttons})
        self.telegram.send(self.chat_id, text, {"inline_keyboard": buttons})

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
        # The current proposal is the recovery record: publish it before the
        # denormalized mail state.  If the process stops between these two
        # atomic file replacements, startup can copy this record into the mail
        # state without losing the newer status or external result.
        self.store.save(self._proposal_name(proposal.source_mail_id, proposal.id), value)
        mail_name = f"mail-{proposal.source_mail_id}"
        state = self.store.load_model(mail_name, MailState) if hasattr(self.store, "load_model") else None
        if isinstance(state, MailState):
            proposals = [proposal if item.id == proposal.id else item
                         for item in state.proposals]
            changed = proposals != state.proposals
            state.proposals = proposals
            if proposal.status in {ProposalStatus.WRITING, ProposalStatus.CREATED,
                                   ProposalStatus.FAILED, ProposalStatus.UNCERTAIN}:
                service = "todoist" if proposal.kind.value == "task" else "google_calendar"
                reference = WriteAttemptReference(
                    mail_id=proposal.source_mail_id,
                    proposal_id=proposal.id, proposal_version=proposal.version, service=service,
                    idempotency_key=f"mailhelp:{proposal.source_mail_id}:{proposal.id}:v{proposal.version}",
                )
                attempts = [item for item in state.write_attempts
                            if (item.proposal_id, item.proposal_version, item.service) !=
                            (reference.proposal_id, reference.proposal_version, reference.service)]
                attempts.append(reference)
                changed = changed or attempts != state.write_attempts
                state.write_attempts = attempts
            if changed:
                state.updated_at = datetime.now(timezone.utc)
                self.store.save(mail_name, state.model_dump(mode="json"))
        if proposal.status == ProposalStatus.CREATED:
            self._book_created(proposal)

    @staticmethod
    def _action_key(proposal: Proposal) -> str:
        """Identify the externally visible action independently of its source mail."""
        def encoded(value: date | datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        identity = {
            "kind": proposal.kind.value, "title": proposal.title.strip().casefold(),
            "description": proposal.description.strip().casefold(), "target": proposal.target,
            "due": encoded(proposal.due), "start": encoded(proposal.start),
            "end": encoded(proposal.end), "all_day": proposal.all_day,
            "location": (proposal.location or "").strip().casefold(),
            "video_link": str(proposal.video_link) if proposal.video_link is not None else None,
        }
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    def _book_created(self, proposal: Proposal) -> None:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        reference = (proposal.source_mail_id, proposal.id, proposal.version)
        if any((item.mail_id, item.proposal_id, item.proposal_version) == reference
               for item in ledger.entries):
            return
        ledger.entries.append(ActionLedgerEntry(
            action_key=self._action_key(proposal), mail_id=proposal.source_mail_id,
            proposal_id=proposal.id, proposal_version=proposal.version,
            kind=proposal.kind, title=proposal.title, target=proposal.target,
            external_id=proposal.external_id, external_link=proposal.external_link,
        ))
        self.store.save("action-ledger", ledger.model_dump(mode="json"))

    def _prior_actions(self, proposal: Proposal) -> list[ActionLedgerEntry]:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        current = (proposal.source_mail_id, proposal.id, proposal.version)
        key = self._action_key(proposal)
        return [item for item in ledger.entries
                if item.action_key == key
                and (item.mail_id, item.proposal_id, item.proposal_version) != current]

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError("Nachrichten dürfen nur an den konfigurierten Chat gesendet werden")
        self.telegram.send(chat_id, text)

    def send_proposal(self, proposal: Proposal) -> None:
        """Persist first, then expose controls for precisely that immutable version."""
        self.persist(proposal)
        text = format_proposal(proposal, self.configured_timezone)
        mail = self.store.load_model(f"mail-{proposal.source_mail_id}", MailState)
        sender = mail.display_headers.sender if isinstance(mail, MailState) and mail.display_headers else "—"
        subject = mail.display_headers.subject if isinstance(mail, MailState) and mail.display_headers else "—"
        parts = numbered_message_parts(sender, subject, text)
        for part in parts[:-1]:
            self.telegram.send(self.chat_id, part)
        if not proposal_is_writable(proposal):
            buttons = [[
                {"text": "Manuell prüfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode(self.store)},
                {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode(self.store)},
            ]]
        elif proposal.open_questions:
            buttons = [[
                {"text": "Klären", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode(self.store)},
                {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode(self.store)},
            ]]
        else:
            confirm = {"text": "Anlegen" if proposal.kind == ProposalKind.EVENT else "Bestätigen",
                       "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.CONFIRM).encode(self.store)}
            reject = {"text": "Verwerfen", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.REJECT).encode(self.store)}
            buttons = [[confirm, reject]] if proposal.kind == ProposalKind.EVENT else [[
                confirm,
                {"text": "Ändern", "callback_data": Decision(mail_id=proposal.source_mail_id, proposal_id=proposal.id, version=proposal.version, action=DecisionAction.EDIT).encode(self.store)},
                reject,
            ]]
        markup = {"inline_keyboard": buttons}
        validate_callback_markup(markup)
        self.telegram.send(self.chat_id, parts[-1], markup)

    def poll_once(self) -> None:
        self._resume_writes()
        offset_state = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset())
        assert isinstance(offset_state, TelegramOffset)
        offset = max(offset_state.offset, self._durable_dialog_offset())
        updates = self.telegram.poll(offset)
        self.logger.event("DEBUG", "telegram.dialog", "updates_received",
                          offset=offset, count=len(updates))
        for raw in updates:
            raw_id = raw.get("update_id") if isinstance(raw, dict) else None
            if not isinstance(raw_id, int) or isinstance(raw_id, bool) or raw_id < offset:
                self.logger.event("WARNING", "telegram.dialog", "invalid_update",
                                  update_id=raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None,
                                  reason="missing_or_stale_update_id")
                if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id < offset:
                    self._reject_duplicate_relevance(raw)
                continue
            try:
                update = TelegramUpdate.model_validate(raw)
                update_kind = "callback_query" if update.callback_query is not None else "message"
                self.logger.event("INFO", "telegram.dialog", "update_processing",
                                  update_id=raw_id, update_kind=update_kind)
                self._handle(update)
            except ValidationError as exc:
                self.logger.event("WARNING", "telegram.dialog", "invalid_update",
                                  update_id=raw_id, reason="schema_validation",
                                  validation_path=_validation_path(exc))
                self.telegram.send(self.chat_id, "Telegram-Eingabe ist syntaktisch ungültig und wurde verworfen.")
            except Exception as exc:
                # Do not acknowledge an update that failed operationally.  It
                # remains queued and can be retried after a transient provider,
                # network, or persistence problem has recovered.
                self.logger.event("ERROR", "telegram.dialog", "update_processing_failed",
                                  update_id=raw_id, error=exc,
                                  stacktrace=traceback.format_exc())
                raise
            offset = raw_id + 1
            self.store.save("telegram-offset", TelegramOffset(offset=offset).model_dump())
            self.logger.event("INFO", "telegram.dialog", "update_processed",
                              update_id=raw_id, next_offset=offset)

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
                self.logger.event("WARNING", "telegram.dialog", "unauthorized_update",
                                  update_id=update.update_id, update_kind="callback_query",
                                  user_id=callback.sender.id, chat_id=callback.message.chat.id)
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
                decision = Decision.parse(callback.data, self.store)
            except (ValueError, ValidationError):
                self.telegram.answer_callback(callback.id, "Aktion ist syntaktisch ungültig.")
                return
            self._decide(callback.id, decision)
            return
        message = update.message
        assert message is not None
        if not self._authorized(message.sender.id, message.chat.id):
            self.logger.event("WARNING", "telegram.dialog", "unauthorized_update",
                              update_id=update.update_id, update_kind="message",
                              user_id=message.sender.id, chat_id=message.chat.id)
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
        if decision.action in {DecisionAction.CONFIRM, DecisionAction.CONFIRM_DUPLICATE} and proposal.status != ProposalStatus.PENDING_CONFIRMATION:
            self.telegram.answer_callback(callback_id, "Zuerst müssen die offenen Fragen beantwortet werden.")
            return
        duplicates = self._prior_actions(proposal) if decision.action in {
            DecisionAction.CONFIRM, DecisionAction.CONFIRM_DUPLICATE} else []
        if decision.action == DecisionAction.CONFIRM and duplicates:
            previous = duplicates[-1]
            self.telegram.answer_callback(callback_id, "Diese Aktion wurde bereits angelegt; erneute Freigabe erforderlich.")
            duplicate_decision = decision.model_copy(update={"action": DecisionAction.CONFIRM_DUPLICATE})
            self.telegram.send(self.chat_id, "\n".join([
                f"Bereits angelegt: {'Aufgabe' if previous.kind == ProposalKind.TASK else 'Termin'} „{previous.title}“.",
                f"Frühere Quelle: Mail {previous.mail_id}, Vorschlag {previous.proposal_id}, Version {previous.proposal_version}.",
                "Soll die Aktion wirklich ein zweites Mal angelegt bzw. versendet werden?",
            ]), {"inline_keyboard": [[
                {"text": "Erneut anlegen", "callback_data": duplicate_decision.encode(self.store)},
                {"text": "Nicht erneut", "callback_data": decision.model_copy(update={"action": DecisionAction.REJECT}).encode(self.store)},
            ]]})
            return
        if decision.action == DecisionAction.CONFIRM_DUPLICATE and not duplicates:
            self.telegram.answer_callback(callback_id, "Die Doppelanlage-Bestätigung ist veraltet; es wurde nichts angelegt.")
            return
        changed = (proposal.model_copy(update={"status": ProposalStatus.REJECTED})
                   if decision.action == DecisionAction.REJECT else
                   apply_decision(proposal, decision.model_copy(update={"action": DecisionAction.CONFIRM}),
                                  self.user_id, self.chat_id, self.user_id, self.chat_id))
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
            # Also repairs a crash after the authoritative proposal file was
            # replaced but before its embedding MailState was replaced.
            self.persist(proposal)
            if proposal.status in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING,
                                   ProposalStatus.UNCERTAIN, ProposalStatus.SIMULATED}:
                self._execute(proposal)

    def _answer(self, answer: str) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.logger.event("INFO", "telegram.dialog", "answer_rejected",
                              reason="no_open_dialog")
            self.telegram.send(self.chat_id, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen.")
            return
        assert dialog.mail_id is not None
        proposal = self.store.load_model(self._proposal_name(dialog.mail_id, dialog.proposal_id), Proposal)
        if proposal is None:
            self.logger.event("WARNING", "telegram.dialog", "answer_rejected",
                              reason="proposal_missing", mail_id=dialog.mail_id,
                              proposal_id=dialog.proposal_id, version=dialog.version)
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(self.chat_id, "Der zugehörige Vorschlag wurde nicht gefunden.")
            return
        assert isinstance(proposal, Proposal)
        if proposal.version != dialog.version or proposal.status != ProposalStatus.NEEDS_CLARIFICATION:
            self.logger.event("WARNING", "telegram.dialog", "answer_rejected",
                              reason="stale_dialog", mail_id=dialog.mail_id,
                              proposal_id=dialog.proposal_id, dialog_version=dialog.version,
                              proposal_version=proposal.version, proposal_status=proposal.status.value)
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            self.telegram.send(self.chat_id, "Die Rückfrage ist veraltet; es wurde nichts geändert.")
            return
        question = proposal.open_questions[0] if proposal.open_questions else "Welche Änderung soll übernommen werden?"
        if self.revision_service is None:
            self.logger.event("ERROR", "telegram.dialog", "answer_revision_unavailable",
                              mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                              version=dialog.version)
            self.telegram.send(self.chat_id, "Die Überarbeitung ist derzeit nicht verfügbar; der Vorschlag blieb unverändert.")
            return
        try:
            _, candidate = self.revision_service.revise_proposal(proposal, question, answer)
            revised = validate_revision_successor(proposal, candidate)
        except (ValueError, ValidationError) as exc:
            self.logger.event("WARNING", "telegram.dialog", "answer_revision_rejected",
                              mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                              version=dialog.version, error=exc)
            self.telegram.send(self.chat_id, "Die Antwort konnte nicht widerspruchsfrei übernommen werden; der Vorschlag und die Rückfrage blieben unverändert.")
            return
        # send_proposal persists the immutable version before exposing it.
        self.send_proposal(revised)
        self.store.save("telegram-dialog", TelegramDialogState().model_dump())
        self.logger.event("INFO", "telegram.dialog", "answer_revision_completed",
                          mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                          previous_version=dialog.version, new_version=revised.version)


def _validation_path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(part) for part in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
