"""Planung 5.0, step 21.3 (5.0.7): card kinds by stripe, symbol and text in an actual browser."""
from datetime import UTC, date, datetime

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def event(number, pid, **fields):
    return proposal(number, pid, kind="event", title=f"Sitzung {pid}", target="calendar-1",
                    start=datetime(2026, 12, 11, 17, tzinfo=UTC), end=datetime(2026, 12, 11, 19, tzinfo=UTC),
                    evidence="Die Sitzung beginnt um 18 Uhr im Rathaus.", **fields)


def test_kinds_are_told_apart_by_stripe_symbol_and_text(page, mailhelp):
    moved = dict(classification="change", original_date=date(2026, 12, 4), target_event_id="gr-1")
    save_mail(mailhelp.store, 61, "Rathaus <rathaus@x.test>", "Sitzung", [event(61, "termin")])
    save_mail(mailhelp.store, 62, "Verein <verein@x.test>", "Antrag", [
        proposal(62, "aufgabe", title="Antrag abgeben", evidence="Bitte den Antrag bis Freitag abgeben.")])
    save_mail(mailhelp.store, 63, "Rathaus <rathaus@x.test>", "Verschiebung", [
        event(63, "aenderung", time_changes=["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr"], **moved)])
    save_mail(mailhelp.store, 64, "Rathaus <rathaus@x.test>", "Absage", [
        event(64, "absage", is_cancellation=True, **{**moved, "classification": "cancellation"})])
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/")
    stripes = {}
    for number, pid, kind, label in ((61, "termin", "event", "📅 Termin"), (62, "aufgabe", "task", "✅ Aufgabe"),
                                     (63, "aenderung", "change", "🔄 Terminänderung"),
                                     (64, "absage", "cancel", "🚫 Terminabsage")):
        card = page.locator(f"article#v-{mail_id(number)}-{pid}").first
        expect(card).to_have_class(f"card kind-{kind}")
        expect(card.locator(".kind-label")).to_have_text(label)
        stripes[kind] = card.evaluate("node => [getComputedStyle(node).borderLeftColor,"
                                      " getComputedStyle(node).borderLeftStyle]")
    # Appointment, task and cancellation differ in colour; a change shares the appointment colour
    # and differs by its double stripe (besides symbol and text).
    assert len({stripes[kind][0] for kind in ("event", "task", "cancel")}) == 3
    assert stripes["change"] == [stripes["event"][0], "double"]
    if page.device == "desktop":
        # The card current in Telegram keeps its stripe in the split view's list.
        current = page.locator(".master-pane article.card.current.kind-event").first
        assert current.evaluate("node => getComputedStyle(node).borderLeftColor") == stripes["event"][0]
    assert audit(page, "card-kinds-" + page.device, page.mobile) == []
    page.emulate_media(color_scheme="dark")
    assert audit(page, "card-kinds-dark-" + page.device, page.mobile) == []
