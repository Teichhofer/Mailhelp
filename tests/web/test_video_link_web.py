"""7.9: the conference link supplement in the web and in Telegram, and the explicit re-evaluation.

A proposal closed as ``already_exists`` before 7.9 is never re-offered on its own: only the
button "Mit Kalender erneut abgleichen" compares its link again and creates a new version that
needs its own confirmation.
"""
from datetime import UTC, datetime

import pytest

from mailhelp.domain.proposal import CalendarSupplement, DuplicateMatchInfo, DuplicateSource, ProposalStatus
from mailhelp.i18n import Locale, use_locale
from mailhelp.proposals.precheck import DuplicatePreCheckService
from mailhelp.review.command_reconciliation import _took_effect
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.errors import StaleCommand
from mailhelp.telegram.formatting import format_proposal
from tests.fakes.calendar_fakes import FakeGoogleCalendar, google_writer, timed
from tests.scenarios.web_scenario import proposal, save_mail

LINK = "https://example.zoom.us/j/555?pwd=Xy1"
OTHER = "https://meet.google.com/old-link"
ENTRY = timed("ev-9", "Online-Elternabend", "2026-11-26T19:30:00+01:00", "2026-11-26T21:00:00+01:00",
              description="Eigene Notizen")


def closed(number=60, **fields):
    """A proposal the pre-check of 7.7 closed as a duplicate although it carried the link."""
    values = dict(kind="event", title="Online-Elternabend", target="calendar-1",
                  start=datetime(2026, 11, 26, 18, 30, tzinfo=UTC), end=datetime(2026, 11, 26, 20, 0, tzinfo=UTC),
                  video_link=LINK, status=ProposalStatus.ALREADY_EXISTS,
                  duplicate_match=DuplicateMatchInfo(source=DuplicateSource.GOOGLE_CALENDAR, external_id="ev-9",
                                                     matched_title="Online-Elternabend"))
    values.update(fields)
    return proposal(number, "videolink", **values)


def page_of(web, item):
    web.site.refresh_overview()
    return web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()


def test_an_old_duplicate_with_a_link_is_compared_again_only_on_request(web):
    item = closed()
    save_mail(web.store, 60, "schule@example.test", "Einwahllink", [item])
    calendar = FakeGoogleCalendar(ENTRY)
    web.dialog.decision_service.precheck = DuplicatePreCheckService(writer=google_writer(calendar))
    page = page_of(web, item)
    assert "Mit Kalender erneut abgleichen" in page and 'value="confirm"' not in page
    web.submit(web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="recheck_proposal",
                        proposal_id="videolink"))
    web.run()
    current = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert (current.version, current.status, current.duplicate_match) == (2, ProposalStatus.PENDING_CONFIRMATION, None)
    assert current.calendar_supplement is not None and current.target_event_id == "ev-9"
    page = page_of(web, item)
    assert "Bestehenden Termin aktualisieren: Videolink ergänzen" in page and f"<strong>{LINK}</strong>" in page
    assert "Mit Kalender erneut abgleichen" not in page
    assert calendar.patches == [] and web.writer.created == 0  # the re-check never writes


def test_a_re_evaluation_is_bound_to_its_version_and_survives_a_restart(web):
    item = closed()
    save_mail(web.store, 60, "schule@example.test", "Einwahllink", [item])
    calendar = FakeGoogleCalendar({**ENTRY, "description": f"Notizen {LINK}"})  # the link is there by now
    web.dialog.decision_service.precheck = DuplicatePreCheckService(writer=google_writer(calendar))
    fields = web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="recheck_proposal", proposal_id="videolink")
    assert web.submit({**fields, "version": "2", "key": "f" * 32}).status == 409  # not the offered version
    command = ReviewCommand(kind=CommandKind.RECHECK, source=CommandSource.WEB, actor="web:x",
                            mail_id=item.source_mail_id, proposal_id=item.id, version=1, idempotency_key="restart-7")
    assert not _took_effect(web.dialog.review, command)  # queued before a restart: still to be done
    web.submit(fields)
    web.run()
    current = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert (current.version, current.status) == (2, ProposalStatus.ALREADY_EXISTS)
    assert current.calendar_supplement is None and calendar.patches == []
    assert _took_effect(web.dialog.review, command)
    # The new closed version is offered again; the old one is refused as outdated.
    assert web.submit({**fields, "key": "e" * 32}).status == 409


def test_an_open_proposal_without_a_link_is_rechecked_as_before(web):
    item = closed(64, video_link=None)
    save_mail(web.store, 64, "schule@example.test", "Elternabend", [item])
    command = ReviewCommand(kind=CommandKind.RECHECK, source=CommandSource.WEB, actor="web:x",
                            mail_id=item.source_mail_id, proposal_id=item.id, version=1, idempotency_key="closed-1")
    with pytest.raises(StaleCommand):
        web.dialog.review._recheck_target(command)
    assert _took_effect(web.dialog.review, command)  # nothing to do for a closed proposal without link


def test_an_old_duplicate_without_a_link_offers_nothing(web):
    item = closed(61, video_link=None)
    save_mail(web.store, 61, "schule@example.test", "Elternabend", [item])
    page = page_of(web, item)
    assert "Mit Kalender erneut abgleichen" not in page and 'class="actions decision-bar"' not in page


def test_a_replacement_strikes_the_calendar_link(web):
    supplement = CalendarSupplement(operation="replace", previous=OTHER, proposed=LINK, target_event_id="ev-9",
                                    source_mail_id="0" * 23 + "1")
    item = closed(62, status=ProposalStatus.PENDING_CONFIRMATION, duplicate_match=None, target_event_id="ev-9")
    item = item.model_copy(update={"calendar_supplement": supplement.model_copy(
        update={"source_mail_id": item.source_mail_id})})
    save_mail(web.store, 62, "schule@example.test", "Neuer Einwahllink", [item])
    page = page_of(web, item)
    assert "Videolink ersetzen" in page and f"<del>{OTHER}</del> → <strong>{LINK}</strong>" in page
    assert 'class="card kind-change' in page or "kind-change" in page


def test_telegram_names_the_target_update_in_both_languages():
    base = closed(63, status=ProposalStatus.PENDING_CONFIRMATION, duplicate_match=None, target_event_id="ev-9")
    added = base.model_copy(update={"calendar_supplement": CalendarSupplement(
        operation="add", proposed=LINK, target_event_id="ev-9", source_mail_id=base.source_mail_id)})
    text = format_proposal(added, "Europe/Berlin")
    assert "🔗 Bestehenden Termin aktualisieren: Videolink ergänzen" in text and f"- neu: {LINK}" in text
    assert "🔄 Terminänderung gegenüber Kalender" not in text and "- bisher" not in text
    replaced = added.model_copy(update={"calendar_supplement": added.calendar_supplement.model_copy(
        update={"operation": "replace", "previous": OTHER})})
    with use_locale(Locale.EN):
        english = format_proposal(replaced, "Europe/Berlin")
    assert "🔗 Update existing event: replace video link" in english
    assert f"- before: {OTHER}" in english and f"- new: {LINK}" in english
