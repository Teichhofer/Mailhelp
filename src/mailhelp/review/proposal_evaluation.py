"""Proposal evaluation and acceptance rate metrics (Planung 6.5, 3.1).

Computes acceptance rates overall, by task/event, by week, by topic,
and by sender from stored proposal states and learning decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import state_names
from ..domain.mail import MailState
from ..domain.proposal import Proposal, ProposalKind, ProposalStatus
from ..mailbox.sender_filter import sender_addresses
from ..persistence.storage import JsonStore
from ..review.learning_log import _read, learning_path
from .reject_reasons import REJECT_REASONS

ACCEPTED_STATUSES = frozenset({
    ProposalStatus.CREATED,
    ProposalStatus.CONFIRMED,
    ProposalStatus.SIMULATED,
    ProposalStatus.ALREADY_EXISTS,
    ProposalStatus.MERGED,
})

PERIODS = (
    (1, "Heute (24 Std.)"),
    (7, "7 Tage"),
    (30, "30 Tage"),
    (90, "90 Tage"),
    (0, "Gesamter Zeitraum"),
)


@dataclass
class DecidedProposalRecord:
    mail_id: str
    proposal_id: str
    kind: str  # "task" or "event"
    is_accepted: bool
    is_rejected: bool
    status: str
    resolution: str | None
    sender: str
    topics: list[str]
    decided_at: datetime
    reject_reason: str | None = None
    is_removed: bool = False


@dataclass
class ProposalEvaluationSummary:
    total_decided: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_removed: int = 0
    total_quote: float = 0.0

    tasks_decided: int = 0
    tasks_accepted: int = 0
    tasks_rejected: int = 0
    tasks_removed: int = 0
    tasks_quote: float = 0.0

    events_decided: int = 0
    events_accepted: int = 0
    events_rejected: int = 0
    events_removed: int = 0
    events_quote: float = 0.0


@dataclass
class WeeklyEvaluation:
    week_key: str
    week_label: str
    decided: int = 0
    accepted: int = 0
    rejected: int = 0
    removed: int = 0
    quote: float = 0.0


@dataclass
class TopicEvaluation:
    topic_id: str
    topic_name: str
    decided: int = 0
    accepted: int = 0
    rejected: int = 0
    quote: float = 0.0


@dataclass
class SenderEvaluation:
    sender: str
    decided: int = 0
    accepted: int = 0
    rejected: int = 0
    quote: float = 0.0


@dataclass
class RejectReasonCount:
    reason_key: str
    reason_label: str
    count: int = 0
    percentage: float = 0.0


@dataclass
class ProposalEvaluationReport:
    days: int
    summary: ProposalEvaluationSummary
    weeks: list[WeeklyEvaluation] = field(default_factory=list)
    topics: list[TopicEvaluation] = field(default_factory=list)
    senders: list[SenderEvaluation] = field(default_factory=list)
    reasons: list[RejectReasonCount] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.summary.total_decided == 0


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _snapshot[T](value: T) -> T:
    """Shared read-only model projection, invalidated by the store's file signature."""
    return value


