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
from ..domain.proposal_sources import ProposalRelation
from ..domain.reconciliation import ProposalMatchCache, ProposalMergeJournal
from ..domain.relevance import IrrelevantSenders, RelevanceDialog
from ..domain.run import ImapCheckpoint, MailRunState, TelegramOffset
from ..notifications.notifications import NotificationQueue
from ..runtime.diagnostics import DiagnosticsState
from ..runtime.initial_setup import InitialDraft
from ..runtime.oauth_web import OAuthJobs
from ..runtime.setup import SetupState
from ..runtime.web_password import PasswordState

__all__ = [
    "ActivityReport",
    "ActionLedger",
    "DuplicateIndex",
    "DiagnosticsState",
    "ImapCheckpoint",
    "InitialDraft",
    "IrrelevantSenders",
    "MailRunState",
    "MailState",
    "NotificationQueue",
    "OAuthJobs",
    "PasswordState",
    "ProposalClarificationState",
    "ProposalMatchCache",
    "ProposalMergeJournal",
    "ProposalRelation",
    "RelevanceDialog",
    "ReportMail",
    "SetupState",
    "TelegramDialogState",
    "TelegramOffset",
    "TelegramOutboxState",
]
