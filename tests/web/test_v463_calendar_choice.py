"""4.6, step 17.4: before/after display and choosing the meant calendar entry (web and Telegram)."""
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from mailhelp.models import CalendarCandidate, ProposalStatus
from mailhelp.proposals.calendar_target import AMBIGUOUS
from mailhelp.proposals.precheck import DuplicatePreCheckService
from mailhelp.review.calendar_display import candidate_label, change_parts
from mailhelp.review.commands import ReviewCommand
from mailhelp.review.results import ResultStatus
from mailhelp.telegram.callbacks import Decision, DecisionAction
from mailhelp.telegram.formatting import format_proposal
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed
from tests.fakes.shared_telegram_dialog import callback
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

FIRST = timed("gr-1", "Gemeinderatssitzung", "2026-12-04T18:00:00+01:00", "2026-12-04T20:00:00+01:00")
SECOND = timed("gr-2", "Gemeinderatssitzung Ausschuss", "2026-12-04T16:00:00+01:00", "2026-12-04T17:00:00+01:00")


def candidates():
    return [CalendarCandidate(event_id="gr-1", title="Gemeinderatssitzung",
                              start=datetime(2026, 12, 4, 17, tzinfo=UTC), end=datetime(2026, 12, 4, 19, tzinfo=UTC)),
            CalendarCandidate(event_id="gr-2", title="Gemeinderatssitzung Ausschuss",
                              start=datetime(2026, 12, 4, 15, tzinfo=UTC), end=datetime(2026, 12, 4, 16, tzinfo=UTC))]


def ambiguous(number=50):
    return proposal(number, "aenderung", kind="event", classification="change", title="Gemeinderatssitzung",
                    target="calendar-1", start=datetime(2026, 12, 11, 17, tzinfo=UTC),
                    end=datetime(2026, 12, 11, 19, tzinfo=UTC), original_date=date(2026, 12, 4),
                    calendar_candidates=candidates(), open_questions=[AMBIGUOUS])


def prepared(web):
    item = ambiguous()
    save_mail(web.store, 50, "rathaus@example.test", "Terminverschiebung", [item])
    calendar = FakeGoogleCalendar(FIRST, SECOND)
    web.dialog.decision_service.precheck = DuplicatePreCheckService(writer=google_writer(calendar))
    return item, calendar


def current(web, item):
    return web.dialog.repository.load_current(item.source_mail_id, item.id)


def test_labels_and_change_parts_name_the_values_before_and_after():
    timed_, all_day = candidates()[0], CalendarCandidate(event_id="d", start=date(2026, 12, 4), end=date(2026, 12, 5))
    assert candidate_label(timed_, "Europe/Berlin") == "„Gemeinderatssitzung“ am 04.12.2026 18:00 Uhr"
    assert candidate_label(all_day, None) == "„ohne Titel“ am 04.12.2026"
    assert change_parts("Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr") == (
        "Beginn", "04.12.2026 18:00 Uhr", "11.12.2026 18:00 Uhr")
    assert change_parts("Ort Saal 1 → Saal 2") == ("Ort", "Saal 1", "Saal 2")
    for unreadable in ("Zeit aktualisiert", "Beginn → neu", "Beginn alt →", ""):
        assert change_parts(unreadable) is None


def test_the_web_card_strikes_the_old_value_and_offers_the_candidates(web):
    item, _ = prepared(web)
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()
    assert "Passende Kalendertermine" in page and "„Gemeinderatssitzung Ausschuss“ am 04.12.2026 16:00 Uhr" in page
    assert page.count('name="kind" value="choose_calendar_event"') == 2
    moved = item.model_copy(update={"calendar_candidates": [], "open_questions": [], "target_event_id": "gr-1",
                                    "status": ProposalStatus.PENDING_CONFIRMATION,
                                    "time_changes": ["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr",
                                                     "Zeit unbekannt"]})
    save_mail(web.store, 50, "rathaus@example.test", "Terminverschiebung", [moved])
    web.site.refresh_overview()
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()
    assert "Beginn: <del>04.12.2026 18:00 Uhr</del> → <strong>11.12.2026 18:00 Uhr</strong>" in page
    assert "<li>Zeit unbekannt</li>" in page and "Bestehenden Termin aktualisieren" in page
    cancelled = moved.model_copy(update={"classification": "cancellation", "is_cancellation": True, "time_changes": []})
    save_mail(web.store, 50, "rathaus@example.test", "Terminabsage", [cancelled])
    web.site.refresh_overview()
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()
    assert "Termin im Kalender stornieren" in page and "Termin absagen" in page


