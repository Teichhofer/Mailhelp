"""Recognize exact, locally recorded briefing content, never an untrusted subject or header alone."""
from hashlib import sha256

from ..storage import CorruptState, JsonStore
from .briefing_scheduler import STATE, BriefingState


def is_own_briefing(store: JsonStore, account: str, raw: bytes) -> bool:
    try:
        state = store.peek_model(STATE, BriefingState)
    except CorruptState:
        return False
    if state is None:
        return False
    digest = sha256(raw).hexdigest()
    return any(run.account == account and run.draft.get("content_sha256") == digest for run in state.runs.values())
