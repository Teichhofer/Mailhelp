"""Öffentliche Liste der Modelle, deren JSON-Form dauerhaft gespeichert wird.

Die expliziten Exporte bilden die Persistenzgrenze: interne Transport- und
Command-Modelle gehören nicht automatisch zum Dateiformat. Die Implementierung
der Invarianten verbleibt in den jeweiligen Domain-Kontexten.
"""

from __future__ import annotations

from ..activity.models import ActivityReport, ReportMail
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

__all__ = [
    "ActivityReport",
    "ActionLedger",
    "DuplicateIndex",
    "ImapCheckpoint",
    "IrrelevantSenders",
    "MailRunState",
    "MailState",
    "ProposalClarificationState",
    "RelevanceDialog",
    "ReportMail",
    "TelegramDialogState",
    "TelegramOffset",
    "TelegramOutboxState",
]
