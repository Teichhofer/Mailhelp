"""Regression: proposals with IDs longer than 32 characters can be decided.

The deterministic review task for oversized attachments is called
``manual_attachment_<mail id>`` (42 characters).  ``Proposal.id`` allows 64
characters, but the internal ``Decision`` model only accepted 32.  Rejecting
or confirming such a task in the web therefore ended with "Die Eingabe ist
ungültig." and Telegram could not build its buttons.
"""
from __future__ import annotations

import re

import pytest
from pydantic import BaseModel

from mailhelp.domain import processing, proposal_sources
from mailhelp.domain import proposal as proposal_module
from mailhelp.models import Proposal
from mailhelp.review import archive, commands
from mailhelp.review.errors import StaleCommand
from mailhelp.review.inbox import CommandStatus
from mailhelp.telegram import callbacks
from mailhelp.telegram.callbacks import Decision, DecisionAction
from tests.fakes.shared_telegram_dialog import callback
from tests.fakes.shared_web_actions import Web as Web
from tests.fakes.shared_web_actions import web as web
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MAIL = mail_id(30)
LONG_ID = f"manual_attachment_{MAIL}"


@pytest.fixture
def long_web(web):
    item = proposal(30, LONG_ID, title="Nachricht manuell prüfen: Unterlagen zur Sitzung",
                    target="Inbox", target_provider="todoist")
    save_mail(web.store, 30, "Gemeinde <info@gemeinde.test>", "Unterlagen zur Sitzung", [item])
    return web


def test_the_manual_attachment_id_is_longer_than_32_characters():
    assert len(LONG_ID) == 42


def test_rejecting_a_long_id_in_the_web_succeeds(long_web):
    location = long_web.submit(long_web.form(f"/vorschlag/{MAIL}/{LONG_ID}", kind="reject",
                                             proposal_id=LONG_ID)).headers["Location"]
    long_web.run()
    entry = long_web.commands.get(location.rsplit("/", 1)[1])
    assert entry.status == CommandStatus.DONE and entry.result.message == "Vorschlag verworfen."
    assert long_web.store.load(f"proposal-{MAIL}-{LONG_ID}")["status"] == "rejected"


def test_confirming_a_long_id_in_the_web_writes_once(long_web):
    location = long_web.submit(long_web.form(f"/vorschlag/{MAIL}/{LONG_ID}", kind="confirm",
                                             proposal_id=LONG_ID)).headers["Location"]
    long_web.run()
    assert long_web.commands.get(location.rsplit("/", 1)[1]).result.status.value == "written"
    assert long_web.writer.created == 1
    assert long_web.store.load(f"proposal-{MAIL}-{LONG_ID}")["status"] == "created"


def test_telegram_buttons_for_a_long_id_use_durable_tokens_and_work(long_web):
    item = Proposal.model_validate(long_web.store.load(f"proposal-{MAIL}-{LONG_ID}"))
    buttons = long_web.dialog.presenter.present(item).reply_markup["inline_keyboard"][0]
    assert all(button["callback_data"].startswith("decision:") for button in buttons)
    reject = next(button["callback_data"] for button in buttons if button["text"] == "Verwerfen")
    parsed = Decision.parse(reject, long_web.store)
    assert (parsed.proposal_id, parsed.action) == (LONG_ID, DecisionAction.REJECT)
    long_web.telegram.updates = [callback(1, reject)]
    long_web.run()
    assert long_web.store.load(f"proposal-{MAIL}-{LONG_ID}")["status"] == "rejected"


def test_the_legacy_callback_without_store_refuses_a_long_id_cleanly():
    decision = Decision(mail_id=MAIL, proposal_id=LONG_ID, version=1, action=DecisionAction.REJECT)
    with pytest.raises(ValueError, match="64 UTF-8-Bytes"):
        decision.encode()
    with pytest.raises(ValueError, match="64 UTF-8-Bytes"):
        Decision.parse(f"proposal:{MAIL}:{LONG_ID}:1:reject")


