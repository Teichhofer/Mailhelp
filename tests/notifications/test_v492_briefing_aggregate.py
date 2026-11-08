"""Briefings read authoritative cards and do not re-count mails merely edited afterwards."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.models import MailState, RelevanceDialog, Summary
from mailhelp.notifications.briefing_aggregate import BriefingAggregator
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

START, END = datetime(2026, 11, 8, 6, tzinfo=UTC), datetime(2026, 11, 8, 12, tzinfo=UTC)


@pytest.fixture
def aggregator(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        yield BriefingAggregator(store, ReviewViews(store, "Europe/Berlin"))


def saved(agg, number, proposals=(), *, irrelevant=False, stamp=None):
    save_mail(agg.store, number, "Person <person@example.test>", "Synthetic subject", proposals, text="Synthetic")
    state = agg.store.load_model("mail-" + mail_id(number), MailState)
    state.created_at = stamp or START + timedelta(hours=1)
    state.updated_at = END + timedelta(days=1)  # later user edits are not newly analysed mails
    state.steps.completion = state.steps.relevance = "completed"
    state.steps.summary = "skipped" if irrelevant else "completed"
    state.summary = None if irrelevant else Summary(sentences=["Synthetische Zusammenfassung"], deadlines=["09.11."])
    agg.store.save("mail-" + state.id, state.model_dump(mode="json"))
    return state


def test_collects_all_current_open_cards_and_new_summaries(aggregator):
    event = proposal(1, "meeting", kind="event", title="Treffen", open_questions=["Wann?"],
                     known_temporal_facts={"date": "2026-11-09"})
    task = proposal(1, "answer", title="Antworten", due="2026-11-09")
    saved(aggregator, 1, [event, task])
    result = aggregator.collect(START, END)
    assert (len(result.events), len(result.tasks), result.scanned, result.irrelevant) == (1, 1, 1, 0)
    assert result.events[0].questions and result.tasks[0].when == "09.11.2026"
    assert result.summaries[0].deadlines == ("09.11.",) and not result.empty


def test_counts_filtered_mails_without_making_an_empty_digest_nonempty(aggregator):
    saved(aggregator, 2, irrelevant=True)
    saved(aggregator, 3, irrelevant=True, stamp=START)
    saved(aggregator, 4, irrelevant=True, stamp=END + timedelta(seconds=1))
    result = aggregator.collect(START, END)
    assert result.scanned == result.irrelevant == 1 and result.empty


def test_completed_mail_without_a_summary_is_counted_without_invented_content(aggregator):
    state = saved(aggregator, 91)
    state.summary, state.steps.summary = None, "pending"
    aggregator.store.save("mail-" + state.id, state.model_dump(mode="json"))
    content = aggregator.collect(START, END)
    assert content.scanned == 1 and content.irrelevant == 0 and not content.summaries and content.empty


def test_uses_current_proposal_status_and_old_open_cards_outside_the_summary_window(aggregator):
    task = proposal(5, "old", title="Noch offen")
    closed = proposal(5, "closed", status="rejected")
    saved(aggregator, 5, [task, closed], stamp=START - timedelta(days=1))
    result = aggregator.collect(START, END)
    assert [item.proposal_id for item in result.tasks] == ["old"] and result.scanned == 0


def test_snapshot_timestamp_and_retention_are_respected(aggregator):
    state = saved(aggregator, 6)
    aggregator.store.save("analysis-" + state.id, {"schema_version": 1, "recorded_at": END.isoformat(),
        "summary": {"sentences": ["Gespeicherte Analyse"], "deadlines": []}})
    result = aggregator.collect(START, END)
    assert result.summaries[0].text == "Gespeicherte Analyse"
    aggregator.store.save("analysis-" + state.id, {"schema_version": 1, "removed": True})
    assert "nicht mehr aufbewahrt" in aggregator.collect(START, END).summaries[0].text
    assert "Synthetische Zusammenfassung" not in str(aggregator.collect(START, END))


def test_relevance_questions_and_unfinished_mails(aggregator):
    state = saved(aggregator, 7)
    state.steps.completion = "pending"
    state.awaiting_relevance = True
    state.relevance_dialog = RelevanceDialog(mail_id=state.id, version=1)
    # Validate the synthetic dialog through the persisted mail model.
    aggregator.store.save("mail-" + state.id, state.model_dump(mode="json"))
    result = aggregator.collect(START, END)
    assert result.relevance and result.scanned == 0 and not result.empty


def test_corrupt_records_are_not_modified_and_missing_headers_are_explained(aggregator):
    state = saved(aggregator, 8)
    state.display_headers, state.summary = None, None
    aggregator.store.save("mail-" + state.id, state.model_dump(mode="json"))
    bad = aggregator.store.directory / ("mail-" + mail_id(9) + ".json")
    bad.write_bytes(b"{broken")
    result = aggregator.collect(START, END)
    assert result.damaged and result.summaries[0].subject == "Mail ohne Betreff"
    assert bad.read_bytes() == b"{broken"


def test_corrupt_only_mail_data_must_not_be_silently_treated_as_an_empty_briefing(aggregator):
    path = aggregator.store.directory / ("mail-" + mail_id(99) + ".json")
    path.write_bytes(b"{broken")
    result = aggregator.collect(START, END)
    assert result.damaged and not result.empty


@pytest.mark.parametrize("start,end", [(END, START), (START.replace(tzinfo=None), END),
                                      (START, END.replace(tzinfo=None))])
def test_invalid_windows_are_rejected(aggregator, start, end):
    with pytest.raises(ValueError, match="Zeitfenster"):
        aggregator.collect(start, end)
