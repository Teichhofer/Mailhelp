"""4.6, step 17.8: from the mail to the changed or cancelled calendar entry (synthetic data).

Acceptance criteria of Planung 4.6: no stale entry after a move, never a blindly
overwritten entry, a cancellation only after confirmation, unchanged write safety.
"""
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from mailhelp.config import TargetSettings, Topic
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import ActionRoute, EventExtraction, ExtractedEvent, MailState, ProposalStatus
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.proposals.calendar_target import AMBIGUOUS
from mailhelp.proposals.precheck import DuplicatePreCheckService
from mailhelp.storage import JsonStore
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed
from tests.fakes.shared_services import AnalyzerStub, Notify

pytestmark = pytest.mark.e2e

SESSION = timed("gr-1", "Bauausschuss", "2026-12-04T18:00:00+01:00", "2026-12-04T20:00:00+01:00",
                description="Eigene Notizen zur Sitzung")


class Model(AnalyzerStub):
    """Answers as the 4.6 prompts require."""

    def __init__(self, event):
        super().__init__("relevant")
        self.event = event

    def action_route(self, mail):
        return "ar", ActionRoute(action_state="event", task_count=0, event_count=1, reason="Terminänderung")

    def extract_events(self, mail, *, expected_count):
        return "e", EventExtraction(events=[self.event])


def process(tmp_path, calendar, event, text):
    writer = google_writer(calendar)
    raw = (f"From: Rathaus <rathaus@example.test>\r\nSubject: Bauausschuss\r\n"
           f"Date: Mon, 23 Nov 2026 09:00:00 +0100\r\n\r\n{text}").encode()
    with JsonStore(tmp_path / "data") as store:
        run = Orchestrator(Model(event), store, Notify(), 1,
                           [Topic(id="kommune", name="Kommune", description="Gemeinde", enabled=True)], 50_000,
                           precheck=DuplicatePreCheckService(writer=writer),
                           targets=TargetSettings(todoist_project="inbox", google_calendar="calendar-1"),
                           user_timezone="Europe/Berlin")
        result = run.process(FetchedMail("INBOX", 1, 1, raw, received_at=datetime(2026, 11, 23, 8, 1, tzinfo=UTC)))
    (proposal,) = MailState.model_validate(result.state).proposals
    return proposal, writer


def confirm(proposal, writer):
    # The explicit confirmation of exactly this version (as Telegram or the web set it).
    confirmed = proposal.model_copy(update={"status": ProposalStatus.CONFIRMED, "confirmed_web_actor": None})
    return execute_confirmed(confirmed, writer, lambda _: None, authorize=lambda: True)


def move(**changes):
    values = dict(title="Bauausschuss", evidence="am 04.12.2026 wird auf den 11.12.2026 verschoben",
                  date_text="11.12.2026", time_requirement="required_unknown", responsibility="user",
                  certainty="certain", classification="change", original_date_text="04.12.2026")
    values.update(changes)
    return ExtractedEvent(**values)


def test_a_confirmed_move_leaves_no_entry_on_the_old_day(tmp_path):
    calendar = FakeGoogleCalendar(SESSION)
    proposal, writer = process(tmp_path, calendar, move(),
                               "Die Sitzung am 04.12.2026 wird auf den 11.12.2026 verschoben.")
    assert proposal.status == ProposalStatus.PENDING_CONFIRMATION and proposal.target_event_id == "gr-1"
    assert calendar.patches == []  # nothing changes before the explicit confirmation
    written, result = confirm(proposal, writer)
    assert written.status == ProposalStatus.CREATED and result["operation"] == "event_changed"
    assert list(calendar.events) == ["gr-1"]  # moved, not duplicated
    entry = calendar.events["gr-1"]
    assert entry["start"] == {"dateTime": "2026-12-11T18:00:00+01:00"}
    assert entry["summary"] == "Bauausschuss" and entry["description"].startswith("Eigene Notizen zur Sitzung")
    assert not any(request.method == "POST" for request in calendar.requests)


def test_two_possible_entries_are_never_overwritten_blindly(tmp_path):
    other = timed("gr-2", "Bauausschuss (Vorbesprechung)", "2026-12-04T16:00:00+01:00", "2026-12-04T17:00:00+01:00")
    calendar = FakeGoogleCalendar(SESSION, other)
    proposal, writer = process(tmp_path, calendar, move(),
                               "Die Sitzung am 04.12.2026 wird auf den 11.12.2026 verschoben.")
    assert proposal.status == ProposalStatus.NEEDS_CLARIFICATION and proposal.open_questions[0] == AMBIGUOUS
    with pytest.raises(ValueError, match="Nur neue, sichere"):
        confirm(proposal, writer)
    assert calendar.patches == []


def test_a_cancellation_is_written_only_after_the_confirmation(tmp_path):
    calendar = FakeGoogleCalendar(SESSION)
    cancel = move(classification="cancellation", date_text="04.12.2026", original_date_text=None,
                  evidence="Die Sitzung am 04.12.2026 entfällt.")
    proposal, writer = process(tmp_path, calendar, cancel, "Die Sitzung am 04.12.2026 entfällt.")
    assert proposal.is_cancellation and proposal.status == ProposalStatus.PENDING_CONFIRMATION
    assert calendar.patches == []
    written, result = confirm(proposal, writer)
    assert written.status == ProposalStatus.CREATED and result["operation"] == "event_cancelled"
    assert calendar.events["gr-1"]["status"] == "cancelled"
    # Confirming the same version again writes nothing a second time.
    again, _ = confirm(proposal, writer)
    assert again.status == ProposalStatus.CREATED and len(calendar.patches) == 1


def test_the_router_counts_a_cancellation_as_an_event():
    """Regression 4.6.7: the real model answered "none" for "Die Teambesprechung ist abgesagt"."""
    prompts = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    router = " ".join(prompts["action_router"]["system_prompt"].split())
    assert "Eine Absage eines bestimmten Termins ist deshalb nie \"none\"." in router
    assert "\"event\" mit event_count 1, auch wenn die Mail keine Handlung verlangt" in router
