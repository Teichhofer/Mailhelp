"""Tasks are created rather than blocked (5.0.2): only a clear match stops a confirmation."""
from datetime import UTC, datetime

import pytest

from mailhelp.domain.proposal import Proposal
from mailhelp.domain.proposal_sources import ProposalSource
from mailhelp.proposals.proposal_matching import relationship
from mailhelp.proposals.proposal_reconciliation import ProposalReconciliationService
from mailhelp.storage import JsonStore

NOW = datetime(2030, 11, 20, 14, tzinfo=UTC)


def task(number, pid, title, mail=None, subject="seminar", **changes):
    mail_id = f"{mail if mail is not None else number:024x}"
    return Proposal.model_validate({"id": pid, "version": 1, "source_mail_id": mail_id,
        "kind": "task", "target": "tasks", "target_provider": "todoist", "title": title,
        "description": "Synthetische Aufgabe", "evidence": "Synthetischer Beleg", "responsibility": "user",
        "certainty": "certain", "classification": "new", "status": "pending_confirmation",
        "sources": [ProposalSource(mail_id=mail_id, proposal_id=pid, sent_at=NOW, subject=subject,
                                   anchors=["shared-thread"]).model_dump()], **changes})


@pytest.fixture
def service(tmp_path):
    with JsonStore(tmp_path) as store:
        yield ProposalReconciliationService(store)


def test_two_different_tasks_of_one_mail_do_not_block_each_other(service):
    """Regression: both tasks of one mail were reset to "Zuordnung prüfen" and never reached Todoist."""
    first = task(1, "p_quali", "Mitarbeiterqualifikation prüfen")
    second = task(1, "p_seminar", "Zum Seminar anmelden", due="2030-11-17")
    service.save(first)
    service.save(second)
    assert relationship(service.store, first, second) == "different"
    assert service.confirmation_candidates(first) == []
    assert service.confirmation_candidates(second) == []


def test_the_same_task_extracted_twice_from_one_mail_is_still_recognised(service):
    first = task(1, "p_a", "Zum Seminar anmelden")
    twice = task(1, "p_b", "zum seminar anmelden ")
    assert relationship(service.store, twice, first) == "same"


@pytest.mark.parametrize(("title", "expected"), [
    ("Zum Seminar anmelden", "same"),
    ("Anmelden zum Seminar", "possible"),
    ("Seminar anmelden bis Freitag", "different"),
    ("Rechnung bezahlen", "different"),
])
def test_a_later_mail_of_the_thread_asks_only_for_a_clear_match(service, title, expected):
    earlier = task(1, "p_a", "Zum Seminar anmelden")
    later = task(2, "p_b", title)
    assert relationship(service.store, later, earlier) == expected


def test_tasks_outside_the_thread_or_on_other_days_are_independent(service):
    earlier = task(1, "p_a", "Zum Seminar anmelden")
    assert relationship(service.store, task(2, "p_b", "Zum Seminar anmelden", subject="anderes"), earlier) == "different"
    dated = task(1, "p_a", "Zum Seminar anmelden", due="2030-11-17")
    assert relationship(service.store, task(2, "p_b", "Zum Seminar anmelden", due="2030-11-18"), dated) == "different"
