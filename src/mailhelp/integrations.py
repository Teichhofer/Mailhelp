"""Compatibility facade for integrations; implementations live in external/."""
from .external.contracts import (AuthenticationError, OAuthTokenError, CalendarAccessError,
    IntegrationModel, TodoistTaskResponse, TodoistTaskListResponse, CalendarEventResponse,
    CalendarListResponse, CalendarOverlapEvent, ExternalWriter, AccessTokenProvider,
    PreparedWrite, proposal_is_writable, _path)
from .external.oauth import GoogleOAuthTokenProvider, OAuthTokenResponse
from .external.ical import CalendarFileWriter, calendar_file, _ical_datetime, _ical_text, _fold_ical_line
from .external.calendar import _now
from .external.transport import _google_error_reason
from .external.http_writer import HttpWriter
from .external.confirmed import execute_confirmed, _with_external_result
