"""Count estimates are diagnostics; complete extracted facts remain actionable."""
import pytest

from mailhelp.models import ExtractionCountConflict, ProposalStatus
from tests.fakes.proposal_builder_fakes import builder, event, task


@pytest.mark.parametrize("kind", ["task", "event"])
@pytest.mark.parametrize("expected,actual", [(1, 2), (2, 1)])
def test_count_estimate_never_adds_an_unanswerable_quantity_question(kind, expected, actual):
    conflict = ExtractionCountConflict(category=kind, expected_count=expected, actual_count=actual,
                                       router_call_id="router", extractor_call_id="extractor")
    tasks = [task(title=f"Antwort {index}") for index in range(actual)] if kind == "task" else []
    events = [event(title=f"Sitzung {index}") for index in range(actual)] if kind == "event" else []
    proposals = builder().build(tasks, events, [conflict])
    assert len(proposals) == actual
    assert all(item.status == ProposalStatus.PENDING_CONFIRMATION and item.open_questions == [] for item in proposals)
