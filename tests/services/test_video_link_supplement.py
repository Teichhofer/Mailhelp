"""7.9: a later mail with the conference link supplements the existing calendar entry (synthetic data).

The defect (Planung 7.9, section 2): an entry without a dial-in link was found again with the same
times, and the pre-check closed the proposal carrying the link as ``already_exists``. The link never
reached the calendar.
"""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mailhelp.domain.conference import LinkAssessment, assess, is_conference, links_in, normalized, with_link
from mailhelp.domain.extraction import CalendarDuplicateDecision
from mailhelp.domain.proposal import (
    CalendarSupplement,
    Proposal,
    ProposalCertainty,
    ProposalClassification,
    ProposalKind,
    ProposalResponsibility,
    ProposalStatus,
)
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.contracts import CalendarOverlapEvent
from mailhelp.external.microsoft import OutlookCalendar
from mailhelp.persistence.ledger import ActionLedgerEntry
from mailhelp.proposals.conference_supplement import log, plan
from mailhelp.proposals.conflicts import choose
from mailhelp.proposals.precheck import DuplicatePreCheckService
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed

LINK = "https://example.zoom.us/j/1234567890?pwd=AbC123"
OTHER = "https://meet.google.com/abc-defg-hij"
NOTES = "Eigene Notizen: Fragen zur Klassenfahrt sammeln."


def entry(**extra):
    return timed("ev-1", "Online-Elternabend", "2026-11-26T19:30:00+01:00", "2026-11-26T21:00:00+01:00",
                 **{"description": NOTES, **extra})


def proposal(classification=ProposalClassification.NEW, link=LINK, **changes):
    values = dict(
        id="p_link", version=1, kind=ProposalKind.EVENT, responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN, classification=classification, title="Online-Elternabend",
        description="Zugangsdaten zum Elternabend", evidence="Einwahl über den Zoom-Link",
        source_mail_id="c" * 24, target="calendar-1", target_provider="google",
        start=datetime(2026, 11, 26, 18, 30, tzinfo=UTC), end=datetime(2026, 11, 26, 20, 0, tzinfo=UTC),
        video_link=link, meeting_mode="video")
    values.update(changes)
    return Proposal(**values)


def check(calendar, item, **service):
    writer = google_writer(calendar)
    return DuplicatePreCheckService(writer=writer, **service).check_proposal(item), writer


def confirm(item, writer):
    confirmed = item.model_copy(update={"status": ProposalStatus.CONFIRMED, "confirmed_web_actor": None})
    return execute_confirmed(confirmed, writer, lambda _: None, authorize=lambda: True)


def change(**changes):
    """A change as the extraction delivers it: the target entry is still asked for."""
    return proposal(ProposalClassification.CHANGE, status=ProposalStatus.NEEDS_CLARIFICATION,
                    open_questions=["Welcher bestehende Eintrag soll geändert werden?"], **changes)


@pytest.mark.parametrize("make", [proposal, change], ids=["new", "change"])
def test_a_link_for_an_entry_without_one_becomes_a_confirmable_update(make):
    calendar = FakeGoogleCalendar(entry())
    checked, _writer = check(calendar, make())
    assert checked.status == ProposalStatus.PENDING_CONFIRMATION
    assert checked.target_event_id == "ev-1" and checked.duplicate_match is None
    supplement = checked.calendar_supplement
    assert supplement is not None and supplement.operation == "add" and supplement.proposed == LINK
    assert supplement.target_event_id == "ev-1" and supplement.previous is None
    assert calendar.patches == []  # nothing is written before the explicit confirmation


