"""Synthetic regression scenarios for the observations in the 2.4 plan."""
import pytest
from reconciliation_fakes import Events, Existing, current, process

from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore


def test_regression_video_without_end_gets_explicitly_labelled_one_hour_default(tmp_path):
    store = JsonStore(tmp_path)
    result, _ = process(store, Events())
    proposal = result.state["proposals"][0]
    assert proposal["status"] == "pending_confirmation"
    assert proposal["end"] == "2030-11-20T15:00:00+01:00"


@pytest.mark.parametrize("titles", [("Kurze Videokonferenz", "Skype-Termin Fachbeirat"),
                                    ("Skype-Termin Fachbeirat", "Kurze Videokonferenz")])
def test_regression_related_open_decisions_are_one_proposal_in_either_order(tmp_path, titles):
    store = JsonStore(tmp_path)
    for uid, title in enumerate(titles, 1):
        process(store, Events(title, end="15:30 Uhr"), uid)
    assert len(ReviewViews(store, "Europe/Berlin").overview().open) == 1


def test_regression_existing_beirat_event_has_record_and_view_without_delivery(tmp_path):
    store = JsonStore(tmp_path)
    result, notify = process(store, Events("Beiratssitzung online", end="15:30 Uhr", task=True),
                             precheck=Existing())
    assert len(current(store)) == 2
    overview = ReviewViews(store, "Europe/Berlin").overview()
    assert len(overview.open) == 1 and len(overview.recent) == 1
    assert result.state["proposals"][1]["end"] == "2030-11-20T15:30:00+01:00"
    assert result.state["proposals"][1]["id"] not in notify.messages


def test_missing_canonical_record_before_delivery_marks_failure_without_resending(tmp_path, monkeypatch):
    from mailhelp.proposal_reconciliation import ProposalReconciliationService
    store = JsonStore(tmp_path)
    process(store, Events(end="15:30 Uhr"), 1)
    monkeypatch.setattr(ProposalReconciliationService, "resolve", lambda *args: None)
    result, _ = process(store, Events("Skype-Termin", end="15:30 Uhr"), 2)
    assert result.outcome.value == "failed"
    assert result.state["steps"]["proposal_notification"] == "sending"
