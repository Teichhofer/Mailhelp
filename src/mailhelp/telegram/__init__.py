"""Public Telegram API, retained across the package-level decomposition."""

from .authorization import AuthorizedUpdateValidator, UpdateValidation
from .client import TelegramChatNotFoundError, TelegramClient, _validation_path
from .dialog import EventLogger, TelegramDialogController, TelegramTransport
from .formatting import (
    format_proposal, numbered_message_parts, split_message, validate_callback_data,
    validate_callback_markup,
)
from .ledger import ActionLedgerPort, ActionLedgerService
from .models import (
    Decision, DecisionAction, InternalTelegramModel, RelevanceDecision, TelegramBot,
    TelegramBotResponse, TelegramCallbackQuery, TelegramChat, TelegramMessage,
    TelegramTransportModel, TelegramUpdate, TelegramUpdatesResponse, TelegramUser,
    TelegramWriteResponse, TelegramWriteResult, apply_decision,
)
from .persistence import (
    ProposalPersistence, ProposalRepository, clarification_name, proposal_name,
    proposal_version_name,
)
from .presenter import ProposalPresentation, ProposalPresenter
from .delivery import ProposalDeliveryService
from .decisions import ProposalDecisionService
from .relevance import RelevanceDialogProcessor, RelevanceDialogs
from .revisions import ProposalRevisionProcessor, ProposalRevisions, ProposalRevisionService
from .temporal import (
    DeterministicTemporalAnswer, deterministic_classification_revision,
    deterministic_temporal_revision,
    parse_deterministic_temporal_answer,
)
from .writes import ConfirmedWriteExecutor, WriteExecution

__all__ = [name for name in globals() if not name.startswith("_")]
