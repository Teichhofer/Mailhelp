"""Authorized local processing controls; no external writes."""
import hashlib
from datetime import UTC, datetime

from .. import state_names
from ..domain.mail import MailState
from ..persistence.storage import JsonStore
from .archive import HistoryEvent, append_event
from .commands import CommandKind, ReviewCommand
from .errors import StaleCommand


def apply(store: JsonStore, command: ReviewCommand) -> None:
    with store.locked():
        name = state_names.mail(command.mail_id)
        state = store.load_model(name, MailState)
        if state is None:
            raise StaleCommand("Die Mail ist nicht mehr vorhanden.")
        if state.processing_operation != command.idempotency_key:
            if state.analysis_round != command.version or state.error is None or state.processing_filed:
                raise StaleCommand("Die Mail wurde inzwischen geändert oder verarbeitet.")
            if command.kind == CommandKind.RETRY_MAIL:
                if state.missing_analysis_steps:
                    raise StaleCommand("Analyse-Daten wurden entfernt; diese Mail kann nicht fortgesetzt werden.")
                state.processing_retry = None
                state.deferred_until = None
                state.error.notification_marked_at = None
            else:
                state.processing_filed = True
                state.steps.completion = "completed"
                state.steps.action_detection = "skipped"
                state.deferred_until = None
            state.analysis_round += 1
            state.processing_operation = command.idempotency_key
            state.updated_at = datetime.now(UTC)
            store.save(name, state.model_dump(mode="json"))
        identifier = hashlib.sha256(command.idempotency_key.encode()).hexdigest()[:32]
        append_event(store, state.id, HistoryEvent(id=identifier, version=command.version,
                     kind=command.kind.value,
                     status="retrying" if command.kind == CommandKind.RETRY_MAIL else "not_processed",
                     source=command.source.value,
                     actor=command.actor, at=state.updated_at))
