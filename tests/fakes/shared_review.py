"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mailhelp.models import (
    MailState,
)
from mailhelp.persistence.ledger import ActionLedgerService
from mailhelp.review import CommandKind, CommandSource, ReviewCommand

action_key = ActionLedgerService.action_key

from tests.fakes.factories import build_mail_state
from tests.fakes.shared_telegram_dialog import controller

MAIL = "a" * 24

OTHER = "b" * 24

TELEGRAM = "telegram:1:2"

EVENT = dict(kind="event", start="2026-10-21T12:30:00+02:00", end="2026-10-21T15:30:00+02:00",
             target="calendar")

def command(kind, *, mail_id=MAIL, proposal_id="p1", version=1, source=CommandSource.WEB,
            actor="web:session", key="key-00000001", **extra):
    if kind == CommandKind.RELEVANCE:
        proposal_id = None
    return ReviewCommand(kind=kind, source=source, actor=actor, mail_id=mail_id,
                         proposal_id=proposal_id, version=version, idempotency_key=key, **extra)

def mail_state(mail_id=MAIL, uid=1, proposals=(), sender="Ada Muster <ada@example.test>",
               subject="Elternabend", updated=None):
    return build_mail_state(mail_id, uid=uid, proposals=proposals, sender=sender, subject=subject,
                            updated=updated)

def setup(store, *items, writers=None, test_mode=False, mail_id=MAIL, uid=1, **mail):
    """Persist a mail with its proposals the way the orchestrator does."""
    store.save(f"mail-{mail_id}", mail_state(mail_id, uid, items, **mail).model_dump(mode="json"))
    dialog, telegram, log = controller(store, writers=writers, test_mode=test_mode)
    for item in items:
        dialog.persist(item)
    return dialog, telegram, log

def web(dialog, allowed=True):
    dialog.review.web_authorizer = lambda actor: allowed and actor == "web:session"
    return dialog.review
