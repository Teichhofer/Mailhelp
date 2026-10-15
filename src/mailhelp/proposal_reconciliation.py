"""Restart-safe local reconciliation before any decision notification or external write."""
import hashlib
import json
import re

from .domain.proposal import Proposal, ProposalStatus, invalidate_creation_permissions, required_revision_questions
from .domain.proposal_sources import ProposalMatchDecision, ProposalReference, ProposalRelation
from .domain.reconciliation import ProposalMatchCache, ProposalMergeJournal
from .persistence.proposals import ProposalRepository
from .proposal_matching import compatible, reference_key, relationship, same_thread, sources
from .proposal_merge import merge_facts
from .storage import JsonStore

OPEN = {ProposalStatus.NEEDS_CLARIFICATION, ProposalStatus.PENDING_CONFIRMATION}
PROTECTED = {ProposalStatus.CONFIRMED, ProposalStatus.WRITING, ProposalStatus.UNCERTAIN, ProposalStatus.FAILED}


class ProposalReconciliationService:
    def __init__(self, store: JsonStore, matcher=None, max_candidates=8, policy=""):
        self.store, self.matcher, self.max_candidates = store, matcher, max_candidates
        self.policy = policy
        self.repository = ProposalRepository(store)

    def compare(self, proposal, candidates):
        payload = [self.policy, proposal.model_dump(mode="json"),
                   [p.model_dump(mode="json") for p in candidates]]
        key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        name = f"reconciliation-cache-{key}"
        cached = self.store.load_model(name, ProposalMatchCache)
        if cached is None:
            call, raw = self.matcher(proposal, candidates)
            cached = ProposalMatchCache(call_id=call, decision=ProposalMatchDecision.model_validate(raw))
            if cached.decision.candidate is not None and cached.decision.candidate >= len(candidates):
                raise ValueError("Ungültiger Abgleichindex")
            self.store.save(name, cached.model_dump(mode="json"))
        return cached.decision

    def current(self) -> list[Proposal]:
        result = []
        for name in self.store.names("proposal-"):
            if re.search(r"-v[1-9][0-9]*$", name):
                continue
            proposal = self.store.peek_model(name, Proposal)
            if proposal is None:
                raise ValueError("Vorschlagsbestand geändert; erneut prüfen")
            result.append(proposal)
        return result

    def required(self, mail_id, proposal_id) -> Proposal:
        proposal = self.repository.load_current(mail_id, proposal_id)
        if proposal is None:
            raise ValueError("Vorschlag fehlt; erneut prüfen")
        return proposal

    def target_facts(self, proposal: Proposal) -> Proposal:
        protected = proposal.protected_fields
        if not proposal.sources:
            # Legacy provenance cannot establish which values a human edited.
            # Preserve all existing facts and expose contradictions for review.
            fields = ("start", "end", "due", "known_temporal_facts", "location", "video_link", "description")
            protected = list(dict.fromkeys([*protected, *[f for f in fields if getattr(proposal, f)]]))
        return proposal.model_copy(update={"sources": sources(self.store, proposal), "protected_fields": protected})

    def _snapshot(self, proposal):
        return sorted((p.source_mail_id, p.id, p.version, p.status) for p in self.current()
                      if compatible(proposal, p) and p.status in OPEN | PROTECTED
                      and relationship(self.store, proposal, p) != "different")

    def recover(self) -> None:
        with self.store.locked():
            for name in self.store.names("reconciliation-merge-"):
                journal = self.store.load_model(name, ProposalMergeJournal)
                if journal is None:
                    raise ValueError("Abgleichjournal fehlt")
                if journal.status == "prepared":
                    self._finish(name, journal)

    def _finish(self, name: str, journal: ProposalMergeJournal) -> None:
        assert journal.revision is not None and journal.alias is not None
        target = self.repository.load_current(journal.target.mail_id, journal.target.proposal_id)
        source = self.repository.load_current(journal.source.mail_id, journal.source.proposal_id)
        if source is not None and source.version not in {journal.source_version, journal.alias.version}:
            raise ValueError("Abgleichquelle wurde inzwischen geändert")
        if source is not None and source.version == journal.source_version and source.status not in OPEN | {
                ProposalStatus.MERGED}:
            raise ValueError("Abgleichquelle ist inzwischen entschieden")
        if source is not None and source.version == journal.alias.version and source != journal.alias:
            raise ValueError("Abgleichquelle stimmt nicht mit der gespeicherten Revision überein")
        if target is None or target.version not in {journal.target_version, journal.revision.version}:
            raise ValueError("Abgleichziel wurde inzwischen geändert")
        if target.status not in OPEN:
            raise ValueError("Abgleichziel ist nicht mehr offen")
        if target.version == journal.revision.version and target != journal.revision:
            raise ValueError("Abgleichziel stimmt nicht mit der gespeicherten Revision überein")
        self.repository.save_revision(journal.revision)
        self.repository.save_revision(journal.alias)
        journal.status, journal.revision, journal.alias = "completed", None, None
        self.store.save(name, journal.model_dump(mode="json"))

    def merge(self, incoming: Proposal, target: Proposal, *, uncertain=False, expected_revision=None) -> Proposal:
        with self.store.locked():
            if expected_revision is not None and self._snapshot(incoming) != expected_revision:
                raise ValueError("Abgleichstand wurde inzwischen geändert; erneut prüfen")
            latest = self.repository.load_current(target.source_mail_id, target.id)
            if latest is None or latest.version != target.version or latest.status not in OPEN:
                raise ValueError("Vorschlag inzwischen geändert oder in Ausführung")
            if not compatible(incoming, latest):
                raise ValueError("Art oder Ziel der Vorschläge unterscheiden sich")
            latest = self.target_facts(latest)
            revision = merge_facts(latest, incoming, uncertain=uncertain)
            alias = incoming.model_copy(update={"version": incoming.version + 1, "status": ProposalStatus.MERGED,
                "canonical_ref": ProposalReference(mail_id=latest.source_mail_id, proposal_id=latest.id),
                "merge_review_required": uncertain})
            alias = Proposal.model_validate(alias.model_dump())
            self._commit(incoming, latest, revision, alias)
            return alias

    def _commit(self, source, target, revision, alias):
        revision, alias = invalidate_creation_permissions(revision), invalidate_creation_permissions(alias)
        journal = ProposalMergeJournal(source=ProposalReference(mail_id=source.source_mail_id, proposal_id=source.id),
            target=ProposalReference(mail_id=target.source_mail_id, proposal_id=target.id),
            source_version=source.version, target_version=target.version, revision=revision, alias=alias,
            policy=self.policy)
        key = hashlib.sha256(json.dumps([reference_key(source), source.version,
                              reference_key(target), target.version, alias.status, self.policy]).encode()).hexdigest()
        name = f"reconciliation-merge-{key}"
        self.store.save(name, journal.model_dump(mode="json"))
        self._finish(name, journal)

    def manual(self, source: Proposal, target: Proposal, *, separate=False) -> Proposal:
        with self.store.locked():
            self.recover()
            actual = self.required(source.source_mail_id, source.id)
            latest = self.required(target.source_mail_id, target.id)
            target_ref = ProposalReference(mail_id=latest.source_mail_id, proposal_id=latest.id)
            if (separate and latest.status not in OPEN and target_ref in actual.matching_candidates
                    and actual.status in OPEN and actual.version == source.version
                    and latest.version == target.version):
                independent = actual.model_copy(update={"version": actual.version + 1,
                    "matching_candidates": [r for r in actual.matching_candidates if r != target_ref],
                    "separated_from": [*actual.separated_from, target_ref]})
                independent = invalidate_creation_permissions(independent)
                questions = required_revision_questions(independent)
                independent = Proposal.model_validate(independent.model_copy(update={"open_questions": questions,
                    "status": ProposalStatus.NEEDS_CLARIFICATION if questions else
                              ProposalStatus.PENDING_CONFIRMATION}).model_dump())
                self.repository.save_revision(independent)
                return independent
            if actual.version != source.version or latest.version != target.version or latest.status not in OPEN:
                raise ValueError("Zuordnungsversion wurde inzwischen geändert")
            if not compatible(source, latest):
                raise ValueError("Art oder Ziel der Vorschläge unterscheiden sich")
            source = source.model_copy(update={"sources": sources(self.store, source)})
            latest = self.target_facts(latest)
            ref = ProposalReference(mail_id=source.source_mail_id, proposal_id=source.id)
            pending = ref in latest.pending_sources
            if source.status not in OPEN and not (source.status == ProposalStatus.MERGED and
                    source.merge_review_required and pending):
                raise ValueError("Quelle ist bereits entschieden oder zugeordnet")
            questions = [q for q in latest.open_questions if q != "Zuordnung der zusätzlichen Quelle prüfen."]
            remaining = [r for r in latest.pending_sources if r != ref]
            matches = [r for r in latest.matching_candidates if r != ref]
            if not matches:
                questions = [q for q in questions if q !=
                    "Zuordnung zu bestehenden Entscheidungen prüfen; keine Neuanlage freigegeben."]
            base = latest.model_copy(update={"pending_sources": remaining, "matching_candidates": matches,
                                            "open_questions": questions})
            if separate:
                if not pending and target_ref not in source.matching_candidates:
                    raise ValueError("Nur ungeprüfte Zusätze können getrennt werden")
                own = [(s.mail_id, s.proposal_id) for s in source.sources]
                base = base.model_copy(update={"sources": [s for s in base.sources
                    if (s.mail_id, s.proposal_id) not in own], "separated_from": [*base.separated_from, ref]})
                questions = list(dict.fromkeys([*questions, *required_revision_questions(base)]))
                revision = base.model_copy(update={"version": latest.version + 1, "open_questions": questions,
                    "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION})
                alias = source.model_copy(update={"version": source.version + 1, "canonical_ref": None,
                    "merge_review_required": False, "separated_from": [*source.separated_from,
                       target_ref], "matching_candidates": [r for r in source.matching_candidates if r != target_ref]})
                questions = required_revision_questions(alias)
                alias = alias.model_copy(update={"open_questions": questions,
                    "status": ProposalStatus.NEEDS_CLARIFICATION if questions else ProposalStatus.PENDING_CONFIRMATION})
                alias = Proposal.model_validate(alias.model_dump())
                self._commit(source, latest, Proposal.model_validate(revision.model_dump()), alias)
                return alias
            clean = source.model_copy(update={"canonical_ref": None, "matching_candidates": [],
                "merge_review_required": False, "status": ProposalStatus.NEEDS_CLARIFICATION})
            if not latest.target_provider and source.target_provider:
                base = base.model_copy(update={"target_provider": source.target_provider})
            revision = merge_facts(base, clean)
            if revision.version == latest.version:
                revision = revision.model_copy(update={"version": latest.version + 1})
            alias = source.model_copy(update={"version": source.version + 1, "status": ProposalStatus.MERGED,
                "canonical_ref": ProposalReference(mail_id=latest.source_mail_id, proposal_id=latest.id),
                "merge_review_required": False, "matching_candidates": []})
            self._commit(source, latest, revision, Proposal.model_validate(alias.model_dump()))
            return alias

    def reconcile(self, proposal: Proposal, max_candidates=None) -> Proposal:
        self.recover()
        with self.store.locked():
            prior = self.repository.load_current(proposal.source_mail_id, proposal.id)
            if prior is not None:
                return prior
            proposal = proposal.model_copy(update={"sources": sources(self.store, proposal)})
            candidates = [item for item in self.current() if compatible(proposal, item)
                          and item.status in OPEN | PROTECTED
                          and relationship(self.store, proposal, item) != "different"]
            strong = [item for item in candidates if relationship(self.store, proposal, item) == "same"]
            revision = self._snapshot(proposal)
        limit = self.max_candidates if max_candidates is None else max_candidates
        chosen: Proposal | None
        if proposal.status not in OPEN:
            return self.save(proposal)
        if len(strong) == 1 and len(candidates) == 1:
            chosen = strong[0]
            uncertain = False
        elif candidates and len(candidates) <= limit and self.matcher is not None:
            try:
                decision = self.compare(proposal, candidates)
                chosen = candidates[decision.candidate] if decision.candidate is not None else None
                if decision.relation == "different":
                    return self.save(proposal, revision)
                if decision.relation == "related_action" and chosen is not None:
                    with self.store.locked():
                        if self._snapshot(proposal) != revision:
                            raise ValueError("Abgleichstand geändert")
                        self.relate(proposal, chosen, "related")
                        return self.save(proposal, revision)
                uncertain = decision.relation != "same_occurrence"
            except (ValueError, IndexError, RuntimeError):
                chosen, uncertain = None, True
        else:
            chosen = (candidates[0] if len(candidates) == 1 and
                      same_thread(sources(self.store, proposal), sources(self.store, candidates[0])) else None)
            uncertain = True
        if chosen is not None and chosen.status in OPEN:
            uncertain = uncertain or chosen.target_provider != proposal.target_provider
            return self.merge(proposal, chosen, uncertain=uncertain, expected_revision=revision)
        if candidates:
            proposal = proposal.model_copy(update={"status": ProposalStatus.NEEDS_CLARIFICATION,
                "matching_candidates": [ProposalReference(mail_id=p.source_mail_id, proposal_id=p.id)
                                        for p in candidates[:50]],
                "open_questions": list(dict.fromkeys([*proposal.open_questions,
                                   "Zuordnung zu bestehenden Entscheidungen prüfen; keine Neuanlage freigegeben."]))})
        return self.save(proposal, revision)

    def save(self, proposal: Proposal, expected_revision=None) -> Proposal:
        with self.store.locked():
            if expected_revision is not None and self._snapshot(proposal) != expected_revision:
                raise ValueError("Abgleichstand wurde inzwischen geändert; erneut prüfen")
            prior = self.repository.load_current(proposal.source_mail_id, proposal.id)
            if prior is not None:
                return prior
            self.repository.save_revision(proposal)
        return proposal

    def confirmation_candidates(self, proposal: Proposal) -> list[ProposalReference]:
        with self.store.locked():
            return [ProposalReference(mail_id=p.source_mail_id, proposal_id=p.id) for p in self.current()
                    if p.status in OPEN | PROTECTED and compatible(proposal, p)
                    and relationship(self.store, proposal, p) != "different"][:50]

    def resolve(self, reference: ProposalReference) -> Proposal | None:
        seen: set[tuple[str, str]] = set()
        while True:
            key = reference.mail_id, reference.proposal_id
            if key in seen or len(seen) >= 50:
                raise ValueError("Ungültige kanonische Referenzkette")
            seen.add(key)
            proposal = self.store.peek_model(f"proposal-{key[0]}-{key[1]}", Proposal)
            if proposal is None or proposal.canonical_ref is None:
                return proposal
            reference = proposal.canonical_ref

    def relate(self, source: Proposal, target: Proposal, kind="rsvp_for") -> None:
        relation = ProposalRelation(source=ProposalReference(mail_id=source.source_mail_id, proposal_id=source.id),
            target=ProposalReference(mail_id=target.source_mail_id, proposal_id=target.id), kind=kind)
        key = hashlib.sha256(json.dumps(relation.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        self.store.save(f"reconciliation-relation-{key}", relation.model_dump(mode="json"))