def test_the_confirmed_supplement_writes_the_link_once_and_keeps_the_entry():
    calendar = FakeGoogleCalendar(entry(attendees=[{"email": "lehrerin@example.test"}]))
    checked, writer = check(calendar, proposal())
    written, result = confirm(checked, writer)
    assert written.status == ProposalStatus.CREATED and result["operation"] == "event_changed"
    ((event_id, body),) = calendar.patches
    assert event_id == "ev-1" and "start" not in body and "end" not in body and "summary" not in body
    stored = calendar.events["ev-1"]
    assert stored["description"].startswith(NOTES) and stored["description"].count(LINK) == 1
    assert stored["summary"] == "Online-Elternabend" and stored["attendees"] == [{"email": "lehrerin@example.test"}]
    assert stored["start"] == {"dateTime": "2026-11-26T19:30:00+01:00"}
    # A second fetch of the same mail finds the link and writes nothing.
    again, _writer = check(calendar, proposal())
    assert again.status == ProposalStatus.ALREADY_EXISTS and again.calendar_supplement is None
    assert len(calendar.patches) == 1


def test_an_identical_link_stays_a_duplicate():
    calendar = FakeGoogleCalendar(entry(description=f"{NOTES}\nEinwahl: HTTPS://EXAMPLE.ZOOM.US/j/1234567890?pwd=AbC123."))
    checked, _writer = check(calendar, proposal())
    assert checked.status == ProposalStatus.ALREADY_EXISTS and checked.calendar_supplement is None


def test_a_native_conference_field_counts_as_present():
    calendar = FakeGoogleCalendar(entry(conferenceData={"entryPoints": [{"entryPointType": "video", "uri": LINK},
                                                                         {"entryPointType": "phone", "uri": "tel:1"}]}))
    checked, _writer = check(calendar, proposal())
    assert checked.status == ProposalStatus.ALREADY_EXISTS


def test_a_ledger_hit_does_not_skip_the_content_check():
    calendar = FakeGoogleCalendar(entry())
    checked, _writer = check(calendar, proposal(), ledger=Ledger(external_id="ev-1"))
    assert checked.status == ProposalStatus.PENDING_CONFIRMATION and checked.calendar_supplement is not None
    assert checked.target_event_id == "ev-1"


class Ledger:
    """One earlier Mailhelp creation of this proposal."""

    def __init__(self, external_id):
        self.external_id = external_id

    def prior_actions(self, item):
        return [ActionLedgerEntry(action_key="a" * 64, action_key_version=2, mail_id="b" * 24, proposal_id="p0",
                                  proposal_version=1, kind=ProposalKind.EVENT, title="Online-Elternabend",
                                  target="calendar-1", external_id=self.external_id)]


@pytest.mark.parametrize(("events", "external_id", "item"), [
    ((entry(description=LINK),), "ev-1", proposal()),  # the link is there already
    ((), "ev-1", proposal()),  # the entry is gone: nothing to supplement
    ((entry(),), None, proposal()),  # no entry id was recorded
    ((entry(),), "ev-1", proposal(link=None)),  # the mail had no link
])
def test_without_anything_to_supplement_the_ledger_hit_stays_a_duplicate(events, external_id, item):
    checked, _writer = check(FakeGoogleCalendar(*events), item, ledger=Ledger(external_id))
    assert checked.status == ProposalStatus.ALREADY_EXISTS and checked.calendar_supplement is None


def test_a_ledger_hit_without_a_calendar_writer_stays_a_duplicate():
    checked = DuplicatePreCheckService(ledger=Ledger("ev-1")).check_proposal(proposal())
    assert checked.status == ProposalStatus.ALREADY_EXISTS


def test_a_registration_page_is_no_conference_access():
    calendar = FakeGoogleCalendar(entry())
    checked, _writer = check(calendar, proposal(link="https://schule.example.test/anmeldung?kurs=4"))
    assert checked.status == ProposalStatus.ALREADY_EXISTS and checked.calendar_supplement is None


