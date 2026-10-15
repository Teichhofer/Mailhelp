"""Status page contacts: empty IMAP discoveries, Telegram polls and the access check at start (3.3.2)."""
from __future__ import annotations

from threading import Event

import pytest
from shared_application import Orch
from shared_application import settings as app_settings

from mailhelp.application import Application
from mailhelp.external.providers import Writers
from mailhelp.metrics import MetricsRecorder, MetricsSettings
from mailhelp.target_profiles import ProfileWriters, UnavailableWriter


class Service:
    """Synthetic client: ``check_access`` succeeds or raises the given error."""

    def __init__(self, service: str = "", error: Exception | None = None):
        self.service, self.error, self.checked = service, error, 0

    def check_access(self) -> None:
        self.checked += 1
        if self.error is not None:
            raise self.error


class MetricsLogger:
    """Records events and forwards them to the metrics like JsonlLogger.event."""

    def __init__(self, metrics: MetricsRecorder):
        self.metrics, self.events = metrics, []

    def event(self, level, module, event, **context):
        self.events.append((level, module, event))
        self.metrics.observe(event, {"service": module, **context})


def contacts(tmp_path, mode, *events):
    metrics = MetricsRecorder(tmp_path / "llm.jsonl", MetricsSettings(), mode)
    for service, event in events:
        metrics.observe(event, {"service": service})
    return set(metrics.runtime()["contacts"])


def test_empty_imap_discovery_counts_as_successful_contact(tmp_path):
    """Regression: a mail cycle without new mail left the IMAP mailbox 'unbekannt'."""
    assert contacts(tmp_path, "standard", ("imap", "messages_discovered")) == {"IMAP-Postfach"}


def test_completed_telegram_poll_counts_as_contact_without_messages(tmp_path):
    """Regression: Telegram stayed 'unbekannt' while the receiver polled successfully."""
    assert contacts(tmp_path, "standard", ("telegram", "poll_completed")) == {"Telegram"}
    assert contacts(tmp_path, "standard", ("telegram", "poll_failed"), ("imap", "request_failed")) == set()


@pytest.mark.parametrize(("mode", "expected"), [("standard", {"KI-Modelle (OpenRouter)", "Jev (Relevanz)"}),
                                                ("local", {"Ollama"})])
def test_confirmed_model_access_marks_the_models_of_the_mode(tmp_path, mode, expected):
    assert contacts(tmp_path, mode, ("llm", "access_confirmed")) == expected


def test_confirmed_access_marks_telegram_and_every_write_service(tmp_path):
    services = ("todoist", "google_calendar", "caldav_calendar", "caldav_tasks", "apple_reminders",
                "outlook_calendar", "microsoft_todo")
    assert contacts(tmp_path, "standard", ("telegram", "access_confirmed"),
                    *((service, "access_confirmed") for service in services)) == {
        "Telegram", "Todoist", "Google Kalender", "CalDAV-Kalender", "CalDAV-Aufgaben", "Apple Erinnerungen",
        "Outlook-Kalender", "Microsoft To Do"}
    assert contacts(tmp_path, "standard", ("telegram", "access_check_failed"),
                    ("unavailable", "access_confirmed")) == set()


def application(tmp_path, *, openrouter=None, telegram=None, todoist=None, calendar=None, telegram_enabled=True):
    settings = app_settings(tmp_path)
    if not telegram_enabled:
        settings = settings.model_copy(update={"telegram": settings.telegram.model_copy(update={"enabled": False})})
    logger = MetricsLogger(MetricsRecorder(tmp_path / "llm.jsonl", MetricsSettings(), "standard"))
    return Application(settings, object(), logger, object(), openrouter or Service(), object(),
                       telegram or Service(), todoist or Service("todoist"), calendar or Service("google_calendar"),
                       Orch(), Event())


def test_access_check_at_start_confirms_each_reachable_service(tmp_path):
    app = application(tmp_path)
    app.confirm_access()
    assert [event for event in app.logger.events] == [
        ("INFO", "llm", "access_confirmed"), ("INFO", "telegram", "access_confirmed"),
        ("INFO", "todoist", "access_confirmed"), ("INFO", "google_calendar", "access_confirmed")]
    assert set(app.logger.metrics.runtime()["contacts"]) == {
        "KI-Modelle (OpenRouter)", "Jev (Relevanz)", "Telegram", "Todoist", "Google Kalender"}


def test_failed_or_missing_check_only_logs_and_leaves_the_service_unknown(tmp_path):
    todoist = Service("todoist", RuntimeError("401"))
    app = application(tmp_path, todoist=todoist, telegram=object())
    app.confirm_access()
    assert ("WARNING", "telegram", "access_check_failed") in app.logger.events
    assert ("WARNING", "todoist", "access_check_failed") in app.logger.events
    assert set(app.logger.metrics.runtime()["contacts"]) == {
        "KI-Modelle (OpenRouter)", "Jev (Relevanz)", "Google Kalender"}


def test_access_check_sends_nothing_to_a_disabled_telegram(tmp_path):
    telegram = Service()
    app = application(tmp_path, telegram=telegram, telegram_enabled=False)
    app.confirm_access()
    assert telegram.checked == 0 and "Telegram" not in app.logger.metrics.runtime()["contacts"]


def test_access_check_covers_active_target_profiles_only(tmp_path):
    first = Writers(calendar=Service("google_calendar"), tasks=Service("todoist"))
    other = Writers(calendar=Service("caldav_calendar"), tasks=UnavailableWriter("tasks", "x", 1))
    unused = Writers(calendar=Service("outlook_calendar"), tasks=Service("microsoft_todo"))
    app = application(tmp_path)
    app.profile_writers = ProfileWriters({1: first, 2: unused})
    app.confirm_access()
    assert first.calendar.checked == first.tasks.checked == 1
    assert unused.calendar.checked == unused.tasks.checked == 0
    app.profile_writers = ProfileWriters({1: other})
    app.logger.events.clear()
    app.confirm_access()
    assert [event for event in app.logger.events if event[1] not in {"llm", "telegram"}] == [
        ("INFO", "caldav_calendar", "access_confirmed")]


def test_access_check_stops_with_the_service(tmp_path):
    openrouter = Service()
    app = application(tmp_path, openrouter=openrouter)
    app.stop_event.set()
    app.confirm_access()
    assert openrouter.checked == 0 and app.logger.events == []


def test_access_check_runs_beside_the_mail_loop(tmp_path):
    app = application(tmp_path)
    thread = app.confirm_access_in_background()
    thread.join(timeout=5)
    assert thread.daemon and not thread.is_alive()
    assert ("INFO", "google_calendar", "access_confirmed") in app.logger.events
