"""5.1 R4: a re-analysis is compared with the mail's proposals and adopted once, safely."""
from datetime import UTC, date, datetime, timedelta

import pytest

from mailhelp.config import ReanalysisSettings
from mailhelp.domain.mail import MailState
from mailhelp.domain.proposal import DuplicateMatchInfo, ProposalStatus
from mailhelp.domain.reanalysis import ReanalysisJob, ReanalysisStatus
from mailhelp.persistence.proposals import ProposalRepository
from mailhelp.processing.reanalysis import ReanalysisJobs
from mailhelp.processing.reanalysis_adoption import AdoptionRefused, Change, ReanalysisAdoption, compare
from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
MAIL = mail_id(7)


class Precheck:
    def __init__(self, existing=()):
        self.existing = set(existing)

    def check_proposal(self, item, mail_context=None):
        if item.id not in self.existing:
            return item
        match = DuplicateMatchInfo(source="action_ledger", matched_title=item.title, checked_at=NOW)
        return item.model_copy(update={"status": ProposalStatus.ALREADY_EXISTS, "duplicate_match": match})


class Engine:
    def __init__(self, store, existing=()):
        self.precheck, self.reconciliation = Precheck(existing), ProposalReconciliationService(store)


def job(*candidates, status=ReanalysisStatus.COMPLETED, round_=1, **fields):
    return ReanalysisJob(id="a" * 32, mail_id=MAIL, source_round=round_, config_fingerprint="f" * 64,
                         imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 7},
                         key_hash="b" * 64, status=status, stage="done" if status == ReanalysisStatus.COMPLETED
                         else "route", max_attempts=2, max_llm_calls=5, proposals=list(candidates),
                         created_at=NOW, updated_at=NOW, **fields)


@pytest.fixture
def setup(tmp_path):
    store = JsonStore(tmp_path)
    jobs = ReanalysisJobs(store, ReanalysisSettings(), RecordingLogger(), lambda: NOW)
    sent = []
    adoption = ReanalysisAdoption(jobs, Engine(store), sent.append, lambda: NOW)
    return store, jobs, adoption, sent


def existing():
    return [proposal(7, "gleich", title="Elternabend vorbereiten"),
            proposal(7, "offen", title="Formular Klassenfahrt abgeben", due=date(2026, 11, 20)),
            proposal(7, "angelegt", title="Antrag Schulbuch stellen", status="created", external_id="todo-1"),
            proposal(7, "verworfen", title="Kuchen backen Basar", status="rejected"),
            proposal(7, "alt", title="Sporttasche packen"),
            proposal(7, "zusammen", title="Ehemals zusammengeführt", status="merged",
                     canonical_ref={"mail_id": MAIL, "proposal_id": "gleich"})]


def candidates():
    return [proposal(7, "gleich", title="Elternabend vorbereiten"),
            proposal(7, "neu-offen", title="Formular Klassenfahrt abgeben", due=date(2026, 11, 18)),
            proposal(7, "neu-angelegt", title="Antrag Schulbuch stellen", due=date(2026, 11, 30)),
            proposal(7, "neu-verworfen", title="Kuchen backen Basar"),
            proposal(7, "zusatz", title="Rückmeldung Teilnahme Elternabend", description="Bis Montag")]


def seed(store, proposals=None, **fields):
    proposals = existing() if proposals is None else proposals
    save_mail(store, 7, "Schule <schule@example.test>", "Elternabend", proposals, text="Info",
              steps=dict(preparation="completed", completion="completed"), **fields)
    for item in proposals:
        ProposalRepository(store).save_revision(item)


def test_every_kind_of_difference_is_named_without_changing_anything(setup):
    store, jobs, adoption, _ = setup
    seed(store)
    jobs.save(job(*candidates()))
    before = store.load(f"mail-{MAIL}")
    comparison = adoption.comparison("a" * 32)
    changes = {(item.existing.id if item.existing else None, item.candidate.id if item.candidate else None):
               item.change for item in comparison.items}
    assert changes == {("gleich", "gleich"): Change.UNCHANGED, ("offen", "neu-offen"): Change.CHANGED,
                       ("angelegt", "neu-angelegt"): Change.PROTECTED,
                       ("verworfen", "neu-verworfen"): Change.REJECTED, (None, "zusatz"): Change.NEW,
                       ("alt", None): Change.MISSING}
    changed = next(item for item in comparison.items if item.change == Change.CHANGED)
    assert changed.fields == ("due",)
    assert comparison.adoptable and comparison.analysis_round == 1
    assert comparison.versions == {item.id: 1 for item in existing()}
    assert store.load(f"mail-{MAIL}") == before