def test_another_link_in_the_entry_asks_which_applies_and_the_choice_is_kept():
    calendar = FakeGoogleCalendar(entry(description=f"{NOTES}\nEinwahl: {OTHER}."))
    checked, writer = check(calendar, proposal())
    assert checked.status == ProposalStatus.NEEDS_CLARIFICATION
    (conflict,) = checked.field_conflicts
    assert conflict.field == "video_link" and conflict.question in checked.open_questions
    assert [variant.text for variant in conflict.variants] == [OTHER, LINK]
    supplement = checked.calendar_supplement
    assert supplement is not None and supplement.operation == "replace" and supplement.previous == OTHER
    # Choosing the new link keeps the replacement; the re-check asks nothing again.
    chosen = choose(checked, conflict.id, "b")
    assert chosen.status == ProposalStatus.PENDING_CONFIRMATION and chosen.version == 2
    again = DuplicatePreCheckService(writer=writer).check_proposal(chosen)
    assert again.status == ProposalStatus.PENDING_CONFIRMATION and again.calendar_supplement == supplement
    written, _result = confirm(again, writer)
    description = calendar.events["ev-1"]["description"]
    assert written.status == ProposalStatus.CREATED and LINK in description and OTHER not in description
    assert description.startswith(NOTES)
    # Choosing the calendar's link means nothing is to change.
    kept = choose(checked, conflict.id, "a")
    calendar.events["ev-1"]["description"] = f"{NOTES}\nEinwahl: {OTHER}."
    assert DuplicatePreCheckService(writer=writer).check_proposal(kept).status == ProposalStatus.ALREADY_EXISTS


def test_a_cancellation_never_supplements():
    calendar = FakeGoogleCalendar(entry())
    checked, _writer = check(calendar, proposal(ProposalClassification.CANCELLATION,
                                                status=ProposalStatus.NEEDS_CLARIFICATION,
                                                open_questions=["Welcher bestehende Eintrag soll storniert werden?"]))
    assert checked.is_cancellation and checked.calendar_supplement is None


def test_a_new_time_and_a_new_link_are_confirmed_together():
    calendar = FakeGoogleCalendar(entry())
    later = proposal(start=datetime(2026, 11, 26, 19, 0, tzinfo=UTC), end=datetime(2026, 11, 26, 20, 30, tzinfo=UTC))
    checked, writer = check(calendar, later)
    assert checked.time_changes and checked.calendar_supplement is not None
    confirm(checked, writer)
    ((_event_id, body),) = calendar.patches
    assert body["start"] == {"dateTime": "2026-11-26T19:00:00+00:00"} and LINK in body["description"]
    assert "Termin geändert" in body["description"]


def test_a_link_added_meanwhile_ends_without_a_write():
    calendar = FakeGoogleCalendar(entry())
    checked, writer = check(calendar, proposal())
    calendar.events["ev-1"]["description"] = f"{NOTES}\n{LINK}"
    written, result = confirm(checked, writer)
    assert result["operation"] == "supplement_present" and calendar.patches == []
    assert written.status == ProposalStatus.CREATED


@pytest.mark.parametrize("change", [
    {"description": f"{NOTES}\n{OTHER}"},  # another link appeared after the confirmation
    {"hangoutLink": OTHER},
])
def test_a_different_link_added_meanwhile_is_never_overwritten(change):
    calendar = FakeGoogleCalendar(entry())
    checked, writer = check(calendar, proposal())
    calendar.events["ev-1"].update(change)
    written, _result = confirm(checked, writer)
    assert written.status == ProposalStatus.FAILED and calendar.patches == []


def test_a_supplement_bound_to_another_entry_is_refused():
    calendar = FakeGoogleCalendar(entry(), entry(id="ev-2"))
    checked, writer = check(calendar, proposal())
    moved = checked.model_copy(update={"target_event_id": "ev-2"})
    written, _result = confirm(moved, writer)
    assert written.status == ProposalStatus.FAILED and calendar.patches == []


def test_the_write_check_accepts_a_replacement_whose_old_link_disappeared():
    calendar = FakeGoogleCalendar(entry(description=f"{NOTES}\n{OTHER}"))
    checked, writer = check(calendar, proposal())
    chosen = choose(checked, checked.field_conflicts[0].id, "b")
    calendar.events["ev-1"]["description"] = NOTES  # the old link was removed by hand
    written, _result = confirm(chosen, writer)
    assert written.status == ProposalStatus.CREATED and calendar.events["ev-1"]["description"].count(LINK) == 1


