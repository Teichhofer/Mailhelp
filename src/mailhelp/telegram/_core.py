"""Strict Telegram trust boundary and restart-safe proposal dialogs."""
from __future__ import annotations

from datetime import date, date as calendar_date, datetime, time as clock_time, timedelta, timezone
from enum import StrEnum
import hashlib
import json
import secrets
import re
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ..models import (ActionLedger, ActionLedgerEntry, AnswerStatus, MailState, Proposal, ProposalClarificationState, ProposalKind, ProposalNotification, ProposalRevisionDelta, ProposalRevisionStatus, ProposalStatus, QuestionStatus, RelevanceDialog, TemporalFact,
                     RelevanceDialogStatus, TelegramDialogState, TelegramOffset, TelegramAnswerInterpretation, TelegramClarification,
                     WriteAttemptReference)
from ..integrations import ExternalWriter, execute_confirmed, proposal_is_writable
from ..adapter import PermanentError, RetryableError, RetryPolicy, uncertain_write
from ..storage import JsonStore, mail_state_names
from ..logging import EventLogger, NullLogger
from ..analysis import (ContradictoryRevision, IncompleteUserAnswer, LlmInvalidJson,
                       LlmProviderResponseInvalid, LlmSchemaValidationFailed,
                       LlmTokenLimitExceeded, TechnicalRevisionError,
                       validate_revision_successor)
from ..models import apply_proposal_revision
import time, traceback, uuid


class DeterministicTemporalAnswer(BaseModel):
    """Facts explicitly present in one narrowly supported Telegram answer."""

    model_config = ConfigDict(extra="forbid", strict=True)
    date: calendar_date | None = None
    start: clock_time | None = None
    end: clock_time | None = None


_DATE = r"(?:(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))"
_TIME = r"(?P<{name}_hour>\d{{1,2}})(?::(?P<{name}_minute>\d{{2}}))?\s*(?:Uhr)?"
_TEMPORAL_ANSWERS = (
    re.compile(rf"\s*{_DATE}\s*(?:(?:T|,|um)?\s*{_TIME.format(name='start')}(?:\s*(?:bis|[-–])\s*{_TIME.format(name='end')})?)?\s*", re.IGNORECASE),
    re.compile(rf"\s*{_TIME.format(name='start')}\s*(?:bis|[-–])\s*{_TIME.format(name='end')}\s*", re.IGNORECASE),
    re.compile(rf"\s*{_TIME.format(name='start')}\s*", re.IGNORECASE),
)


def parse_deterministic_temporal_answer(answer: str) -> DeterministicTemporalAnswer | None:
    """Parse only numeric, context-free date/time forms; never infer a fact."""
    match = next((pattern.fullmatch(answer) for pattern in _TEMPORAL_ANSWERS
                  if pattern.fullmatch(answer) is not None), None)
    if match is None:
        return None
    values = match.groupdict()
    parsed_date = None
    if values.get("year"):
        parsed_date = date(int(values["year"]), int(values["month"]), int(values["day"]))
    elif values.get("iso_year"):
        parsed_date = date(int(values["iso_year"]), int(values["iso_month"]), int(values["iso_day"]))
    def parsed_time(name: str) -> clock_time | None:
        hour = values.get(f"{name}_hour")
        return (clock_time(int(hour), int(values.get(f"{name}_minute") or 0))
                if hour is not None else None)
    return DeterministicTemporalAnswer(
        date=parsed_date, start=parsed_time("start"), end=parsed_time("end"))


def deterministic_temporal_revision(proposal: Proposal, question: str,
                                    normalized_answer: str,
                                    configured_timezone: str) -> Proposal | None:
    """Build an unambiguous clock-time revision without another LLM call."""
    if proposal.kind != ProposalKind.EVENT or not any(
            word in question.casefold() for word in ("datum", "beginn", "ende", "uhrzeit", "wann")):
        return None
    parsed = parse_deterministic_temporal_answer(normalized_answer)
    if parsed is None:
        return None
    expected = (proposal.known_temporal_facts.date
                if proposal.known_temporal_facts is not None
                else proposal.temporal_fact.normalized_date
                if proposal.temporal_fact is not None else None)
    allowed_dates = {expected}
    if "ende" in question.casefold() and expected is not None:
        allowed_dates.add(expected + timedelta(days=1))
    if parsed.date is not None and expected is not None and parsed.date not in allowed_dates:
        raise ContradictoryRevision("Die Antwort widerspricht dem validierten Termindatum")
    day = parsed.date or expected
    question_lower = question.casefold()
    wants_end = "ende" in question_lower
    wants_start = "beginn" in question_lower or "uhrzeit" in question_lower or "wann" in question_lower
    # A lone clock value answers only the requested endpoint. A range explicitly
    # proves both endpoints, irrespective of which temporal question was open.
    start_time = parsed.start if parsed.end is not None or wants_start and not wants_end else None
    end_time = parsed.end if parsed.end is not None else parsed.start if wants_end else None
    if day is None and (start_time is not None or end_time is not None):
        return None
    zone = ZoneInfo(configured_timezone)
    def localize(value: clock_time | None, value_day: date | None) -> datetime | None:
        if value is None or value_day is None:
            return None
        naive = datetime.combine(value_day, value)
        candidates = []
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
                if not candidates or candidate.utcoffset() != candidates[0].utcoffset():
                    candidates.append(candidate)
        if len(candidates) != 1:
            raise ContradictoryRevision("Die Ortszeit ist wegen der Zeitumstellung nicht eindeutig")
        return candidates[0]
    start = localize(start_time, day)
    end_day = parsed.date or day
    known_start = (proposal.known_temporal_facts.start
                   if proposal.known_temporal_facts is not None else proposal.start)
    reference_start = start or known_start
    end = localize(end_time, end_day)
    if (end is not None and reference_start is not None and end <= reference_start
            and parsed.end is not None):
        # ``day`` is guaranteed above whenever a clock value exists.  A range
        # whose end clock is not later therefore explicitly crosses midnight.
        end = localize(end_time, day + timedelta(days=1))
    elif end is not None and reference_start is not None and end <= reference_start:
        raise ContradictoryRevision("Das Terminende muss nach dem Beginn liegen")
    changes: dict[str, Any] = {}
    if parsed.date is not None and expected is None:
        changes["temporal_date"] = parsed.date
    if start is not None:
        changes["start"] = start
        if end is None and proposal.duration_minutes is not None:
            end = start + timedelta(minutes=proposal.duration_minutes)
    if end is not None:
        changes["end"] = end
    revised = apply_proposal_revision(proposal, ProposalRevisionDelta(
        answered_question=question, changes=changes))
    if parsed.date is not None and (proposal.temporal_fact is None or
                                    proposal.temporal_fact.normalized_date is None):
        revised = Proposal.model_validate(revised.model_copy(update={"temporal_fact": TemporalFact(
            raw_text=normalized_answer, normalized_date=parsed.date,
            year_source="telegram", status="resolved")}).model_dump())
    return revised