def test_choosing_in_the_web_binds_the_entry_in_a_new_version(web):
    item, _ = prepared(web)
    web.submit(web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="choose_calendar_event", candidate="1"))
    web.run()
    chosen = current(web, item)
    assert (chosen.version, chosen.target_event_id, chosen.calendar_candidates) == (2, "gr-2", [])
    assert AMBIGUOUS not in chosen.open_questions
    # The changed proposal is presented again for an explicit confirmation; nothing is written.
    assert web.writer.created == 0 and chosen.status == ProposalStatus.PENDING_CONFIRMATION


def test_a_choice_for_an_old_version_or_a_missing_candidate_has_no_effect(web):
    item, calendar = prepared(web)
    actor = "web:" + web.auth.sessions()[0].id
    command = dict(kind="choose_calendar_event", source="web", actor=actor, mail_id=item.source_mail_id,
                   proposal_id=item.id, version=1, idempotency_key="choose-candidate-1", candidate=1)
    web.dialog.persist(item.model_copy(update={"version": 2}))
    assert web.dialog.review.execute(ReviewCommand(**command)).status == ResultStatus.STALE
    command.update(version=2, idempotency_key="choose-candidate-2", candidate=5)
    assert web.dialog.review.execute(ReviewCommand(**command)).status == ResultStatus.INVALID
    web.dialog.decision_service.precheck = None
    command.update(idempotency_key="choose-candidate-3", candidate=0)
    assert web.dialog.review.execute(ReviewCommand(**command)).status == ResultStatus.INVALID
    assert current(web, item).target_event_id is None and calendar.patches == []


def test_telegram_lists_the_candidates_and_offers_a_button_for_each(web):
    item, _ = prepared(web)
    web.dialog.delivery.deliver(item)
    text, markup = web.telegram.sent[-1][1], web.telegram.sent[-1][2]
    assert "📅 Passende Kalendertermine:\n1. „Gemeinderatssitzung“ am 04.12.2026 18:00 Uhr" in text
    labels = [button["text"] for row in markup["inline_keyboard"] for button in row]
    assert labels.count("Termin 1 meinen") == labels.count("Termin 2 meinen") == 1
    choice = next(Decision.parse(button["callback_data"], web.store)
                  for row in markup["inline_keyboard"] for button in row if button["text"] == "Termin 1 meinen")
    assert (choice.action, choice.candidate, choice.version) == (DecisionAction.CHOOSE_EVENT, 0, 1)
    web.telegram.updates = [callback(1, choice.encode(web.store))]
    web.run()
    assert current(web, item).target_event_id == "gr-1"


def test_telegram_names_changes_as_before_and_after_in_plain_text():
    moved = ambiguous().model_copy(update={
        "calendar_candidates": [], "open_questions": [], "target_event_id": "gr-1",
        "status": ProposalStatus.PENDING_CONFIRMATION,
        "time_changes": ["Ort Saal 1 → Saal 2", "Zeit aktualisiert"]})
    text = format_proposal(moved, "Europe/Berlin")
    assert "🔄 Terminänderung gegenüber Kalender:\n- Ort: bisher Saal 1 → neu Saal 2\n- Zeit aktualisiert" in text


def test_a_candidate_belongs_to_the_choice_command_only():
    base = dict(source="web", actor="web:x", mail_id=mail_id(1), proposal_id="p", version=1,
                idempotency_key="candidate-check")
    with pytest.raises(ValidationError, match="Terminauswahl"):
        ReviewCommand(kind="choose_calendar_event", **base)
    with pytest.raises(ValidationError, match="Terminauswahl"):
        ReviewCommand(kind="confirm", candidate=0, **base)
    with pytest.raises(ValidationError):
        ReviewCommand(kind="choose_calendar_event", candidate=10, **base)
    decision = dict(mail_id=mail_id(1), proposal_id="p", version=1)
    with pytest.raises(ValidationError, match="Terminauswahl"):
        Decision(action=DecisionAction.CHOOSE_EVENT, **decision)
    with pytest.raises(ValidationError, match="Terminauswahl"):
        Decision(action=DecisionAction.CONFIRM, candidate=0, **decision)
