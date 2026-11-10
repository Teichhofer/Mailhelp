"""5.1 (R4): compare a re-analysis with the mail's proposals and adopt it safely.

Adoption never authorizes a write. A proposal that is written, being written or
in an unclear write state keeps its external id, target binding, idempotency key
and write evidence; a rejected proposal stays rejected; a proposal the new run no
longer finds is kept. Only additional findings become new, unconfirmed proposals,
and only open proposals receive a new version. Every adoption names the analysis
round and the proposal versions it was shown; any change in between refuses it.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .. import state_names
from ..domain.mail import MailState, next_updated_at
from ..domain.processing import ProposalNotification
from ..domain.proposal import Proposal, ProposalStatus
from ..domain.reanalysis import ReanalysisJob, ReanalysisStatus
from ..persistence.proposals import ProposalRepository
from .reanalysis import ReanalysisJobs

OPEN = {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}
# The facts a person checks; a change in any of them is shown and needs a new version.
CONTENT_FIELDS = ("kind", "title", "description", "due", "start", "end", "all_day", "location",
                  "responsibility", "certainty", "classification", "open_questions")


class Change(StrEnum):
    UNCHANGED = "unchanged"
    NEW = "new"
    CHANGED = "changed"
    PROTECTED = "protected"
    REJECTED = "rejected"
    MISSING = "missing"


ADOPTED = {Change.NEW, Change.CHANGED}


@dataclass(frozen=True)
class Item:
    change: Change
    existing: Proposal | None
    candidate: Proposal | None
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comparison:
    job_id: str
    mail_id: str
    analysis_round: int
    items: tuple[Item, ...]
    # The versions of the mail's proposals the comparison was made against.
    versions: dict[str, int]

    @property
    def adoptable(self) -> bool:
        return any(item.change in ADOPTED for item in self.items)


class AdoptionRefused(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _words(proposal: Proposal) -> set[str]:
    return set(re.findall(r"\w{3,}", (proposal.base_title or proposal.title).casefold()))


def _similar(left: Proposal, right: Proposal) -> bool:
    """Same kind and largely the same title words: the same matter, possibly with changed details."""
    if left.kind != right.kind:
        return False
    a, b = _words(left), _words(right)
    return bool(a & b) and len(a & b) / len(a | b) >= 0.6


def _differences(existing: Proposal, candidate: Proposal) -> tuple[str, ...]:
    return tuple(name for name in CONTENT_FIELDS if getattr(existing, name) != getattr(candidate, name))


def compare(state: MailState, job: ReanalysisJob) -> Comparison:
    """Each candidate against the mail's proposals; nothing is changed."""
    remaining = [item for item in state.proposals if item.status != ProposalStatus.MERGED]
    items: list[Item] = []
    for candidate in job.proposals:
        match = next((item for item in remaining if item.id == candidate.id), None) or next(
            (item for item in remaining if _similar(item, candidate)), None)
        if match is None:
            items.append(Item(Change.NEW, None, candidate))
            continue
        remaining.remove(match)
        fields = _differences(match, candidate)
        if match.status == ProposalStatus.REJECTED or match.resolution is not None:
            change = Change.REJECTED
        elif not fields:
            change = Change.UNCHANGED
        elif match.status in OPEN:
            change = Change.CHANGED
        else:
            change = Change.PROTECTED
        items.append(Item(change, match, candidate, fields))
    items.extend(Item(Change.MISSING, item, None) for item in remaining)
    return Comparison(job.id, job.mail_id, job.source_round, tuple(items),
                      {item.id: item.version for item in state.proposals})


class ReanalysisAdoption:
    """Adopts a completed re-analysis once, after checking round and versions again."""

    def __init__(self, jobs: ReanalysisJobs, engine: Any, send_proposal: Callable[[Proposal], None],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.jobs, self.engine, self.send_proposal, self.clock = jobs, engine, send_proposal, clock
        self.repository = ProposalRepository(jobs.store)

    def comparison(self, job_id: str) -> Comparison | None:
        job = self.jobs.get(job_id)
        state = self.repository.load_mail(job.mail_id) if job is not None else None
        if job is None or state is None or job.status != ReanalysisStatus.COMPLETED:
            return None
        return compare(state, job)

    def adopt(self, job_id: str, *, expected_round: int, expected_versions: dict[str, int]) -> Comparison:
        with self.jobs.lock:
            job = self.jobs.get(job_id)
            if job is None or job.status != ReanalysisStatus.COMPLETED:
                raise AdoptionRefused("not_completed")
            if job.adopted_at is not None:
                raise AdoptionRefused("already_adopted")
            state = self.repository.load_mail(job.mail_id)
            if state is None:
                raise AdoptionRefused("mail_missing")
            if expected_round != state.analysis_round or job.source_round != state.analysis_round:
                raise AdoptionRefused("stale")
            comparison = compare(state, job)
            if comparison.versions != expected_versions:
                raise AdoptionRefused("stale")
            changed = [self._revise(item) for item in comparison.items if item.change == Change.CHANGED]
            added = self._add(state, [item.candidate for item in comparison.items
                                      if item.change == Change.NEW and item.candidate is not None])
            job.adopted_at = self.clock()
            self.jobs.save(job)
        for proposal in changed + added:
            self.send_proposal(proposal)
        self.jobs.logger.event("INFO", "reanalysis", "reanalysis_adopted", job_id=job.id, mail_id=job.mail_id,
                               added=[item.id for item in added], revised=[item.id for item in changed])
        return comparison

    def _revise(self, item: Item) -> Proposal:
        """A new version of an open proposal; no earlier confirmation carries over."""
        assert item.existing is not None and item.candidate is not None
        revised = item.existing.model_copy(update={
            **{name: getattr(item.candidate, name) for name in CONTENT_FIELDS},
            "evidence": item.candidate.evidence, "version": item.existing.version + 1,
            "status": item.candidate.status, "confirmed_web_actor": None})
        revised = Proposal.model_validate(revised.model_dump(mode="json"))
        self.repository.save_revision(revised)
        return revised

    def _add(self, state: MailState, candidates: list[Proposal]) -> list[Proposal]:
        """Additional findings as new, unconfirmed proposals of the mail, checked like any new proposal."""
        if not candidates:
            return []
        limit = state.proposal_policy["max_semantic_candidates"] if state.proposal_policy is not None else None
        checked = [self.engine.precheck.check_proposal(item, mail_context=state.mail) for item in candidates]
        reconciled = [self.engine.reconciliation.reconcile(item, limit) for item in checked]
        added = [self.engine.reconciliation.required(item.source_mail_id, item.id) for item in reconciled]
        current = self.repository.load_mail(state.id)
        assert current is not None  # loaded under the jobs lock a moment ago
        notifications = [ProposalNotification(
            proposal_id=item.id, proposal_version=item.version,
            status="completed" if item.status in {ProposalStatus.ALREADY_EXISTS, ProposalStatus.MERGED}
            else "pending") for item in added]
        updated = current.model_copy(update={
            "proposals": current.proposals + added,
            "proposal_notifications": current.proposal_notifications + notifications,
            "updated_at": next_updated_at(current)})
        self.jobs.store.save(state_names.mail(state.id), updated.model_dump(mode="json"))
        return [item for item in added if item.status not in {ProposalStatus.ALREADY_EXISTS, ProposalStatus.MERGED}]
