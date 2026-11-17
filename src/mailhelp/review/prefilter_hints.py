"""7.7.5: suggested prefilter rules from stored decisions – read only, never a model call.

Two sources beside the sender hints of 6.5 (which look at rejected proposals):

* the relevance check: a sender whose recent mails the model always judged irrelevant, with no
  human answer to the contrary, is suggested for an ignore rule;
* confirmed proposals: a sender whose recent mails were all relevant and each led to at least one
  proposal the user confirmed is suggested as a VIP.

Senders covered by any rule (including an exception) and dismissed hints are never suggested. Two or
more suggested addresses of one domain also suggest the domain, never for large mail providers.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ..domain.mail import MailState
from ..domain.proposal import ProposalStatus
from ..domain.relevance import IrrelevantSenders
from ..mailbox.sender_filter import FREEMAIL, active_rules, rule_covers, sender_addresses
from ..persistence.storage import CorruptState, JsonStore
from ..state_names import MAIL_PREFIX, is_mail_state
from .explanation import RULE_PREFIXES, RULE_REASONS

# A confirmed proposal: written, being verified or – in test mode – simulated.
CONFIRMED = {ProposalStatus.CREATED, ProposalStatus.VERIFYING, ProposalStatus.SIMULATED}


@dataclass(frozen=True)
class PrefilterHint:
    action: Literal["ignore", "vip"]
    kind: Literal["address", "domain"]
    value: str
    count: int
    subjects: tuple[str, ...]


def _model_said_irrelevant(state: MailState) -> bool:
    relevance = state.relevance
    assert relevance is not None
    by_rule = relevance.reason in RULE_REASONS or relevance.reason.startswith(RULE_PREFIXES)
    human = state.relevance_dialog is not None and state.relevance_dialog.decision is not None
    return relevance.decision == "irrelevant" and state.prefilter_rule is None and not by_rule and not human


def _confirmed(state: MailState) -> bool:
    assert state.relevance is not None
    return state.relevance.decision == "relevant" and any(item.status in CONFIRMED for item in state.proposals)


def _recent(store: JsonStore, cutoff: datetime) -> dict[str, list[MailState]]:
    """Recent decided mails with exactly one readable sender, grouped by that address."""
    groups: dict[str, list[MailState]] = {}
    for name in store.names(MAIL_PREFIX):
        if not is_mail_state(name):
            continue
        try:
            state = store.peek_model(name, MailState)
        except CorruptState:
            continue
        if state is None or state.created_at < cutoff or state.relevance is None or state.display_headers is None:
            continue
        addresses = sender_addresses(state.display_headers.sender)
        if len(addresses) == 1:
            groups.setdefault(addresses.pop(), []).append(state)
    return groups


def prefilter_hints(store: JsonStore, blocked: IrrelevantSenders, now: datetime, *, days: int = 30,
                    irrelevant_mails: int = 3, vip_mails: int = 5, dismissed: Iterable[str] = (),
                    enabled: bool = True) -> list[PrefilterHint]:
    if not enabled:
        return []
    skipped = set(dismissed)
    rules = active_rules(blocked, 1) + [rule for number in blocked.mailboxes
                                        for rule in active_rules(blocked, int(number))]
    hints: list[PrefilterHint] = []
    for address, states in sorted(_recent(store, now - timedelta(days=days)).items()):
        if address in skipped or rule_covers(rules, address):
            continue
        subjects = tuple(state.display_headers.subject for state in states[:3] if state.display_headers)
        if len(states) >= irrelevant_mails and all(_model_said_irrelevant(state) for state in states):
            hints.append(PrefilterHint("ignore", "address", address, len(states), subjects))
        elif len(states) >= vip_mails and all(_confirmed(state) for state in states):
            hints.append(PrefilterHint("vip", "address", address, len(states), subjects))
    domains: dict[str, list[PrefilterHint]] = {}
    for hint in hints:
        if hint.action == "ignore":
            domains.setdefault(hint.value.rsplit("@", 1)[1], []).append(hint)
    for domain, items in sorted(domains.items()):
        if len(items) >= 2 and domain not in FREEMAIL and domain not in skipped:
            hints.append(PrefilterHint("ignore", "domain", domain, sum(item.count for item in items),
                                       tuple(subject for item in items for subject in item.subjects)[:3]))
    return sorted(hints, key=lambda hint: (-hint.count, hint.kind, hint.value))


__all__ = ["CONFIRMED", "PrefilterHint", "prefilter_hints"]