def collect_decided_proposals(store: JsonStore, cutoff: datetime | None = None, now: datetime | None = None) -> list[DecidedProposalRecord]:
    """Collect every decided proposal from stored states and decisions.jsonl without double counting."""
    results: list[DecidedProposalRecord] = []
    seen: set[tuple[str, str]] = set()
    mail_cache: dict[str, MailState | None] = {}
    now = now or datetime.now(UTC)
    listing = store.scan()

    def get_mail(mid: str) -> MailState | None:
        if mid not in mail_cache:
            try:
                name = state_names.mail(mid)
                mail_cache[mid] = store.cached(name, MailState, _snapshot, listing.get(name))
            except Exception:
                mail_cache[mid] = None
        return mail_cache[mid]

    # 1. Stored proposal states
    for name in store.names(state_names.PROPOSAL_PREFIX):
        suffix = name.removeprefix(state_names.PROPOSAL_PREFIX)
        if "-v" in suffix and suffix.rsplit("-v", 1)[1].isdigit():
            continue
        try:
            proposal = store.cached(name, Proposal, _snapshot, listing.get(name))
        except Exception:
            continue
        if not proposal:
            continue
        is_accepted = proposal.status in ACCEPTED_STATUSES
        is_rejected = proposal.status == ProposalStatus.REJECTED
        is_removed = proposal.status == ProposalStatus.REMOVED
        if not (is_accepted or is_rejected or is_removed):
            continue

        mail_id = proposal.source_mail_id
        prop_id = proposal.id
        seen.add((mail_id, prop_id))

        mail = get_mail(mail_id)
        decided_at = now
        sender = "Absender entfernt"
        topics: list[str] = []
        if mail is not None:
            decided_at = mail.updated_at or mail.created_at or now
            if mail.display_headers and mail.display_headers.sender:
                sender = mail.display_headers.sender
            elif mail.mail and isinstance(mail.mail.get("headers"), dict):
                sender = mail.mail["headers"].get("from") or mail.mail["headers"].get("sender") or sender
            if mail.relevance and mail.relevance.topic_ids:
                topics = list(mail.relevance.topic_ids)

        if cutoff is not None and decided_at < cutoff:
            continue

        reject_reason = getattr(proposal, "reject_reason", None)
        if reject_reason is None and proposal.resolution == "already_done":
            reject_reason = "already_done"

        kind_str = "event" if proposal.kind == ProposalKind.EVENT else "task"
        results.append(DecidedProposalRecord(
            mail_id=mail_id,
            proposal_id=prop_id,
            kind=kind_str,
            is_accepted=is_accepted,
            is_rejected=is_rejected,
            is_removed=is_removed,
            status=proposal.status.value,
            resolution=proposal.resolution,
            sender=sender,
            topics=topics,
            decided_at=decided_at,
            reject_reason=reject_reason,
        ))

    # 2. decisions.jsonl for decisions whose proposal states were removed by retention
    log_path = learning_path(store.directory)
    for record in _read(log_path):
        record_mail_id = record.get("mail_id")
        record_prop_id = record.get("proposal_id")
        if not record_mail_id or not record_prop_id:
            continue
        if (record_mail_id, record_prop_id) in seen:
            continue

        recorded_at = _parse_iso(record.get("recorded_at"))
        if recorded_at is None:
            continue
        if cutoff is not None and recorded_at < cutoff:
            continue

        kind_val = record.get("kind")
        is_accepted = kind_val in {"confirm", "confirm_duplicate", "merge_proposals", "already_done"}
        is_rejected = kind_val == "reject"
        is_removed = kind_val == "remove"
        if not (is_accepted or is_rejected or is_removed):
            continue

        seen.add((record_mail_id, record_prop_id))

        decided_obj = (record.get("proposal") or {}).get("decided") or {}
        original_obj = (record.get("proposal") or {}).get("original") or {}
        prop_kind = decided_obj.get("kind") or original_obj.get("kind") or "task"

        sender = (record.get("mail") or {}).get("headers", {}).get("sender") or "Absender entfernt"
        topics = (record.get("analysis") or {}).get("relevance", {}).get("topic_ids") or []
        reject_reason = record.get("reject_reason")
        if reject_reason is None and kind_val == "already_done":
            reject_reason = "already_done"

        results.append(DecidedProposalRecord(
            mail_id=record_mail_id,
            proposal_id=record_prop_id,
            kind=prop_kind,
            is_accepted=is_accepted,
            is_rejected=is_rejected,
            is_removed=is_removed,
            status="removed" if is_removed else "rejected" if is_rejected else "created",
            resolution="already_done" if kind_val == "already_done" else None,
            sender=sender,
            topics=list(topics),
            decided_at=recorded_at,
            reject_reason=reject_reason,
        ))

    return results


