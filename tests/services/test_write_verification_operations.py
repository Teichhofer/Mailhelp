"""5.2 V7: changes, additions, cancellations, duplicates and calendar files are verified per operation.

The calendar is the simulated ``FakeGoogleCalendar`` behind the real HTTP adapter; synthetic data only.
"""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.ical import CalendarFileWriter
from mailhelp.models import CalendarDuplicateDecision, Proposal, ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from mailhelp.telegram.writes import ConfirmedWriteExecutor
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 20, 9, tzinfo=UTC)
ENTRY = timed("gr-1", "Gemeinderatssitzung (eigener Titel)", "2026-12-04T18:00:00+01:00",
              "2026-12-04T20:00:00+01:00", description="Unterlagen im Ordner GR", location="Saal 1")
MOVE = ["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr"]


class Persistence:
    def __init__(self, store):
        self.store = store

    def persist(self, proposal):
        self.store.save(state_names.proposal(proposal.source_mail_id, proposal.id), proposal.model_dump(mode="json"))


class Telegram:
    def __init__(self):
        self.sent, self.documents = [], []

    def send(self, chat_id, text, *args, **kwargs):
        self.sent.append(text)

    def send_document(self, chat_id, filename, content, caption):
        self.documents.append(filename)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def proposal(**changes):
    values = dict(schema_version=3, id="p1", version=2, kind="event", responsibility="user", certainty="certain",
                  classification="change", title="Gemeinderatssitzung", evidence="verschoben", target="calendar-1",
                  source_mail_id="a" * 24, status="confirmed", target_event_id="gr-1", time_changes=MOVE,
                  start=datetime(2026, 12, 11, 18, tzinfo=BERLIN), end=datetime(2026, 12, 11, 20, tzinfo=BERLIN),
                  confirmed_web_actor=None)
    values.update(changes)
    return Proposal.model_validate(values)


def new_event(**changes):
    return proposal(classification="new", target_event_id=None, time_changes=[], title="Elternabend",
                    description="Agenda", **changes)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.external.calendar._now", lambda zone: datetime(2026, 11, 20, 10, tzinfo=BERLIN))
    with JsonStore(tmp_path / "data") as store:
        persistence, telegram, clock = Persistence(store), Telegram(), Clock()
        checks = WriteVerifications(store, now=clock)

        def execute(handler, item, matcher=None):
            persistence.persist(item)
            executor = ConfirmedWriteExecutor(store, {"google_calendar": google_writer(handler, matcher)},
                                              persistence, telegram, 2, False, None, "Europe/Berlin", checks)
            return executor, executor.execute(item)

        yield store, checks, telegram, clock, execute


def record_of(checks, item):
    return checks.load(item)


def test_a_change_is_verified_against_the_existing_entry_with_its_own_title(run):
    store, checks, telegram, _clock, execute = run
    calendar = FakeGoogleCalendar(ENTRY)
    _executor, result = execute(calendar, proposal(location="Saal 2"))
    record = record_of(checks, proposal())
    assert result.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert (record.operation, record.receipt.result) == ("update", "updated")
    assert record.expected["title"] == "Gemeinderatssitzung (eigener Titel)" and record.expected["location"] == "Saal 2"
    assert telegram.sent == [f"✅ Bestehender Termin „Gemeinderatssitzung“ geändert und geprüft: {MOVE[0]}. "
                             "Titel und Beschreibung bleiben erhalten; die Änderung ist in der Beschreibung vermerkt."]


def test_a_change_overwritten_by_hand_before_the_read_is_a_mismatch(run):
    _store, checks, telegram, _clock, execute = run
    calendar = FakeGoogleCalendar(ENTRY)

    def handler(request):
        answer = calendar(request)
        if request.method == "PATCH":
            calendar.events["gr-1"]["start"] = {"dateTime": "2026-12-04T18:00:00+01:00"}
        return answer

    _executor, result = execute(handler, proposal())
    record = record_of(checks, proposal())
    assert result.status == ProposalStatus.VERIFYING and set(record.differences) == {"start"}
    assert len(calendar.patches) == 1 and telegram.sent[0].startswith("⚠️ Eintrag vorhanden, Angaben weichen ab")


def test_a_cancellation_is_proven_by_the_cancelled_entry(run):
    _store, checks, telegram, _clock, execute = run
    calendar = FakeGoogleCalendar(ENTRY)
    item = proposal(classification="cancellation", is_cancellation=True, time_changes=[])
    _executor, result = execute(calendar, item)
    record = record_of(checks, item)
    assert result.status == ProposalStatus.CREATED and (record.operation, record.state) == (
        "cancel", VerificationState.VERIFIED)
    assert telegram.sent == ["✅ Termin „Gemeinderatssitzung“ im Kalender abgesagt und geprüft."]


