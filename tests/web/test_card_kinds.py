"""Planung 5.0, step 21.3 (5.0.7): every card shows its kind by stripe, symbol and text."""
import re
from contextlib import nullcontext
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.web import pages
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

CSS = (Path(pages.__file__).parent / "static" / "app.css").read_text(encoding="utf-8")


def event(**fields):
    return proposal(60, "termin", kind="event", title="Gemeinderatssitzung", target="calendar-1",
                    start=datetime(2026, 12, 11, 17, tzinfo=UTC), end=datetime(2026, 12, 11, 19, tzinfo=UTC),
                    evidence="Die Sitzung beginnt um 18 Uhr.", **fields)


CHANGE = dict(classification="change", original_date=date(2026, 12, 4), target_event_id="gr-1",
              time_changes=["Beginn 04.12.2026 18:00 Uhr → 11.12.2026 18:00 Uhr"])
CANCEL = dict(classification="cancellation", original_date=date(2026, 12, 4), target_event_id="gr-1",
              is_cancellation=True)


def card(web, item):
    save_mail(web.store, 60, "rathaus@example.test", "Sitzung", [item])
    web.site.refresh_overview(force=True)
    page = web.browser.request("GET", "/").body.decode()
    start = page.index(f'id="v-{mail_id(60)}-{item.id}"')
    return page[page.rindex("<article", 0, start):page.index("</article>", start)]


@pytest.mark.parametrize(("item", "kind", "label"), [
    (lambda: event(), "event", "📅 Termin"),
    (lambda: proposal(60, "aufgabe", title="Antrag abgeben", evidence="Bitte bis Freitag abgeben."),
     "task", "✅ Aufgabe"),
    (lambda: event(**CHANGE), "change", "🔄 Terminänderung"),
    (lambda: event(**CANCEL), "cancel", "🚫 Terminabsage"),
])
def test_each_kind_has_its_own_class_symbol_and_text(web, item, kind, label):
    markup = card(web, item())
    assert markup.startswith(f'<article class="card kind-{kind}"')
    assert f'<p class="kind"><span class="kind-label">{label}</span></p>' in markup
    # The evidence is a styled quotation.
    assert '<blockquote class="evidence">' in markup


def test_a_version_follows_the_kind_label(web):
    markup = card(web, event(version=2, status=ProposalStatus.PENDING_CONFIRMATION))
    assert '<span class="kind-label">📅 Termin</span> · Version 2</p>' in markup


def test_the_reply_draft_box_is_marked_as_a_draft(web):
    from mailhelp.notifications.drafts import DraftService
    save_mail(web.store, 61, "verein@example.test", "Einladung", [proposal(61, "a")], text="Kommst du?")
    web.site.experience.drafts = DraftService(web.store, web.auth.active, lambda: nullcontext(None),
                                              "me@test", analyzer=None)
    page = web.browser.request("GET", f"/mail/{mail_id(61)}").body.decode()
    assert '<section class="card draft-box kind-draft" id="antwort"' in page
    assert '<p class="kind"><span class="kind-label">✍️ Antwortentwurf</span></p>' in page


def rule(selector):
    found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert found, selector
    return found.group(1)


def test_every_kind_has_a_colour_token_and_the_change_a_second_mark():
    for kind, token in (("event", "kind-event"), ("task", "kind-task"), ("change", "kind-event"),
                        ("cancel", "danger"), ("draft", "kind-draft")):
        assert f"--kind-colour: var(--{token})" in rule(f".kind-{kind}")
    # A change shares the appointment colour and differs by a double stripe besides symbol and text.
    assert "border-left-style: double" in rule(".kind-change.card")
    assert "var(--kind-colour)" in rule(".kind-label")
