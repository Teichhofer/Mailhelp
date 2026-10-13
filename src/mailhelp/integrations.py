"""Compatibility facade for integrations; implementations live in external/.

Deprecated: only public names are re-exported, and the facade is removed in 3.0.
Mailhelp itself imports from ``external/``.
"""
from __future__ import annotations

from .external.confirmed import execute_confirmed
from .external.contracts import (
    AccessTokenProvider,
    AuthenticationError,
    CalendarAccessError,
    CalendarEventResponse,
    CalendarListResponse,
    CalendarOverlapEvent,
    ExternalRefused,
    ExternalServiceError,
    ExternalUnavailable,
    ExternalUncertain,
    ExternalWriter,
    IntegrationModel,
    OAuthTokenError,
    PreparedWrite,
    TodoistTaskListResponse,
    TodoistTaskResponse,
    proposal_is_writable,
    validation_path,
)
from .external.http_writer import HttpWriter
from .external.ical import CalendarFileWriter, calendar_file
from .external.oauth import GoogleOAuthTokenProvider, OAuthTokenResponse

__all__ = ['AuthenticationError', 'OAuthTokenError', 'CalendarAccessError', 'ExternalServiceError',
           'ExternalUnavailable', 'ExternalRefused', 'ExternalUncertain', 'IntegrationModel',
           'TodoistTaskResponse', 'TodoistTaskListResponse', 'CalendarEventResponse', 'CalendarListResponse',
           'CalendarOverlapEvent', 'ExternalWriter', 'AccessTokenProvider', 'PreparedWrite',
           'proposal_is_writable', 'validation_path', 'GoogleOAuthTokenProvider', 'OAuthTokenResponse',
           'CalendarFileWriter', 'calendar_file', 'HttpWriter', 'execute_confirmed']
