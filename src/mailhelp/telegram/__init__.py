"""Public Telegram API, retained across the package-level decomposition."""

from __future__ import annotations

from ..persistence.ledger import ActionLedgerPort, ActionLedgerService
from ..persistence.proposals import (
    ProposalPersistence,
    ProposalRepository,
    clarification_name,
    proposal_name,
    proposal_version_name,
)
from ..temporal_answers import (
    DeterministicTemporalAnswer,
    deterministic_classification_revision,
    deterministic_temporal_revision,
    normalize_deterministic_temporal_answer,
    parse_deterministic_temporal_answer,
)
from .authorization import AuthorizedUpdateValidator, UpdateValidation
from .callbacks import (
    Decision,
    DecisionAction,
    RelevanceDecision,
    apply_decision,
    validate_callback_data,
    validate_callback_markup,
)
from .client import TelegramChatNotFoundError, TelegramClient, validation_path
from .decisions import ProposalDecisionService
from .delivery import ProposalDeliveryService
from .dialog import EventLogger, TelegramDialogController, TelegramTransport
from .formatting import format_proposal, numbered_message_parts, split_message
from .models import (
    InternalTelegramModel,
    TelegramBot,
    TelegramBotResponse,
    TelegramCallbackQuery,
    TelegramChat,
    TelegramMessage,
    TelegramTransportModel,
    TelegramUpdate,
    TelegramUpdatesResponse,
    TelegramUser,
    TelegramWriteResponse,
    TelegramWriteResult,
)
from .outbox import TelegramOutbox
from .presenter import ProposalPresentation, ProposalPresenter
from .relevance import RelevanceDialogProcessor, RelevanceDialogs
from .revisions import (
    ProposalRevisionProcessor,
    ProposalRevisions,
    ProposalRevisionService,
)
from .writes import ConfirmedWriteExecutor, WriteExecution

__all__ = [name for name in globals() if not name.startswith("_")]
