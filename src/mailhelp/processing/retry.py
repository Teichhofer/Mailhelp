"""Bound processing retries before fetching a mail or consuming its budget."""
from datetime import datetime, timedelta

from ..domain.retry import ProcessingRetry
from ..models import MailState, ProcessingErrorCode

DELAYS = (60, 300, 1800, 7200)


def fingerprint(state: MailState, configuration: str) -> str:
    assert state.error is not None
    return f"{configuration}:{state.error.stage.value}:{state.error.code.value}"


def failed(state: MailState, configuration: str, now: datetime) -> None:
    error = state.error
    assert error is not None
    if error.code == ProcessingErrorCode.LLM_RATE_LIMITED:
        return
    key = fingerprint(state, configuration)
    retry = state.processing_retry
    if retry is None or retry.fingerprint != key:
        retry = state.processing_retry = ProcessingRetry(
            fingerprint=key, attempts=1, first_failed_at=now, last_failed_at=now)
    else:
        retry.attempts = min(5, retry.attempts + 1)
        retry.last_failed_at = now
    retry.abandoned = retry.attempts == 5 or error.retryable is False
    state.deferred_until = None if retry.abandoned else now + timedelta(seconds=DELAYS[retry.attempts - 1])


def blocked(state: MailState, configuration: str, now: datetime) -> bool:
    if state.processing_filed:
        return True
    retry = state.processing_retry
    if (retry is not None and state.error is not None and state.error.code != ProcessingErrorCode.LLM_RATE_LIMITED
            and retry.fingerprint != fingerprint(state, configuration)):
        state.processing_retry = None
        state.deferred_until = None
    return bool((state.processing_retry is not None and state.processing_retry.abandoned)
                or (state.deferred_until is not None and state.deferred_until > now))


def succeeded(state: MailState) -> None:
    state.processing_retry = None
    state.deferred_until = None
