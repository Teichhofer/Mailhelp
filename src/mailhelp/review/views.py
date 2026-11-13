"""Read models: open decisions, proposal cards, recent results and run status.

Views only read.  They use ``JsonStore.peek_model``, so no migration is saved,
no damaged file is moved and nothing is written; a damaged record is skipped
and counted.  Each view is built under the store's thread lock and therefore
reflects one consistent moment, even while the main thread keeps working.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .. import state_names
from ..domain.prepared import PreparedAttachment, PreparedMail
from ..domain.processing import (
    AnswerStatus,
    ProposalClarificationState,
    ProposalRevisionStatus,
    TelegramOutboxState,
)
from ..domain.proposal import UNVERIFIED_LEGACY_ACTOR, answerable_questions, reconciliation_only
from ..domain.verification import OPERATIONS, WriteVerification, operation_id
from ..formatting import format_datetime_local
from ..models import (
    DisplayHeaders,
    MailRunState,
    MailState,
    Proposal,
    ProposalKind,
    ProposalStatus,
    RelevanceDialog,
    RelevanceDialogStatus,
    TelegramDialogState,
)
from ..processing.attachments import AttachmentCache, OriginalFile
from ..storage import CorruptState, JsonStore
from .calendar_display import candidate_label
from .cards import CardContent, answer_example, card_content, display_question, sender_name, yes_no_question
from .commands import CommandKind
from .verification_texts import VerificationSummary, summary

_OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
_SNAPSHOT = re.compile(r"-v\d+\Z")
_CHANGE_QUESTION = "Was soll geändert werden?"
_CHANGE_EXAMPLE = "„Titel: Elternabend“ oder „Ort: Raum 3“"
RECENT_LIMIT = 8
# A cached overview is rebuilt at least this often (changes from outside the process).
OVERVIEW_MAX_AGE_SECONDS = 60
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
STATUS_LABELS = {
    ProposalStatus.PENDING_CONFIRMATION: "Wartet auf Bestätigung",
    ProposalStatus.NEEDS_CLARIFICATION: "Klärung nötig",
    ProposalStatus.CONFIRMED: "Bestätigt – wird angelegt",
    ProposalStatus.WRITING: "Wird angelegt",
    ProposalStatus.CREATED: "Angelegt",
    ProposalStatus.VERIFYING: "Gespeichert – Eintrag wird geprüft",
    ProposalStatus.SIMULATED: "Simuliert (Testmodus)",
    ProposalStatus.REJECTED: "Verworfen",
    ProposalStatus.FAILED: "Anlage fehlgeschlagen",
    ProposalStatus.UNCERTAIN: "Wird abgeglichen",
    ProposalStatus.ALREADY_EXISTS: "Bereits vorhanden",
    ProposalStatus.MERGED: "Zusammengeführt",
}
Model = TypeVar("Model", bound=BaseModel)


@dataclass(frozen=True)
class ConflictOption:
    """One value of a field conflict as shown: origin, value and a short button text (5.9.3)."""
    id: str
    origin: str
    value: str
    button: str
    keep: bool


@dataclass(frozen=True)
class ConflictChoice:
    id: str
    label: str
    # The question in the configured zone, and the stored question it stands for.
    question: str
    stored_question: str
    options: tuple[ConflictOption, ...]


@dataclass(frozen=True)
class ProposalView:
    mail_id: str
    proposal_id: str
    version: int
    status: ProposalStatus
    card: CardContent
    sender: str
    subject: str
    state: str
    editing: bool
    answer_saved: bool
    paused: bool
    current: bool
    queued: bool
    question: str | None
    example: str | None
    yes_no: bool
    actions: frozenset[CommandKind]
    confirm_label: str
    external_link: str | None
    updated_at: datetime | None
    duplicate_match: Any | None = None
    target_event_id: str | None = None
    time_changes: list[str] | None = None
    is_cancellation: bool = False
    series_key: str | None = None
    base_title: str | None = None
    # Display labels of Proposal.calendar_candidates, in the same order (4.6).
    calendar_candidates: tuple[str, ...] = ()
    # 5.0.3: only the reconciliation is open; the card links to the Vorschlagsabgleich.
    reconciliation_required: bool = False
    # 4.7: opens the source mail in the mail program (validated Proposal.mail_link).
    mail_link: str | None = None
    # 5.2: the check of a written entry, if there is one.
    verification: VerificationSummary | None = None
    # 5.9.3: contradicting source values, each with its options.
    conflicts: tuple[ConflictChoice, ...] = ()


@dataclass(frozen=True)
class RelevanceView:
    mail_id: str
    version: int
    sender: str
    subject: str


@dataclass(frozen=True)
class MailView:
    """The stored mail behind a proposal or relevance question, for reading."""

    mail_id: str
    sender: str
    subject: str
    received: str | None
    # None once retention removed the full mail (or it was never stored).
    text: str | None
    attachments_omitted: int
    text_shortened: bool
    extracted_attachments: tuple[PreparedAttachment, ...] = ()
    calendar_events: tuple[dict[str, Any], ...] = ()
    # Attachment index → stored original document (2.3); empty for older mails.
    originals: dict[int, OriginalFile] = field(default_factory=dict)
    # Label of its mailbox; empty with a single mailbox (3.1).
    mailbox: str = ""


@dataclass(frozen=True)
class ErrorView:
    """A mail whose processing stopped with an error (no content, only the cause)."""

    mail_id: str
    subject: str
    stage: str
    cause: str
    occurred_at: datetime
    retryable: bool | None
    next_attempt: datetime | None = None
    # Technical codes for identities (notification references); labels are display only.
    stage_code: str = ""
    cause_code: str = ""

    @property
    def reference(self) -> str:
        return f"{self.mail_id}:{self.stage_code}:{self.cause_code}"


def processed(state: MailState) -> bool:
    """5.9.7: a mail counts as processed once its completion step is done.

    Computed from the stored state on every call: retention only cleans states, so the count
    survives restarts and never counts twice; a mail being analyzed again counts once it is
    completed again.
    """
    return state.steps.completion == "completed"


def count_processed(store: JsonStore) -> int:
    """Read-only count of processed mails (Telegram /status)."""
    with store.locked():
        reader = _Reader(store)
        return sum(processed(state) for name in state_names.mail_state_names(store)
                   if (state := reader.model(name, MailState)) is not None)


def german_number(value: int) -> str:
    """1234 → "1.234" (German thousands separator)."""
    return f"{value:,}".replace(",", ".")


@dataclass(frozen=True)
class SystemStatus:
    mails_total: int
    mails_failed: int
    mails_deferred: int
    mails_waiting_relevance: int
    last_processed: datetime | None
    # Outcome of the analysis in the current run: completed, irrelevant, duplicate, ...
    analysis: dict[str, int]
    run_total: int
    run_finished: int
    proposals: dict[ProposalStatus, int]
    errors: tuple[ErrorView, ...]
    telegram_held: int
    telegram_unprocessed: int
    llm_calls_last_minute: int
    already_done: int = 0
    # 5.9.7: states whose processing is completed (irrelevant mails and duplicates included).
    mails_processed: int = 0


STAGE_LABELS = {
    "preparation": "Aufbereitung", "relevance": "Relevanzprüfung", "summary": "Zusammenfassung",
    "summary_notification": "Telegram-Zusammenfassung", "action_detection": "Aktionserkennung",
    "action_router": "Aktionszuordnung", "task_extraction": "Aufgabenerkennung",
    "event_extraction": "Terminerkennung", "normalization": "Normalisierung",
    "proposal_building": "Vorschlagserstellung", "proposal_notification": "Telegram-Vorschlag",
    "completion": "Abschluss",
}
ERROR_LABELS = {
    "mime_limit_exceeded": "Mail zu groß oder zu komplex",
    "llm_schema_validation_exhausted": "KI-Antwort wiederholt ungültig",
    "provider_response_invalid": "Ungültige Antwort des KI-Anbieters",
    "invalid_json": "KI-Antwort war kein gültiges JSON",
    "schema_validation_failed": "KI-Antwort entsprach nicht dem Schema",
    "permanent_adapter_error": "Dienst lehnt dauerhaft ab",
    "llm_rate_limited": "KI-Aufruflimit erreicht",
    "internal_error": "Interner Fehler",
}
ERROR_LIMIT = 5


@dataclass(frozen=True)
class RunStatus:
    counters: dict[str, int]
    run_complete: bool
    started_at: datetime | None


@dataclass(frozen=True)
class Overview:
    relevance: tuple[RelevanceView, ...]
    open: tuple[ProposalView, ...]
    recent: tuple[ProposalView, ...]
    run: RunStatus
    damaged: int
    fingerprint: str


@dataclass(frozen=True)
class _MailSummary:
    """What the overview needs of a mail; full mail states stay on disk."""
    display_headers: DisplayHeaders | None
    updated_at: datetime
    uid: int
    proposal_ids: tuple[str, ...]
    relevance_dialog: RelevanceDialog | None


def _same[M](value: M) -> M:
    return value


def _summary(mail: MailState) -> _MailSummary:
    return _MailSummary(mail.display_headers, mail.updated_at, mail.imap.uid,
                        tuple(item.id for item in mail.proposals), mail.relevance_dialog)


@dataclass
class _Reader:
    store: JsonStore
    damaged: set[str] = field(default_factory=set)
    # With a listing (scan), states are read from the store's projection cache.
    listing: dict[str, tuple[int, int, int]] | None = None

    def model(self, name: str, model: type[Model]) -> Model | None:
        return self.project(name, model, _same)

    def project[M: BaseModel, T](self, name: str, model: type[M], project: Callable[[M], T]) -> T | None:
        try:
            if self.listing is None:
                value = self.store.peek_model(name, model)
                return None if value is None else project(value)
            signature = self.listing.get(name)
            if signature is None and not self.store.authoritative(name):
                return None
            return self.store.cached(name, model, project, signature)
        except CorruptState:
            self.damaged.add(name)
            return None

    def mail(self, mail_id: str) -> _MailSummary | None:
        return self.project(state_names.mail(mail_id), MailState, _summary)

    def names(self, prefix: str) -> list[str]:
        assert self.listing is not None  # Only the overview lists states; it always has a listing.
        return [name for name in self.listing if name.startswith(prefix)]

    def raw(self, name: str) -> dict[str, Any]:
        """An unvalidated state object; damaged or missing ones read as empty."""
        try:
            value = self.store.peek(name, {})
        except CorruptState:
            self.damaged.add(name)
            return {}
        return value if isinstance(value, dict) else {}


class ReviewViews:
    """Build read models from the persisted state without changing it."""

    def __init__(self, store: JsonStore, configured_timezone: str, test_mode: bool = False):
        self.store, self.configured_timezone, self.test_mode = store, configured_timezone, test_mode
        # Account id -> (number, label) of every enabled mailbox; empty with a single mailbox (3.1).
        self.mailboxes: dict[str, tuple[int, str]] = {}
        self.profile_label: Callable[[Proposal], str] = lambda proposal: ""
        self.profile_available: Callable[[Proposal], bool] = lambda proposal: True
        # (cache key, monotonic time, overview): reading every state took up to seconds per page view.
        self._overview: tuple[tuple[Any, ...], float, Overview] | None = None
        self.clock: Callable[[], float] = time.monotonic

    def overview(self) -> Overview:
        """Rebuilt after a state change; the overview depends on stored state alone.

        File metadata and a maximum age also catch files changed outside this
        process, including an in-place repair or damage to an existing record.
        """
        with self.store.locked():
            now = self.clock()
            listing = self.store.scan()
            # Only states shown in the overview count; mailbox polls and queues do not.
            relevant = tuple(item for item in listing.items() if _shown(item[0]))
            key = (self.store.settings_revision, relevant,
                   tuple(sorted(self.mailboxes.items())), self.profile_label, self.profile_available)
            cached = self._overview
            if cached is not None and cached[0] == key and now - cached[1] < OVERVIEW_MAX_AGE_SECONDS:
                return cached[2]
            reader = _Reader(self.store, listing=listing)
            proposals = self._proposals(reader)
            relevance = self._relevance(reader)
            run = self._run(reader)
        open_views = [view for view, _ in sorted(
            (item for item in proposals if item[0].status in _OPEN),
            key=lambda item: (not item[0].current, item[1], item[0].mail_id, item[0].proposal_id))]
        recent = sorted((view for view, _ in proposals if view.status not in _OPEN),
                        key=lambda view: view.updated_at or _EPOCH, reverse=True)[:RECENT_LIMIT]
        overview = Overview(
            relevance=tuple(relevance), open=tuple(open_views), recent=tuple(recent),
            run=run, damaged=len(reader.damaged),
            fingerprint=_fingerprint(relevance, open_views, recent) + "-" + hashlib.sha256(
                repr(key[:2]).encode()).hexdigest()[:8],
        )
        self._overview = (key, now, overview)
        return overview

    def proposal(self, mail_id: str, proposal_id: str, version: int | None = None) -> ProposalView | None:
        """Resolve by identity, independently of the recent-results window."""
        with self.store.locked():
            reader = _Reader(self.store)
            item = reader.model(state_names.proposal(mail_id, proposal_id, version), Proposal)
            if item is None or (item.source_mail_id, item.id) != (mail_id, proposal_id):
                return None
            mail = reader.model(state_names.mail(mail_id), MailState)
            pointer = reader.model("telegram-dialog", TelegramDialogState) or TelegramDialogState()
            clarification = reader.model(state_names.clarification(mail_id, proposal_id, item.version),
                                         ProposalClarificationState)
            outbox = reader.model("telegram-outbox", TelegramOutboxState) or TelegramOutboxState()
            gate = outbox.active
            current = gate is not None and (gate.mail_id, gate.proposal_id) == (mail_id, proposal_id)
            queued = any((entry.mail_id, entry.proposal_id, entry.version) ==
                         (mail_id, proposal_id, item.version) for entry in outbox.entries)
            return self._view(item, mail, clarification, pointer, current, queued, self._verification(reader, item))

    def system(self, now: datetime | None = None) -> SystemStatus:
        """Operating figures from the stored state; nothing is changed."""
        now = now or datetime.now(UTC)
        with self.store.locked():
            reader = _Reader(self.store)
            mails = [state for name in state_names.mail_state_names(self.store)
                     if (state := reader.model(name, MailState)) is not None]
            runs = [run for name in self.store.names(state_names.MAIL_RUN_PREFIX)
                    if (run := reader.model(name, MailRunState)) is not None]
            outbox = reader.model("telegram-outbox", TelegramOutboxState) or TelegramOutboxState()
            inbox = reader.raw("telegram-inbox")
            budget = reader.raw("llm-budget")
            proposals = [proposal for name in self.store.names(state_names.PROPOSAL_PREFIX)
                         if not _SNAPSHOT.search(name)
                         if (proposal := reader.model(name, Proposal)) is not None]
        analysis: dict[str, int] = {}
        for run in runs:
            for entry in run.entries:
                if entry.analysis_terminal is not None:
                    analysis[entry.analysis_terminal] = analysis.get(entry.analysis_terminal, 0) + 1
        counts: dict[ProposalStatus, int] = {}
        for proposal in proposals:
            counts[proposal.status] = counts.get(proposal.status, 0) + 1
        failed = sorted(((state, state.error) for state in mails if state.error is not None),
                        key=lambda pair: pair[1].occurred_at, reverse=True)
        calls = budget.get("calls")
        entries = inbox.get("entries")
        return SystemStatus(
            already_done=sum(proposal.resolution == "already_done" for proposal in proposals),
            mails_total=len(mails),
            mails_failed=len(failed),
            mails_processed=sum(processed(state) for state in mails),
            mails_deferred=sum(state.deferred_until is not None and state.deferred_until > now
                               for state in mails),
            mails_waiting_relevance=sum(state.awaiting_relevance for state in mails),
            last_processed=max((state.updated_at for state in mails), default=None),
            analysis=analysis,
            run_total=sum(len(run.entries) for run in runs),
            run_finished=sum(entry.analysis_terminal is not None for run in runs for entry in run.entries),
            proposals=counts,
            errors=tuple(ErrorView(
                mail_id=state.id,
                subject=state.display_headers.subject if state.display_headers else "Mail ohne Betreff",
                stage=STAGE_LABELS[error.stage.value], cause=ERROR_LABELS[error.code.value],
                occurred_at=error.occurred_at, retryable=error.retryable,
                next_attempt=state.deferred_until,
                stage_code=error.stage.value, cause_code=error.code.value,
            ) for state, error in failed[:ERROR_LIMIT]),
            telegram_held=len(outbox.entries),
            telegram_unprocessed=len(entries) if isinstance(entries, list) else 0,
            llm_calls_last_minute=(sum(isinstance(value, (int, float)) and now.timestamp() - value < 60
                                       for value in calls) if isinstance(calls, list) else 0),
        )

    def mailbox_label(self, account: str) -> str:
        """The configured label, "Entferntes Postfach" for an unknown account; empty with one mailbox."""
        if not self.mailboxes:
            return ""
        return self.mailboxes.get(account, (0, "Entferntes Postfach"))[1]

    def mail(self, mail_id: str) -> MailView | None:
        """The mail with its complete text, or None if no such mail is known."""
        with self.store.locked():
            state = _Reader(self.store).model(state_names.mail(mail_id), MailState)
        if state is None:
            return None
        content = state.prepared or PreparedMail()
        display = state.display_headers
        sender = display.sender if display else content.headers.sender or "—"
        subject = display.subject if display else content.headers.subject or "—"
        received = None
        stamp = content.received
        if stamp is not None:
            try:
                received = format_datetime_local(datetime.fromisoformat(stamp), self.configured_timezone)
            except ValueError:
                received = None
        omitted = content.metadata.get("attachments_omitted")
        originals = AttachmentCache(self.store).originals(mail_id) if content.text is not None else {}
        return MailView(
            mail_id=mail_id, sender=sender, subject=subject, received=received, text=content.text,
            attachments_omitted=omitted if isinstance(omitted, int) else 0,
            text_shortened=content.metadata.get("text_shortened") is True,
            extracted_attachments=tuple(content.extracted_attachments),
            calendar_events=tuple(content.calendar_events), originals=originals,
            mailbox=self.mailbox_label(state.imap.account_id))

    def _relevance(self, reader: _Reader) -> list[RelevanceView]:
        result = []
        for name in reader.names(state_names.MAIL_PREFIX):
            if not state_names.is_mail_state(name):
                continue
            mail = reader.project(name, MailState, _summary)
            dialog = mail.relevance_dialog if mail is not None else None
            if dialog is None or dialog.status != RelevanceDialogStatus.OPEN:
                continue
            headers = mail.display_headers  # type: ignore[union-attr]
            result.append(RelevanceView(
                mail_id=dialog.mail_id, version=dialog.version,
                sender=sender_name(headers.sender) if headers else "—",
                subject=headers.subject if headers else "Mail ohne Betreff"))
        return result

    def _run(self, reader: _Reader) -> RunStatus:
        counters: dict[str, int] = {}
        complete, started = True, None
        for name in reader.names(state_names.MAIL_RUN_PREFIX):
            run = reader.model(name, MailRunState)
            if run is None:
                continue
            for key, value in run.counters.model_dump().items():
                counters[key] = counters.get(key, 0) + value
            complete = complete and run.run_complete
            started = run.created_at if started is None else max(started, run.created_at)
        return RunStatus(counters=counters, run_complete=complete, started_at=started)

    def _proposals(self, reader: _Reader) -> list[tuple[ProposalView, tuple[int, int]]]:
        pointer = reader.model("telegram-dialog", TelegramDialogState) or TelegramDialogState()
        outbox = reader.model("telegram-outbox", TelegramOutboxState) or TelegramOutboxState()
        queued = {(entry.mail_id, entry.proposal_id, entry.version)
                  for entry in outbox.entries if entry.kind == "proposal"}
        gate = outbox.active
        mails: dict[str, _MailSummary | None] = {}
        result = []
        for name in reader.names(state_names.PROPOSAL_PREFIX):
            if _SNAPSHOT.search(name):
                continue
            proposal = reader.model(name, Proposal)
            if proposal is None:
                continue
            mail_id = proposal.source_mail_id
            if mail_id not in mails:
                mails[mail_id] = reader.mail(mail_id)
            mail = mails[mail_id]
            clarification = reader.model(
                state_names.clarification(mail_id, proposal.id, proposal.version),
                ProposalClarificationState)
            current = (gate is not None and gate.kind == "proposal"
                       and (gate.mail_id, gate.proposal_id) == (mail_id, proposal.id))
            view = self._view(proposal, mail, clarification, pointer, current,
                              (mail_id, proposal.id, proposal.version) in queued, self._verification(reader, proposal))
            result.append((view, _mail_position(mail, proposal)))
        return result

    def _verification(self, reader: _Reader, proposal: Proposal) -> VerificationSummary | None:
        if proposal.status not in {ProposalStatus.VERIFYING, ProposalStatus.CREATED}:
            return None
        for operation in OPERATIONS:
            record = reader.model(state_names.write_verification(operation_id(
                proposal.source_mail_id, proposal.id, proposal.version, operation)), WriteVerification)
            if record is not None:
                return summary(record, ZoneInfo(self.configured_timezone))
        return None

    def _view(self, proposal: Proposal, mail: MailState | _MailSummary | None,
              clarification: ProposalClarificationState | None,
              pointer: TelegramDialogState, current: bool, queued: bool,
              verification: VerificationSummary | None = None) -> ProposalView:
        open_ = proposal.status in _OPEN
        editing = open_ and (pointer.mail_id, pointer.proposal_id, pointer.version) == (
            proposal.source_mail_id, proposal.id, proposal.version)
        answer_saved = (clarification is not None and clarification.authorized_answer is not None
                        and clarification.answer_status != AnswerStatus.INVALID) or (
            editing and pointer.retry_required)
        paused = clarification is not None and ProposalRevisionStatus.PAUSED in {
            clarification.interpretation_status, clarification.proposal_revision_status}
        card = card_content(proposal, self.configured_timezone, self.test_mode)
        label = self.profile_label(proposal)
        if label:
            card = replace(card, profile_label=label, target=proposal.target)
        question = example = None
        answerable = answerable_questions(proposal)
        # 5.0.3: a reconciliation block is decided in the Vorschlagsabgleich, not answered.
        blocked = open_ and reconciliation_only(proposal)
        if open_ and answerable:
            question = display_question(answerable[0])
            example = answer_example(answerable[0])
        elif open_ and (editing or not card.writable):
            question, example = _CHANGE_QUESTION, _CHANGE_EXAMPLE
        actions = (_open_actions(proposal, editing, blocked)
                   if open_ and not answer_saved and not paused else set())
        if paused:
            state = "Verarbeitung pausiert – bitte Betreiber prüfen lassen"
        elif answer_saved:
            state = "Antwort gespeichert – wird verarbeitet"
        elif editing:
            state = "Rückfrage offen"
        else:
            state = "Schon erledigt" if proposal.resolution == "already_done" else STATUS_LABELS[proposal.status]
        if not self.profile_available(proposal):
            actions.discard(CommandKind.CONFIRM)
            state = "Zielprofil nicht verfügbar – Zugriff prüfen oder Ziel umstellen"
        if proposal.status == ProposalStatus.CONFIRMED and proposal.confirmed_web_actor == UNVERIFIED_LEGACY_ACTOR:
            state = "Freigabe des Altbestands nicht prüfbar – Anlage gesperrt"
        if verification is not None:
            state = verification.title
            if verification.recheckable and proposal.status == ProposalStatus.VERIFYING:
                actions.add(CommandKind.VERIFY_ENTRY)
        headers = mail.display_headers if mail is not None else None
        target = "Als Aufgabe anlegen" if proposal.kind == ProposalKind.TASK else "Im Kalender anlegen"
        if proposal.target_event_id is not None:
            target = "Termin absagen" if proposal.is_cancellation else "Bestehenden Termin aktualisieren"
        return ProposalView(
            mail_id=proposal.source_mail_id, proposal_id=proposal.id,
            version=proposal.version, status=proposal.status, card=card,
            sender=sender_name(headers.sender) if headers else "—",
            subject=headers.subject if headers else "—",
            state=state, editing=editing, answer_saved=answer_saved, paused=paused,
            current=current and open_, queued=queued and open_,
            question=question, example=example,
            yes_no=bool(open_ and answerable) and yes_no_question(answerable[0]),
            reconciliation_required=blocked,
            actions=frozenset(actions),
            confirm_label="Simulieren" if self.test_mode else target,
            external_link=proposal.external_link if proposal.status == ProposalStatus.CREATED else None,
            updated_at=mail.updated_at if mail is not None else None,
            duplicate_match=proposal.duplicate_match,
            target_event_id=proposal.target_event_id,
            time_changes=proposal.time_changes,
            is_cancellation=proposal.is_cancellation,
            series_key=proposal.series_key, base_title=proposal.base_title,
            calendar_candidates=tuple(candidate_label(item, self.configured_timezone)
                                      for item in proposal.calendar_candidates),
            mail_link=proposal.mail_link,
            verification=verification,
            conflicts=conflict_choices(proposal, self.configured_timezone),
        )


def _open_actions(proposal: Proposal, editing: bool, blocked: bool) -> set[CommandKind]:
    """The actions of an open proposal without a saved answer or pause."""
    actions = {CommandKind.REJECT, CommandKind.ALREADY_DONE}
    if not blocked:
        actions.add(CommandKind.ANSWER)
    if proposal.status == ProposalStatus.PENDING_CONFIRMATION:
        actions.add(CommandKind.CONFIRM)
    if editing:
        actions.add(CommandKind.CANCEL_CLARIFICATION)
    if proposal.duplicate_check_failed:
        actions.add(CommandKind.RECHECK)
    if proposal.calendar_candidates:
        actions.add(CommandKind.CHOOSE_EVENT)
    if proposal.field_conflicts:
        actions.add(CommandKind.CHOOSE_VARIANT)
    return actions


def conflict_choices(proposal: Proposal, configured_timezone: str) -> tuple[ConflictChoice, ...]:
    """Field conflicts with their values in the configured zone (5.9.3)."""
    from ..proposals import conflicts
    zone = ZoneInfo(configured_timezone)
    return tuple(ConflictChoice(
        id=item.id, label=conflicts.label(item), question=conflicts.question(item, proposal.sources, zone),
        stored_question=item.question,
        options=tuple(ConflictOption(id=variant.id, origin=conflicts.origin_text(variant, proposal.sources),
                                     value=conflicts.value_text(item, variant, zone),
                                     button=conflicts.button_text(item, variant, zone),
                                     keep=variant.origin != "source")
                      for variant in item.variants))
        for item in proposal.field_conflicts)


def _mail_position(mail: _MailSummary | None, proposal: Proposal) -> tuple[int, int]:
    if mail is None:
        return (0, 0)
    ids = mail.proposal_ids
    return (mail.uid, ids.index(proposal.id) if proposal.id in ids else 0)


_SHOWN_PREFIXES = (state_names.PROPOSAL_PREFIX, state_names.MAIL_PREFIX, state_names.CLARIFICATION_PREFIX,
                   state_names.WRITE_VERIFICATION_PREFIX)


def _shown(name: str) -> bool:
    return name.startswith(_SHOWN_PREFIXES) or name in {"telegram-dialog", "telegram-outbox"}


def _fingerprint(relevance: list[RelevanceView], open_views: list[ProposalView],
                 recent: list[ProposalView]) -> str:
    """Changes whenever something visible in the overview changes."""
    parts = [f"r:{item.mail_id}:{item.version}" for item in relevance]
    parts += [f"p:{view.mail_id}:{view.proposal_id}:{view.version}:{view.status}:"
              f"{view.state}:{view.current}" for view in open_views]
    parts += [f"d:{view.mail_id}:{view.proposal_id}:{view.version}:{view.status}:{view.state}"
              for view in recent]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


__all__ = ["ERROR_LABELS", "ErrorView", "MailView", "Overview", "ProposalView", "STAGE_LABELS",
           "SystemStatus", "RECENT_LIMIT", "RelevanceView", "ReviewViews",
           "RunStatus", "STATUS_LABELS"]
