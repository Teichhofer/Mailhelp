"""Tests for Telegram rejection reasons (Planung 6.5, D3, 3.2)."""
from __future__ import annotations

import json

import pytest

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.persistence.storage import JsonStore
from mailhelp.review.learning_log import DecisionLearningLog
from mailhelp.review.reject_reasons import USER_REJECT_REASONS
from mailhelp.telegram.callbacks import Decision, DecisionAction
from tests.fakes.factories import build_proposal
from tests.fakes.shared_review import setup
from tests.fakes.shared_telegram_dialog import callback

MAIL = "a" * 24


def test_telegram_rejection_offers_five_reason_buttons_and_sets_reason(tmp_path):
    prop = build_proposal(status=ProposalStatus.PENDING_CONFIRMATION, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, transport, log = setup(store, prop)
        learning = DecisionLearningLog(store, 30, log)
        dialog.learning = learning

        # User clicks "Verwerfen"
        reject_data = f"proposal:{MAIL}:p1:1:reject"
        transport.updates = [callback(1, reject_data)]
        dialog.poll_once()

        # Proposal status changed to rejected
        current = dialog.repository.load_current(MAIL, "p1")
        assert current is not None
        assert current.status == ProposalStatus.REJECTED

        # Rejection message was sent with 5 inline buttons
        assert len(transport.sent) == 1
        chat_id, text, markup = transport.sent[0]
        assert "Vorschlag wurde verworfen" in text
        assert markup is not None and "inline_keyboard" in markup
        rows = markup["inline_keyboard"]
        assert len(rows) == 5

        button_texts = [row[0]["text"] for row in rows]
        expected_texts = [label for _, label in USER_REJECT_REASONS]
        assert button_texts == expected_texts

        # Click the first reason: "Betrifft mich nicht"
        first_callback_data = rows[0][0]["callback_data"]
        transport.updates = [callback(2, first_callback_data)]
        dialog.poll_once()

        # Proposal reject_reason was saved
        updated = dialog.repository.load_current(MAIL, "p1")
        assert updated is not None
        assert updated.reject_reason == "not_for_me"

        # Confirmation sent
        assert len(transport.sent) == 2
        _, conf_text, _ = transport.sent[1]
        assert "Grund gespeichert: Betrifft mich nicht." in conf_text

        # Learning log recorded reject_reason
        records = [json.loads(line) for line in learning.path.read_text(encoding="utf-8").splitlines()]
        assert len(records) >= 1
        assert records[0]["reject_reason"] == "not_for_me"


def test_telegram_rejection_reason_stale_and_duplicate(tmp_path):
    prop = build_proposal(status=ProposalStatus.REJECTED, source_mail_id=MAIL, id="p1", version=1)
    with JsonStore(tmp_path) as store:
        dialog, transport, log = setup(store, prop)
        # Decision for a reason
        decision = Decision(mail_id=MAIL, proposal_id="p1", version=1,
                            action=DecisionAction.REJECT_REASON, reason="info_only")
        cb_data = decision.encode(store)

        # Pressing once works
        transport.updates = [callback(1, cb_data)]
        dialog.poll_once()
        assert dialog.repository.load_current(MAIL, "p1").reject_reason == "info_only"

        # Pressing second time (duplicate) returns confirmation without error
        transport.updates = [callback(2, cb_data)]
        dialog.poll_once()
        assert "Grund gespeichert" in transport.sent[-1][1]

        # Old / stale version
        stale_decision = Decision(mail_id=MAIL, proposal_id="p1", version=99,
                                  action=DecisionAction.REJECT_REASON, reason="info_only")
        stale_data = stale_decision.encode(store)
        transport.updates = [callback(3, stale_data)]
        dialog.poll_once()
        assert "diese Schaltfläche ist veraltet" in transport.sent[-1][1]


def test_decision_callback_reject_reason_validation_and_encoding():
    # 1. Action == REJECT_REASON requires reason
    with pytest.raises(ValueError, match="Nur die Angabe eines Grundes nennt einen Ablehnungsgrund"):
        Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.REJECT_REASON, reason=None)

    # 2. Action != REJECT_REASON forbids reason
    with pytest.raises(ValueError, match="Nur die Angabe eines Grundes nennt einen Ablehnungsgrund"):
        Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.CONFIRM, reason="advertising")

    # 3. Invalid reason
    with pytest.raises(ValueError, match="Unbekannter Ablehnungsgrund: invalid_reason"):
        Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.REJECT_REASON, reason="invalid_reason")

    # 4. Store-less encode forbids reason
    dec = Decision(mail_id=MAIL, proposal_id="p1", version=1, action=DecisionAction.REJECT_REASON, reason="advertising")
    with pytest.raises(ValueError, match="Die Angabe eines Grundes benötigt einen dauerhaften Callback-Token"):
        dec.encode(store=None)