_EXPLICIT_CREATE_FALLBACK_ANSWERS = (
    re.compile(r"neu anlegen"),
    re.compile(r"(?:als )?neuen (?:kalender)?(?:eintrag|termin) anlegen"),
    re.compile(r"(?:ja,? )?(?:bitte )?(?:stattdessen |ersatzweise )?(?:einen )?neuen (?:kalender)?(?:eintrag|termin) (?:erstellen|anlegen)"),
)


def deterministic_classification_revision(proposal: Proposal, question: str,
                                          answer: str) -> Proposal | None:
    """Turn an explicit refusal to update an existing event into a new item.

    The intentionally closed vocabulary avoids guessing from ambiguous replies.
    It also keeps this security-relevant state transition independent of an LLM.
    """
    normalized_question = " ".join(question.casefold().split())
    if (proposal.classification.value != "change"
            or "bestehende" not in normalized_question
            or "geändert" not in normalized_question):
        return None
    normalized_answer = " ".join(answer.casefold().strip().rstrip(".!?").split())
    if not any(
            pattern.fullmatch(normalized_answer)
            for pattern in _EXPLICIT_CREATE_FALLBACK_ANSWERS):
        return None
    return apply_proposal_revision(proposal, ProposalRevisionDelta(
        answered_question=question,
        changes={"explicit_create_fallback_confirmed": True}),
        allow_create_fallback=True)


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
        display_start = (proposal.start or
                         (proposal.known_temporal_facts.start
                          if proposal.known_temporal_facts else None))
        lines.extend([
            f"Beginn: {display_start.isoformat() if display_start else missing}",
            f"Ende: {proposal.end.isoformat() if proposal.end else missing}",
            f"Dauer: {f'{proposal.duration_minutes} Minuten' if proposal.duration_minutes else missing}",
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
    _EXPIRED_CALLBACK_DESCRIPTION = (
        "bad request: query is too old and response timeout expired or query id is invalid"
    )

    def __init__(self, token: str, timeout: float, transport: httpx.BaseTransport | None = None, poll_timeout: int = 30, policy: RetryPolicy | None = None, logger: EventLogger | None = None):
        self.poll_timeout = poll_timeout
        self.client = httpx.Client(base_url=f"https://api.telegram.org/bot{token}", timeout=timeout, transport=transport)
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def _log_message(self, direction: str, **context: Any) -> None:
        """Keep third-party logger implementations backward compatible."""
        record = getattr(self.logger, "telegram_event", None)
        if record is not None:
            record(direction, **context)

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
        for item in parsed.result:
            if not isinstance(item, TelegramUpdate):
                continue
            if item.message is not None:
                self._log_message(
                    "received", update_id=item.update_id,
                    message_id=item.message.message_id,
                    user_id=item.message.sender.id, chat_id=item.message.chat.id,
                    text=item.message.text,
                )
            else:
                callback = item.callback_query
                assert callback is not None
                self._log_message(
                    "received", update_id=item.update_id,
                    message_id=callback.message.message_id,
                    user_id=callback.sender.id, chat_id=callback.message.chat.id,
                    callback_data=callback.data,
                )
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
            self._log_message(
                "sent", chat_id=chat_id, text=part,
                reply_markup=payload.get("reply_markup"),
            )
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
        self._log_message(
            "sent", chat_id=chat_id, message_type="document",
            filename=filename, caption=caption,
        )
        self.logger.event("INFO", "telegram", "document_send_completed", call_id=call_id,
                          filename=filename, size=len(content))

    def answer_callback(self, callback_id: str, text: str) -> None:
        def request() -> httpx.Response:
            response = self.client.post("/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})
            if not self._is_expired_callback(response):
                self._raise_for_status(response, "answerCallbackQuery")
            return response
        response = uncertain_write(request)
        if self._is_expired_callback(response):
            # Telegram callback acknowledgements have a short lifetime.  The
            # update itself is still final and must be checkpointed; otherwise
            # this obsolete query is returned forever and blocks newer input.
            self.logger.event("WARNING", "telegram", "callback_acknowledgement_expired")
            return
        self._validate_write(response, "answerCallbackQuery")
        self._log_message(
            "sent", message_type="callback_answer",
            callback_id=callback_id, text=text,
        )

    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None:
        """Remove every inline button from an already-sent message."""
        payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}}

        def request() -> httpx.Response:
            response = self.client.post("/editMessageReplyMarkup", json=payload)
            self._raise_for_status(response, "editMessageReplyMarkup")
            return response

        response = uncertain_write(request)
        self._validate_write(response, "editMessageReplyMarkup")

    @staticmethod
    def _is_expired_callback(response: httpx.Response) -> bool:
        description = TelegramClient._description(response)
        return (response.status_code == 400 and description is not None
                and description.casefold() == TelegramClient._EXPIRED_CALLBACK_DESCRIPTION)

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
    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]: ...
    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...
    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None: ...

