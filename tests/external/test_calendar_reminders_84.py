"""8.4: Automatic calendar reminders per target profile (Planung-8.4.md)."""

from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import ValidationError

from mailhelp import state_names
from mailhelp.config import Secrets, TargetProfileSettings, TargetSettings
from mailhelp.domain.proposal import (
    CalendarSupplement,
    DuplicateMatchInfo,
    DuplicateSource,
    Proposal,
    ProposalStatus,
)
from mailhelp.domain.verification import VerificationState
from mailhelp.external.caldav import CalDavCalendar
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.http_writer import HttpWriter
from mailhelp.external.icalendar_data import event_resource, event_summary, parse_calendar, updated_event
from mailhelp.external.microsoft import OutlookCalendar
from mailhelp.external.providers import build_writers
from mailhelp.external.reminders import (
    effective_reminder,
    google_reminders_payload,
    minutes_from_trigger,
    reminder_fact_from_google,
    reminder_fact_from_microsoft,
    reminder_preview_text,
    trigger_for_minutes,
)
from mailhelp.i18n import Locale, use_locale
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.proposals import profile_binding
from mailhelp.review.cards import card_content
from mailhelp.review.verification_texts import FIELD_LABELS
from mailhelp.telegram.formatting import format_proposal
from mailhelp.web import mailbox_site, review_pages, settings_pages
from tests.fakes.shared_application import settings as make_settings
from tests.scenarios.web_scenario import proposal as make_proposal

BERLIN = ZoneInfo("Europe/Berlin")


class _Token:
    def access_token(self) -> str:
        return "synthetic-token"


def _event_proposal(**overrides) -> Proposal:
    base = dict(
        status="confirmed",
        confirmed_web_actor=None,
        kind="event",
        title="Elternabend",
        target="primary",
        start=datetime(2026, 7, 2, 19, 0, tzinfo=BERLIN),
        end=datetime(2026, 7, 2, 21, 0, tzinfo=BERLIN),
        location="Aula",
        description="Agenda",
    )
    base.update(overrides)
    return make_proposal(3, "e", **base)


def test_target_settings_defaults_bounds_and_policy_hash(tmp_path):
    defaults = TargetSettings(google_calendar="primary", todoist_project="inbox")
    assert defaults.calendar_reminder_enabled is True
    assert defaults.calendar_reminder_minutes == 5

    zero = TargetSettings(
        google_calendar="primary",
        todoist_project="inbox",
        calendar_reminder_enabled=True,
        calendar_reminder_minutes=0,
    )
    assert zero.calendar_reminder_minutes == 0

    disabled_prepared = TargetSettings(
        google_calendar="primary",
        todoist_project="inbox",
        calendar_reminder_enabled=False,
        calendar_reminder_minutes=1440,
    )
    assert disabled_prepared.calendar_reminder_enabled is False
    assert disabled_prepared.calendar_reminder_minutes == 1440

    with pytest.raises(ValidationError):
        TargetSettings(google_calendar="primary", todoist_project="inbox", calendar_reminder_minutes=-1)
    with pytest.raises(ValidationError):
        TargetSettings(google_calendar="primary", todoist_project="inbox", calendar_reminder_minutes=1441)

    settings_a = make_settings(tmp_path)
    settings_b = settings_a.model_copy(
        update={
            "targets": settings_a.targets.model_copy(update={"calendar_reminder_minutes": 15}),
            "target_profiles": [
                TargetProfileSettings(
                    id=2,
                    label="Privat",
                    google_calendar="privat",
                    todoist_project="privat",
                    calendar_reminder_enabled=False,
                    calendar_reminder_minutes=30,
                )
            ],
        }
    )
    assert profile_binding.policy_hash(settings_a) != profile_binding.policy_hash(settings_b)
    assert profile_binding.calendar_reminder(settings_b, _event_proposal(target_profile=1)) == (True, 15)
    assert profile_binding.calendar_reminder(settings_b, _event_proposal(target_profile=2)) == (False, 30)
    assert profile_binding.calendar_reminder(settings_b, _event_proposal(target_profile=9)) == (True, 15)


