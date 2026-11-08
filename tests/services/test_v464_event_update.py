"""4.6, steps 17.5/17.6: a confirmed change or cancellation updates the existing entry."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from mailhelp import state_names
from mailhelp.models import Proposal, ProposalStatus
from mailhelp.storage import JsonStore
from mailhelp.telegram.writes import ConfirmedWriteExecutor
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed

BERLIN = ZoneInfo("Europe/Berlin")
ENTRY = timed("gr-1", "Gemeinderatssitzung (eigener Titel)", "2026-12-04T18:00:00+01:00",
              "2026-12-04T20:00:00+01:00", description="Unterlagen im Ordner GR", location="Saal 1")
MOVE = ["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr", "Ende 04.12.2026 20:00 Uhr → 11.12.2026 20:00 Uhr"]


class Persistence:
    def __init__(self, store):
        self.store = store

    def persist(self, proposal):
        self.store.save(state_names.proposal(proposal.source_mail_id, proposal.id), proposal.model_dump(mode="json"))


class Telegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, *args, **kwargs):
        self.sent.append(text)


def confirmed(**changes):
    values = dict(schema_version=3, id="p1", version=2, kind="event", responsibility="user", certainty="certain",
                  classification="change", title="Gemeinderatssitzung", evidence="verschoben", target="calendar-1",
                  source_mail_id="a" * 24, status="confirmed", target_event_id="gr-1", time_changes=MOVE,
                  start=datetime(2026, 12, 11, 18, tzinfo=BERLIN), end=datetime(2026, 12, 11, 20, tzinfo=BERLIN),
                  # Confirmed in Telegram: no web session; omitting it marks an unverifiable legacy approval.
                  confirmed_web_actor=None)
    values.update(changes)
    return Proposal.model_validate(values)


def run(tmp_path, calendar, proposal):
    with JsonStore(tmp_path / "data") as store:
        persistence, telegram = Persistence(store), Telegram()
        persistence.persist(proposal)
        executor = ConfirmedWriteExecutor(store, {"google_calendar": google_writer(calendar)}, persistence,
                                          telegram, 2, False, None, "Europe/Berlin")
        return executor, executor.execute(proposal), telegram, persistence


def test_a_change_moves_the_entry_and_keeps_title_and_description(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.external.calendar._now", lambda zone: datetime(2026, 11, 20, 9, 15, tzinfo=BERLIN))
    calendar = FakeGoogleCalendar(ENTRY)
    _executor, result, telegram, _ = run(tmp_path, calendar, confirmed(location="Saal 2"))
    assert result.status == ProposalStatus.CREATED and result.external_id == "gr-1"
    ((event_id, body),) = calendar.patches
    assert event_id == "gr-1" and "summary" not in body  # the user's title stays
    assert body["start"] == {"dateTime": "2026-12-11T18:00:00+01:00"} and body["location"] == "Saal 2"
    assert body["description"] == ("Unterlagen im Ordner GR\n\n[Mailhelp 20.11.2026 09:15] Termin geändert: "
                                   f"{'; '.join(MOVE)} (bestätigte Vorschlagsversion 2).")
    assert body["extendedProperties"]["private"]["mailhelp_key"] == "mailhelp:" + "a" * 24 + ":p1:v2"
    assert calendar.events["gr-1"]["summary"] == "Gemeinderatssitzung (eigener Titel)"
    assert telegram.sent == [f"✅ Bestehender Termin „Gemeinderatssitzung“ geändert: {'; '.join(MOVE)}. "
                             "Titel und Beschreibung bleiben erhalten; die Änderung ist in der Beschreibung vermerkt."]


def test_an_all_day_change_without_description_or_place_writes_only_the_note(tmp_path):
    fest = {"id": "gr-1", "summary": "Sommerfest", "start": {"date": "2026-07-04"}, "end": {"date": "2026-07-05"}}
    calendar = FakeGoogleCalendar(fest)
    proposal = confirmed(start=date(2026, 7, 11), end=date(2026, 7, 12), all_day=True, time_changes=[])
    _executor, result, telegram, _ = run(tmp_path, calendar, proposal)
    ((_, body),) = calendar.patches
    assert body["start"] == {"date": "2026-07-11"} and "location" not in body
    assert body["description"].startswith("[Mailhelp ") and "Termin geändert: Angaben bestätigt" in body["description"]
    assert result.status == ProposalStatus.CREATED and "bestätigte Angaben übernommen" in telegram.sent[0]


def test_a_deleted_entry_is_never_recreated_by_a_change(tmp_path):
    calendar = FakeGoogleCalendar()
    _executor, result, _, _ = run(tmp_path, calendar, confirmed())
    assert result.status == ProposalStatus.FAILED
    assert calendar.patches == [] and not any(request.method == "POST" for request in calendar.requests)


def test_an_unclear_change_is_matched_after_a_restart_and_never_repeated(tmp_path):
    calendar = FakeGoogleCalendar(ENTRY)
    calendar.lose_patch_answer = True
    executor, unclear, telegram, persistence = run(tmp_path, calendar, confirmed())
    assert unclear.status == ProposalStatus.UNCERTAIN and len(calendar.patches) == 1
    calendar.lose_patch_answer = False
    # A new process resumes the stored record: the key finds the patched entry.
    resumed = executor.execute(executor.store.load_model(state_names.proposal("a" * 24, "p1"), Proposal))
    assert resumed.status == ProposalStatus.CREATED and resumed.external_id == "gr-1"
    assert len(calendar.patches) == 1


def test_a_cancellation_changes_only_the_status(tmp_path):
    calendar = FakeGoogleCalendar(ENTRY)
    cancel = confirmed(classification="cancellation", is_cancellation=True, time_changes=[],
                       start=datetime(2026, 12, 4, 18, tzinfo=BERLIN), end=datetime(2026, 12, 4, 20, tzinfo=BERLIN))
    _executor, result, telegram, _ = run(tmp_path, calendar, cancel)
    ((_, body),) = calendar.patches
    assert body == {"status": "cancelled", "extendedProperties": {"private": {
        "mailhelp_key": "mailhelp:" + "a" * 24 + ":p1:v2"}}}
    assert result.status == ProposalStatus.CREATED
    assert telegram.sent == ["✅ Termin „Gemeinderatssitzung“ im Kalender abgesagt."]


def test_an_unclear_cancellation_is_matched_by_its_target_and_never_repeated(tmp_path):
    """17.6: a cancelled Google entry leaves the key search, so the target itself is read."""
    calendar = FakeGoogleCalendar(ENTRY)
    calendar.lose_patch_answer = True
    cancel = confirmed(classification="cancellation", is_cancellation=True, time_changes=[])
    executor, unclear, telegram, _ = run(tmp_path, calendar, cancel)
    assert unclear.status == ProposalStatus.UNCERTAIN and len(calendar.patches) == 1
    stored = executor.store.load_model(state_names.proposal("a" * 24, "p1"), Proposal)
    resumed = executor.execute(stored)
    assert resumed.status == ProposalStatus.CREATED and resumed.external_id == "gr-1"
    assert len(calendar.patches) == 1  # no second cancellation
    assert telegram.sent[-1] == "✅ Termin „Gemeinderatssitzung“ im Kalender abgesagt."


def test_an_unclear_cancellation_of_a_still_active_entry_stays_unclear(tmp_path):
    """The write may not have arrived: without proof it is neither repeated nor reported as done."""
    calendar = FakeGoogleCalendar(ENTRY)
    calendar.fail[("PATCH", "patch")] = httpx.Response(504)
    cancel = confirmed(classification="cancellation", is_cancellation=True, time_changes=[])
    executor, unclear, _, _ = run(tmp_path, calendar, cancel)
    assert unclear.status == ProposalStatus.UNCERTAIN
    resumed = executor.execute(executor.store.load_model(state_names.proposal("a" * 24, "p1"), Proposal))
    assert resumed.status == ProposalStatus.UNCERTAIN
    assert sum(request.method == "PATCH" for request in calendar.requests) == 1


def test_an_already_cancelled_entry_needs_no_second_write(tmp_path):
    calendar = FakeGoogleCalendar({**ENTRY, "status": "cancelled"})
    cancel = confirmed(classification="cancellation", is_cancellation=True, time_changes=[])
    _executor, result, telegram, _ = run(tmp_path, calendar, cancel)
    assert result.status == ProposalStatus.CREATED and calendar.patches == []
    assert "war im Kalender bereits abgesagt oder gelöscht" in telegram.sent[0]
