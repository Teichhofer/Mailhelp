"""Öffentliche Liste der Modelle, deren JSON-Form dauerhaft gespeichert wird.

Die expliziten Exporte bilden die Persistenzgrenze: interne Transport- und
Command-Modelle gehören nicht automatisch zum Dateiformat. Die Implementierung
der Invarianten verbleibt in den jeweiligen Domain-Kontexten.
"""
from ..domain.duplicate import DuplicateIndex
from ..domain.mail import MailState
from ..domain.processing import ProposalClarificationState, TelegramDialogState
from ..domain.relevance import IrrelevantSenders, RelevanceDialog
from ..domain.proposal import ActionLedger
from ..domain.run import ImapCheckpoint, MailRunState, TelegramOffset

__all__ = [
    "ActionLedger",
    "DuplicateIndex",
    "ImapCheckpoint",
    "IrrelevantSenders",
    "MailRunState",
    "MailState",
    "ProposalClarificationState",
    "RelevanceDialog",
    "TelegramDialogState",
    "TelegramOffset",
]
