"""Failure handling of the mail pipeline (7.0, R5)."""
from __future__ import annotations

import time
import traceback
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..domain.processing import ProcessingErrorCode, ValidationIssue
from ..llm.adapter import PermanentError
from ..llm.openrouter import RateLimitExceeded
from ..mailbox.mime import MimeLimitExceeded
from . import mail_pipeline as mail_pipeline_module
from .analysis import (
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationExceeded,
)

if TYPE_CHECKING:
    from .mail_pipeline import MailPipeline, ProcessingOutcome, ProcessingRun


def handle_failure(pipeline: MailPipeline, run: ProcessingRun, exc: Exception) -> ProcessingOutcome:
    """Record a failed step; called inside ``except`` so the traceback is current."""
    name, state, stage, started = run.name, run.state, run.stage, run.started
    if isinstance(exc, mail_pipeline_module.AnalysisDataUnavailable):
        pipeline.o.failure(name, state, ProcessingErrorCode.ANALYSIS_DATA_REMOVED, stage,
                       "Analyse-Daten fehlen. Bitte bei Bedarf eine bewusste Neuprüfung starten.", False)
        pipeline.o.logger.event("ERROR", "orchestrator", "analysis_data_unavailable", mail_id=state.id,
                            stage=stage.value)
        return mail_pipeline_module.ProcessingOutcome.FAILED
    if isinstance(exc, RateLimitExceeded):
        state.deferred_until = datetime.fromtimestamp(exc.next_allowed_at, UTC)
        retry_at = state.deferred_until.isoformat()
        pipeline.o.failure(name, state, ProcessingErrorCode.LLM_RATE_LIMITED, stage,
                      f"LLM-Limit erreicht. Automatischer neuer Versuch nach {retry_at}.", True)
        pipeline.o.logger.event("WARNING", "orchestrator", "llm_rate_limited", mail_id=state.id,
                          next_allowed_at=retry_at, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                          error=exc, stacktrace=traceback.format_exc())
        return mail_pipeline_module.ProcessingOutcome.WAITING
    if isinstance(exc, MimeLimitExceeded):
        pipeline.o.failure(name, state, ProcessingErrorCode.MIME_LIMIT_EXCEEDED, stage,
                      "Die Nachricht überschreitet ein Sicherheitslimit. "
                      "Bitte Anhänge oder Nachrichtengröße reduzieren.", False)
        pipeline.o.logger.event("WARNING", "orchestrator", "mime_limit_exceeded", mail_id=state.id, stage=stage.value,
                          limit=exc.limit, error=exc, stacktrace=traceback.format_exc())
        return mail_pipeline_module.ProcessingOutcome.FAILED
    if isinstance(exc, LlmProviderResponseInvalid):
        pipeline.o.failure(name, state, ProcessingErrorCode.PROVIDER_RESPONSE_INVALID, stage,
                      "Der LLM-Anbieter hat keine verwendbare Antwort geliefert.", True)
        pipeline.o.logger.event("ERROR", "orchestrator", "provider_response_invalid", mail_id=state.id,
                          stage=stage.value, reason=exc.reason, error=exc, stacktrace=traceback.format_exc())
    elif isinstance(exc, LlmInvalidJson):
        pipeline.o.failure(name, state, ProcessingErrorCode.INVALID_JSON, stage,
                      "Die LLM-Antwort enthielt kein gültiges JSON.", True)
        pipeline.o.logger.event("ERROR", "orchestrator", "invalid_json", mail_id=state.id, stage=stage.value,
                          error=exc, stacktrace=traceback.format_exc())
    elif isinstance(exc, LlmSchemaValidationExceeded):
        state.validation_errors.append(ValidationIssue(
            stage=stage, code="schema_validation_failed", occurred_at=datetime.now(UTC)
        ))
        pipeline.o.failure(name, state, ProcessingErrorCode.SCHEMA_VALIDATION_FAILED, stage,
                      "Die automatische Auswertung war nicht zuverlässig. "
                      "Bitte die Nachricht manuell prüfen.", True)
        pipeline.o.logger.event("ERROR", "orchestrator", "schema_validation_failed", mail_id=state.id,
                          stage=stage.value, error=exc, stacktrace=traceback.format_exc())
    elif isinstance(exc, PermanentError):
        detail = getattr(exc, "safe_detail", None)
        suffix = f" {detail}" if detail else ""
        pipeline.o.failure(name, state, ProcessingErrorCode.PERMANENT_ADAPTER_ERROR, stage,
                      ("Ein externer Dienst hat die Anfrage dauerhaft abgelehnt. "
                       f"Bitte dessen Konfiguration prüfen.{suffix}"), False)
        pipeline.o.logger.event("ERROR", "orchestrator", "permanent_adapter_error", mail_id=state.id, stage=stage.value,
                          error=exc, stacktrace=traceback.format_exc())
    else:
        pipeline.o.failure(name, state, ProcessingErrorCode.INTERNAL_ERROR, stage,
                      "Ein interner Fehler ist aufgetreten. Bitte Protokoll und Konfiguration prüfen.")
        pipeline.o.logger.event("ERROR", "orchestrator", "processing_failed", mail_id=state.id, stage=stage.value,
                          error=exc, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                          stacktrace=traceback.format_exc())
    return pipeline.o.failure_outcome(name, state, stage)
