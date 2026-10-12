"""Compatibility facade for integrations; implementations live in external/.

Deprecated: only public names are re-exported, and the facade is removed in 3.0.
Mailhelp itself imports from ``external/``.
"""
from __future__ import annotations

from .external.contracts import (AuthenticationError, OAuthTokenError, CalendarAccessError,
    IntegrationModel, TodoistTaskResponse, TodoistTaskListResponse, CalendarEventResponse,
    CalendarListResponse, CalendarOverlapEvent, ExternalWriter, AccessTokenProvider,
    PreparedWrite, proposal_is_writable, validation_path)
from .external.oauth import GoogleOAuthTokenProvider, OAuthTokenResponse
from .external.ical import CalendarFileWriter, calendar_file
from .external.http_writer import HttpWriter
from .external.confirmed import execute_confirmed

__all__ = ['AuthenticationError', 'OAuthTokenError', 'CalendarAccessError', 'IntegrationModel', 'TodoistTaskResponse', 'TodoistTaskListResponse', 'CalendarEventResponse', 'CalendarListResponse', 'CalendarOverlapEvent', 'ExternalWriter', 'AccessTokenProvider', 'PreparedWrite', 'proposal_is_writable', 'validation_path', 'GoogleOAuthTokenProvider', 'OAuthTokenResponse', 'CalendarFileWriter', 'calendar_file', 'HttpWriter', 'execute_confirmed']
