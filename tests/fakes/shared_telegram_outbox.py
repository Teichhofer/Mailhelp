"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from __future__ import annotations

from shared_telegram_dialog import (
    Telegram,
    proposal,
)

from mailhelp.models import (
    MailState,
    ProposalNotification,
    TelegramOutboxState,
)

A, B, C, D = "a" * 24, "b" * 24, "c" * 24, "d" * 24

def item(mail_id, title, questions=(), **changes):
    return proposal(source_mail_id=mail_id, title=title,
                    open_questions=list(questions), **changes)

def stored(store, value, status="pending", relevance=None):
    """Persist a mail projection whose proposal notification is tracked."""
    state = MailState(
        id=value.source_mail_id, config_fingerprint="f" * 64,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1,
              "uid": int(value.source_mail_id[0], 16)},
        proposals=[value],
        proposal_notifications=[ProposalNotification(
            proposal_id=value.id, proposal_version=value.version, status=status)],
        awaiting_relevance=relevance is not None and relevance.status == "open",
        relevance_dialog=relevance,
    )
    store.save(f"mail-{value.source_mail_id}", state.model_dump(mode="json"))

def texts(transport):
    return [text for _, text, _ in transport.sent]

def shown(transport, title):
    return any(title in text for text in texts(transport))

def notification(store, mail_id):
    return store.load_model(f"mail-{mail_id}", MailState).proposal_notifications[0].status

def outbox(store):
    return store.load_model("telegram-outbox", TelegramOutboxState)

def shown_open(store, c, value):
    """Persist a proposal that was already delivered and is still undecided."""
    stored(store, value, status="completed")
    c.repository.save_revision(value)

class _Log:
    def __init__(self): self.events = []
    def event(self, *args, **fields): self.events.append((args, fields))

class _FailingTelegram(Telegram):
    def __init__(self, failing):
        super().__init__()
        self.failing = failing
    def send(self, chat, text, reply_markup=None):
        if text in self.failing:
            raise RuntimeError("synthetic transport failure")
        super().send(chat, text, reply_markup)
