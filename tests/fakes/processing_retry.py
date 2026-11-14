"""Synthetic mail states for processing recovery tests."""
from datetime import UTC, datetime

from mailhelp.models import MailState, ProcessingError, ProcessingErrorCode, ProcessingStage


def terminal():
    state = MailState(id="a" * 24, config_fingerprint="0" * 64,
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 7, "uid": 1},
                      mail={"text": "Synthetic"},
                      relevance={"decision": "relevant", "topic_ids": ["test"], "reason": "Synthetic"},
                      summary={"sentences": ["Synthetic"]})
    for name in ("preparation", "relevance", "summary", "completion"):
        setattr(state.steps, name, "completed")
    state.steps.action_detection = "failed"
    return state


def errored():
    state = terminal()
    state.error = ProcessingError(code=ProcessingErrorCode.INTERNAL_ERROR,
                                  stage=ProcessingStage.RELEVANCE, occurred_at=datetime.now(UTC))
    return state
