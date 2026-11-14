"""6.3: markup behind the swipe on "Offen" – blocked reasons and the one-time tip (Planung 6.3, 3.4, 3.6)."""
import re
from dataclasses import replace

import pytest

from mailhelp.review.commands import CommandKind
from mailhelp.review.views import ReviewViews
from mailhelp.web.actions import SWIPE_BLOCKED_DEFAULT, proposal_actions, swipe_blocked
from mailhelp.web.review_pages import SWIPE_HINT, overview_page
from tests.scenarios.web_scenario import mail_id

OPEN = frozenset({CommandKind.REJECT, CommandKind.ALREADY_DONE})


def page(web):
    web.site.refresh_overview()
    return web.browser.request("GET", "/").body.decode()


def bar(html, anchor):
    card = html[html.index(f'id="{anchor}"'):]
    return re.search(r'<div class="actions decision-bar"([^>]*)>', card[:card.index("</article>")]).group(1)


@pytest.fixture
def view(web):
    return ReviewViews(web.store, "Europe/Berlin").proposal(mail_id(1), "elternabend")


def test_a_confirmable_card_has_no_block_and_an_unconfirmable_one_names_the_reason(web):
    html = page(web)
    assert bar(html, f"v-{mail_id(1)}-elternabend") == ""
    # The appointment without a start time waits for the answer to its question.
    assert bar(html, f"v-{mail_id(2)}-zahnarzt") == ' data-swipe-blocked="Erst die Rückfrage beantworten."'


@pytest.mark.parametrize(("extra", "fields", "reason"), [
    ({CommandKind.CHOOSE_VARIANT, CommandKind.ANSWER, CommandKind.RECHECK}, {"question": "Wann?"},
     "Erst den Widerspruch klären."),
    ({CommandKind.ANSWER, CommandKind.RECHECK}, {"question": "Wann?"}, "Erst die Rückfrage beantworten."),
    ({CommandKind.ANSWER, CommandKind.RECHECK}, {"question": None, "reconciliation_required": True},
     "Erst im Vorschlagsabgleich entscheiden."),
    ({CommandKind.RECHECK, CommandKind.CHOOSE_EVENT}, {"question": None}, "Erst die Dublettenprüfung wiederholen."),
    ({CommandKind.CHOOSE_EVENT}, {"question": None}, "Erst den gemeinten Termin wählen."),
    (set(), {"question": "Wann?"}, SWIPE_BLOCKED_DEFAULT),
])
def test_every_blocked_reason_in_its_order(view, extra, fields, reason):
    assert swipe_blocked(replace(view, actions=OPEN | extra, **fields)) == reason


def test_the_reason_is_escaped_in_the_attribute(view, monkeypatch):
    import mailhelp.web.actions as actions
    monkeypatch.setattr(actions, "swipe_blocked", lambda _view: 'Erst "x" & <y>')
    html = proposal_actions("csrf")(replace(view, actions=OPEN))
    assert 'data-swipe-blocked="Erst &quot;x&quot; &amp; &lt;y&gt;"' in html


def test_the_tip_stands_hidden_above_the_cards_and_only_with_cards(web):
    html = page(web)
    assert html.count("data-swipe-hint") == 2  # the tip and its close button
    assert html.index(SWIPE_HINT) < html.index('<div class="open-items">')
    # Regression 6.3.1: as a .notice the hidden tip was taken for the result message of an action.
    assert '<div class="swipe-hint" data-swipe-hint hidden>' in html and "notice" not in SWIPE_HINT
    overview = ReviewViews(web.store, "Europe/Berlin").overview()
    empty = overview_page(replace(overview, open=(), relevance=()))
    assert "data-swipe-hint" not in empty