def test_an_entry_still_active_after_its_cancellation_is_reported_after_the_budget(run):
    _store, checks, telegram, clock, execute = run
    calendar = FakeGoogleCalendar(ENTRY)

    def ignoring(request):  # the provider accepts the change but the entry stays active
        answer = calendar(request)
        calendar.events["gr-1"].pop("status", None)
        return answer

    item = proposal(classification="cancellation", is_cancellation=True, time_changes=[])
    executor, _ = execute(ignoring, item)
    assert record_of(checks, item).last_error == "still_active" and telegram.sent == []
    for delay in (1, 5, 15, 60):
        clock.value += timedelta(seconds=delay)
        executor.resume()
    record = record_of(checks, item)
    assert record.state == VerificationState.MISMATCH and record.differences["status"].actual == "weiterhin aktiv"
    assert len(calendar.patches) == 1
    assert telegram.sent == ["⚠️ Eintrag vorhanden, Angaben weichen ab: „Gemeinderatssitzung“ – Status: erwartet "
                             "abgesagt, gefunden weiterhin aktiv. Mailhelp ändert den Eintrag nicht automatisch und "
                             "legt keinen neuen an."]


def test_an_entry_cancelled_before_is_checked_without_a_write(run):
    _store, checks, telegram, _clock, execute = run
    calendar = FakeGoogleCalendar()
    item = proposal(classification="cancellation", is_cancellation=True, time_changes=[])
    _executor, result = execute(calendar, item)
    record = record_of(checks, item)
    assert result.status == ProposalStatus.CREATED and record.receipt.result == "existing"
    assert calendar.patches == [] and telegram.sent == [
        "✅ Termin „Gemeinderatssitzung“ war im Kalender bereits abgesagt oder gelöscht (geprüft); nichts geändert."]


@pytest.mark.parametrize(("missing", "times", "message"), [
    (["description"], False, "fehlende Informationen wurden ergänzt und geprüft"),
    (["description"], True, "aktualisiert und geprüft: Beginn"),
    ([], False, "wurde erkannt und frisch geprüft"),
])
def test_a_recognised_duplicate_is_verified_as_it_is_now(run, missing, times, message):
    _store, checks, telegram, _clock, execute = run
    start = "2026-12-11T18:00:00+01:00" if not times else "2026-12-11T19:00:00+01:00"
    calendar = FakeGoogleCalendar(timed("dup-1", "Elternabend 4b", start, "2026-12-11T20:00:00+01:00"))
    matcher = lambda *_: ("call", CalendarDuplicateDecision(same_event=True, missing_fields=missing, reason="same"))  # noqa: E731
    _executor, result = execute(calendar, new_event(), matcher)
    record = record_of(checks, new_event())
    assert result.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
    assert record.operation == ("append" if missing or times else "duplicate")
    assert record.expected["title"] == "Elternabend 4b" and message in telegram.sent[-1]
    assert [request.method for request in calendar.requests].count("POST") == 0


def test_an_unclear_change_is_found_by_its_key_and_checked_against_its_intent(run):
    _store, checks, telegram, _clock, execute = run
    calendar = FakeGoogleCalendar(ENTRY)
    calendar.lose_patch_answer = True
    executor, result = execute(calendar, proposal())
    assert result.status == ProposalStatus.UNCERTAIN and record_of(checks, proposal()).is_intent
    calendar.lose_patch_answer = False
    executor.resume()
    record = record_of(checks, proposal())
    assert (record.receipt.result, record.state) == ("found_by_key", VerificationState.VERIFIED)
    assert len(calendar.patches) == 1 and "geändert und geprüft" in telegram.sent[-1]


def test_a_new_preparation_with_another_operation_replaces_the_intent(run):
    store, checks, _telegram, _clock, _execute = run
    writer = google_writer(FakeGoogleCalendar())
    item = new_event()
    checks.intent(item, writer, {"kind": "event", "title": "A"}, "create")
    checks.intent(item, writer, {"kind": "event", "title": "B"}, "duplicate")
    assert record_of(checks, item).operation == "duplicate" and len(store.names("write-verification-")) == 1


def test_a_delivered_calendar_file_is_recorded_as_not_verifiable(run):
    store, checks, _telegram, _clock, _execute = run
    telegram = Telegram()
    item = new_event(target="telegram")
    created, result = execute_confirmed(item, CalendarFileWriter(telegram, 2), lambda value: None,
                                        verification=checks)
    record = record_of(checks, item)
    assert created.status == ProposalStatus.CREATED and result["operation"] == "calendar_file"
    assert record.state == VerificationState.UNSUPPORTED and record.target.provider == "calendar_file"
    assert len(telegram.documents) == 1
