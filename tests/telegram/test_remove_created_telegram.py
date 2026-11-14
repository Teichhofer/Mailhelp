"""Tests for Telegram remove created entries (Planung 6.6, D4, 3.4).

Verifies D4:
- Message "Angelegt ..." includes inline button "Wieder entfernen"
- Button press asks confirmation ("Wirklich entfernen: ...?") with "Ja, entfernen" and "Abbrechen"
- Abbrechen keeps entry and notifies user
- Ja, entfernen removes entry, sets status to REMOVED, notifies user
- Stale or duplicate press explains reason without second write
- Expired window reports expiration
- Simulation and calendar file omit removal button
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mailhelp.models import ProposalKind, ProposalStatus
from mailhelp.storage import JsonStore
from mailhelp.telegram.callbacks import Decision, DecisionAction
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import setup
from tests.fakes.shared_telegram_dialog import Writer, callback

MAIL = "a" * 24


def test_telegram_remove_created_full_flow(tmp_path):
    prop = build_proposal(
        status=ProposalStatus.PENDING_CONFIRMATION,
        source_mail_id=MAIL,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        start="2026-10-21T19:00:00+02:00",
        end="2026-10-21T20:30:00+02:00",
        target="calendar",
        title="Elternabend",
    )
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = setup(store, prop, writers={"google_calendar": writer})

        # 1. User confirms proposal
        confirm_data = f"proposal:{MAIL}:p1:1:confirm"
        transport.updates = [callback(1, confirm_data)]
        dialog.poll_once()

        # Proposal is now CREATED
        current = dialog.repository.load_current(MAIL, "p1")
        assert current is not None
        assert current.status == ProposalStatus.CREATED

        # Message sent has "Wieder entfernen" button
        assert len(transport.sent) == 1
        _, text, markup = transport.sent[0]
        assert "Angelegt" in text
        assert markup is not None and "inline_keyboard" in markup
        button = markup["inline_keyboard"][0][0]
        assert button["text"] == "Wieder entfernen"

        # 2. User presses "Wieder entfernen"
        transport.updates = [callback(2, button["callback_data"])]
        dialog.poll_once()

        # Bot asks for confirmation with Ja / Abbrechen
        assert len(transport.sent) == 2
        _, ask_text, ask_markup = transport.sent[1]
        assert "Wirklich entfernen: „Elternabend“?" in ask_text
        assert ask_markup is not None
        buttons = ask_markup["inline_keyboard"][0]
        assert len(buttons) == 2
        yes_btn, cancel_btn = buttons[0], buttons[1]
        assert yes_btn["text"] == "Ja, entfernen"
        assert cancel_btn["text"] == "Abbrechen"

        # 3. User clicks "Ja, entfernen"
        transport.updates = [callback(3, yes_btn["callback_data"])]
        dialog.poll_once()

        # Result reported to user
        assert len(transport.sent) == 3
        _, done_text, _ = transport.sent[2]
        assert "Entfernt und geprüft." in done_text

        # Proposal status is REMOVED
        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated is not None
        assert updated.status == ProposalStatus.REMOVED
        assert writer.removed == 1

        # 4. Duplicate click on "Ja, entfernen"
        transport.updates = [callback(4, yes_btn["callback_data"])]
        dialog.poll_once()

        assert len(transport.sent) == 4
        _, dup_text, _ = transport.sent[3]
        assert "Bereits entfernt." in dup_text
        assert writer.removed == 1


def test_telegram_remove_created_cancel(tmp_path):
    prop = build_proposal(
        status=ProposalStatus.CREATED,
        source_mail_id=MAIL,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        start="2026-10-21T19:00:00+02:00",
        end="2026-10-21T20:30:00+02:00",
        target="calendar",
        title="Elternabend",
        external_id="ext-1",
        created_at=datetime.now(UTC),
    )
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = setup(store, prop, writers={"google_calendar": writer})

        # Ask to remove
        ask_token = Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.REMOVE_ASK).encode(store)
        transport.updates = [callback(1, ask_token)]
        dialog.poll_once()

        assert len(transport.sent) == 1
        _, _, markup = transport.sent[0]
        cancel_token = markup["inline_keyboard"][0][1]["callback_data"]

        # User cancels
        transport.updates = [callback(2, cancel_token)]
        dialog.poll_once()

        assert len(transport.sent) == 2
        _, cancel_text, _ = transport.sent[1]
        assert "Entfernen abgebrochen" in cancel_text

        # Proposal is still CREATED and nothing removed
        current = dialog.repository.load_current(MAIL, "p1")
        assert current.status == ProposalStatus.CREATED
        assert writer.removed == 0


def test_telegram_remove_created_expired_and_stale(tmp_path):
    past = datetime.now(UTC) - timedelta(minutes=15)
    prop = build_proposal(
        status=ProposalStatus.CREATED,
        source_mail_id=MAIL,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        start="2026-10-21T19:00:00+02:00",
        end="2026-10-21T20:30:00+02:00",
        target="calendar",
        title="Elternabend",
        external_id="ext-1",
        created_at=past,
    )
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = setup(store, prop, writers={"google_calendar": writer})

        # 1. Expired removal window
        ask_token = Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.REMOVE_ASK).encode(store)
        transport.updates = [callback(1, ask_token)]
        dialog.poll_once()

        assert len(transport.sent) == 1
        _, exp_text, _ = transport.sent[0]
        assert "Frist zum Entfernen" in exp_text

        # 2. Proposal is already REMOVED or changed
        dialog.persist(prop.model_copy(update={"status": ProposalStatus.REMOVED}))
        transport.updates = [callback(2, ask_token)]
        dialog.poll_once()

        assert len(transport.sent) == 2
        _, stale_text, _ = transport.sent[1]
        assert "inzwischen geändert oder bereits entfernt" in stale_text


def test_telegram_simulation_omits_remove_button(tmp_path):
    prop = build_proposal(
        status=ProposalStatus.PENDING_CONFIRMATION,
        source_mail_id=MAIL,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        start="2026-10-21T19:00:00+02:00",
        end="2026-10-21T20:30:00+02:00",
        target="calendar",
        title="Elternabend",
    )
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = setup(store, prop, writers={"google_calendar": writer}, test_mode=True)

        confirm_data = f"proposal:{MAIL}:p1:1:confirm"
        transport.updates = [callback(1, confirm_data)]
        dialog.poll_once()

        assert len(transport.sent) == 1
        _, text, markup = transport.sent[0]
        assert "Testmodus" in text
        assert markup is None