class ProposalRevisionService(Protocol):
    def interpret_telegram_answer(self, proposal: Proposal, question: str, authorized_answer: str) -> tuple[str, TelegramAnswerInterpretation]: ...
    def clarify_telegram_answer(self, question: str, authorized_answer: str, reason: str) -> tuple[str, TelegramClarification]: ...
    def revise_proposal(self, proposal: Proposal, question: str, authorized_answer: str) -> tuple[str, Proposal]: ...


class EventLogger(Protocol):
    def event(self, level: str, module: str, event: str, **fields: Any) -> None: ...


class ProposalPersistence(Protocol):
    """Narrow state boundary used by dialog components."""

    def persist(self, proposal: Proposal) -> None: ...
    def send_proposal(self, proposal: Proposal) -> None: ...


class UpdateValidation(Protocol):
    def authorized(self, user_id: int, chat_id: int) -> bool: ...
    def decision(self, value: str) -> Decision: ...
    def relevance_decision(self, value: str) -> RelevanceDecision: ...


class RelevanceHandler(Protocol):
    def resolve_relevance(self, mail_id: str, version: int, decision: str, offset: int) -> MailState: ...
    def resume_mail(self, state: MailState) -> None: ...


class RelevanceDialogs(Protocol):
    def open(self) -> list[RelevanceDialog]: ...
    def durable_offset(self) -> int: ...
    def decide(self, decision: RelevanceDecision, offset: int, notify: bool) -> str | None: ...


class WriteExecution(Protocol):
    def execute(self, proposal: Proposal) -> None: ...
    def resume(self) -> None: ...


class ProposalRevisions(Protocol):
    def answer(self, answer: str) -> None: ...
    def resume(self) -> None: ...


class ActionLedgerPort(Protocol):
    def book_created(self, proposal: Proposal) -> None: ...
    def prior_actions(self, proposal: Proposal) -> list[ActionLedgerEntry]: ...


class AuthorizedUpdateValidator:
    """Validate Telegram identities and decode untrusted callback payloads."""

    def __init__(self, store: JsonStore, user_id: int, chat_id: int):
        self.store, self.user_id, self.chat_id = store, user_id, chat_id

    def authorized(self, user_id: int, chat_id: int) -> bool:
        return (user_id, chat_id) == (self.user_id, self.chat_id)

    def decision(self, value: str) -> Decision:
        return Decision.parse(value, self.store)

    @staticmethod
    def relevance_decision(value: str) -> RelevanceDecision:
        return RelevanceDecision.parse(value)


class RelevanceDialogProcessor:
    """Own relevance lookup, replay offsets, and relevance resolution."""

    def __init__(self, store: JsonStore, telegram: TelegramTransport, chat_id: int):
        self.store, self.telegram, self.chat_id = store, telegram, chat_id
        self.handler: RelevanceHandler | None = None

    def all(self) -> list[RelevanceDialog]:
        result = []
        for name in mail_state_names(self.store) if hasattr(self.store, "names") else []:
            state = self.store.load_model(name, MailState)
            if isinstance(state, MailState) and state.relevance_dialog is not None:
                result.append(state.relevance_dialog)
        return result

    def open(self) -> list[RelevanceDialog]:
        return [item for item in self.all() if item.status == RelevanceDialogStatus.OPEN]

    def durable_offset(self) -> int:
        return max((item.telegram_offset or 0 for item in self.all()), default=0)

    def decide(self, decision: RelevanceDecision, offset: int, notify: bool = False) -> str | None:
        try:
            if self.handler is None:
                raise ValueError("Relevanzverarbeitung ist nicht verfügbar")
            state = self.handler.resolve_relevance(
                decision.mail_id, decision.version, decision.decision, offset)
        except ValueError as exc:
            if notify:
                self.telegram.send(self.chat_id, str(exc))
                return None
            raise
        if decision.decision == "relevant":
            self.handler.resume_mail(state)
        text = f"✅ E-Mail wurde als {decision.decision} eingestuft."
        if notify:
            self.telegram.send(self.chat_id, text)
            return None
        return text


