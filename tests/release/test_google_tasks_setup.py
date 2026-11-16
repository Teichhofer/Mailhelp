"""7.2.2: task-list selection and the date limitation through the public surfaces."""
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from mailhelp.review.cards import card_content
from mailhelp.telegram.formatting import format_proposal
from mailhelp.web.review_pages import _card_facts
from tests.fakes.factories import build_proposal


@pytest.mark.parametrize("provider", ["google_tasks", "todoist", ""])
def test_google_tasks_date_limit_is_visible_in_web_and_telegram(provider):
    proposal = build_proposal(target_provider=provider, due=datetime(2026, 11, 20, 13, tzinfo=UTC))
    card = card_content(proposal, "Europe/Berlin")
    expected = "Google Tasks übernimmt das Datum; die genaue Frist steht im Text."
    for text in (format_proposal(proposal, "Europe/Berlin"), "".join(_card_facts(card))):
        assert (expected in text) == (provider == "google_tasks")
    # The confirmed proposal and its precise deadline remain intact.
    assert proposal.due.hour == 13
    assert replace(card, target_hint=None).due == card.due