def test_a_new_event_and_a_merge_write_the_link_once():
    calendar = FakeGoogleCalendar()
    writer = google_writer(calendar)
    created = writer._calendar_event_body(proposal(), "k" * 16)
    assert created["description"].count(LINK) == 1
    existing = CalendarOverlapEvent.model_validate(entry(description=f"{NOTES}\n{LINK}"))
    decision = CalendarDuplicateDecision(same_event=True, missing_fields=["video_link"], reason="x")
    assert writer._calendar_merge_body(proposal(), "k" * 16, existing, decision) == {
        "extendedProperties": {"private": {"mailhelp_key": "k" * 16}}, "description": f"{NOTES}\n{LINK}"}


def test_native_google_and_outlook_conference_fields_are_read():
    google = CalendarOverlapEvent.model_validate(entry(hangoutLink=OTHER, conferenceData={"entryPoints": "x"}))
    assert google.conference_links == [OTHER]
    assert CalendarOverlapEvent.model_validate(entry(conferenceData=[])).conference_links == []
    outlook = OutlookCalendar(token=SimpleNamespace(), target="default")
    item = {"id": "o1", "subject": "Online-Elternabend", "start": {"dateTime": "2026-11-26T18:30:00",
                                                                    "timeZone": "UTC"},
            "end": {"dateTime": "2026-11-26T20:00:00", "timeZone": "UTC"}}
    assert outlook._overlap({**item, "onlineMeeting": {"joinUrl": LINK}}).conference_links == [LINK]
    assert outlook._overlap(item).conference_links == []


def test_conference_links_are_compared_without_changing_their_parameters():
    assert normalized("HTTPS://Example.Zoom.US/j/1?pwd=AbC.") == "https://example.zoom.us/j/1?pwd=AbC"
    assert is_conference("https://team.webex.com/meet/x") and not is_conference("http://zoom.us/j/1")
    assert not is_conference("https://zoom.us.example.test/j/1")
    assert links_in(["a https://x.test/1, und https://x.test/1.", None]) == ["https://x.test/1"]
    assert assess("https://x.test/info", ["kein Link"]) == LinkAssessment("not_conference")
    assert assess(LINK, ["https://example.zoom.us/j/1234567890?pwd=other"]).state == "conflict"
    assert with_link("", LINK) == f"[Mailhelp-Videolink]\n{LINK}"
    assert with_link(f"alt: {OTHER}).", LINK, OTHER) == f"alt: {LINK})."
    assert with_link(f"Notiz {LINK}", LINK, OTHER) == f"Notiz {LINK}"


def test_a_replacement_names_its_previous_value_and_belongs_to_its_entry():
    with pytest.raises(ValueError, match="bisherigen Wert"):
        CalendarSupplement(operation="replace", proposed=LINK, target_event_id="ev-1", source_mail_id="c" * 24)
    with pytest.raises(ValueError, match="bisherigen Wert"):
        CalendarSupplement(operation="add", previous=OTHER, proposed=LINK, target_event_id="ev-1",
                           source_mail_id="c" * 24)
    supplement = CalendarSupplement(operation="add", proposed=LINK, target_event_id="ev-1", source_mail_id="c" * 24)
    with pytest.raises(ValueError, match="gebundenen Zieltermin"):
        proposal(calendar_supplement=supplement)


def test_the_diagnosis_names_states_and_ids_but_never_the_link():
    events = []
    logger = SimpleNamespace(event=lambda *args, **fields: events.append((args, fields)))
    existing = CalendarOverlapEvent.model_validate(entry())
    log(logger, proposal(), existing, plan(proposal(), existing))
    log(logger, proposal(link=None), existing, plan(proposal(link=None), existing))
    assert events == [(("INFO", "precheck", "video_link_missing"), {"proposal_id": "p_link",
                                                                     "existing_event_id": "ev-1"})]
    assert LINK not in repr(events)