class ActionLedgerService:
    """Record externally created actions and detect semantic duplicates."""

    def __init__(self, store: JsonStore):
        self.store = store

    @staticmethod
    def action_key(proposal: Proposal) -> str:
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

    def book_created(self, proposal: Proposal) -> None:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        reference = (proposal.source_mail_id, proposal.id, proposal.version)
        if any((item.mail_id, item.proposal_id, item.proposal_version) == reference
               for item in ledger.entries):
            return
        ledger.entries.append(ActionLedgerEntry(
            action_key=self.action_key(proposal), mail_id=proposal.source_mail_id,
            proposal_id=proposal.id, proposal_version=proposal.version,
            kind=proposal.kind, title=proposal.title, target=proposal.target,
            external_id=proposal.external_id, external_link=proposal.external_link,
        ))
        self.store.save("action-ledger", ledger.model_dump(mode="json"))

    def prior_actions(self, proposal: Proposal) -> list[ActionLedgerEntry]:
        ledger = self.store.load_model("action-ledger", ActionLedger, ActionLedger())
        assert isinstance(ledger, ActionLedger)
        current = (proposal.source_mail_id, proposal.id, proposal.version)
        key = self.action_key(proposal)
        return [item for item in ledger.entries if item.action_key == key and
                (item.mail_id, item.proposal_id, item.proposal_version) != current]


def proposal_name(mail_id: str, proposal_id: str) -> str:
    return f"proposal-{mail_id}-{proposal_id}"


def proposal_version_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"proposal-{mail_id}-{proposal_id}-v{version}"


def clarification_name(mail_id: str, proposal_id: str, version: int) -> str:
    return f"clarification-{mail_id}-{proposal_id}-v{version}"


class ConfirmedWriteExecutor:
    """Execute and recover writes using only explicit infrastructure ports."""

    def __init__(self, store: JsonStore, writers: dict[str, ExternalWriter], persistence: ProposalPersistence, telegram: TelegramTransport, chat_id: int, test_mode: bool, ledger: ActionLedgerPort):
        self.store, self.writers, self.persistence = store, writers, persistence
        self.telegram, self.chat_id, self.test_mode, self.ledger = telegram, chat_id, test_mode, ledger

    def writer_for(self, proposal: Proposal) -> ExternalWriter | None:
        return self.writers.get("todoist" if proposal.kind == ProposalKind.TASK else "google_calendar")

    def execute(self, proposal: Proposal) -> None:
        if not proposal_is_writable(proposal):
            return
        if proposal.status == ProposalStatus.SIMULATED and proposal.simulation_notified:
            return
        writer = self.writer_for(proposal)
        if writer is None:
            return
        changed, result = execute_confirmed(proposal, writer, self.persistence.persist, self.test_mode)
        if result.get("simulation"):
            kind = "Aufgabe" if proposal.kind == ProposalKind.TASK else "Kalendertermin"
            text = (f"Testmodus: {kind} „{proposal.title}“ wurde bestätigt, "
                    "aber extern nicht angelegt (nur simuliert).")
        elif result.get("operation") == "duplicate_updated":
            text = (f"Bereits vorhandener gleicher Termin „{proposal.title}“ wurde erkannt; "
                    "fehlende Informationen wurden ergänzt. Kein neuer Termin wurde angelegt.")
        elif result.get("operation") == "duplicate_skipped":
            text = (f"Bereits vorhandener gleicher Termin „{proposal.title}“ wurde erkannt. "
                    "Kein neuer Termin wurde angelegt.")
        elif changed.status == ProposalStatus.CREATED:
            details = f" (ID: {changed.external_id})" if changed.external_id else ""
            link = f" {changed.external_link}" if changed.external_link else ""
            kind = "Aufgabe" if proposal.kind == ProposalKind.TASK else "Kalendertermin"
            text = f"Erstellt: {kind} extern angelegt „{proposal.title}“{details}.{link}"
        elif changed.status == ProposalStatus.UNCERTAIN:
            if changed.uncertain_notified:
                return
            text = f"Unklarer Schreiberfolg bei „{proposal.title}“; wird weiter abgeglichen und nicht automatisch wiederholt."
        else:
            text = f"Erstellen von „{proposal.title}“ fehlgeschlagen."
        self.telegram.send(self.chat_id, text)
        if changed.status == ProposalStatus.UNCERTAIN:
            self.persistence.persist(changed.model_copy(update={"uncertain_notified": True}))
        elif changed.status == ProposalStatus.SIMULATED:
            self.persistence.persist(changed.model_copy(update={"simulation_notified": True}))

    def resume(self) -> None:
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
            self.persistence.persist(proposal)
            if proposal.status in {ProposalStatus.CONFIRMED, ProposalStatus.WRITING,
                                   ProposalStatus.UNCERTAIN, ProposalStatus.SIMULATED}:
                self.execute(proposal)



