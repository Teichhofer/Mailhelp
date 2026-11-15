"""Proposals of one analysed mail: build, count, deadlines, images and previews (7.0, R5)."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo

from ..config import (
    EventDefaultsSettings,
    TargetSettings,
)
from ..domain.deep_links import mail_link
from ..domain.extraction import ExtractionCountConflict
from ..domain.mail import MailState
from ..domain.proposal import Proposal
from ..mailbox.sender_filter import is_irrelevant_sender
from ..proposals.action_normalization import DEADLINE_DATE_PATTERN, MailDateContext, resolve_day
from ..proposals.proposal_builder import ProposalBuilder
from ..telegram.formatting import mail_line
from .attachments import AttachmentCache

if TYPE_CHECKING:
    from .orchestrator import Orchestrator


def build_proposals(orchestrator: Orchestrator, state: MailState) -> list[Proposal]:
    """Cross from untrusted extracted facts into application-owned proposals."""
    mail = state.prepared
    assert mail is not None
    context = MailDateContext(
        date_context_status=mail.date_context_status,
        date_header_parsed=mail.date_header_parsed,
        imap_received_at=mail.imap_received_at,
        user_timezone=mail.user_timezone or orchestrator.user_timezone,
    )
    headers = state.display_headers
    return ProposalBuilder(
        state.id,
        (
            TargetSettings.model_validate(state.proposal_policy["targets"])
            if state.proposal_policy is not None and "targets" in state.proposal_policy
            else orchestrator.targets
        ),
        context,
        source_sender=headers.sender if headers else "—",
        source_subject=headers.subject if headers else "—",
        event_defaults=(
            EventDefaultsSettings.model_validate(state.proposal_policy["event_defaults"])
            if state.proposal_policy is not None
            else None
        ),
        target_profile=(state.proposal_policy.get("target_profile", 1) if state.proposal_policy is not None else 1),
        # 4.7: mails prepared before 4.7 have no link kind and keep their descriptions.
        mail_link=mail_link(mail.headers.message_id,
                            (state.proposal_policy or {}).get("mail_link_kind", "none")),
    ).build(
        state.task_extraction.tasks if state.task_extraction else [],
        state.event_extraction.events if state.event_extraction else [],
        state.extraction_count_conflicts,
        calendar_events=mail.calendar_events,
    )


def record_count_conflict(orchestrator: Orchestrator, name: str, state: MailState, category: Literal["task", "event"],
                           expected: int, actual: int, router_call_id: str | None,
                           extractor_call_id: str) -> None:
    if expected == actual:
        return
    assert router_call_id is not None  # a count comes from the router's own call
    key = (category, router_call_id, extractor_call_id)
    if any((item.category, item.router_call_id, item.extractor_call_id) == key
           for item in state.extraction_count_conflicts):
        return
    conflict = ExtractionCountConflict(
        category=category, expected_count=expected, actual_count=actual,
        router_call_id=router_call_id, extractor_call_id=extractor_call_id,
    )
    state.extraction_count_conflicts.append(conflict)
    orchestrator.save(name, state)
    orchestrator.logger.event("WARNING", "orchestrator", "extraction_count_conflict",
                      mail_id=state.id, category=category, expected_count=expected,
                      actual_count=actual, router_call_id=router_call_id,
                      extractor_call_id=extractor_call_id)


def read_images(orchestrator: Orchestrator, name: str, state: MailState, raw: bytes) -> None:
    """Vision OCR before relevance; progress is saved per attachment.

    It runs at most once per mail, never for a blocked sender and only while
    the original message is available (a resumed mail has no raw bytes).
    """
    assert state.mail is not None and state.prepared is not None and orchestrator.vision is not None
    metadata = state.mail["metadata"]
    if "vision" in metadata:
        return
    if not raw:
        metadata["vision"] = "unavailable"
    elif is_irrelevant_sender(state.prepared.headers.sender, orchestrator.blocked_senders(),
                              orchestrator.mailbox_number(state.imap.account_id)):
        metadata["vision"] = "skipped_sender"
    else:
        attachments = state.mail.get("extracted_attachments", [])
        for update in orchestrator.vision.extract(raw, attachments):
            attachments[update.index] = update.attachment
            if update.call_id is not None:
                state.llm_call_ids.append(update.call_id)
            orchestrator.save(name, state)
            orchestrator.logger.event("WARNING" if update.error else "INFO", "orchestrator",
                              "vision_attachment", mail_id=state.id, attachment=update.index,
                              outcome=update.attachment["vision"], call_id=update.call_id,
                              error_type=update.error,
                              characters=update.attachment.get("character_count", 0))
        metadata["vision"] = "completed"
    orchestrator.save(name, state)


def cache_previews(orchestrator: Orchestrator, state: MailState, raw: bytes) -> None:
    """Image previews are optional; a failure never stops the analysis."""
    assert state.mail is not None  # previews are cached while the mail is prepared
    try:
        AttachmentCache(orchestrator.store).prepare(state.id, raw, state.mail["extracted_attachments"],
                                            orchestrator.original_attachments)
    except (OSError, ValueError) as exc:
        orchestrator.logger.event("WARNING", "orchestrator", "preview_failed", mail_id=state.id,
                          error_class=type(exc).__name__)


def _future_deadlines(orchestrator: Orchestrator, state: MailState) -> list[str]:
    if state.summary is None:
        return []
    raw = getattr(state.summary, "deadlines", []) or []
    if not raw:
        return []
    context = (
        MailDateContext(
            date_context_status=state.prepared.date_context_status,
            date_header_parsed=state.prepared.date_header_parsed,
            imap_received_at=state.prepared.imap_received_at,
            user_timezone=state.prepared.user_timezone or orchestrator.user_timezone,
        )
        if state.prepared is not None
        else None
    )
    try:
        today = datetime.fromtimestamp(orchestrator.clock(), UTC).astimezone(ZoneInfo(orchestrator.user_timezone)).date()
    except Exception:
        today = datetime.now(UTC).date()
    token_re = re.compile(rf"(?i)(?<![\d.])({DEADLINE_DATE_PATTERN})(?![\d.-]?\d)")
    future: list[str] = []
    for item in raw:
        match = token_re.search(item)
        if match is not None:
            token = match.group(0)
            day = resolve_day(token, context) if context is not None else None
            if day is None:
                for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
                    try:
                        day = datetime.strptime(token, fmt).date()
                        break
                    except ValueError:
                        pass
            if day is not None and day < today:
                continue
        future.append(item)
        if len(future) == 3:
            break
    return future


def notification_text(orchestrator: Orchestrator, state: MailState) -> str:
    """Format the compact mail notification from validated display values."""
    assert state.prepared is not None and state.relevance is not None and state.summary is not None
    headers = state.prepared.headers
    sentences = "\n".join(f"• {sentence}" for sentence in state.summary.sentences)
    deadlines = orchestrator._future_deadlines(state)
    deadline_line = f"\nFristen: {'; '.join(deadlines)}" if deadlines else ""
    return f"{mail_line(headers.sender or '—', headers.subject or '—')}\n{sentences}{deadline_line}"