def test_reminder_helpers_cover_all_branches_and_locales():
    assert effective_reminder(True, 5, all_day=False) == 5
    assert effective_reminder(True, 0, all_day=False) == 0
    assert effective_reminder(False, 5, all_day=False) is None
    assert effective_reminder(True, 5, all_day=True) is None

    assert google_reminders_payload(True, 5, all_day=True) is None
    assert google_reminders_payload(False, 5, all_day=False) == {"useDefault": False, "overrides": []}
    assert google_reminders_payload(True, 0, all_day=False) == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": 0}],
    }

    assert reminder_fact_from_google(None) is None
    assert reminder_fact_from_google({"useDefault": True}) == "default"
    assert reminder_fact_from_google({"useDefault": None}) is None
    assert reminder_fact_from_google({"useDefault": False, "overrides": []}) == "none"
    assert reminder_fact_from_google({"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]}) == "5"
    assert reminder_fact_from_google({"useDefault": False, "overrides": [{"method": "email", "minutes": 5}]}) == "other"
    assert reminder_fact_from_google({"useDefault": False, "overrides": "bad"}) == "other"

    assert reminder_fact_from_microsoft(None, None) is None
    assert reminder_fact_from_microsoft(False, 15) == "none"
    assert reminder_fact_from_microsoft(True, None) == "other"
    assert reminder_fact_from_microsoft(True, 0) == "0"

    assert trigger_for_minutes(0) == "PT0S"
    assert trigger_for_minutes(15) == "-PT15M"
    assert minutes_from_trigger("PT0S") == 0
    assert minutes_from_trigger("-PT5M") == 5
    assert minutes_from_trigger("-PT1H30M") == 90
    assert minutes_from_trigger("-PT30S") is None
    assert minutes_from_trigger("INVALID") is None

    with use_locale(Locale.DE):
        assert reminder_preview_text(True, 5, all_day=False) == "Erinnerung: 5 Minuten vor Beginn"
        assert reminder_preview_text(True, 1, all_day=False) == "Erinnerung: 1 Minute vor Beginn"
        assert reminder_preview_text(True, 0, all_day=False) == "Erinnerung: zum Beginn"
        assert reminder_preview_text(False, 5, all_day=False) == "Erinnerung: keine"
        assert reminder_preview_text(True, 5, all_day=True) is None
        assert reminder_preview_text(True, 5, all_day=False, operation="cancel") is None
        assert reminder_preview_text(True, 5, all_day=False, duplicate_skipped=True) is None

    with use_locale(Locale.EN):
        assert reminder_preview_text(True, 5, all_day=False) == "Reminder: 5 minutes before start"
        assert reminder_preview_text(True, 1, all_day=False) == "Reminder: 1 minute before start"
        assert reminder_preview_text(True, 0, all_day=False) == "Reminder: at start"
        assert reminder_preview_text(False, 5, all_day=False) == "Reminder: none"


def test_google_calendar_payload_update_duplicate_and_verification(tmp_path):
    sent: list[tuple[str, dict]] = []
    stored: dict[str, dict] = {}
    override_get: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/events"):
            body = json.loads(request.content.decode())
            sent.append(("POST", body))
            ev_id = f"ev-{len(stored) + 1}"
            stored[ev_id] = {**body, "id": ev_id, "htmlLink": f"https://calendar.example.invalid/{ev_id}"}
            return httpx.Response(200, json=stored[ev_id])
        if request.method == "PATCH" and "/events/" in path:
            ev_id = path.rsplit("/", 1)[1]
            body = json.loads(request.content.decode())
            sent.append(("PATCH", body))
            stored[ev_id] = {**stored[ev_id], **body}
            return httpx.Response(200, json=stored[ev_id])
        if request.method == "GET" and "/events/" in path:
            ev_id = path.rsplit("/", 1)[1]
            data = override_get.get(ev_id, stored.get(ev_id))
            return httpx.Response(200, json=data) if data else httpx.Response(404)
        if request.method == "GET" and path.endswith("/calendars/primary"):
            return httpx.Response(200, json={"id": "owner@example.test"})
        return httpx.Response(200, json={"items": []})

    # 1. Timed event with default 5-minute popup reminder + verification
    writer = HttpWriter(
        "google_calendar", "tok", "primary", calendar_timezone="Europe/Berlin",
        transport=httpx.MockTransport(handler),
    )
    with JsonStore(tmp_path / "data") as store:
        checks = WriteVerifications(store)
        item = _event_proposal()

        def persist(value: Proposal) -> None:
            store.save(state_names.proposal(value.source_mail_id, value.id), value.model_dump(mode="json"))

        persist(item)
        verifying, _res = execute_confirmed(item, writer, persist, verification=checks)
        created, record = checks.check(verifying, writer, persist)
        assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
        assert sent[0][1]["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]}

        # 2. Mismatch when provider silently falls back to useDefault=True
        override_get["ev-2"] = {
            **stored["ev-1"],
            "id": "ev-2",
            "reminders": {"useDefault": True},
        }
        item2 = _event_proposal(id="p2")
        persist(item2)
        verifying2, _res2 = execute_confirmed(item2, writer, persist, verification=checks)
        still_verifying, record2 = checks.check(verifying2, writer, persist)
        assert still_verifying.status == ProposalStatus.VERIFYING
        assert record2.state == VerificationState.MISMATCH
        assert record2.differences["reminder"].expected == "5"
        assert record2.differences["reminder"].actual == "default"
        assert FIELD_LABELS["reminder"] == "Erinnerung"

    # 3. Disabled reminder sends explicit empty overrides
    writer_off = HttpWriter(
        "google_calendar", "tok", "primary", calendar_timezone="Europe/Berlin",
        transport=httpx.MockTransport(handler),
    )
    writer_off.calendar_reminder_enabled = False
    writer_off.calendar_reminder_minutes = 15
    writer_off.create(_event_proposal(id="p3"), "key-off")
    assert sent[-1][1]["reminders"] == {"useDefault": False, "overrides": []}

    # 4. All-day event sends no reminders
    writer.create(
        _event_proposal(id="p4", all_day=True, start=date(2026, 7, 2), end=date(2026, 7, 3)),
        "key-allday",
    )
    assert "reminders" not in sent[-1][1]

    # 5. Confirmed timed update carries reminder
    update_prop = _event_proposal(
        id="p5",
        target_event_id="ev-1",
        time_changes=["Beginn geändert"],
    )
    writer_off.create(update_prop, "key-upd")
    assert sent[-1][0] == "PATCH"
    assert sent[-1][1]["reminders"] == {"useDefault": False, "overrides": []}


def test_outlook_calendar_payload_and_verification(tmp_path):
    sent: list[tuple[str, dict]] = []
    stored: dict[str, dict] = {}
    override_get: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/events"):
            body = json.loads(request.content.decode())
            sent.append(("POST", body))
            ev_id = f"ms-{len(stored) + 1}"
            stored[ev_id] = {
                "id": ev_id,
                "subject": body["subject"],
                "body": body.get("body"),
                "location": body.get("location"),
                "start": body["start"],
                "end": body["end"],
                "isAllDay": body.get("isAllDay", False),
                "isCancelled": False,
                "webLink": f"https://outlook.office.com/{ev_id}",
                "isReminderOn": body.get("isReminderOn"),
                "reminderMinutesBeforeStart": body.get("reminderMinutesBeforeStart"),
            }
            return httpx.Response(201, json=stored[ev_id])
        if request.method == "GET" and "/events/" in path:
            ev_id = path.rsplit("/", 1)[1]
            data = override_get.get(ev_id, stored.get(ev_id))
            return httpx.Response(200, json=data) if data else httpx.Response(404)
        if request.method == "GET" and path.endswith("/me"):
            return httpx.Response(200, json={"id": "user-1"})
        return httpx.Response(200, json={"value": []})

    writer = OutlookCalendar(
        _Token(), "default", transport=httpx.MockTransport(handler),
        calendar_timezone="Europe/Berlin",
    )
    with JsonStore(tmp_path / "data") as store:
        checks = WriteVerifications(store)
        item = _event_proposal(target="default", target_provider="outlook")

        def persist(value: Proposal) -> None:
            store.save(state_names.proposal(value.source_mail_id, value.id), value.model_dump(mode="json"))

        persist(item)
        verifying, _ = execute_confirmed(item, writer, persist, verification=checks)
        created, record = checks.check(verifying, writer, persist)
        assert created.status == ProposalStatus.CREATED and record.state == VerificationState.VERIFIED
        assert sent[0][1]["isReminderOn"] is True
        assert sent[0][1]["reminderMinutesBeforeStart"] == 5

        # Mismatch if Graph drops reminder
        item2 = _event_proposal(id="p2", target="default", target_provider="outlook")
        persist(item2)
        verifying2, _ = execute_confirmed(item2, writer, persist, verification=checks)
        override_get["ms-2"] = {**stored["ms-2"], "isReminderOn": False}
        still_verifying, record2 = checks.check(verifying2, writer, persist)
        assert still_verifying.status == ProposalStatus.VERIFYING
        assert record2.state == VerificationState.MISMATCH
        assert record2.differences["reminder"].expected == "5"
        assert record2.differences["reminder"].actual == "none"

    # Disabled & all-day
    writer_off = OutlookCalendar(
        _Token(), "default", transport=httpx.MockTransport(handler),
        calendar_timezone="Europe/Berlin",
    )
    writer_off.calendar_reminder_enabled = False
    writer_off.calendar_reminder_minutes = 10
    writer_off.create(_event_proposal(id="p3", target="default", target_provider="outlook"), "key-ms-off")
    assert sent[-1][1]["isReminderOn"] is False
    assert "reminderMinutesBeforeStart" not in sent[-1][1]

    writer.create(
        _event_proposal(
            id="p4", target="default", target_provider="outlook",
            all_day=True, start=date(2026, 7, 2), end=date(2026, 7, 3),
        ),
        "key-ms-allday",
    )
    assert sent[-1][1]["isAllDay"] is True
    assert sent[-1][1]["isReminderOn"] is False


def test_caldav_valarm_creation_update_preservation_and_verification(tmp_path):
    base_body = {
        "summary": "Elternabend",
        "description": "Agenda",
        "start": {"dateTime": "2026-07-02T19:00:00+02:00"},
        "end": {"dateTime": "2026-07-02T21:00:00+02:00"},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]},
    }
    ics = event_resource("uid-1", base_body, "k1")
    text = ics.decode()
    assert text.count("BEGIN:VALARM") == 1
    assert "TRIGGER:-PT5M" in text
    assert "ACTION:DISPLAY" in text
    assert "DESCRIPTION:Mailhelp-Erinnerung" in text
    assert event_summary(parse_calendar(ics), "Europe/Berlin")["reminder"] == "5"

    # 0 minutes -> PT0S
    zero_ics = event_resource(
        "uid-0",
        {**base_body, "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]}},
        "k0",
    )
    assert "TRIGGER:PT0S" in zero_ics.decode()
    assert event_summary(parse_calendar(zero_ics), "Europe/Berlin")["reminder"] == "0"

    # Disabled -> no VALARM; update replaces old VALARM and preserves foreign properties
    with_foreign = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-keep\r\n"
        b"X-CUSTOM:keep-me\r\nDTSTART:20260702T170000Z\r\nDTEND:20260702T190000Z\r\n"
        b"SUMMARY:Alt\r\nBEGIN:VALARM\r\nTRIGGER:-PT30M\r\nACTION:DISPLAY\r\nDESCRIPTION:Alt\r\nEND:VALARM\r\n"
        b"END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    updated_off = updated_event(
        with_foreign,
        {**base_body, "reminders": {"useDefault": False, "overrides": []}},
        "k2",
    )
    assert b"X-CUSTOM:keep-me" in updated_off
    assert b"UID:uid-keep" in updated_off
    assert b"BEGIN:VALARM" not in updated_off
    assert event_summary(parse_calendar(updated_off), "Europe/Berlin")["reminder"] == "none"

    # Update to new reminder replaces previous VALARM cleanly
    updated_on = updated_event(
        with_foreign,
        {**base_body, "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}},
        "k3",
    )
    assert updated_on.decode().count("BEGIN:VALARM") == 1
    assert b"TRIGGER:-PT10M" in updated_on
    assert b"X-CUSTOM:keep-me" in updated_on

    # End-to-end CalDavCalendar read_entry verification
    resources: dict[str, bytes] = {}
    collection = "https://dav.example.test/cal/"

    def dav_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "PUT":
            resources[url] = request.content
            return httpx.Response(201, headers={"ETag": '"e1"'})
        if request.method == "GET" and url in resources:
            return httpx.Response(200, content=resources[url], headers={"ETag": '"e1"'})
        if request.method == "PROPFIND":
            return httpx.Response(207, content=b"<d:multistatus xmlns:d='DAV:'/>")
        return httpx.Response(404)

    writer = CalDavCalendar(
        collection, "u", "p", transport=httpx.MockTransport(dav_handler),
        calendar_timezone="Europe/Berlin",
    )
    prop = _event_proposal(target=collection, target_provider="caldav")
    created = writer.create(prop, "key-dav-1")
    read = writer.read_entry(created["id"])
    assert read is not None and read.facts["reminder"] == "5"


def test_build_writers_passes_profile_reminder_settings(tmp_path):
    settings = make_settings(tmp_path)
    settings = settings.model_copy(
        update={
            "targets": settings.targets.model_copy(
                update={"calendar_reminder_enabled": False, "calendar_reminder_minutes": 20}
            )
        }
    )
    secrets = Secrets(
        imap={1: {"username": "u", "password": "p"}},
        openrouter_api_key="o",
        todoist_token="t",
        google_oauth_client_id="gi",
        google_oauth_client_secret="gs",
        google_oauth_refresh_token="gr",
    )
    built = build_writers(settings, secrets, tmp_path, transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    try:
        assert built.calendar.calendar_reminder_enabled is False
        assert built.calendar.calendar_reminder_minutes == 20
    finally:
        built.close()


def test_web_telegram_previews_and_settings_controls():
    timed_event = _event_proposal()
    all_day_event = _event_proposal(all_day=True, start=date(2026, 7, 2), end=date(2026, 7, 3))
    cancel_event = _event_proposal(target_event_id="ev-1", is_cancellation=True)
    dup_event = _event_proposal(
        duplicate_match=DuplicateMatchInfo(source=DuplicateSource.GOOGLE_CALENDAR, matched_title="Elternabend")
    )
    video_only = _event_proposal(
        target_event_id="ev-1",
        calendar_supplement=CalendarSupplement(
            operation="add",
            proposed="https://video.example.test/room",
            target_event_id="ev-1",
            source_mail_id=timed_event.source_mail_id,
        ),
    )

    with use_locale(Locale.DE):
        card_on = card_content(timed_event, "Europe/Berlin", reminder_setting=(True, 5))
        assert card_on.reminder == "Erinnerung: 5 Minuten vor Beginn"
        assert "Erinnerung: 5 Minuten vor Beginn" in "".join(review_pages._card_facts(card_on))
        assert "🔔 Erinnerung: 5 Minuten vor Beginn" in format_proposal(
            timed_event, "Europe/Berlin", reminder_setting=(True, 5)
        )

        card_off = card_content(timed_event, "Europe/Berlin", reminder_setting=(False, 5))
        assert card_off.reminder == "Erinnerung: keine"
        assert card_content(all_day_event, "Europe/Berlin", reminder_setting=(True, 5)).reminder is None
        assert card_content(cancel_event, "Europe/Berlin", reminder_setting=(True, 5)).reminder is None
        assert card_content(dup_event, "Europe/Berlin", reminder_setting=(True, 5)).reminder is None
        assert card_content(video_only, "Europe/Berlin", reminder_setting=(True, 5)).reminder is None

        html_active = settings_pages._input(
            "targets.calendar_reminder_minutes", 5, {"targets": {"calendar_reminder_enabled": True}}
        )
        assert 'type="number" min="0" max="1440"' in html_active
        assert "aktuell deaktiviert" not in html_active

        html_inactive = settings_pages._input(
            "targets.calendar_reminder_minutes", 5, {"targets": {"calendar_reminder_enabled": False}}
        )
        assert 'type="number" min="0" max="1440"' in html_inactive
        assert "aktuell deaktiviert" in html_inactive

        profile_control = mailbox_site.control("calendar_reminder_minutes", 5, prefix="profile-2")
        assert 'type="number" min="0" max="1440"' in profile_control

    with use_locale(Locale.EN):
        card_en = card_content(timed_event, "Europe/Berlin", reminder_setting=(True, 0))
        assert card_en.reminder == "Reminder: at start"
        assert "🔔 Reminder: at start" in format_proposal(
            timed_event, "Europe/Berlin", reminder_setting=(True, 0)
        )