def test_adoption_adds_new_findings_unconfirmed_and_versions_only_open_proposals(setup):
    store, jobs, adoption, sent = setup
    seed(store)
    jobs.save(job(*candidates()))
    adoption.adopt("a" * 32, expected_round=1, expected_versions={item.id: 1 for item in existing()})
    state = store.load_model(f"mail-{MAIL}", MailState)
    current = {item.id: item for item in state.proposals}
    # The additional finding is a new, unconfirmed proposal with a pending notification.
    assert current["zusatz"].status == ProposalStatus.PENDING_CONFIRMATION and current["zusatz"].version == 1
    assert ("zusatz", 1, "pending") in {(n.proposal_id, n.proposal_version, n.status)
                                        for n in state.proposal_notifications}
    # The open proposal keeps its identity and gets a new version with the new facts.
    assert (current["offen"].version, current["offen"].due) == (2, date(2026, 11, 18))
    # Written, rejected and no longer found proposals stay exactly as they were.
    assert current["angelegt"] == existing()[2] and current["angelegt"].external_id == "todo-1"
    assert current["verworfen"].status == ProposalStatus.REJECTED and current["alt"] == existing()[4]
    assert [item.id for item in sent] == ["offen", "zusatz"]
    assert jobs.get("a" * 32).adopted_at == NOW
    with pytest.raises(AdoptionRefused, match="already_adopted"):
        adoption.adopt("a" * 32, expected_round=1, expected_versions={})


def test_a_confirmation_never_carries_over_to_a_new_version(setup):
    store, jobs, adoption, _ = setup
    confirmed = proposal(7, "offen", title="Formular Klassenfahrt abgeben", status="pending_confirmation",
                         confirmed_web_actor="web:sitzung")
    seed(store, [confirmed])
    jobs.save(job(proposal(7, "x", title="Formular Klassenfahrt abgeben", description="neu")))
    adoption.adopt("a" * 32, expected_round=1, expected_versions={"offen": 1})
    revised = ProposalRepository(store).load_current(MAIL, "offen")
    assert (revised.version, revised.description, revised.confirmed_web_actor) == (2, "neu", None)


def test_a_finding_that_already_exists_elsewhere_is_recorded_but_not_announced(setup):
    store, jobs, _, sent = setup
    seed(store, [])
    adoption = ReanalysisAdoption(jobs, Engine(store, existing={"zusatz"}), sent.append, lambda: NOW)
    jobs.save(job(proposal(7, "zusatz", title="Rückmeldung Teilnahme")))
    adoption.adopt("a" * 32, expected_round=1, expected_versions={})
    state = store.load_model(f"mail-{MAIL}", MailState)
    assert state.proposals[0].status == ProposalStatus.ALREADY_EXISTS
    assert state.proposal_notifications[0].status == "completed" and sent == []


def test_nothing_to_adopt_changes_nothing_but_marks_the_job(setup):
    store, jobs, adoption, sent = setup
    seed(store)
    jobs.save(job(proposal(7, "gleich", title="Elternabend vorbereiten")))
    before = store.load(f"mail-{MAIL}")
    comparison = adoption.adopt("a" * 32, expected_round=1, expected_versions={i.id: 1 for i in existing()})
    assert not comparison.adoptable and store.load(f"mail-{MAIL}") == before and sent == []


@pytest.mark.parametrize(("change", "reason"), [
    ("round", "stale"), ("versions", "stale"), ("job_round", "stale"), ("running", "not_completed"),
    ("unknown", "not_completed"), ("mail", "mail_missing")])
def test_a_stale_or_unfinished_adoption_is_refused_and_changes_nothing(setup, change, reason):
    store, jobs, adoption, sent = setup
    seed(store)
    jobs.save(job(*candidates(), status=ReanalysisStatus.RUNNING if change == "running" else
                  ReanalysisStatus.COMPLETED, round_=2 if change == "job_round" else 1))
    versions = {item.id: 1 for item in existing()}
    if change == "versions":
        versions["offen"] = 2
    if change == "mail":
        store.delete(f"mail-{MAIL}")
    before = store.load(f"mail-{MAIL}")
    with pytest.raises(AdoptionRefused, match=reason):
        adoption.adopt("b" * 32 if change == "unknown" else "a" * 32,
                       expected_round=2 if change == "round" else 1, expected_versions=versions)
    assert store.load(f"mail-{MAIL}") == before and sent == []


def test_a_comparison_needs_a_completed_job_and_its_mail(setup):
    store, jobs, adoption, _ = setup
    assert adoption.comparison("a" * 32) is None
    jobs.save(job(status=ReanalysisStatus.QUEUED))
    seed(store)
    assert adoption.comparison("a" * 32) is None
    jobs.save(job())
    store.delete(f"mail-{MAIL}")
    assert adoption.comparison("a" * 32) is None


def test_matching_needs_the_same_kind_and_an_adoption_needs_a_completed_job():
    state = MailState(id=MAIL, config_fingerprint="f" * 64, created_at=NOW - timedelta(days=1),
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 7},
                      proposals=[proposal(7, "t", title="Elternabend Klasse")])
    event = proposal(7, "e", kind="event", title="Elternabend Klasse", target="calendar-1",
                     start=datetime(2026, 11, 20, 18, tzinfo=UTC), end=datetime(2026, 11, 20, 19, tzinfo=UTC))
    assert [item.change for item in compare(state, job(event)).items] == [Change.NEW, Change.MISSING]
    with pytest.raises(ValueError, match="abgeschlossener"):
        job(status=ReanalysisStatus.QUEUED, adopted_at=NOW)
