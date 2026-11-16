"""7.3: understandable reports of failed mails – stage, cause, advice and retries, never content.

The report names only the processing stage, the typed error code, times, the number of attempts,
validation paths and model call ids. Mail text, addresses, tokens and provider answers are never
part of it, also not of the copyable text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from ..domain.mail import MailState
from ..domain.processing import ProcessingErrorCode
from .explanation import ERROR_TEXTS
from .views import ERROR_LABELS, STAGE_LABELS

MAX_ATTEMPTS = 5
ADVICE = {
    ProcessingErrorCode.ANALYSIS_DATA_REMOVED:
        "Die Mail kann nicht fortgesetzt werden; bei Bedarf ablegen und den Vorgang von Hand erledigen.",
    ProcessingErrorCode.MIME_LIMIT_EXCEEDED:
        "Grenzen unter Einstellungen → Aufrufbudget und Mailgrenzen prüfen oder die Mail ablegen.",
    ProcessingErrorCode.LLM_SCHEMA_VALIDATION_EXHAUSTED:
        "Später erneut versuchen; bleibt es dabei, das Modell des genannten Schritts prüfen.",
    ProcessingErrorCode.PROVIDER_RESPONSE_INVALID:
        "Später erneut versuchen; der Anbieter war vermutlich vorübergehend gestört.",
    ProcessingErrorCode.INVALID_JSON:
        "Später erneut versuchen; bleibt es dabei, das Modell des genannten Schritts prüfen.",
    ProcessingErrorCode.SCHEMA_VALIDATION_FAILED:
        "Später erneut versuchen; bleibt es dabei, das Modell des genannten Schritts prüfen.",
    ProcessingErrorCode.PERMANENT_ADAPTER_ERROR:
        "Zugangsdaten und Kontostand beim Anbieter prüfen (Diagnose), dann erneut versuchen.",
    ProcessingErrorCode.LLM_RATE_LIMITED:
        "Mailhelp versucht es automatisch erneut, sobald das Abfragelimit es zulässt.",
    ProcessingErrorCode.INTERNAL_ERROR:
        "Erneut versuchen; bleibt der Fehler, den kopierten Bericht für die Fehlersuche verwenden.",
}


def retry_pending(state: MailState) -> bool:
    """A failed mail whose next attempt is already due: retried by hand, or waiting for the rate limit."""
    return state.retry_requested


def retry_text(state: MailState) -> str:
    retry = state.processing_retry
    if retry_pending(state):
        return "Erneuter Versuch angefordert; die Mail wird beim nächsten Abruf verarbeitet."
    if retry is None:
        return "Keine automatischen Versuche."
    if retry.abandoned:
        return f"{retry.attempts} von {MAX_ATTEMPTS} automatischen Versuchen durchgeführt. Automatische " \
               "Wiederholung pausiert."
    return f"{retry.attempts} von {MAX_ATTEMPTS} automatischen Versuchen durchgeführt; Mailhelp versucht es " \
           "weiter."


def error_summary(code: str, stage: str, attempts: int | None) -> str:
    """One line for the mail list, e.g. ``Fehler: KI-Antwort wiederholt ungültig (Stufe: …, 5 Fehlversuche)``."""
    tried = "" if not attempts else f", {attempts} Fehlversuch{'e' if attempts != 1 else ''}"
    return f"Fehler: {ERROR_LABELS.get(code, code)} (Stufe: {STAGE_LABELS.get(stage, stage)}{tried})"


def _local(value: datetime | None, zone: ZoneInfo) -> str:
    return "–" if value is None else value.astimezone(zone).strftime("%d.%m.%Y, %H:%M:%S Uhr")


@dataclass(frozen=True)
class ErrorReport:
    mail_id: str
    subject: str
    stage: str
    stage_label: str
    code: str
    label: str
    explanation: str
    advice: str
    retry: str
    occurred: str
    first_failed: str
    last_failed: str
    occurred_utc: str
    attempts: str
    paths: tuple[str, ...]
    call_ids: tuple[str, ...]

    def text(self) -> str:
        """The copyable report: only identifiers, codes and times."""
        lines = ["=== Mailhelp Fehlerbericht ===", f"Mail-ID: {self.mail_id}", f"Betreff: {self.subject[:80]}",
                 f"Fehlercode: {self.code}", f"Verarbeitungsstufe: {self.stage}", f"Zeitpunkt: {self.occurred_utc}",
                 f"Versuche: {self.attempts}"]
        lines += [f"Feldpfad: {path}" for path in self.paths]
        lines += [f"LLM-Calls: {', '.join(self.call_ids)}"] if self.call_ids else []
        return "\n".join([*lines, "=============================="])


def error_report(state: MailState, subject: str, timezone: str) -> ErrorReport | None:
    """The report of a failed mail that is not filed; ``None`` otherwise."""
    error = state.error
    if error is None or state.processing_filed:
        return None
    zone, retry = ZoneInfo(timezone), state.processing_retry
    if retry is None:
        attempts = "angefordert" if retry_pending(state) else "–"
    else:
        attempts = f"{retry.attempts}/{MAX_ATTEMPTS}" + (" (pausiert)" if retry.abandoned else "")
    return ErrorReport(
        mail_id=state.id, subject=subject, stage=error.stage.value,
        stage_label=STAGE_LABELS.get(error.stage.value, error.stage.value), code=error.code.value,
        label=ERROR_LABELS.get(error.code.value, error.code.value), explanation=ERROR_TEXTS[error.code],
        advice=ADVICE[error.code], retry=retry_text(state), occurred=_local(error.occurred_at, zone),
        first_failed=_local(retry.first_failed_at if retry else None, zone),
        last_failed=_local(retry.last_failed_at if retry else None, zone),
        occurred_utc=error.occurred_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        attempts=attempts,
        paths=tuple(".".join(str(part) for part in issue.path) for issue in state.validation_errors if issue.path),
        call_ids=tuple(state.llm_call_ids[-5:]))
