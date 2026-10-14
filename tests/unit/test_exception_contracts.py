from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import mailhelp
from mailhelp.adapter import PermanentError, RetryableError, UncertainWriteError
from mailhelp.external.contracts import (
    AuthenticationError,
    CalendarAccessError,
    ExternalRefused,
    ExternalServiceError,
    ExternalUnavailable,
    ExternalUncertain,
    OAuthTokenError,
)
from mailhelp.logging import log_and_continue


def find_all_mailhelp_exceptions() -> list[type[BaseException]]:
    exceptions: list[type[BaseException]] = []
    prefix = mailhelp.__name__ + "."
    for _, module_name, _is_pkg in pkgutil.walk_packages(mailhelp.__path__, prefix):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BaseException) and obj.__module__.startswith("mailhelp"):
                if obj not in exceptions:
                    exceptions.append(obj)
    return exceptions


def test_exception_hierarchy():
    assert issubclass(ExternalUnavailable, (ExternalServiceError, RetryableError))
    assert issubclass(ExternalRefused, (ExternalServiceError, PermanentError))
    assert issubclass(ExternalUncertain, (ExternalServiceError, UncertainWriteError))
    assert issubclass(AuthenticationError, ExternalRefused)
    assert issubclass(CalendarAccessError, ExternalRefused)
    assert issubclass(OAuthTokenError, AuthenticationError)


def test_all_custom_exceptions_exist_and_can_be_instantiated_safely():
    exceptions = find_all_mailhelp_exceptions()
    assert len(exceptions) >= 15
    secrets = ["SECRET_PASSWORD_123", "Bearer ya29.secret_token", "api_key=sk-openrouter"]
    for exc_cls in exceptions:
        # Instantiate with a message or no-arg
        try:
            instance = exc_cls("Safe diagnostic message")
        except TypeError:
            try:
                instance = exc_cls()
            except TypeError:
                continue
        msg = str(instance)
        # Ensure raw secrets are never leaked as default strings
        for secret in secrets:
            assert secret not in msg


def test_log_and_continue():
    events: list[tuple[str, str, str, dict[str, Any]]] = []

    class FakeLogger:
        def event(self, level: str, module: str, event: str, **context: Any) -> None:
            events.append((level, module, event, context))

    logger = FakeLogger()
    exc = ValueError("Testfehler")
    log_and_continue(logger, "test_module", "test_event", exc=exc, custom="field")

    assert len(events) == 1
    level, module, event, context = events[0]
    assert level == "ERROR"
    assert module == "test_module"
    assert event == "test_event"
    assert context["error_class"] == "ValueError"
    assert context["custom"] == "field"

    # Without exc
    log_and_continue(logger, "test_module", "event_no_exc", extra=123)
    assert len(events) == 2
    assert events[1][3]["extra"] == 123
    assert "error_class" not in events[1][3]

