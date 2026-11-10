"""5.2 V8: durable read retries, provider wait hints, restarts, concurrent checks and lock-free reads."""
import threading
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState, WriteVerification, operation_id
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.processing.write_verification import WriteVerifications, retry_after
from mailhelp.storage import JsonStore
from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


def limited(headers):
    return httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.invalid"),
                                 response=httpx.Response(429, headers=headers))


def confirmed():
    return proposal(3, "a", status="confirmed", confirmed_web_actor=None, title="Unterlagen senden",
                    due=date(2026, 11, 11))


@pytest.fixture
def store(tmp_path):
    with JsonStore(tmp_path / "data") as value:
        yield value


def persist_into(store):
    def persist(item):
        store.save(state_names.proposal(item.source_mail_id, item.id), item.model_dump(mode="json"))
    return persist


def record(store):
    return store.load_model(state_names.write_verification(operation_id(mail_id(3), "a", 1, "create")),
                            WriteVerification)


@pytest.mark.parametrize(("headers", "seconds"), [
    ({"Retry-After": "120"}, 120.0),
    ({"Retry-After": "999999"}, 3600.0),
    ({"Retry-After": "Tue, 10 Nov 2026 09:02:00 GMT"}, 120.0),
    ({"Retry-After": "Tue, 10 Nov 2026 08:00:00 GMT"}, 0.0),
    ({"Retry-After": "Tue, 10 Nov 2026 09:02:00 -0000"}, 0.0),
    ({"Retry-After": "bald"}, 0.0),
    ({}, 0.0),
])
def test_provider_wait_hints_are_read_and_bounded(headers, seconds):
    assert retry_after(limited(headers), NOW) == seconds
    assert retry_after(ValueError("x"), NOW) == 0.0


def test_a_wait_hint_postpones_the_next_read_and_ends_it_beyond_the_deadline(store):
    provider, clock = SimulatedProvider(), [NOW]
    checks = WriteVerifications(store, now=lambda: clock[0])
    writer = VerifyingWriter(provider, script=[limited({"Retry-After": "120"}), limited({"Retry-After": "3000"})])
    changed, _ = execute_confirmed(confirmed(), writer, persist_into(store), verification=checks)
    checks.check(changed, writer, persist_into(store))
    assert record(store).next_check_at == NOW + timedelta(seconds=120)
    clock[0] = NOW + timedelta(seconds=120)
    checks.check(changed, writer, persist_into(store))
    assert (record(store).state, record(store).last_error) == (VerificationState.UNAVAILABLE, "rate_limited")
    assert provider.writes == [f"mailhelp:{mail_id(3)}:a:v1"]


def test_a_restart_continues_the_stored_check_with_its_attempts(store):
    provider, clock = SimulatedProvider(), [NOW]
    first = WriteVerifications(store, now=lambda: clock[0])
    writer = VerifyingWriter(provider, script=[None])
    changed, _ = execute_confirmed(confirmed(), writer, persist_into(store), verification=first)
    first.check(changed, writer, persist_into(store))
    assert record(store).attempts == 1
    clock[0] += timedelta(seconds=1)
    restarted = WriteVerifications(store, now=lambda: clock[0])  # a new process, a fresh token, same account
    created, checked = restarted.check(changed, VerifyingWriter(provider), persist_into(store))
    assert (checked.state, checked.attempts, created.status.value) == (VerificationState.VERIFIED, 2, "created")
    assert len(provider.writes) == 1


def test_only_one_check_of_an_operation_runs_at_a_time(store):
    provider = SimulatedProvider()
    checks = WriteVerifications(store, now=lambda: NOW)
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persist_into(store), verification=checks)
    reading, release, second = threading.Event(), threading.Event(), []

    def slow_read():
        reading.set()
        release.wait(5)

    writer.on_read = slow_read
    thread = threading.Thread(target=checks.check, args=(changed, writer, persist_into(store)))
    thread.start()
    assert reading.wait(5)
    second.append(checks.check(changed, VerifyingWriter(provider), persist_into(store)))
    release.set()
    thread.join(5)
    assert second[0][1].state == VerificationState.PENDING and provider.reads == ["t1"]
    assert record(store).state == VerificationState.VERIFIED


def test_the_read_never_holds_the_state_lock(store):
    provider = SimulatedProvider()
    checks = WriteVerifications(store, now=lambda: NOW)
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persist_into(store), verification=checks)
    free = []

    def probe():  # another thread (e.g. the web server) must get the store meanwhile
        def take():
            got = store._thread_lock.acquire(timeout=2)
            free.append(got)
            if got:
                store._thread_lock.release()
        other = threading.Thread(target=take)
        other.start()
        other.join(5)

    writer.on_read = probe
    checks.check(changed, writer, persist_into(store))
    assert free == [True]
