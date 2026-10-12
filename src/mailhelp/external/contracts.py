"""Provider response schemas and shared write contracts."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..adapter import PermanentError, RetryableError, UncertainWriteError
from ..models import Proposal


class ExternalServiceError(Exception):
    """Base class for errors originating from external services."""


class ExternalUnavailable(ExternalServiceError, RetryableError):
    """External service is temporarily unreachable or returned a retryable status."""


class ExternalRefused(ExternalServiceError, PermanentError):
    """External service permanently rejected the credentials or request."""


class ExternalUncertain(ExternalServiceError, UncertainWriteError):
    """Write outcome is uncertain and must be reconciled before retry."""


class AuthenticationError(ExternalRefused):
    """Anmeldedaten wurden dauerhaft abgelehnt; ein Schreibzugriff ist nicht unklar."""


class OAuthTokenError(AuthenticationError):
    """Client oder Refresh-Token wurden am OAuth-Endpunkt abgelehnt."""


class CalendarAccessError(ExternalRefused):
    """Ein bezogener Access-Token konnte den Zielkalender nicht erreichen."""


class IntegrationModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class TodoistTaskResponse(IntegrationModel):
    id: str | int
    content: str = ""
    description: str = ""
    due: dict[str, Any] | None = None
    url: str | None = None


class TodoistTaskListResponse(IntegrationModel):
    results: list[TodoistTaskResponse]
    next_cursor: str | None


class CalendarEventResponse(IntegrationModel):
    id: str = Field(min_length=1)
    htmlLink: str | None = None


class CalendarListResponse(IntegrationModel):
    items: list[CalendarEventResponse]


class CalendarOverlapEvent(IntegrationModel):
    id: str = Field(min_length=1)
    summary: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=4000)
    location: str | None = Field(default=None, max_length=1000)
    htmlLink: str | None = None
    start: dict[str, str]
    end: dict[str, str]


class ExternalWriter(Protocol):
    def reconcile(self, key: str) -> dict[str, Any] | None: ...
    def create(self, proposal: Proposal, key: str) -> dict[str, Any]: ...


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...
    def invalidate(self) -> None: ...


def proposal_is_writable(proposal: Proposal) -> bool:
    """Return whether the proposal may be confirmed and externally created."""
    return proposal.is_creatable


@dataclass(frozen=True)
class PreparedWrite:
    operation: Callable[[], dict[str, Any]]
    requires_write: bool = True


def validation_path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"

