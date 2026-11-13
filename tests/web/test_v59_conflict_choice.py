"""5.9.3: a field conflict is decided on the card with one click; nothing is created by it."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal_sources import ProposalSource
from mailhelp.models import ProposalStatus
from mailhelp.proposals.proposal_merge import merge_facts
from mailhelp.review.commands import ReviewCommand
from mailhelp.review.results import ResultStatus
from mailhelp.review.views import ReviewViews
from mailhelp.telegram import TelegramDialogController
from mailhelp.telegram.callbacks import Decision, DecisionAction
from mailhelp.web.actions import conflict_boxes
from mailhelp.web.review_pages import proposal_card
from tests.fakes.shared_telegram_dialog import Logger, callback
from tests.scenarios.web_scenario import Revisions, mail_id, proposal, save_mail

START = datetime(2026, 12, 4, 17, tzinfo=UTC)


def conflicted():
    def event(number, end):
        return proposal(number, f"abend{number}", kind="event", title="Elternabend", target="calendar-1",
                        start=START, end=end, sources=[ProposalSource(
                            mail_id=mail_id(number), proposal_id=f"abend{number}", subject="Elternabend",
                            sent_at=START - timedelta(days=62 - number)).model_dump()])
    return merge_facts(event(60, START + timedelta(minutes=30)), event(61, START + timedelta(hours=2, minutes=30)))


@pytest.fixture
def item(web):
    merged = conflicted()
    save_mail(web.store, 60, "schule@example.test", "Elternabend", [merged])
    return merged


def current(web, item):
    return web.dialog.repository.load_current(item.source_mail_id, item.id)


def page(web, item):
    web.site.refresh_overview()
    return web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/{item.id}").body.decode()


def test_the_card_compares_both_values_in_the_local_zone_with_one_form_each(web, item):
    html = page(web, item)
    assert "⚠️ Widerspruch: Endzeit – welcher Wert soll gelten?" in html
    assert '<p class="compare-tag">bisher</p><p class="conflict-value"><strong>18:30 Uhr</strong>' in html
    assert "laut Mail „Elternabend“ vom 03.12." in html and "<strong>20:30 Uhr</strong>" in html
    assert html.count('name="kind" value="choose_conflict_variant"') == 2
    assert ">18:30 Uhr behalten</button>" in html and ">20:30 Uhr übernehmen</button>" in html
    assert "angelegt wird erst nach deiner Bestätigung" in html
    # Shown once as a comparison, not again in the list of open questions.
    assert "Offene Fragen" not in html


def test_regression_choosing_the_new_value_revises_without_creating_anything(web, item):
    """Regression 5.9.3: a conflict could only be solved by typing the value as free text."""
    fields = web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="choose_conflict_variant", variant="b")
    assert web.submit(fields).status == 303
    web.run()
    chosen = current(web, item)
    assert chosen.version == item.version + 1 and chosen.end == START + timedelta(hours=2, minutes=30)
    assert chosen.field_conflicts == [] and chosen.status == ProposalStatus.PENDING_CONFIRMATION
    assert {"start", "end"} <= set(chosen.protected_fields)
    assert web.writer.created == 0
    # The same form again (double tap, browser retry) has no second effect.
    web.submit(fields)
    web.run()
    assert current(web, item).version == chosen.version


def test_an_outdated_or_foreign_choice_changes_nothing(web, item):
    fields = web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="choose_conflict_variant", variant="a")
    web.dialog.persist(item.model_copy(update={"version": item.version + 1}))
    web.site.refresh_overview()
    stale = web.submit(fields)
    assert stale.status == 409 and "inzwischen geändert" in stale.body.decode()
    without_token = {**fields, "csrf": "", "key": "f" * 32}
    assert web.submit(without_token).status == 403
    actor = "web:" + web.auth.sessions()[0].id
    command = dict(kind="choose_conflict_variant", source="web", actor=actor, mail_id=item.source_mail_id,
                   proposal_id=item.id, version=item.version + 1, idempotency_key="variant-unknown",
                   conflict_id="interval-9", variant="a")
    assert web.dialog.review.execute(ReviewCommand(**command)).status == ResultStatus.STALE
    assert current(web, item).end == item.end


def test_a_session_revoked_before_the_choice_runs_cannot_act(web, item):
    fields = web.form(f"/vorschlag/{item.source_mail_id}/{item.id}", kind="choose_conflict_variant", variant="b")
    assert web.submit(fields).status == 303
    web.auth.revoke(web.auth.sessions()[0].id)
    web.run()
    assert current(web, item) == item


def test_without_the_action_the_comparison_is_shown_without_forms(web, item):
    view = ReviewViews(web.store, "Europe/Berlin").proposal(item.source_mail_id, item.id)
    card = proposal_card(view)
    assert "⚠️ Widerspruch: Endzeit" in card and "<form" not in card
    assert "<form" not in conflict_boxes(replace(view, actions=frozenset()), "csrf")


def test_conflict_and_variant_belong_to_the_choice_command_only():
    base = dict(source="web", actor="web:x", mail_id=mail_id(1), proposal_id="p", version=1,
                idempotency_key="variant-check")
    with pytest.raises(ValidationError, match="Widerspruch und Variante"):
        ReviewCommand(kind="choose_conflict_variant", conflict_id="due-2", **base)
    with pytest.raises(ValidationError, match="Widerspruch und Variante"):
        ReviewCommand(kind="confirm", variant="a", **base)
    with pytest.raises(ValidationError):
        ReviewCommand(kind="choose_conflict_variant", conflict_id="DUE", variant="a", **base)


def buttons(web):
    return [button for row in web.telegram.sent[-1][2]["inline_keyboard"] for button in row]


def test_telegram_names_each_value_and_offers_a_button_per_value(web, item):
    web.dialog.delivery.deliver(item)
    text = web.telegram.sent[-1][1]
    assert ("⚠️ Widerspruch: Endzeit – welcher Wert soll gelten?\n• bisher: 18:30 Uhr\n"
            "• laut Mail „Elternabend“ vom 03.12.: 20:30 Uhr") in text
    assert item.field_conflicts[0].question not in text  # not repeated as an open question
    first_row = web.telegram.sent[-1][2]["inline_keyboard"][0]
    assert [button["text"] for button in first_row] == ["18:30 Uhr behalten", "20:30 Uhr übernehmen"]
    choice = Decision.parse(first_row[1]["callback_data"], web.store)
    assert (choice.action, choice.conflict_id, choice.variant, choice.version) == (
        DecisionAction.CHOOSE_VARIANT, "interval-2", "b", item.version)


def test_a_telegram_choice_revises_once_and_an_outdated_button_changes_nothing(web, item):
    web.dialog.delivery.deliver(item)
    data = next(button["callback_data"] for button in buttons(web) if button["text"] == "20:30 Uhr übernehmen")
    web.telegram.updates = [callback(1, data)]
    web.run()
    chosen = current(web, item)
    assert chosen.version == item.version + 1 and chosen.end == START + timedelta(hours=2, minutes=30)
    assert chosen.status == ProposalStatus.PENDING_CONFIRMATION and web.writer.created == 0
    # The same button again (repeated update or a tap on the old message) is outdated.
    web.telegram.updates = [callback(2, data)]
    web.run()
    assert current(web, item).version == chosen.version
    assert any("veraltet" in text for _, text, _ in web.telegram.sent)


def test_a_variant_choice_needs_a_durable_token():
    choice = Decision(mail_id=mail_id(1), proposal_id="p", version=1, action=DecisionAction.CHOOSE_VARIANT,
                      conflict_id="due-2", variant="a")
    with pytest.raises(ValueError, match="dauerhaften Callback-Token"):
        choice.encode()
    with pytest.raises(ValidationError, match="Widerspruch und Variante"):
        Decision(mail_id=mail_id(1), proposal_id="p", version=1, action=DecisionAction.CHOOSE_VARIANT)
    with pytest.raises(ValidationError, match="Widerspruch und Variante"):
        Decision(mail_id=mail_id(1), proposal_id="p", version=1, action=DecisionAction.CONFIRM, variant="a")


def test_the_receipt_names_the_field_and_the_chosen_value(web, item):
    web.dialog.delivery.deliver(item)
    data = next(button["callback_data"] for button in buttons(web) if button["text"] == "18:30 Uhr behalten")
    web.telegram.updates = [callback(1, data)]
    web.run()
    assert current(web, item).end == item.end and current(web, item).version == item.version + 1
    receipts = [text for _, text in web.telegram.answered] + [text for _, text, _ in web.telegram.sent]
    assert any("Endzeit 18:30 Uhr behalten; neue Version bitte separat bestätigen." in text for text in receipts)


def test_a_choice_survives_a_restart_and_a_foreign_chat_cannot_choose(web, item):
    web.dialog.delivery.deliver(item)
    data = next(button["callback_data"] for button in buttons(web) if button["text"] == "20:30 Uhr übernehmen")
    # A foreign user or chat is ignored and changes nothing.
    web.telegram.updates = [callback(1, data, user=9, chat=9)]
    web.run()
    assert current(web, item) == item
    # After a restart, a new controller on the same store still resolves the durable token.
    web.dialog = TelegramDialogController(
        web.store, web.telegram, 1, 2, Logger(), {"todoist": web.writer, "google_calendar": web.writer},
        False, "Europe/Berlin", Revisions(), commands=web.commands)
    web.telegram.updates = [callback(2, data)]
    web.run()
    chosen = current(web, item)
    assert chosen.version == item.version + 1 and chosen.end == START + timedelta(hours=2, minutes=30)
    assert web.writer.created == 0
