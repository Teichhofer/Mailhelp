"""Öffentliche Liste der Modelle, deren JSON-Form dauerhaft gespeichert wird.

Die expliziten Exporte bilden die Persistenzgrenze: interne Transport- und
Command-Modelle gehören nicht automatisch zum Dateiformat. Die Implementierung
der Invarianten verbleibt in den jeweiligen Domain-Kontexten.
"""

from __future__ import annotations

from ..activity.models import ActivityReport, ReportMail
from ..diagnostics import DiagnosticsState
from ..domain.duplicate import DuplicateIndex
from ..domain.mail import MailState
from ..domain.processing import (
    ProposalClarificationState,
    TelegramDialogState,
    TelegramOutboxState,
)
from ..domain.proposal import ActionLedger
from ..domain.relevance import IrrelevantSenders, RelevanceDialog
from ..domain.run import ImapCheckpoint, MailRunState, TelegramOffset
from ..notifications import NotificationQueue
from ..setup import SetupState

__all__ = [
    "ActivityReport",
    "ActionLedger",
    "DuplicateIndex",
    "DiagnosticsState",
    "ImapCheckpoint",
    "IrrelevantSenders",
    "MailRunState",
    "MailState",
    "NotificationQueue",
    "ProposalClarificationState",
    "RelevanceDialog",
    "ReportMail",
    "SetupState",
    "TelegramDialogState",
    "TelegramOffset",
    "TelegramOutboxState",
]
