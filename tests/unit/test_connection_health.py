"""7.9.2: the durable sign-in status of the used connections (synthetic events only)."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.logging import JsonlLogger
from mailhelp.persistence.storage import JsonStore
from mailhelp.support.connection_health import (
    STATE,
    ConnectionHealthRecorder,
    classify,
    current,
    digest,
    used_connections,
)
from mailhelp.support.metrics import MetricsRecorder, MetricsSettings

T0 = datetime(2026, 11, 18, 20, 18, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def health(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        clock = Clock()
        warnings = []
        recorder = ConnectionHealthRecorder(store, clock, warnings.append)
        recorder.clock_, recorder.warnings = clock, warnings
        yield recorder


@pytest.mark.parametrize(("event", "context", "expected"), [
    ("token_refresh_denied", {"service": "google_oauth", "status": 400},
     ("google_oauth", "google_oauth", None, "refresh_denied")),
    ("token_credentials_accepted", {"service": "microsoft_oauth"}, ("microsoft_oauth", "microsoft_oauth", None, None)),
    ("token_refresh_started", {"service": "google_oauth"}, None),
    ("authentication_failed", {"service": "todoist", "status": 401}, ("todoist", "todoist", None, "login_rejected")),
    ("target_access_failed", {"service": "google_calendar", "profile": 2},
     ("google_calendar", "google_calendar", 2, "permission_denied")),
    ("access_check_failed", {"service": "caldav_calendar", "error": "AuthenticationError: abgelehnt", "profile": 1},
     ("caldav_calendar", "caldav_calendar", 1, "login_rejected")),
    ("access_check_failed", {"service": "google_calendar", "error": "ReadTimeout: zu langsam"}, None),
    ("access_confirmed", {"service": "outlook_calendar", "profile": True},
     ("outlook_calendar", "outlook_calendar", None, None)),
    ("create_failed", {"service": "todoist"}, None),
    ("poll_failed", {"service": "imap", "account_id": "a1", "mailbox": 2,
                     "error": "IMAP-Anmeldung vom Server abgelehnt. Bitte prüfen."},
     ("imap:a1", "imap", 2, "login_rejected")),
    ("poll_failed", {"service": "imap", "account_id": "a1", "error": "IMAP-Ordner nicht lesbar: X"}, None),
    ("messages_discovered", {"service": "imap", "account_id": "a1"}, ("imap:a1", "imap", None, None)),
    ("messages_discovered", {"service": "imap"}, None),
    ("poll_failed", {"service": "iserv", "account": 1,
                     "error": "IServ-Anmeldung fehlgeschlagen oder weiterer Anmeldeschritt erforderlich"},
     ("iserv:1", "iserv", 1, "login_rejected")),
    ("access_check_failed", {"service": "iserv", "account": 1, "error": "IServSignInError: Unbekanntes Formular"},
     ("iserv:1", "iserv", 1, "login_rejected")),
    ("poll_failed", {"service": "iserv", "account": 1, "error": "IServ antwortete mit HTTP-Status 503"}, None),
    ("letters_listed", {"service": "iserv", "account": 1}, ("iserv:1", "iserv", 1, None)),
    ("letters_listed", {"service": "iserv"}, None),
    ("request", {"service": "web"}, None),
])
def test_only_explicit_sign_in_outcomes_count(event, context, expected):
    """Timeouts, unreadable folders and server errors are other kinds of failure (Planung 7.9, 4.5)."""
    assert classify(event, context) == expected


def test_a_refused_renewal_stays_until_the_next_successful_one_and_survives_a_restart(health, tmp_path):
    health.observe("token_refresh_denied", {"service": "google_oauth", "status": 400})
    (problem,) = current(health.store)
    assert (problem.key, problem.code, problem.first_seen, problem.last_success) == (
        "google_oauth", "refresh_denied", T0, None)
    # A restart reads the same readable file.
    assert [item.key for item in current(JsonStore(tmp_path / "data"))] == ["google_oauth"]
    health.clock_.now = T0 + timedelta(minutes=15)
    health.observe("token_refresh_denied", {"service": "google_oauth", "status": 400})
    (again,) = current(health.store)
    assert again.first_seen == T0 and again.last_seen == T0 + timedelta(minutes=15) and again.sequence == 2
    health.clock_.now = T0 + timedelta(minutes=30)
    health.observe("token_credentials_accepted", {"service": "google_oauth"})
    assert current(health.store) == ()
    stored = health.store.load(STATE)
    assert stored["successes"] == {"google_oauth": "2026-11-18T20:48:00Z"} and "tok" not in str(stored)


def test_only_the_repaired_connection_loses_its_warning(health):
    health.observe("authentication_failed", {"service": "todoist", "status": 401})
    health.observe("poll_failed", {"service": "imap", "account_id": "a1", "mailbox": 1,
                                   "error": "IMAP-Anmeldung vom Server abgelehnt."})
    health.clock_.now = T0 + timedelta(seconds=1)
    health.observe("create_completed", {"service": "todoist"})
    assert [item.key for item in current(health.store)] == ["imap:a1"]


def test_late_results_never_override_newer_ones(health):
    health.clock_.now = T0 + timedelta(minutes=5)
    health.observe("access_confirmed", {"service": "google_calendar"})
    health.clock_.now = T0  # an older check reports late (a clock step back)
    health.observe("authentication_failed", {"service": "google_calendar"})
    assert current(health.store) == ()
    health.clock_.now = T0 + timedelta(minutes=10)
    health.observe("authentication_failed", {"service": "google_calendar", "profile": 3})
    health.clock_.now = T0 + timedelta(minutes=6)
    health.observe("access_confirmed", {"service": "google_calendar"})
    (problem,) = current(health.store)
    assert problem.number == 3 and problem.last_success == T0 + timedelta(minutes=5)
    # The same failure at the same time writes nothing; another kind replaces it and keeps the profile.
    saved = health.store.load(STATE)
    health.clock_.now = T0 + timedelta(minutes=10)
    health.observe("authentication_failed", {"service": "google_calendar"})
    assert health.store.load(STATE) == saved
    health.observe("target_access_failed", {"service": "google_calendar"})
    (changed,) = current(health.store)
    assert changed.code == "permission_denied" and changed.number == 3


def test_a_quiet_success_is_written_only_when_it_is_newer(health):
    health.observe("messages_discovered", {"service": "imap", "account_id": "a1"})
    saved = health.store.load(STATE)
    health.observe("messages_discovered", {"service": "imap", "account_id": "a1"})
    assert health.store.load(STATE) == saved
    health.observe("request", {"service": "web"})
    assert health.store.load(STATE) == saved


def test_a_damaged_or_missing_file_starts_empty(health):
    assert health.load().problems == {}  # missing after an upgrade
    health.store.save(STATE, {"schema_version": 99})
    fresh = ConnectionHealthRecorder(health.store, health.clock_, health.warnings.append)
    assert fresh.load().problems == {} and health.warnings == ["connection_health_damaged"]
    assert current(health.store) == ()  # the page shows nothing instead of failing
    fresh.observe("token_refresh_denied", {"service": "notion_oauth"})
    assert [item.key for item in current(health.store)] == ["notion_oauth"]


def test_removed_connections_leave_no_warning_behind(health):
    health.observe("token_refresh_denied", {"service": "google_oauth"})
    health.observe("poll_failed", {"service": "imap", "account_id": "old",
                                   "error": "IMAP-Anmeldung vom Server abgelehnt."})
    saved = health.store.load(STATE)
    health.retain(*used_connections(["google_calendar"], ["old"], []))
    assert health.store.load(STATE) == saved
    health.retain(*used_connections(["todoist"], ["new"], [2]))
    assert current(health.store) == ()
    assert used_connections(["google_tasks", "notion"], ["a"], [1]) == (
        {"google_tasks", "google_oauth", "notion", "notion_oauth"}, {"imap:a", "iserv:1"})


def test_the_digest_changes_with_the_warnings_not_with_their_repetition(health):
    empty = digest(current(health.store))
    health.observe("token_refresh_denied", {"service": "google_oauth"})
    first = digest(current(health.store))
    health.clock_.now = T0 + timedelta(minutes=15)
    health.observe("token_refresh_denied", {"service": "google_oauth"})
    assert empty != first == digest(current(health.store))


def test_the_event_stream_reaches_the_status(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        logger = JsonlLogger(tmp_path / "logs" / "application.jsonl")
        logger.metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings())
        logger.metrics.health = ConnectionHealthRecorder(store)
        logger.event("ERROR", "google_oauth", "token_refresh_denied", status=400)
        assert [item.code for item in current(store)] == ["refresh_denied"]