class ProposalRevisionProcessor:
    """Own authorized answers, revision retries, and restart recovery."""

    def __init__(self, store: JsonStore, revision_service: ProposalRevisionService | None, persistence: ProposalPersistence, telegram: TelegramTransport, chat_id: int, logger: EventLogger, configured_timezone: str, *, interpretation_attempts: int, interpretation_backoff_seconds: int, revision_attempts: int, revision_backoff_seconds: int):
        self.store, self.revision_service = store, revision_service
        self.persistence, self.telegram, self.chat_id = persistence, telegram, chat_id
        self.logger, self.configured_timezone = logger, configured_timezone
        self.interpretation_attempts = interpretation_attempts
        self.interpretation_backoff_seconds = interpretation_backoff_seconds
        self.revision_attempts = revision_attempts
        self.revision_backoff_seconds = revision_backoff_seconds

    def resume(self) -> None:
        self._resume_durable_revisions()
        self._resume_legacy_revision()

    def answer(self, answer: str) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.logger.event("INFO", "telegram.dialog", "answer_rejected",
                              reason="no_open_dialog")
            self.telegram.send(self.chat_id, "Keine offene Rückfrage. Bitte zuerst „Ändern“ wählen.")
            return
        assert dialog.mail_id is not None
        proposal = self.store.load_model(proposal_name(dialog.mail_id, dialog.proposal_id), Proposal)
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
        clarification_record_name = clarification_name(dialog.mail_id, dialog.proposal_id, dialog.version)
        existing = self.store.load_model(clarification_record_name, ProposalClarificationState)
        if isinstance(existing, ProposalClarificationState):
            if existing.question_status == QuestionStatus.ANSWERED:
                self.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
                self.telegram.send(self.chat_id, "Keine offene Rückfrage. Die vorherige Antwort ist bereits gespeichert.")
                return
            if (existing.authorized_answer is not None and
                    existing.answer_status == AnswerStatus.PENDING):
                self.telegram.send(self.chat_id, "Die autorisierte Antwort ist bereits sicher gespeichert und wird verarbeitet.")
                return
        if self.revision_service is None:
            self.logger.event("ERROR", "telegram.dialog", "answer_revision_unavailable",
                              mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                              version=dialog.version)
            self.telegram.send(self.chat_id, "Die Überarbeitung ist derzeit nicht verfügbar; der Vorschlag blieb unverändert.")
            return
        # This is the acknowledgement boundary: persist the authorized input
        # atomically before the first fallible interpretation call.  The raw
        # answer exists only in this state file and is never added to logs.
        pending = ProposalClarificationState(
            mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
            version=dialog.version, question=question, authorized_answer=answer)
        self.store.save(clarification_record_name, pending.model_dump(mode="json"))
        self._interpret_pending(pending)

    def _interpret_pending(self, state: ProposalClarificationState) -> None:
        """Interpret one durably stored authorized answer without logging it."""
        assert state.authorized_answer is not None
        name = clarification_name(state.mail_id, state.proposal_id, state.version)
        proposal = self.store.load_model(proposal_name(state.mail_id, state.proposal_id), Proposal)
        if not isinstance(proposal, Proposal) or proposal.version != state.version:
            return
        assert self.revision_service is not None
        local_temporal = (proposal.kind == ProposalKind.EVENT and
                          parse_deterministic_temporal_answer(
                              state.authorized_answer) is not None)
        try:
            deterministic = deterministic_classification_revision(
                proposal, state.question, state.authorized_answer)
            if deterministic is None:
                deterministic = deterministic_temporal_revision(
                    proposal, state.question, state.authorized_answer,
                    self.configured_timezone)
            if deterministic is not None:
                answered = ProposalClarificationState(
                    mail_id=state.mail_id, proposal_id=state.proposal_id,
                    version=state.version, question=state.question,
                    authorized_answer=state.authorized_answer,
                    interpretation_status=ProposalRevisionStatus.COMPLETED,
                    interpretation_attempts=state.interpretation_attempts,
                    question_status=QuestionStatus.ANSWERED,
                    answer_status=AnswerStatus.VALID,
                    normalized_answer=state.authorized_answer,
                    proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED,
                )
                self.store.save(name, answered.model_dump(mode="json"))
                self.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
                self._revise_answered(answered)
                return
            _, interpretation = self.revision_service.interpret_telegram_answer(
                proposal, state.question, state.authorized_answer)
            if not interpretation.usable:
                incomplete = IncompleteUserAnswer(interpretation.reason)
                invalid = state.model_copy(update={
                    "answer_status": AnswerStatus.INVALID,
                    "interpretation_status": ProposalRevisionStatus.COMPLETED,
                    "next_interpretation_at": None,
                })
                self.store.save(name, invalid.model_dump(mode="json"))
                _, clarification = self.revision_service.clarify_telegram_answer(
                    state.question, state.authorized_answer, interpretation.reason)
                self.logger.event("INFO", "telegram.dialog", "answer_clarification_requested",
                                  mail_id=state.mail_id, proposal_id=state.proposal_id,
                                  version=state.version,
                                  error_class=type(incomplete).__name__,
                                  proposal_reference=f"{state.mail_id}:{state.proposal_id}:v{state.version}",
                                  revision_status=ProposalRevisionStatus.PENDING.value)
                self.telegram.send(self.chat_id, clarification.message)
                return
        except (LlmProviderResponseInvalid, LlmInvalidJson,
                LlmSchemaValidationFailed, RetryableError,
                TechnicalRevisionError, ValidationError, httpx.TransportError) as exc:
            self._defer_interpretation(name, state, exc)
            return
        except ContradictoryRevision as exc:
            if not local_temporal:
                self._defer_interpretation(name, state, exc, contradictory=True)
                return
            paused = state.model_copy(update={
                "interpretation_status": ProposalRevisionStatus.PAUSED,
                "interpretation_attempts": state.interpretation_attempts + 1,
                "next_interpretation_at": None,
            })
            self.store.save(name, paused.model_dump(mode="json"))
            self._log_revision_failure(state.mail_id, state.proposal_id,
                                       state.version, exc,
                                       ProposalRevisionStatus.PAUSED)
            expected = (proposal.known_temporal_facts.date
                        if proposal.known_temporal_facts is not None
                        else proposal.temporal_fact.normalized_date
                        if proposal.temporal_fact is not None else None)
            suffix = f" Erwartet wird {expected.isoformat()}." if expected else ""
            self.telegram.send(
                self.chat_id,
                "Das genannte Datum widerspricht dem bereits validierten Termindatum."
                + suffix + " Bitte bestätige das richtige Datum konkret.")
            return
        # The validated value is the recovery record.  It must reach disk before
        # removing the active user question or making another fallible LLM call.
        answered = ProposalClarificationState(
            mail_id=state.mail_id, proposal_id=state.proposal_id,
            version=state.version, question=state.question,
            authorized_answer=state.authorized_answer,
            interpretation_status=ProposalRevisionStatus.COMPLETED,
            interpretation_attempts=state.interpretation_attempts,
            question_status=QuestionStatus.ANSWERED, answer_status=AnswerStatus.VALID,
            normalized_answer=interpretation.normalized_answer,
            proposal_revision_status=ProposalRevisionStatus.RETRY_REQUIRED,
        )
        self.store.save(name, answered.model_dump(mode="json"))
        self.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
        self._revise_answered(answered)

    def _defer_interpretation(self, name: str, state: ProposalClarificationState,
                              exc: Exception, *, contradictory: bool = False) -> None:
        attempts = state.interpretation_attempts + 1
        exhausted = attempts >= self.interpretation_attempts
        status = (ProposalRevisionStatus.PAUSED if exhausted else
                  ProposalRevisionStatus.RETRY_REQUIRED)
        updated = state.model_copy(update={
            "interpretation_status": status,
            "interpretation_attempts": attempts,
            "next_interpretation_at": (None if exhausted else datetime.now(timezone.utc) +
                                       timedelta(seconds=self.interpretation_backoff_seconds)),
        })
        self.store.save(name, updated.model_dump(mode="json"))
        self._log_revision_failure(state.mail_id, state.proposal_id, state.version, exc, status)
        if exhausted:
            message = "Die Interpretation wurde nach mehreren Versuchen pausiert. Die gespeicherte Antwort bleibt erhalten."
        elif contradictory:
            message = "Die Antwort widerspricht möglicherweise dem bestehenden Vorschlag und wird erneut geprüft."
        else:
            message = (("Technischer Abbruch: Das Modell hat sein Ausgabetokenlimit erreicht. "
                        "Die sicher gespeicherte Antwort wird mit der Ausweichstrategie erneut bewertet.")
                       if isinstance(exc, LlmTokenLimitExceeded) else
                       "Die interne Verarbeitung ist verzögert. Die sicher gespeicherte Antwort wird erneut bewertet.")
        self.telegram.send(self.chat_id, message)

    def _revise_answered(self, state: ProposalClarificationState) -> None:
        """Retry a revision solely from its already validated durable answer."""
        name = clarification_name(state.mail_id, state.proposal_id, state.version)
        current = self.store.load_model(proposal_name(state.mail_id, state.proposal_id), Proposal)
        if isinstance(current, Proposal) and current.version > state.version:
            mail = self.store.load_model(f"mail-{state.mail_id}", MailState)
            notification = (next((item for item in mail.proposal_notifications
                                  if (item.proposal_id, item.proposal_version) ==
                                  (current.id, current.version)), None)
                            if isinstance(mail, MailState) else None)
            if notification is None or notification.status == "pending":
                self.persistence.send_proposal(current)
            elif notification.status != "completed":
                return
            self.store.save(name, state.model_copy(update={
                "proposal_revision_status": ProposalRevisionStatus.COMPLETED,
            }).model_dump(mode="json"))
            return
        original = self.store.load_model(proposal_version_name(state.mail_id, state.proposal_id, state.version), Proposal)
        if not isinstance(original, Proposal) or self.revision_service is None:
            return
        try:
            candidate = deterministic_classification_revision(
                original, state.question, state.normalized_answer)
            if candidate is None:
                candidate = deterministic_temporal_revision(
                    original, state.question, state.normalized_answer,
                    self.configured_timezone)
            deterministic = candidate is not None
            if candidate is None:
                _, candidate = self.revision_service.revise_proposal(
                    original, state.question, state.normalized_answer)
            revised = validate_revision_successor(original, candidate)
        except Exception as exc:
            classified = (exc if isinstance(exc, (
                ContradictoryRevision, TechnicalRevisionError, RetryableError,
                ValidationError, httpx.TransportError))
                          else TechnicalRevisionError(type(exc).__name__))
            attempts = state.revision_attempts + 1
            exhausted = attempts >= self.revision_attempts
            status = (ProposalRevisionStatus.PAUSED if exhausted
                      else ProposalRevisionStatus.RETRY_REQUIRED)
            self._log_revision_failure(state.mail_id, state.proposal_id,
                                       state.version, classified, status)
            # The question and validated answer deliberately remain untouched.
            updated = state.model_copy(update={
                "proposal_revision_status": status,
                "revision_attempts": attempts,
                "next_revision_at": (None if exhausted else datetime.now(timezone.utc) +
                                     timedelta(seconds=self.revision_backoff_seconds)),
            })
            self.store.save(name, updated.model_dump(mode="json"))
            self.telegram.send(self.chat_id, (
                "Die Überarbeitung der gespeicherten Antwort wurde nach mehreren Versuchen pausiert. Die Antwort bleibt erhalten."
                if exhausted else
                "Die interne Verarbeitung der gespeicherten Antwort ist verzögert."))
            return
        if deterministic:
            self.logger.event("INFO", "analysis", "proposal_revision_delta_applied",
                              proposal_id=original.id,
                              previous_version=original.version,
                              new_version=revised.version)
        self.persistence.send_proposal(revised)
        self.store.save(name, state.model_copy(update={
            "proposal_revision_status": ProposalRevisionStatus.COMPLETED,
            "next_revision_at": None,
        }).model_dump(mode="json"))
        self.logger.event("INFO", "telegram.dialog", "answer_revision_completed",
                          mail_id=state.mail_id, proposal_id=state.proposal_id,
                          previous_version=state.version, new_version=revised.version)

    def _log_revision_failure(self, mail_id: str, proposal_id: str, version: int,
                              exc: Exception,
                              status: ProposalRevisionStatus) -> None:
        """Log a revision failure without untrusted answer or question content."""
        fields: dict[str, Any] = {}
        if isinstance(exc, ValidationError):
            fields["validation_errors"] = [
                {"location": [str(part) for part in error["loc"]],
                 "type": error["type"], "message": error["msg"]}
                for error in exc.errors(include_url=False, include_context=False,
                                        include_input=False)
            ]
        self.logger.event(
            "WARNING", "telegram.dialog", "answer_revision_failed",
            mail_id=mail_id, proposal_id=proposal_id, version=version,
            error_class=type(exc).__name__,
            proposal_reference=f"{mail_id}:{proposal_id}:v{version}",
            revision_status=status.value,
            **fields,
        )

    def _resume_durable_revisions(self) -> None:
        if self.revision_service is None or not hasattr(self.store, "names"):
            return
        for name in self.store.names("clarification-"):
            state = self.store.load_model(name, ProposalClarificationState)
            assert isinstance(state, ProposalClarificationState)
            now = datetime.now(timezone.utc)
            if (state.answer_status == AnswerStatus.PENDING and
                    state.authorized_answer is not None and
                    state.interpretation_status in {
                        ProposalRevisionStatus.PENDING,
                        ProposalRevisionStatus.RETRY_REQUIRED} and
                    state.interpretation_attempts < self.interpretation_attempts and
                    (state.next_interpretation_at is None or
                     state.next_interpretation_at <= now)):
                self._interpret_pending(state)
                # Interpretation can replace this record with an answered one;
                # load it again so revision can continue in the same resume.
                state = self.store.load_model(name, ProposalClarificationState)
                assert isinstance(state, ProposalClarificationState)
            if (state.question_status == QuestionStatus.ANSWERED and
                    state.proposal_revision_status == ProposalRevisionStatus.RETRY_REQUIRED and
                    (state.next_revision_at is None or
                     state.next_revision_at <= now)):
                self._revise_answered(state)

    def _resume_legacy_revision(self) -> None:
        """Resume a durable normalized answer without asking the person again."""
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if not isinstance(dialog, TelegramDialogState) or not dialog.retry_required:
            return
        assert dialog.mail_id and dialog.proposal_id and dialog.version
        assert dialog.question and dialog.normalized_answer
        proposal = self.store.load_model(
            proposal_name(dialog.mail_id, dialog.proposal_id), Proposal)
        if not isinstance(proposal, Proposal) or proposal.version != dialog.version:
            self.store.save("telegram-dialog", TelegramDialogState().model_dump())
            return
        if self.revision_service is None:
            return
        try:
            _, revised = self.revision_service.revise_proposal(
                proposal, dialog.question, dialog.normalized_answer)
            revised = validate_revision_successor(proposal, revised)
        except Exception as exc:
            self.logger.event("WARNING", "telegram.dialog", "answer_revision_resume_failed",
                              mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                              version=dialog.version, error=exc)
            return
        self.persistence.send_proposal(revised)
        self.store.save("telegram-dialog", TelegramDialogState().model_dump())
        self.logger.event("INFO", "telegram.dialog", "answer_revision_resumed",
                          mail_id=dialog.mail_id, proposal_id=dialog.proposal_id,
                          previous_version=dialog.version, new_version=revised.version)


