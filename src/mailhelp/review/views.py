"""Read models: open decisions, proposal cards, recent results and run status.

Views only read.  They use ``JsonStore.peek_model``, so no migration is saved,
no damaged file is moved and nothing is written; a damaged record is skipped
and counted.  Each view is built under the store's thread lock and therefore
reflects one consistent moment, even while the main thread keeps working.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..domain.processing import (
    AnswerStatus,
    ProposalClarificationState,
    ProposalRevisionStatus,
    TelegramOutboxState,
)
from ..models import (
    MailRunState,
    MailState,
    Proposal,
    ProposalKind,
    ProposalStatus,
    RelevanceDialogStatus,
    TelegramDialogState,
)
from ..storage import CorruptState, JsonStore
from .cards import CardContent, answer_example, card_content, display_question, sender_name, yes_no_question
from .commands import CommandKind

_OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
_SNAPSHOT = re.compile(r"-v\d+\Z")
_CHANGE_QUESTION = "Was soll geändert werden?"
_CHANGE_EXAMPLE = "„Titel: Elternabend“ oder „Ort: Raum 3“"
RECENT_LIMIT = 8
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
STATUS_LABELS = {
    ProposalStatus.PENDING_CONFIRMATION: "Wartet auf Bestätigung",
    ProposalStatus.NEEDS_CLARIFICATION: "Klärung nötig",
    ProposalStatus.CONFIRMED: "Bestätigt – wird angelegt",
    ProposalStatus.WRITING: "Wird angelegt",
    ProposalStatus.CREATED: "Angelegt",
    ProposalStatus.SIMULATED: "Simuliert (Testmodus)",
    ProposalStatus.REJECTED: "Verworfen",
    ProposalStatus.FAILED: "Anlage fehlgeschlagen",
    ProposalStatus.UNCERTAIN: "Wird abgeglichen",
}
Model = TypeVar("Model", bound=BaseModel)


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


@dataclass
class _Reader:
    store: JsonStore
    damaged: set[str] = field(default_factory=set)

    def model(self, name: str, model: type[Model]) -> Model | None:
        try:
            value = self.store.peek_model(name, model)
        except CorruptState:
            self.damaged.add(name)
            return None
        return value  # type: ignore[return-value]


class ReviewViews:
    """Build read models from the persisted state without changing it."""

    def __init__(self, store: JsonStore, configured_timezone: str, test_mode: bool = False):
        self.store, self.configured_timezone, self.test_mode = store, configured_timezone, test_mode

    def overview(self) -> Overview:
        with self.store.locked():
            reader = _Reader(self.store)
            proposals = self._proposals(reader)
            relevance = self._relevance(reader)
            run = self._run(reader)
        open_views = [view for view, _ in sorted(
            (item for item in proposals if item[0].status in _OPEN),
            key=lambda item: (not item[0].current, item[1], item[0].mail_id, item[0].proposal_id))]
        recent = sorted((view for view, _ in proposals if view.status not in _OPEN),
                        key=lambda view: view.updated_at or _EPOCH, reverse=True)[:RECENT_LIMIT]
        return Overview(
            relevance=tuple(relevance), open=tuple(open_views), recent=tuple(recent),
            run=run, damaged=len(reader.damaged),
            fingerprint=_fingerprint(relevance, open_views, recent),
        )

    def proposal(self, mail_id: str, proposal_id: str) -> ProposalView | None:
        """One proposal by identity, open or recently decided."""
        overview = self.overview()
        return next((view for view in overview.open + overview.recent
                     if (view.mail_id, view.proposal_id) == (mail_id, proposal_id)), None)

    def mail(self, mail_id: str) -> MailView | None:
        """The mail with its complete text, or None if no such mail is known."""
        with self.store.locked():
            state = _Reader(self.store).model(f"mail-{mail_id}", MailState)
        if state is None:
            return None
        content = state.mail if isinstance(state.mail, dict) else {}
        headers = content.get("headers") if isinstance(content.get("headers"), dict) else {}
        display = state.display_headers
        sender = display.sender if display else str(headers.get("from") or "—")
        subject = display.subject if display else str(headers.get("subject") or "—")
        received = None
        stamp = content.get("date_header_parsed") or content.get("imap_received_at")
        if isinstance(stamp, str):
            try:
                received = datetime.fromisoformat(stamp).astimezone(
                    ZoneInfo(self.configured_timezone)).strftime("%d.%m.%Y, %H:%M Uhr")
            except ValueError:
                received = None
        text = content.get("text") if isinstance(content.get("text"), str) else None
        metadata = content.get("metadata") if isinstance(content.get("metadata"), dict) else {}
        omitted = metadata.get("attachments_omitted")
        return MailView(
            mail_id=mail_id, sender=sender, subject=subject, received=received, text=text,
            attachments_omitted=omitted if isinstance(omitted, int) else 0,
            text_shortened=metadata.get("text_shortened") is True)

    def _relevance(self, reader: _Reader) -> list[RelevanceView]:
        result = []
        for name in self.store.names("mail-"):
            if name.startswith("mail-run-"):
                continue
            mail = reader.model(name, MailState)
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
        for name in self.store.names("mail-run-"):
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
        mails: dict[str, MailState | None] = {}
        result = []
        for name in self.store.names("proposal-"):
            if _SNAPSHOT.search(name):
                continue
            proposal = reader.model(name, Proposal)
            if proposal is None:
                continue
            mail_id = proposal.source_mail_id
            if mail_id not in mails:
                mails[mail_id] = reader.model(f"mail-{mail_id}", MailState)
            mail = mails[mail_id]
            clarification = reader.model(
                f"clarification-{mail_id}-{proposal.id}-v{proposal.version}",
                ProposalClarificationState)
            current = (gate is not None and gate.kind == "proposal"
                       and (gate.mail_id, gate.proposal_id) == (mail_id, proposal.id))
            view = self._view(proposal, mail, clarification, pointer, current,
                              (mail_id, proposal.id, proposal.version) in queued)
            result.append((view, _mail_position(mail, proposal)))
        return result

    def _view(self, proposal: Proposal, mail: MailState | None,
              clarification: ProposalClarificationState | None,
              pointer: TelegramDialogState, current: bool, queued: bool) -> ProposalView:
        open_ = proposal.status in _OPEN
        editing = open_ and (pointer.mail_id, pointer.proposal_id, pointer.version) == (
            proposal.source_mail_id, proposal.id, proposal.version)
        answer_saved = (clarification is not None and clarification.authorized_answer is not None
                        and clarification.answer_status != AnswerStatus.INVALID) or (
            editing and pointer.retry_required)
        paused = clarification is not None and ProposalRevisionStatus.PAUSED in {
            clarification.interpretation_status, clarification.proposal_revision_status}
        card = card_content(proposal, self.configured_timezone, self.test_mode)
        question = example = None
        if open_ and proposal.open_questions:
            question = display_question(proposal.open_questions[0])
            example = answer_example(proposal.open_questions[0])
        elif open_ and (editing or not card.writable):
            question, example = _CHANGE_QUESTION, _CHANGE_EXAMPLE
        actions: set[CommandKind] = set()
        if open_ and not answer_saved and not paused:
            actions = {CommandKind.REJECT, CommandKind.ANSWER}
            if proposal.status == ProposalStatus.PENDING_CONFIRMATION:
                actions.add(CommandKind.CONFIRM)
            if editing:
                actions.add(CommandKind.CANCEL_CLARIFICATION)
        if paused:
            state = "Verarbeitung pausiert – bitte Betreiber prüfen lassen"
        elif answer_saved:
            state = "Antwort gespeichert – wird verarbeitet"
        elif editing:
            state = "Rückfrage offen"
        else:
            state = STATUS_LABELS[proposal.status]
        headers = mail.display_headers if mail is not None else None
        target = "In Todoist anlegen" if proposal.kind == ProposalKind.TASK else "Im Kalender anlegen"
        return ProposalView(
            mail_id=proposal.source_mail_id, proposal_id=proposal.id,
            version=proposal.version, status=proposal.status, card=card,
            sender=sender_name(headers.sender) if headers else "—",
            subject=headers.subject if headers else "—",
            state=state, editing=editing, answer_saved=answer_saved, paused=paused,
            current=current and open_, queued=queued and open_,
            question=question, example=example,
            yes_no=bool(open_ and proposal.open_questions)
            and yes_no_question(proposal.open_questions[0]),
            actions=frozenset(actions),
            confirm_label="Simulieren" if self.test_mode else target,
            external_link=proposal.external_link if proposal.status == ProposalStatus.CREATED else None,
            updated_at=mail.updated_at if mail is not None else None,
        )


def _mail_position(mail: MailState | None, proposal: Proposal) -> tuple[int, int]:
    if mail is None:
        return (0, 0)
    ids = [item.id for item in mail.proposals]
    return (mail.imap.uid, ids.index(proposal.id) if proposal.id in ids else 0)


def _fingerprint(relevance: list[RelevanceView], open_views: list[ProposalView],
                 recent: list[ProposalView]) -> str:
    """Changes whenever something visible in the overview changes."""
    parts = [f"r:{item.mail_id}:{item.version}" for item in relevance]
    parts += [f"p:{view.mail_id}:{view.proposal_id}:{view.version}:{view.status}:"
              f"{view.state}:{view.current}" for view in open_views]
    parts += [f"d:{view.mail_id}:{view.proposal_id}:{view.version}:{view.status}"
              for view in recent]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


__all__ = ["MailView", "Overview", "ProposalView", "RECENT_LIMIT", "RelevanceView", "ReviewViews",
           "RunStatus", "STATUS_LABELS"]