def test_the_proposal_id_limit_still_applies():
    with pytest.raises(ValueError):
        Decision(mail_id=MAIL, proposal_id="x" * 65, version=1, action=DecisionAction.REJECT)


def _proposal_id_patterns() -> dict[str, str]:
    """Pattern of every model field that holds a reference to ``Proposal.id``."""
    found: dict[str, str] = {}
    for module in (processing, proposal_module, proposal_sources, commands, archive, callbacks):
        for name, model in vars(module).items():
            if not (isinstance(model, type) and issubclass(model, BaseModel)) or model.__module__ != module.__name__:
                continue
            field = model.model_fields.get("proposal_id")
            if field is not None:
                found[f"{module.__name__}.{name}"] = next(
                    item.pattern for item in field.metadata if getattr(item, "pattern", None))
    return found


@pytest.mark.parametrize("value", [LONG_ID, "a" * 64, "Z", "p_1-x"])
def test_every_proposal_id_field_accepts_what_proposal_id_accepts(value):
    """Guard: no reference field may be stricter than the proposal ID itself."""
    reference = next(item.pattern for item in Proposal.model_fields["id"].metadata
                     if getattr(item, "pattern", None))
    assert re.fullmatch(reference, value)
    patterns = _proposal_id_patterns()
    assert "mailhelp.telegram.callbacks.Decision" in patterns and len(patterns) >= 8
    assert {name for name, pattern in patterns.items() if not re.fullmatch(pattern, value)} == set()


def _refused(web):
    return [fields for (level, module, event), fields in web.dialog.logger.events
            if (module, event) == ("review", "command_refused")]


def test_a_refused_validation_logs_field_names_but_no_values(long_web, monkeypatch):
    """Step 4: "Die Eingabe ist ungültig." can be traced in the log without leaking content."""
    def invalid(_command):
        Decision(mail_id=MAIL, proposal_id="geheimer Inhalt ä" * 5, version=1, action=DecisionAction.REJECT)

    monkeypatch.setattr(long_web.dialog.review, "_execute", invalid)
    location = long_web.submit(long_web.form(f"/vorschlag/{MAIL}/{LONG_ID}", kind="reject",
                                             proposal_id=LONG_ID)).headers["Location"]
    long_web.run()
    assert long_web.commands.get(location.rsplit("/", 1)[1]).result.message == "Die Eingabe ist ungültig."
    [fields] = _refused(long_web)
    assert fields == {"kind": "reject", "source": "web", "status": "invalid", "error_class": "ValidationError",
                      "fields": ["proposal_id:string_pattern_mismatch"]}
    assert "geheim" not in repr(long_web.dialog.logger.events)


def test_a_model_level_validation_error_is_named_model(long_web, monkeypatch):
    def invalid(_command):
        Decision(mail_id=MAIL, proposal_id=LONG_ID, version=1, action=DecisionAction.RETARGET)

    monkeypatch.setattr(long_web.dialog.review, "_execute", invalid)
    long_web.submit(long_web.form(f"/vorschlag/{MAIL}/{LONG_ID}", kind="reject", proposal_id=LONG_ID))
    long_web.run()
    assert _refused(long_web)[0]["fields"] == ["model:value_error"]


def test_a_stale_command_is_logged_without_fields(long_web, monkeypatch):
    def stale(_command):
        raise StaleCommand("Vorschlag inzwischen geändert")

    monkeypatch.setattr(long_web.dialog.review, "_execute", stale)
    long_web.submit(long_web.form(f"/vorschlag/{MAIL}/{LONG_ID}", kind="reject", proposal_id=LONG_ID))
    long_web.run()
    assert _refused(long_web) == [{"kind": "reject", "source": "web", "status": "stale",
                                   "error_class": "StaleCommand", "fields": []}]