def _validation_path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(part) for part in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"


class TelegramDialogController:
    """Validate updates, persist offsets, and enforce version-bound decisions."""

    manages_proposal_delivery = True

    def __init__(self, store: JsonStore, telegram: TelegramTransport, user_id: int, chat_id: int, logger: EventLogger, writers: dict[str, ExternalWriter] | None = None, test_mode: bool = False, configured_timezone: str = "UTC", revision_service: ProposalRevisionService | None = None, *, interpretation_attempts: int = 3, interpretation_backoff_seconds: int = 60, revision_attempts: int = 3, revision_backoff_seconds: int = 60):
        from .delivery import ProposalDeliveryService
        from .decisions import ProposalDecisionService
        from .persistence import ProposalRepository
        from .presenter import ProposalPresenter

        self.store, self.telegram, self.user_id, self.chat_id, self.logger = store, telegram, user_id, chat_id, logger
        self.writers, self.test_mode = writers or {}, test_mode
        self.configured_timezone = configured_timezone
        self.revision_service = revision_service
        self.interpretation_attempts = interpretation_attempts
        self.interpretation_backoff_seconds = interpretation_backoff_seconds
        self.revision_attempts = revision_attempts
        self.revision_backoff_seconds = revision_backoff_seconds
        self.validator: UpdateValidation = AuthorizedUpdateValidator(store, user_id, chat_id)
        self.relevance = RelevanceDialogProcessor(store, telegram, chat_id)
        self.ledger: ActionLedgerPort = ActionLedgerService(store)
        self.repository = ProposalRepository(store)
        self.presenter = ProposalPresenter(
            configured_timezone, lambda decision: decision.encode(store))
        self.delivery = ProposalDeliveryService(
            self.repository, self.presenter, telegram, chat_id)
        self.write_executor: WriteExecution = ConfirmedWriteExecutor(store, self.writers, self, telegram, chat_id, test_mode, self.ledger)
        self.decision_service = ProposalDecisionService(
            store, self.repository, self, self.ledger, self.write_executor,
            telegram, user_id, chat_id)
        self.revisions: ProposalRevisions = ProposalRevisionProcessor(store, revision_service, self, telegram, chat_id, logger, configured_timezone, interpretation_attempts=interpretation_attempts, interpretation_backoff_seconds=interpretation_backoff_seconds, revision_attempts=revision_attempts, revision_backoff_seconds=revision_backoff_seconds)

    @property
    def relevance_handler(self) -> RelevanceHandler | None:
        return self.relevance.handler

    @relevance_handler.setter
    def relevance_handler(self, value: RelevanceHandler | None) -> None:
        self.relevance.handler = value

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
    def _version_name(mail_id: str, proposal_id: str, version: int) -> str:
        """Deprecated compatibility alias for the repository naming rule."""
        return proposal_version_name(mail_id, proposal_id, version)

    def persist(self, proposal: Proposal) -> None:
        """Compatibility port; persistence itself belongs to the repository."""
        self.repository.save_revision(proposal)
        if proposal.status == ProposalStatus.CREATED:
            self._book_created(proposal)

    def _book_created(self, proposal: Proposal) -> None:
        self.ledger.book_created(proposal)

    def send(self, chat_id: int, text: str) -> None:
        if chat_id != self.chat_id:
            raise PermissionError("Nachrichten dürfen nur an den konfigurierten Chat gesendet werden")
        self.telegram.send(chat_id, text)

    def send_proposal(self, proposal: Proposal) -> None:
        """Compatibility port delegating delivery to its dedicated service."""
        self.delivery.deliver(proposal)

    def awaiting_decision(self) -> bool:
        """Return whether processing must wait for an explicit Telegram answer.

        Only authoritative proposal records are inspected; immutable version
        snapshots must not keep the application paused after a decision.
        """
        if self._open_relevance_dialogs():
            return True
        names = getattr(self.store, "names", None)
        if names is None:
            return False
        for name in names("proposal-"):
            if "-v" in name:
                continue
            proposal = self.store.load_model(name, Proposal)
            if isinstance(proposal, Proposal) and proposal.status in {
                    ProposalStatus.PENDING_CONFIRMATION,
                    ProposalStatus.NEEDS_CLARIFICATION}:
                return True
        return False

    def awaiting_relevance_decision(self) -> bool:
        """Return whether an unfinished mail analysis needs a relevance answer."""
        return bool(self._open_relevance_dialogs())

    def poll_once(self, timeout: int | None = None) -> None:
        self.write_executor.resume()
        self.revisions.resume()
        offset_state = self.store.load_model("telegram-offset", TelegramOffset, TelegramOffset())
        assert isinstance(offset_state, TelegramOffset)
        offset = max(offset_state.offset, self._durable_dialog_offset())
        updates = self.telegram.poll(offset, timeout=timeout)
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
                                  update_id=raw_id, error_class=type(exc).__name__)
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
            # Stop Telegram's loading indicator before potentially slow state,
            # LLM, or external-service work begins.
            self.telegram.answer_callback(callback.id, "Aktion wird verarbeitet …")
            if not self._authorized(callback.sender.id, callback.message.chat.id):
                self.logger.event("WARNING", "telegram.dialog", "unauthorized_update",
                                  update_id=update.update_id, update_kind="callback_query",
                                  user_id=callback.sender.id, chat_id=callback.message.chat.id)
                self.telegram.send(self.chat_id, "❌ Nicht autorisierte Aktion.")
                return
            try:
                if callback.data.startswith("relevance:"):
                    try:
                        relevance = self.validator.relevance_decision(callback.data)
                    except (ValueError, ValidationError):
                        self.telegram.send(self.chat_id, "❌ Relevanzantwort ist syntaktisch ungültig; bitte erneut versuchen.")
                        return
                    confirmation = self._decide_relevance(relevance, update.update_id + 1)
                else:
                    try:
                        decision = self.validator.decision(callback.data)
                    except (ValueError, ValidationError):
                        self.telegram.send(self.chat_id, "❌ Aktion ist syntaktisch ungültig; bitte erneut versuchen.")
                        return
                    confirmation = self.decision_service.decide(
                        decision, callback.sender.id, callback.message.chat.id)
            except Exception as exc:
                self.logger.event("ERROR", "telegram.dialog", "callback_processing_failed",
                                  update_id=update.update_id, error=exc,
                                  stacktrace=traceback.format_exc())
                self.telegram.send(self.chat_id, "❌ Aktion konnte nicht verarbeitet werden. Bitte erneut versuchen.")
                return
            assert confirmation is not None
            self.telegram.remove_inline_keyboard(callback.message.chat.id, callback.message.message_id)
            self.telegram.send(self.chat_id, confirmation)
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
            self._decide_relevance(RelevanceDecision(mail_id=dialog.mail_id, version=dialog.version, decision=normalized), update.update_id + 1, notify=True)
            return
        self.revisions.answer(message.text)

    def _open_relevance_dialogs(self) -> list[RelevanceDialog]:
        return self.relevance.open()

    def _durable_dialog_offset(self) -> int:
        return self.relevance.durable_offset()

    def _decide_relevance(self, decision: RelevanceDecision, offset: int, notify: bool = False) -> str | None:
        return self.relevance.decide(decision, offset, notify)

    def _authorized(self, user_id: int, chat_id: int) -> bool:
        return self.validator.authorized(user_id, chat_id)

    def _decide(self, decision: Decision) -> str:
        """Compatibility entry point for already-authorized internal callers."""
        return self.decision_service.decide(
            decision, self.user_id, self.chat_id)