def evaluate_proposals(
    store: JsonStore,
    days: int = 0,
    now: datetime | None = None,
    topics_map: dict[str, str] | None = None,
) -> ProposalEvaluationReport:
    """Evaluate decided proposals and generate the evaluation report."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days) if days > 0 else None
    proposals = collect_decided_proposals(store, cutoff, now=now)

    # 1. Summary
    total_decided = len(proposals)
    total_accepted = sum(1 for p in proposals if p.is_accepted)
    total_rejected = sum(1 for p in proposals if p.is_rejected)
    total_removed = sum(1 for p in proposals if p.is_removed)
    total_quote = (total_accepted / total_decided * 100) if total_decided else 0.0

    tasks = [p for p in proposals if p.kind == "task"]
    tasks_decided = len(tasks)
    tasks_accepted = sum(1 for p in tasks if p.is_accepted)
    tasks_rejected = sum(1 for p in tasks if p.is_rejected)
    tasks_removed = sum(1 for p in tasks if p.is_removed)
    tasks_quote = (tasks_accepted / tasks_decided * 100) if tasks_decided else 0.0

    events = [p for p in proposals if p.kind == "event"]
    events_decided = len(events)
    events_accepted = sum(1 for p in events if p.is_accepted)
    events_rejected = sum(1 for p in events if p.is_rejected)
    events_removed = sum(1 for p in events if p.is_removed)
    events_quote = (events_accepted / events_decided * 100) if events_decided else 0.0

    summary = ProposalEvaluationSummary(
        total_decided=total_decided,
        total_accepted=total_accepted,
        total_rejected=total_rejected,
        total_removed=total_removed,
        total_quote=total_quote,
        tasks_decided=tasks_decided,
        tasks_accepted=tasks_accepted,
        tasks_rejected=tasks_rejected,
        tasks_removed=tasks_removed,
        tasks_quote=tasks_quote,
        events_decided=events_decided,
        events_accepted=events_accepted,
        events_rejected=events_rejected,
        events_removed=events_removed,
        events_quote=events_quote,
    )

    # 2. Weekly breakdown
    weekly_groups: dict[str, tuple[str, list[DecidedProposalRecord]]] = {}
    for p in proposals:
        year, week, _ = p.decided_at.isocalendar()
        key = f"{year}-W{week:02d}"
        label = f"KW {week:02d}/{year}"
        weekly_groups.setdefault(key, (label, []))[1].append(p)

    weeks: list[WeeklyEvaluation] = []
    for key in sorted(weekly_groups, reverse=True):
        label, items = weekly_groups[key]
        dec = len(items)
        acc = sum(1 for item in items if item.is_accepted)
        rej = sum(1 for item in items if item.is_rejected)
        rem = sum(1 for item in items if item.is_removed)
        weeks.append(WeeklyEvaluation(
            week_key=key,
            week_label=label,
            decided=dec,
            accepted=acc,
            rejected=rej,
            removed=rem,
            quote=(acc / dec * 100) if dec else 0.0,
        ))

    # 3. Topic breakdown
    topics_map = topics_map or {}
    topic_groups: dict[str, list[DecidedProposalRecord]] = {}
    for p in proposals:
        if not p.topics:
            topic_groups.setdefault("ohne_thema", []).append(p)
        else:
            for tid in p.topics:
                topic_groups.setdefault(tid, []).append(p)

    topics: list[TopicEvaluation] = []
    for tid, items in topic_groups.items():
        dec = len(items)
        acc = sum(1 for item in items if item.is_accepted)
        rej = sum(1 for item in items if item.is_rejected)
        name = "Ohne Thema" if tid == "ohne_thema" else topics_map.get(tid, tid)
        topics.append(TopicEvaluation(
            topic_id=tid,
            topic_name=name,
            decided=dec,
            accepted=acc,
            rejected=rej,
            quote=(acc / dec * 100) if dec else 0.0,
        ))
    topics.sort(key=lambda t: (t.decided, t.quote), reverse=True)

    # 4. Sender breakdown
    sender_groups: dict[str, list[DecidedProposalRecord]] = {}
    for p in proposals:
        sender_groups.setdefault(p.sender, []).append(p)

    senders: list[SenderEvaluation] = []
    for sender, items in sender_groups.items():
        dec = len(items)
        acc = sum(1 for item in items if item.is_accepted)
        rej = sum(1 for item in items if item.is_rejected)
        senders.append(SenderEvaluation(
            sender=sender,
            decided=dec,
            accepted=acc,
            rejected=rej,
            quote=(acc / dec * 100) if dec else 0.0,
        ))
    senders.sort(key=lambda s: (s.rejected, s.decided), reverse=True)

    # 5. Reject reasons breakdown
    reason_counts: dict[str, int] = {}
    for p in proposals:
        if p.is_rejected:
            key = p.reject_reason or "unspecified"
            reason_counts[key] = reason_counts.get(key, 0) + 1

    reasons: list[RejectReasonCount] = []
    for key, count in sorted(reason_counts.items(), key=lambda pair: pair[1], reverse=True):
        label = "Ohne Angabe" if key == "unspecified" else REJECT_REASONS.get(key, key)
        pct = (count / total_rejected * 100) if total_rejected else 0.0
        reasons.append(RejectReasonCount(
            reason_key=key,
            reason_label=label,
            count=count,
            percentage=pct,
        ))

    return ProposalEvaluationReport(
        days=days,
        summary=summary,
        weeks=weeks,
        topics=topics,
        senders=senders,
        reasons=reasons,
    )


DISMISSED_SENDER_HINTS = "dismissed-sender-hints"
LEARNING_RUN_HINT_STATE = "learning-run-hint-state"


@dataclass
class SenderHint:
    sender: str
    total: int
    accepted: int
    rejected: int
    acceptance_rate: float
    most_frequent_reason: str | None
    recommended_action: str  # "filter" or "rule_learning"
    trigger_sentence: str


def list_dismissed_sender_hints(store: JsonStore) -> list[str]:
    data = store.load(DISMISSED_SENDER_HINTS)
    if isinstance(data, dict) and isinstance(data.get("senders"), list):
        return [str(s) for s in data["senders"]]
    return []


def dismiss_sender_hint(store: JsonStore, sender: str) -> None:
    with store.locked():
        current = list_dismissed_sender_hints(store)
        if sender not in current:
            store.save(DISMISSED_SENDER_HINTS, {"senders": [*current, sender]})


def restore_sender_hint(store: JsonStore, sender: str) -> None:
    with store.locked():
        current = list_dismissed_sender_hints(store)
        if sender in current:
            store.save(DISMISSED_SENDER_HINTS, {"senders": [s for s in current if s != sender]})


def sender_hints(store: JsonStore, configuration: Any = None, *, now: datetime | None = None,
                 days: int = 90, min_proposals: int = 5, max_acceptance_rate: float = 0.10,
                 enabled: bool = True) -> list[SenderHint]:
    """Identify senders with many rejections and few acceptances (Planung 6.5, E3, E4, 3.3)."""
    if not enabled:
        return []
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days) if days > 0 else None
    proposals = collect_decided_proposals(store, cutoff=cutoff, now=now)

    dismissed = set(list_dismissed_sender_hints(store))
    blocked: set[str] = set()
    if configuration is not None:
        try:
            blocked.update(configuration.blocked_senders().addresses)
        except Exception:
            pass
    raw_blocked = store.load("irrelevant-senders")
    if isinstance(raw_blocked, dict) and isinstance(raw_blocked.get("addresses"), list):
        blocked.update(raw_blocked["addresses"])


    sender_groups: dict[str, list[DecidedProposalRecord]] = {}
    for p in proposals:
        if p.sender and p.sender != "Absender entfernt":
            sender_groups.setdefault(p.sender, []).append(p)

    hints: list[SenderHint] = []
    for sender, items in sender_groups.items():
        addresses = sender_addresses(sender)
        # Skip if already blocked in irrelevant-senders
        if any(addr in blocked for addr in addresses):
            continue
        # Skip if dismissed
        if sender in dismissed or any(addr in dismissed for addr in addresses):
            continue

        total = len(items)
        if total < min_proposals:
            continue
        accepted = sum(1 for i in items if i.is_accepted)
        rejected = sum(1 for i in items if i.is_rejected)
        rate = (accepted / total) if total else 0.0
        if rate > max_acceptance_rate:
            continue

        # Count rejection reasons
        reason_counts: dict[str, int] = {}
        for i in items:
            if i.is_rejected and i.reject_reason and i.reject_reason != "already_done":
                reason_counts[i.reject_reason] = reason_counts.get(i.reject_reason, 0) + 1

        most_frequent = None
        if reason_counts:
            most_frequent = max(reason_counts.items(), key=lambda pair: pair[1])[0]

        # E4: advertising or not_for_me -> filter; else rule_learning
        action = "filter" if most_frequent in {"advertising", "not_for_me", None} else "rule_learning"
        sentence = f"Von diesem Absender hast du {rejected} von {total} Vorschlägen verworfen. Künftig aussortieren?"

        hints.append(SenderHint(
            sender=sender,
            total=total,
            accepted=accepted,
            rejected=rejected,
            acceptance_rate=rate,
            most_frequent_reason=most_frequent,
            recommended_action=action,
            trigger_sentence=sentence,
        ))

    hints.sort(key=lambda h: (h.rejected, h.total), reverse=True)
    return hints


def sender_hint_for_sender(store: JsonStore, sender: str, configuration: Any = None, *,
                           now: datetime | None = None, days: int = 90, min_proposals: int = 5,
                           max_acceptance_rate: float = 0.10,
                           request_cache: dict[tuple[int, int, float], list[SenderHint]] | None = None,
                           ) -> SenderHint | None:
    """Return a SenderHint for a specific sender if it exceeds the threshold."""
    options = (days, min_proposals, max_acceptance_rate)
    hints = request_cache.get(options) if request_cache is not None else None
    if hints is None:
        hints = sender_hints(store, configuration, now=now, days=days, min_proposals=min_proposals,
                             max_acceptance_rate=max_acceptance_rate)
        if request_cache is not None:
            request_cache[options] = hints
    target_addresses = sender_addresses(sender)
    for h in hints:
        if h.sender == sender or (target_addresses and sender_addresses(h.sender) & target_addresses):
            return h
    return None


def get_learning_run_hint(store: JsonStore, *, now: datetime | None = None,
                          enabled: bool = True, min_rejections: int = 20) -> str | None:
    """Check if a hint for a new rule learning run should be shown (Planung 6.5, E5, 3.4)."""
    if not enabled:
        return None
    now = now or datetime.now(UTC)
    state = store.load(LEARNING_RUN_HINT_STATE)
    if isinstance(state, dict):
        dismissed_until = _parse_iso(state.get("dismissed_until"))
        if dismissed_until and now < dismissed_until:
            return None

    history = store.load("rule-learning-history")
    known_ids: set[str] = set()
    if isinstance(history, dict) and isinstance(history.get("decision_ids"), list):
        known_ids = set(history["decision_ids"])

    log_path = learning_path(store.directory)
    new_rejections = sum(1 for r in _read(log_path)
                         if r.get("kind") == "reject" and r.get("id") not in known_ids)

    if new_rejections < min_rejections:
        return None
    return f"Seit dem letzten Regellauf liegen {new_rejections} neue Ablehnungen vor. Ein neuer Lernlauf kann deine Themenregeln verbessern."


def dismiss_learning_run_hint(store: JsonStore, *, now: datetime | None = None) -> None:
    """Dismiss the learning run hint for 7 days."""
    now = now or datetime.now(UTC)
    dismissed_until = (now + timedelta(days=7)).isoformat()
    store.save(LEARNING_RUN_HINT_STATE, {"dismissed_until": dismissed_until})
