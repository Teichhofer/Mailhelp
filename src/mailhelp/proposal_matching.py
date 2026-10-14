"""Bounded candidate retrieval from authoritative records, including partial times."""
import hashlib
import re
from datetime import date, datetime

from .domain.proposal import Proposal
from .domain.proposal_sources import ProposalSource
from .models import MailState
from .storage import JsonStore


def reference_key(proposal: Proposal):
    return proposal.source_mail_id, proposal.id


def source_reference(store: JsonStore, proposal: Proposal) -> ProposalSource:
    state = store.peek_model(f"mail-{proposal.source_mail_id}", MailState)
    mail = state.prepared if state is not None else None
    if mail is None:
        return ProposalSource(mail_id=proposal.source_mail_id, proposal_id=proposal.id)
    headers = mail.headers
    anchors = re.findall(r"<[^<>\s]{1,500}>", " ".join((headers.message_id, headers.references,
                         headers.in_reply_to)))[:100]
    return ProposalSource(mail_id=proposal.source_mail_id, proposal_id=proposal.id,
        sent_at=mail.received, subject=re.sub(r"^(?:(?:aw|re|fw|fwd|wg|extern)\s*:\s*)+", "",
                                            headers.subject.casefold())[:500],
        anchors=[hashlib.sha256(value.encode()).hexdigest() for value in dict.fromkeys(anchors)])


def sources(store: JsonStore, proposal: Proposal) -> list[ProposalSource]:
    return proposal.sources or [source_reference(store, proposal)]


def day(proposal: Proposal) -> date | None:
    value = proposal.start or proposal.due
    if value is None and proposal.known_temporal_facts is not None:
        value = proposal.known_temporal_facts.start or proposal.known_temporal_facts.date
    if value is None and proposal.temporal_fact is not None:
        value = proposal.temporal_fact.normalized_date
    return value.date() if isinstance(value, datetime) else value


def same_thread(left: list[ProposalSource], right: list[ProposalSource]) -> bool:
    return any(set(a.anchors) & set(b.anchors) and a.subject == b.subject for a in left for b in right)


def compatible(left: Proposal, right: Proposal) -> bool:
    return (reference_key(left) != reference_key(right) and left.kind == right.kind
            and left.target == right.target and (not left.target_provider or not right.target_provider
                                               or left.target_provider == right.target_provider)
            and reference_key(left) not in {(r.mail_id, r.proposal_id) for r in right.separated_from}
            and reference_key(right) not in {(r.mail_id, r.proposal_id) for r in left.separated_from})


def relationship(store: JsonStore, incoming: Proposal, previous: Proposal) -> str:
    """A thread identifies a conversation, never all events or actions in it."""
    thread = same_thread(sources(store, incoming), sources(store, previous))
    exact = incoming.title.casefold().strip() == previous.title.casefold().strip()
    dates = day(incoming), day(previous)
    if all(dates) and dates[0] != dates[1] and incoming.classification != "change":
        return "different"
    if incoming.kind == "task":
        return "same" if thread and exact else "possible" if thread else "different"
    generic = {"termin", "videokonferenz", "besprechung", "konferenz", "treffen", "austausch",
               "kurze", "skype", "online", "meeting", "sitzung", "klasse", "raum",
               "und", "der", "die", "das", "zur", "zum", "mit", "bei", "von", "am", "an", "um", "in"}
    left, right = [set(re.findall(r"\w{2,}", p.title.casefold())) - generic for p in (incoming, previous)]
    purpose = bool(left & right) and len(left & right) / len(left | right) >= 0.6
    descriptions = [p.description.split("\n\nAbsender:", 1)[0].strip() for p in (incoming, previous)]
    same_purpose = purpose or bool((not left or not right) and descriptions[0]
                                  and descriptions[0] == descriptions[1])
    starts = [p.start or (p.known_temporal_facts.start if p.known_temporal_facts else None)
              for p in (incoming, previous)]
    if thread and all(starts) and starts[0] != starts[1] and incoming.classification != "change":
        return "possible"
    if thread and same_purpose and dates[0] is not None and dates[0] == dates[1]:
        return "same"
    if thread or exact and dates[0] is not None and dates[0] == dates[1]:
        return "possible"
    return "different"
