"""6.1.4: refused targets carry a structured reason, so the setup check can say what to do."""
import httpx
import pytest

from mailhelp.external.contracts import AuthenticationError, CalendarAccessError, TargetAccessError
from mailhelp.external.http_writer import HttpWriter
from mailhelp.llm.adapter import PermanentError


def writer(service, response):
    return HttpWriter(service, "synthetic-token", "ziel", calendar_timezone="Europe/Berlin",
                      transport=httpx.MockTransport(lambda request: response))


def google_403(reason):
    return httpx.Response(403, json={"error": {"errors": [{"reason": reason}]}})


@pytest.mark.parametrize(("service", "response", "kind", "reason"), [
    ("todoist", httpx.Response(403), TargetAccessError, "forbidden"),
    ("todoist", httpx.Response(404), TargetAccessError, "not_found"),
    ("google_calendar", httpx.Response(404), CalendarAccessError, "not_found"),
    ("google_calendar", google_403("insufficientPermissions"), CalendarAccessError, "forbidden"),
    ("google_calendar", google_403("accessNotConfigured"), CalendarAccessError, "api_disabled"),
    ("google_calendar", google_403("somethingElse"), CalendarAccessError, "forbidden"),
])
def test_regression_a_refused_target_names_its_reason(service, response, kind, reason):
    """Regression 6.1.4: Todoist 403/404 raised a bare PermanentError; the setup check could only
    say "Unerwarteter Fehler" instead of "Projekt nicht gefunden"."""
    with pytest.raises(kind) as raised:
        writer(service, response).check_access()
    assert raised.value.reason == reason
    assert isinstance(raised.value, PermanentError)  # writes still treat it as a permanent refusal


def test_a_rejected_token_stays_an_authentication_error():
    for service in ("todoist", "google_calendar"):
        with pytest.raises(AuthenticationError):
            writer(service, httpx.Response(401)).check_access()
