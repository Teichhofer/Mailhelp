"""Identity, chronology, authorization invalidation and durable local merges."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal import Proposal, ProposalStatus
from mailhelp.domain.proposal_sources import ProposalReference, ProposalSource
from mailhelp.domain.reconciliation import ProposalMergeJournal
from mailhelp.proposal_matching import compatible, day, relationship, same_thread
from mailhelp.proposal_merge import merge_facts
from mailhelp.proposal_reconciliation import ProposalReconciliationService
from mailhelp.storage import JsonStore

NOW = datetime(2030, 11, 20, 14, tzinfo=UTC)


def candidate(number, **changes):
    return Proposal.model_validate({"id": f"p_{number}", "version": 1, "source_mail_id": f"{number:024x}",
        "kind": "event", "target": "calendar", "target_provider": "google", "title": "Fachbeirat", "description": "Sitzung",
        "evidence": "Synthetische Einladung", "responsibility": "user", "certainty": "certain",
        "classification": "new", "start": NOW, "end": NOW + timedelta(hours=1),
        "status": "pending_confirmation", "sources": [ProposalSource(mail_id=f"{number:024x}",
            proposal_id=f"p_{number}", sent_at=NOW + timedelta(days=number), subject="fachbeirat",
            anchors=["shared-thread"]).model_dump()], **changes})


def ref(p):
    return ProposalReference(mail_id=p.source_mail_id, proposal_id=p.id)


@pytest.fixture
def service(tmp_path):
    with JsonStore(tmp_path) as store:
        yield ProposalReconciliationService(store)


def test_chronology_adds_information_without_reverting_concrete_dates():
    current = candidate(2, title="Skype-Konferenz", location="Online")
    older = candidate(1, start=None, end=None, status="needs_clarification",
                      certainty="uncertain", open_questions=["Wann beginnt der Termin?"],
                      known_temporal_facts={"date": NOW.date()})
    revised = merge_facts(current, older)
    assert revised.start == current.start and revised.end == current.end
    assert revised.known_temporal_facts is None and revised.certainty == "certain"
    assert revised.version == 2 and revised.sources == [*current.sources, *older.sources]
    assert merge_facts(revised, older) == revised


def test_explicit_end_replaces_assumption_and_invalidates_confirmation():
    old = candidate(1, end_origin="standard", default_duration_minutes=60,
                    explicit_duplicate_create_confirmed_version=1)
    newer = candidate(2, end=NOW + timedelta(minutes=90), end_origin="mail_duration")
    merged = merge_facts(old, newer)
    assert merged.end == newer.end and merged.end_origin == "mail_duration"
    assert merged.default_duration_minutes is None
    assert merged.explicit_duplicate_create_confirmed_version is None


def test_protected_and_conflicting_fields_remain_reviewable():
    old = candidate(1, protected_fields=["location", "description"], location=None)
    new = candidate(2, start=NOW + timedelta(hours=2), end=NOW + timedelta(hours=3),
                    location="Raum 3", description="Neue Angaben")
    merged = merge_facts(old, new)
    assert merged.start == old.start and merged.location is None and merged.description == old.description
    assert any("start" in q for q in merged.open_questions)
    assert any("location" in q for q in merged.open_questions)
    assert any("Beschreibung" in q for q in merged.open_questions)
    changed = merge_facts(old, new.model_copy(update={"classification": "change"}))
    assert changed.start == new.start


def test_target_scope_thread_dates_and_explicit_separation(service):
    first, second = candidate(1), candidate(2)
    assert relationship(service.store, second, first) == "same"
    assert not compatible(first, first)
    assert not compatible(second.model_copy(update={"target": "other"}), first)
    assert not compatible(second.model_copy(update={"target_provider": "other"}), first)
    assert not compatible(second, first.model_copy(update={"separated_from": [ref(second)]}))
    assert not compatible(second.model_copy(update={"separated_from": [ref(first)]}), first)
    assert relationship(service.store, second.model_copy(update={"start": NOW + timedelta(days=1)}), first) == "different"
    partial = candidate(2, start=None, end=None, status="needs_clarification",
                        known_temporal_facts={"date": NOW.date()}, open_questions=["Wann beginnt der Termin?"])
    assert relationship(service.store, partial, first) == "same"
    assert day(second.model_copy(update={"start": None, "due": NOW.date()})) == NOW.date()
    assert day(second.model_copy(update={"start": None})) is None
    assert not same_thread(first.sources, [])
    task = candidate(3, kind="task", start=None, end=None)
    assert relationship(service.store, task, task.model_copy(update={"id": "other"})) == "same"
    assert relationship(service.store, task, task.model_copy(update={"id": "other", "title": "Andere Aufgabe"})) == "possible"
    assert relationship(service.store, task, task.model_copy(update={"id": "other", "sources": []})) == "different"


def test_merge_alias_resolves_and_repetition_preserves_human_revision(service):
    first, second = candidate(1), candidate(2, video_link="https://example.test/video")
    service.save(first)
    alias = service.reconcile(second)
    assert alias.status == "merged" and alias.canonical_ref == ref(first)
    assert not alias.is_creatable
    canonical = service.resolve(ref(alias))
    assert canonical.version == 2 and canonical.video_link == second.video_link
    assert service.reconcile(second) == alias
    assert service.current() == [canonical, alias]
    assert service.resolve(ProposalReference(mail_id="missing", proposal_id="missing")) is None


def test_unclear_source_can_be_verified_or_separated(service):
    first, second = candidate(1), candidate(2, start=None, end=None,
        status="needs_clarification", open_questions=["Wann beginnt der Termin?"])
    service.save(first)
    alias = service.reconcile(second)
    canonical = service.required(first.source_mail_id, first.id)
    assert canonical.pending_sources == [ref(second)] and not canonical.is_creatable
    assert alias.merge_review_required
    independent = service.manual(alias, canonical, separate=True)
    assert independent.canonical_ref is None and independent.version == 3
    assert not compatible(independent, service.required(first.source_mail_id, first.id))
    with pytest.raises(ValueError, match="Version|version"):
        service.manual(alias, service.required(first.source_mail_id, first.id))


def test_manual_verification_closes_identity_question(service):
    first, second = candidate(1), candidate(2)
    service.save(first)
    alias = service.merge(second, first, uncertain=True)
    canonical = service.required(first.source_mail_id, first.id)
    verified = service.manual(alias, canonical)
    assert not verified.merge_review_required
    assert not service.required(first.source_mail_id, first.id).pending_sources
    with pytest.raises(ValueError, match="bereits"):
        service.manual(verified, service.required(first.source_mail_id, first.id))


@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain", "failed"])
def test_decided_or_running_target_is_never_overwritten(service, status):
    first = candidate(1, status=status)
    service.save(first)
    result = service.reconcile(candidate(2))
    assert result.matching_candidates == [ref(first)] and not result.is_creatable
    assert service.required(first.source_mail_id, first.id) == first


def test_matching_limit_and_failed_semantics_block_new_creation(service):
    for n in (1, 2):
        service.save(candidate(n))
    calls = []
    service.matcher = lambda p, c: calls.append(p)
    blocked = service.reconcile(candidate(3), max_candidates=1)
    assert len(blocked.matching_candidates) == 2 and not calls
    def broken(p, c):
        raise RuntimeError("synthetic provider unavailable")
    service.matcher = broken
    blocked = service.reconcile(candidate(4))
    assert len(blocked.matching_candidates) == 3 and not blocked.is_creatable


@pytest.mark.parametrize("relation", ["same_occurrence", "unclear", "different", "related_action"])
def test_semantic_comparison_is_cached_and_version_bound(service, relation):
    first, second = candidate(1), candidate(2, sources=[])
    # Similar title and known day, without thread identity, invokes the matcher.
    second = second.model_copy(update={"start": NOW, "end": NOW + timedelta(hours=1)})
    service.save(first)
    calls = []
    def matcher(p, c):
        calls.append((p, c))
        return "synthetic-call", {"candidate": 0, "relation": relation, "reason": "Synthetic evidence"}
    service.matcher, service.policy = matcher, "prompt-policy-one"
    decision = service.compare(second, [first])
    assert service.compare(second, [first]) == decision and len(calls) == 1
    service.policy = "prompt-policy-two"
    service.compare(second, [first])
    assert len(calls) == 2
    result = service.reconcile(second)
    assert (result.status == "merged") == (relation in {"same_occurrence", "unclear"})
    if relation == "related_action":
        assert service.store.names("reconciliation-relation-")


def test_journal_recovers_after_target_written_before_alias(service, monkeypatch):
    first, second = candidate(1), candidate(2)
    service.save(first)
    original = service.repository.save_revision
    def fail_alias(p):
        if p.id == second.id:
            raise OSError("synthetic crash")
        original(p)
    monkeypatch.setattr(service.repository, "save_revision", fail_alias)
    with pytest.raises(OSError):
        service.merge(second, first)
    assert service.required(first.source_mail_id, first.id).version == 2
    restarted = ProposalReconciliationService(service.store)
    restarted.recover()
    restarted.recover()
    assert restarted.resolve(ref(second)).version == 2
    record = service.store.load(service.store.names("reconciliation-merge-")[0])
    assert record["status"] == "completed" and record["alias"] is None and record["revision"] is None


def test_merge_rechecks_candidates_after_semantic_network_call(service):
    first, second = candidate(1), candidate(2, sources=[])
    service.save(first)
    def matcher(p, c):
        service.save(candidate(3))
        return "call", {"candidate": 0, "relation": "same_occurrence", "reason": "Synthetic"}
    service.matcher = matcher
    with pytest.raises(ValueError, match="Abgleichstand"):
        service.reconcile(second)
    assert service.required(first.source_mail_id, first.id) == first


def test_schema_rejects_unbound_incomplete_or_self_merge():
    first, second = candidate(1), candidate(2)
    payload = dict(source=ref(second), target=ref(first), source_version=1, target_version=1)
    with pytest.raises(ValidationError, match="beide"):
        ProposalMergeJournal(**payload)
    with pytest.raises(ValidationError, match="unterschiedliche"):
        ProposalMergeJournal(**{**payload, "target": ref(second)})
    with pytest.raises(ValidationError, match="keine Inhalte"):
        ProposalMergeJournal(**payload, status="completed", alias=second)
    with pytest.raises(ValidationError, match="Version"):
        ProposalMergeJournal(**payload, alias=second, revision=first)
    with pytest.raises(ValidationError):
        candidate(1, status="merged")
    with pytest.raises(ValidationError):
        candidate(1, canonical_ref=ref(first))
    with pytest.raises(ValidationError, match="selbst"):
        candidate(1, canonical_ref=ref(first), status="merged")


@pytest.mark.parametrize("changed", ["source_version", "source_status", "source_revision", "target_revision",
                                      "target_missing", "target_version", "target_status"])
def test_pending_journal_refuses_changed_authoritative_records(service, changed):
    first, second = candidate(1), candidate(2)
    service.save(first)
    service.save(second)
    alias = second.model_copy(update={"version": 2, "status": ProposalStatus.MERGED, "canonical_ref": ref(first)})
    journal = ProposalMergeJournal(source=ref(second), target=ref(first), source_version=1, target_version=1,
                                  alias=alias, revision=merge_facts(first, second))
    if changed == "source_version":
        service.repository.save_revision(second.model_copy(update={"version": 9}))
    elif changed == "source_status":
        service.repository.save_revision(second.model_copy(update={"status": ProposalStatus.CONFIRMED}))
    elif changed == "source_revision":
        service.repository.save_revision(second.model_copy(update={"version": 2, "description": "Human revision"}))
    elif changed == "target_revision":
        service.repository.save_revision(first.model_copy(update={"version": 2, "description": "Human revision"}))
    elif changed == "target_missing":
        service.store.delete(f"proposal-{first.source_mail_id}-{first.id}")
    elif changed == "target_version":
        service.repository.save_revision(first.model_copy(update={"version": 9}))
    else:
        service.repository.save_revision(first.model_copy(update={"status": ProposalStatus.CONFIRMED}))
    service.store.save("reconciliation-merge-interrupted", journal.model_dump(mode="json"))
    with pytest.raises(ValueError, match="Abgleich"):
        service.recover()
    assert service.store.load("reconciliation-merge-interrupted")["status"] == "prepared"


def test_missing_records_are_not_treated_as_empty_candidate_set(service, monkeypatch):
    service.save(candidate(1))
    with pytest.raises(ValueError, match="fehlt"):
        service.required("missing", "missing")
    monkeypatch.setattr(service.store, "peek_model", lambda *a: None)
    with pytest.raises(ValueError, match="Bestand|bestand"):
        service.current()
    monkeypatch.setattr(service.store, "names", lambda prefix: ["reconciliation-merge-missing"])
    with pytest.raises(ValueError, match="journal"):
        service.recover()


@pytest.mark.parametrize("operation", ["merge", "manual"])
def test_local_merge_rejects_incompatible_target(service, operation):
    first, second = candidate(1), candidate(2, target="other-calendar")
    service.save(first)
    service.save(second)
    with pytest.raises(ValueError, match="Art oder Ziel"):
        getattr(service, operation)(second, first)


def test_target_version_or_status_changed_since_preview_blocks_merge(service):
    first, second = candidate(1), candidate(2)
    service.save(first.model_copy(update={"version": 2}))
    service.save(second)
    with pytest.raises(ValueError, match="inzwischen"):
        service.merge(second, first)
    with pytest.raises(ValueError, match="Zuordnungsversion"):
        service.manual(second, first, separate=True)


def test_separation_requires_pending_source_and_noop_manual_merge_still_has_new_version(service):
    first, second = candidate(1), candidate(2)
    first = first.model_copy(update={"sources": [*first.sources, *second.sources]})
    service.save(first)
    service.save(second)
    with pytest.raises(ValueError, match="ungeprüfte"):
        service.manual(second, first, separate=True)
    service.manual(second, first)
    assert service.required(first.source_mail_id, first.id).version == 2


def test_invalid_matching_index_and_nullable_result_never_authorize_creation(service):
    first, second = candidate(1), candidate(2, sources=[])
    service.save(first)
    service.matcher = lambda p, c: ("bad", {"candidate": 99, "relation": "same_occurrence", "reason": "Invalid"})
    assert service.reconcile(second).matching_candidates == [ref(first)]
    service.matcher = lambda p, c: ("none", {"candidate": None, "relation": "unclear", "reason": "Ambiguous"})
    assert not service.reconcile(candidate(3, sources=[])).is_creatable


def test_changed_candidates_after_negative_or_related_match_are_rechecked(service):
    first, second = candidate(1), candidate(2, sources=[])
    service.save(first)
    snapshot = service._snapshot(second)
    service.save(candidate(3))
    with pytest.raises(ValueError, match="Abgleichstand"):
        service.save(second, snapshot)
    service.matcher = lambda p, c: ("related", {"candidate": 0, "relation": "related_action", "reason": "Related"})
    original = service._snapshot
    counts = []
    def changed(p):
        counts.append(p)
        return original(p) if len(counts) == 1 else []
    service._snapshot = changed
    with pytest.raises(ValueError, match="Abgleichstand"):
        service.reconcile(second)


def test_day_can_be_retained_as_temporal_fact_and_no_thread_is_not_identity(service):
    partial = candidate(2, start=None, end=None, status="needs_clarification", open_questions=["Wann beginnt der Termin?"],
        temporal_fact={"status": "resolved", "normalized_date": NOW.date(), "year_source": "explicit_mail"})
    assert day(partial) == NOW.date()
    other = candidate(1, title="Andere Sitzung", sources=[])
    assert relationship(service.store, candidate(2, sources=[]), other) == "different"


def test_manual_partial_date_is_not_overridden_and_invalid_interval_becomes_conflict():
    first = candidate(1, start=None, end=None, status="needs_clarification", open_questions=["Wann beginnt der Termin?"],
                      known_temporal_facts={"date": NOW.date()}, protected_fields=["known_temporal_facts"])
    second = candidate(2, start=NOW + timedelta(days=1), end=NOW + timedelta(days=1, hours=1))
    result = merge_facts(first, second)
    assert result.start is None and result.known_temporal_facts == first.known_temporal_facts
    assert any("manuell" in q for q in result.open_questions)
    original = candidate(1)
    change = candidate(2, start=NOW + timedelta(hours=2), end=NOW + timedelta(hours=3), classification="change",
                       status="needs_clarification", open_questions=["Welcher bestehende Eintrag soll geändert werden?"])
    original = original.model_copy(update={"protected_fields": ["end"]})
    conflict = merge_facts(original, change)
    assert conflict.start == original.start and conflict.end == original.end
    assert any("Zeitintervall" in q for q in conflict.open_questions)


def test_analyzer_only_receives_bounded_comparison_fields_and_revisions_cannot_change_provenance():
    from shared_core import prompt_config

    from mailhelp.analysis import Analyzer, ContradictoryRevision, validate_revision_successor
    from mailhelp.config import PromptStep
    first, second = candidate(1), candidate(2)
    payloads = []
    class Provider:
        def complete(self, model, parameters, system, payload, **metadata):
            payloads.append(payload)
            return "call", {"candidate": 0, "relation": "same_occurrence", "reason": "Synthetic"}
    prompts = prompt_config()
    prompts.prompts["open_proposal_match"] = PromptStep(system_prompt="Compare synthetic proposals")
    call, result = Analyzer(Provider(), prompts).open_proposal_match(second, [first])
    assert call == "call" and result.candidate == 0
    assert "sources" not in payloads[0]["incoming"] and "target" not in payloads[0]["incoming"]
    with pytest.raises(ContradictoryRevision, match="Herkunft"):
        validate_revision_successor(first, first.model_copy(update={"version": 2, "meeting_mode": "video"}))


def test_new_concrete_agreement_replaces_nonbinding_classification_but_not_human_override():
    older = candidate(1, classification="non_binding", status="needs_clarification",
                      open_questions=["Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"])
    newer = candidate(2)
    result = merge_facts(older, newer)
    assert result.classification == "new" and result.status == "pending_confirmation"
    protected = older.model_copy(update={"protected_fields": ["classification"]})
    assert merge_facts(protected, newer).classification == "non_binding"
    partial = candidate(2, start=NOW + timedelta(hours=2), end=None,
                        status="needs_clarification", open_questions=["Wann endet der Termin?"])
    assert merge_facts(candidate(1), partial).start == NOW


def test_legacy_unknown_provider_and_values_require_explicit_local_verification(service):
    first, second = candidate(1, sources=[], target_provider=""), candidate(2)
    service.save(first)
    alias = service.reconcile(second)
    assert alias.matching_candidates == [ref(first)] and not alias.is_creatable
    current = service.required(first.source_mail_id, first.id)
    service.manual(alias, current)
    current = service.required(first.source_mail_id, first.id)
    assert current.target_provider == "google" and "start" in current.protected_fields


def test_multiple_unrelated_candidates_can_be_explicitly_kept_separate(service):
    first, second = candidate(1), candidate(2)
    service.save(first)
    service.save(second)
    third = service.reconcile(candidate(3))
    assert len(third.matching_candidates) == 2
    third = service.manual(third, first, separate=True)
    assert len(third.matching_candidates) == 1 and not third.is_creatable
    third = service.manual(third, second, separate=True)
    assert third.status == "pending_confirmation" and third.matching_candidates == []


def test_retention_keeps_unverified_alias_source_until_identity_is_resolved():
    from shared_retention import state

    from mailhelp.retention import RetentionService
    item = state("a" * 24)
    alias = item.proposals[0].model_copy(update={"status": ProposalStatus.MERGED,
        "canonical_ref": ProposalReference(mail_id="b" * 24, proposal_id="canonical"), "merge_review_required": True})
    item.proposals = [alias]
    assert RetentionService._protected(item)
    item.proposals = [alias.model_copy(update={"merge_review_required": False})]
    assert not RetentionService._protected(item)


def test_failed_incoming_external_check_protects_the_canonical_proposal():
    first, second = candidate(1), candidate(2, status="needs_clarification", duplicate_check_failed=True,
        open_questions=["Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen."])
    result = merge_facts(first, second)
    assert result.duplicate_check_failed and result.status == "needs_clarification" and not result.is_creatable


def test_older_different_facts_do_not_replace_the_later_agreement():
    first = candidate(2, location="Online")
    older = candidate(1, start=NOW - timedelta(hours=1), end=NOW, location="Raum 3")
    current = merge_facts(first, older)
    assert current.start == first.start and current.end == first.end and current.location == first.location


def test_repeated_save_cannot_replace_an_authoritative_human_version(service):
    first = candidate(1, version=3)
    service.save(first)
    assert service.save(first.model_copy(update={"version": 1, "description": "Old information"})) == first


@pytest.mark.parametrize("changes", [
    {"title": "Videokonferenz Finanzen", "description": "Budgetplanung"},
    {"title": "Elternabend Klasse 4a", "description": "Klassenfahrt"},
    {"start": NOW + timedelta(hours=2), "end": NOW + timedelta(hours=3)},
])
def test_a_thread_and_day_do_not_collapse_different_purposes_or_time_slots(service, changes):
    first = candidate(1, title="Videokonferenz Personal", description="Personalplanung")
    second = candidate(2, **changes)
    assert relationship(service.store, second, first) == "possible"
    service.save(first)
    alias = service.reconcile(second)
    assert alias.merge_review_required
    assert not service.required(first.source_mail_id, first.id).is_creatable


@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain", "created", "rejected"])
def test_a_blocked_candidate_can_be_kept_independent_after_its_target_closes(service, status):
    first, second = candidate(1, status="confirmed"), candidate(2)
    service.save(first)
    blocked = service.reconcile(second)
    decided = first.model_copy(update={"status": ProposalStatus(status)})
    service.repository.save_revision(decided)
    independent = service.manual(blocked, decided, separate=True)
    assert independent.status == "pending_confirmation" and independent.version == 2
    assert independent.matching_candidates == [] and ref(first) in independent.separated_from
    assert service.required(first.source_mail_id, first.id) == decided


def test_reciprocal_matching_blocks_are_removed_only_for_the_explicitly_selected_pair(service):
    first, second = candidate(1), candidate(2)
    first = first.model_copy(update={"matching_candidates": [ref(second)], "status": ProposalStatus.NEEDS_CLARIFICATION,
        "open_questions": ["Zuordnung zu bestehenden Entscheidungen prüfen; keine Neuanlage freigegeben."]})
    service.save(first)
    service.save(second)
    service.manual(second, first)
    current = service.required(first.source_mail_id, first.id)
    assert current.matching_candidates == [] and current.status == "pending_confirmation"


def test_special_creation_consent_does_not_survive_a_local_merge(service):
    first = candidate(1, classification="non_binding", explicit_non_binding_create_confirmed=True)
    second = candidate(2, classification="non_binding", status="needs_clarification",
        open_questions=["Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"])
    service.save(first)
    service.merge(second, first)
    current = service.required(first.source_mail_id, first.id)
    assert not current.explicit_non_binding_create_confirmed and current.status == "needs_clarification"
    assert not current.is_creatable


def test_verifying_one_source_does_not_release_other_unresolved_matches(service):
    first, second, third = candidate(1), candidate(2), candidate(3)
    first = first.model_copy(update={"matching_candidates": [ref(second), ref(third)],
        "status": ProposalStatus.NEEDS_CLARIFICATION,
        "open_questions": ["Zuordnung zu bestehenden Entscheidungen prüfen; keine Neuanlage freigegeben."]})
    for item in (first, second, third):
        service.save(item)
    service.manual(second, first)
    current = service.required(first.source_mail_id, first.id)
    assert current.matching_candidates == [ref(third)] and not current.is_creatable


def test_manual_partial_clock_and_date_are_not_overwritten_by_a_complete_interval():
    old = candidate(1, start=None, end=None, status="needs_clarification", open_questions=["Wann endet der Termin?"],
        known_temporal_facts={"date": NOW.date(), "start_time": "15:00:00"},
        protected_fields=["known_temporal_facts"])
    current = merge_facts(old, candidate(2))
    assert current.start is None and current.end is None
    assert current.known_temporal_facts.start_time == old.known_temporal_facts.start_time
    assert any("manuell" in q for q in current.open_questions)


def test_all_day_and_timed_facts_need_explicit_review_instead_of_a_type_error():
    first = candidate(1)
    incoming = candidate(2, all_day=True, start=NOW.date(), end=(NOW + timedelta(days=1)).date())
    current = merge_facts(first, incoming)
    assert current.start == first.start and current.end == first.end and not current.all_day
    assert any("Ganztägige" in q for q in current.open_questions)
