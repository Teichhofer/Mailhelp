"""Acquisition time accounting is context-local and survives nested failures."""
from itertools import count
from threading import RLock

import pytest

from mailhelp.models import TelegramOffset
from mailhelp.runtime import lock_metrics
from mailhelp.storage import JsonStore
from tests.fakes.shared_web_auth import pair


def test_lock_waits_are_scoped_and_restored_after_a_nested_failure(monkeypatch):
    times = iter([1, 1.01, 2, 2.02, 3, 3.015, 4, 4.1])
    monkeypatch.setattr(lock_metrics, "perf_counter", lambda: next(times))
    lock = RLock()
    with lock_metrics.measure_lock_waits() as outer:
        with lock_metrics.measured_lock(lock, "dialog"):
            pass
        with pytest.raises(ValueError, match="synthetic"):
            with lock_metrics.measure_lock_waits() as inner:
                with lock_metrics.measured_lock(lock, "store"):
                    raise ValueError("synthetic")
        with lock_metrics.measured_lock(lock, "store"):
            pass
    with lock_metrics.measured_lock(lock, "dialog"):
        pass
    assert outer == pytest.approx({"dialog_lock_wait_ms": 10, "store_lock_wait_ms": 15})
    assert inner == pytest.approx({"dialog_lock_wait_ms": 0, "store_lock_wait_ms": 20})


@pytest.mark.parametrize("operation", ["save", "load", "peek", "load_model", "delete", "touch", "names", "locked"])
def test_each_store_port_accounts_for_its_lock_wait_in_the_command_scope(tmp_path, monkeypatch, operation):
    store = JsonStore(tmp_path)
    store.save("state", {"offset": 3})
    ticks = count()
    monkeypatch.setattr(lock_metrics, "perf_counter", lambda: float(next(ticks)))
    calls = {
        "save": lambda: store.save("state", {"offset": 4}),
        "load": lambda: store.load("state"),
        "peek": lambda: store.peek("state"),
        "load_model": lambda: store.load_model("state", TelegramOffset),
        "delete": lambda: store.delete("state"),
        "touch": store.touch,
        "names": store.names,
    }
    with lock_metrics.measure_lock_waits() as waits:
        if operation == "locked":
            with store.locked():
                pass
        else:
            calls[operation]()
    assert waits["store_lock_wait_ms"] >= 1000 and waits["dialog_lock_wait_ms"] == 0


def test_session_authorization_accounts_for_the_shared_store_lock_alias(auth, monkeypatch):
    session = auth.authenticate(pair(auth))
    original = auth._lock
    clock = [0.0]
    class ContendedLock:
        def __enter__(self):
            clock[0] += 0.25
            return original.__enter__()
        def __exit__(self, *args):
            return original.__exit__(*args)
    monkeypatch.setattr(auth, "_lock", ContendedLock())
    monkeypatch.setattr(lock_metrics, "perf_counter", lambda: clock[0])
    with lock_metrics.measure_lock_waits() as waits:
        assert auth.active(session.id)
    assert waits["store_lock_wait_ms"] == pytest.approx(250)
