"""5.2 V2: a write answer or a re-found entry becomes CREATED only through a fresh, passed read."""
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from mailhelp import state_names
from mailhelp.config import WriteVerificationSettings
from mailhelp.domain.verification import VerificationState, WriteVerification, operation_id
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.llm.adapter import PermanentError, RetryableError
from mailhelp.models import Proposal, ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from mailhelp.telegram.writes import ConfirmedWriteExecutor
from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
KEY = f"mailhelp:{mail_id(3)}:a:v1"


class Persistence:
    def __init__(self, store):
        self.store, self.saved = store, []

    def persist(self, item):
        self.saved.append(item.status)
        self.store.save(state_names.proposal(item.source_mail_id, item.id), item.model_dump(mode="json"))


class Telegram:
    def __init__(self):
        self.sent = []

    def send(self, chat_id, text, *args, **kwargs):
        self.sent.append(text)


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


def confirmed(**fields):
    values = dict(status="confirmed", confirmed_web_actor=None, title="Unterlagen senden",
                  due=date(2026, 11, 11))
    values.update(fields)
    return proposal(3, "a", **values)


@pytest.fixture
def setup(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        provider, clock = SimulatedProvider(), Clock()
        persistence, telegram = Persistence(store), Telegram()
        checks = WriteVerifications(store, WriteVerificationSettings(), now=clock)

        def executor(writer, item=None):
            item = item or confirmed()
            if store.load(state_names.proposal(item.source_mail_id, item.id)) is None:
                persistence.persist(item)
            return ConfirmedWriteExecutor(store, {"todoist": writer}, persistence, telegram, 2, False, None,
                                          "Europe/Berlin", checks)

        yield store, provider, clock, persistence, telegram, checks, executor


def current(store, version_id="a"):
    return store.load_model(state_names.proposal(mail_id(3), version_id), Proposal)


def record(store, version=1):
    return store.load_model(state_names.write_verification(operation_id(mail_id(3), "a", version, "create")),
                            WriteVerification)


def test_a_write_is_created_only_after_a_fresh_read_and_its_receipt_is_durable_before(setup):
    store, provider, _clock, persistence, telegram, _checks, executor = setup
    writer = VerifyingWriter(provider)
    seen = []
    writer.on_read = lambda: seen.append((current(store).status, record(store).receipt.external_id))
    result = executor(writer).execute(confirmed())
    assert seen == [(ProposalStatus.VERIFYING, "t1")]  # receipt and VERIFYING before the first read
    assert result.status == ProposalStatus.CREATED and current(store).status == ProposalStatus.CREATED
    assert persistence.saved[-3:] == [ProposalStatus.WRITING, ProposalStatus.VERIFYING, ProposalStatus.CREATED]
    assert provider.writes == [KEY] and provider.reads == ["t1"]
    checked = record(store)
    assert (checked.state, checked.attempts, checked.receipt.result, checked.notified) == (
        VerificationState.VERIFIED, 1, "created", VerificationState.VERIFIED)
    assert checked.target.account == "konto-1" and checked.expected["due"] == "2026-11-11"
    assert telegram.sent == ["✅ Angelegt und geprüft als Aufgabe: „Unterlagen senden“\n"
                             "https://aufgaben.example.invalid/t1"]


def test_a_different_due_date_is_reported_once_and_never_written_again(setup):
    store, provider, _clock, _persistence, telegram, _checks, executor = setup
    run = executor(VerifyingWriter(provider, script=[{"due": "2026-11-12"}]))
    assert run.execute(confirmed()).status == ProposalStatus.VERIFYING
    run.resume()
    run.resume()
    checked = record(store)
    assert checked.state == VerificationState.MISMATCH and checked.differences["due"].actual == "2026-11-12"
    assert provider.writes == [KEY] and provider.reads == ["t1"]
    assert current(store).status == ProposalStatus.VERIFYING
    assert telegram.sent == ["⚠️ Eintrag vorhanden, Angaben weichen ab: „Unterlagen senden“ – Fälligkeit: "
                             "erwartet 11.11.2026, gefunden 12.11.2026. Mailhelp ändert den Eintrag nicht "
                             "automatisch und legt keinen neuen an."]


def test_an_entry_that_appears_later_is_found_by_reads_only(setup):
    store, provider, clock, _persistence, telegram, _checks, executor = setup
    run = executor(VerifyingWriter(provider, script=[None, None, "entry"]))
    assert run.execute(confirmed()).status == ProposalStatus.VERIFYING
    pending = record(store)
    assert (pending.state, pending.last_error, pending.next_check_at) == (
        VerificationState.PENDING, "not_visible", NOW + timedelta(seconds=1))
    run.resume()  # not due yet: no read
    assert provider.reads == ["t1"] and telegram.sent == []
    clock.advance(1)
    run.resume()
    assert record(store).next_check_at == NOW + timedelta(seconds=6)
    clock.advance(5)
    run.resume()
    assert current(store).status == ProposalStatus.CREATED and current(store).external_id == "t1"
    assert provider.writes == [KEY] and provider.reads == ["t1", "t1", "t1"] and len(telegram.sent) == 1


def test_an_entry_that_never_appears_stays_unverified_after_the_budget(setup):
    store, provider, clock, _persistence, telegram, _checks, executor = setup
    run = executor(VerifyingWriter(provider, script=[None] * 5))
    run.execute(confirmed())
    for delay in (1, 5, 15, 60):
        clock.advance(delay)
        run.resume()
    run.resume()
    checked = record(store)
    assert (checked.state, checked.attempts, checked.last_error) == (VerificationState.NOT_FOUND, 5, "not_visible")
    assert provider.writes == [KEY] and len(provider.reads) == 5
    assert current(store).status == ProposalStatus.VERIFYING
    assert telegram.sent == ["⚠️ Eintragung noch nicht bestätigt: „Unterlagen senden“ wurde gespeichert, aber der "
                             "Eintrag ist beim Anbieter nicht auffindbar. Mailhelp legt den Eintrag nicht erneut an."]


def test_the_elapsed_time_limit_ends_the_checks_after_a_long_pause(setup):
    store, provider, clock, _persistence, _telegram, _checks, executor = setup
    run = executor(VerifyingWriter(provider, script=[None, None]))
    run.execute(confirmed())
    clock.advance(400)  # e.g. the service was stopped for a while
    run.resume()
    assert record(store).state == VerificationState.NOT_FOUND and record(store).attempts == 2


@pytest.mark.parametrize(("error", "code", "transient"), [
    (PermanentError("401"), "access_denied", False),
    (ValueError("kaputt"), "invalid_response", False),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.invalid"),
                           response=httpx.Response(400)), "provider_refused", False),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.invalid"),
                           response=httpx.Response(429)), "rate_limited", True),
    (httpx.HTTPStatusError("x", request=httpx.Request("GET", "https://a.invalid"),
                           response=httpx.Response(503)), "provider_unavailable", True),
    (httpx.ConnectTimeout("langsam"), "provider_unavailable", True),
    (RetryableError("später"), "provider_unavailable", True),
])
def test_read_errors_are_classified_and_never_taken_for_a_deletion(setup, error, code, transient):
    store, provider, _clock, _persistence, telegram, _checks, executor = setup
    executor(VerifyingWriter(provider, script=[error])).execute(confirmed())
    checked = record(store)
    assert checked.last_error == code and provider.writes == [KEY]
    assert checked.state == (VerificationState.PENDING if transient else VerificationState.UNAVAILABLE)
    assert (telegram.sent == []) is transient
    if not transient:
        assert "Mailhelp legt den Eintrag nicht erneut an" in telegram.sent[0]


def test_an_unexpected_read_error_is_not_hidden(setup):
    store, provider, _clock, _persistence, _telegram, checks, _executor = setup
    writer = VerifyingWriter(provider, script=[RuntimeError("Programmfehler")])
    changed, _ = execute_confirmed(confirmed(), writer, lambda item: None, verification=checks)
    with pytest.raises(RuntimeError, match="Programmfehler"):
        checks.check(changed, writer, lambda item: None)


def test_an_unclear_write_is_found_by_its_key_and_compared_with_the_intent(setup):
    store, provider, _clock, _persistence, telegram, _checks, executor = setup
    run = executor(VerifyingWriter(provider, unclear_write=True))
    assert run.execute(confirmed()).status == ProposalStatus.UNCERTAIN
    intent = record(store)
    assert intent.is_intent and intent.expected["title"] == "Unterlagen senden"
    run.writers["todoist"] = VerifyingWriter(provider)
    run.resume()
    checked = record(store)
    assert checked.receipt.result == "found_by_key" and checked.state == VerificationState.VERIFIED
    assert current(store).status == ProposalStatus.CREATED and provider.writes == [KEY]
    assert telegram.sent[-1].startswith("✅ Angelegt und geprüft")


def test_a_crash_after_the_receipt_reuses_it_and_never_writes_twice(setup):
    store, provider, _clock, persistence, _telegram, checks, executor = setup
    writer = VerifyingWriter(provider)
    original = persistence.persist

    def crash(item):
        if item.status == ProposalStatus.VERIFYING:
            raise OSError("Stromausfall")
        original(item)

    persistence.persist = crash
    with pytest.raises(OSError):
        execute_confirmed(confirmed(), writer, crash, verification=checks)
    persistence.persist = original
    assert record(store).receipt.external_id == "t1"
    writing = confirmed(status="writing")
    persistence.persist(writing)
    executor(writer).execute(writing)
    assert provider.writes == [KEY] and current(store).status == ProposalStatus.CREATED


def test_a_crash_after_a_passed_read_uses_the_result(setup):
    store, provider, _clock, persistence, telegram, checks, executor = setup
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persistence.persist, verification=checks)
    checks.check(changed, writer, lambda item: None)  # passed, but the CREATED write was lost
    assert record(store).state == VerificationState.VERIFIED and current(store).status == ProposalStatus.VERIFYING
    executor(writer).resume()
    assert current(store).status == ProposalStatus.CREATED and provider.reads == ["t1"]
    assert len(telegram.sent) == 1


def test_a_late_result_never_marks_a_newer_version(setup):
    store, provider, _clock, persistence, telegram, checks, executor = setup
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persistence.persist, verification=checks)
    persistence.persist(confirmed(version=2, status="pending_confirmation"))
    result, checked = checks.check(changed, writer, persistence.persist)
    assert checked.state == VerificationState.VERIFIED and result.version == 2
    assert current(store).status == ProposalStatus.PENDING_CONFIRMATION
    store.delete(state_names.proposal(mail_id(3), "a"))
    assert checks.check(changed, writer, persistence.persist)[0] == changed


def test_a_late_success_for_an_old_version_sends_no_success_message(setup):
    store, provider, _clock, persistence, telegram, checks, executor = setup
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persistence.persist, verification=checks)
    persistence.persist(confirmed(version=2, status="pending_confirmation"))
    result = executor(writer).execute(changed)
    assert result.version == 2 and current(store).status == ProposalStatus.PENDING_CONFIRMATION
    assert telegram.sent == [] and record(store).notified == VerificationState.VERIFIED


@pytest.mark.parametrize(("change", "code"), [({"target": "Projekt-2"}, "target_changed"),
                                              ({"account": "konto-2"}, "account_changed")])
def test_a_changed_target_or_account_stops_the_check(setup, change, code):
    store, provider, _clock, persistence, telegram, checks, _executor = setup
    changed, _ = execute_confirmed(confirmed(), VerifyingWriter(provider), persistence.persist,
                                   verification=checks)
    checks.check(changed, VerifyingWriter(provider, **change), persistence.persist)
    assert (record(store).state, record(store).last_error) == (VerificationState.UNAVAILABLE, code)
    assert provider.reads == []


def test_a_verifying_proposal_without_record_is_checked_by_its_external_id(setup):
    store, provider, _clock, persistence, _telegram, checks, executor = setup
    provider.entries["t9"] = VerifyingWriter(provider).expected_facts(confirmed(), KEY)
    item = confirmed(status="verifying", external_id="t9")
    executor(VerifyingWriter(provider), item).execute(item)
    assert record(store).receipt.result == "existing" and current(store).status == ProposalStatus.CREATED
    other = proposal(3, "b", status="verifying", external_id="t9")
    assert checks.check(other, VerifyingWriter(provider, plain=False), persistence.persist) == (other, None)


def test_writers_without_reader_or_operations_keep_their_result(setup):
    store, provider, _clock, persistence, telegram, checks, executor = setup
    created, _ = execute_confirmed(confirmed(), VerifyingWriter(provider, plain=False), persistence.persist,
                                   verification=checks)
    assert created.status == ProposalStatus.CREATED and record(store) is None
    provider.by_key[f"mailhelp:{mail_id(3)}:b:v1"] = {"id": "t5"}
    found, _ = execute_confirmed(proposal(3, "b", status="uncertain", confirmed_web_actor=None),
                                 VerifyingWriter(provider, plain=False), persistence.persist, verification=checks)
    assert found.status == ProposalStatus.CREATED
    # A verifying proposal whose writer cannot read stays as it is and is not written again.
    item = confirmed(status="verifying", external_id="t1")

    class Plain:
        def reconcile(self, key):
            raise AssertionError("kein Abgleich")

    assert executor(Plain(), item).execute(item) == item and telegram.sent == []
    run = executor(VerifyingWriter(provider), item)
    run.verification = None
    assert run.execute(item) == item


def test_an_entry_found_without_a_saved_intent_is_not_compared_with_guessed_facts(setup):
    store, provider, _clock, persistence, _telegram, checks, _executor = setup
    provider.by_key[KEY] = {"id": "t7"}  # e.g. an existing entry completed by another operation
    found, result = execute_confirmed(confirmed(status="uncertain"), VerifyingWriter(provider),
                                      persistence.persist, verification=checks)
    assert found.status == ProposalStatus.CREATED and "verifying" not in result and record(store) is None


def test_a_report_is_not_marked_when_the_state_changed_meanwhile(setup):
    store, provider, _clock, persistence, _telegram, checks, _executor = setup
    writer = VerifyingWriter(provider)
    changed, _ = execute_confirmed(confirmed(), writer, persistence.persist, verification=checks)
    stale = record(store).model_copy(update={"state": VerificationState.MISMATCH})
    checks.mark_notified(stale)
    assert record(store).notified is None
    store.delete(state_names.write_verification(stale.id))
    checks.mark_notified(stale)
    assert record(store) is None


def test_an_intent_never_replaces_a_known_receipt(setup):
    store, provider, _clock, persistence, _telegram, checks, _executor = setup
    writer = VerifyingWriter(provider)
    execute_confirmed(confirmed(), writer, persistence.persist, verification=checks)
    checks.intent(confirmed(), writer, {"title": "anders"})
    assert record(store).receipt.external_id == "t1" and record(store).expected["title"] == "Unterlagen senden"


def test_a_late_check_of_a_verified_newer_record_is_not_repeated(setup):
    store, provider, _clock, persistence, telegram, checks, executor = setup
    run = executor(VerifyingWriter(provider, script=[{"title": "anders"}]))
    run.execute(confirmed())
    sent = list(telegram.sent)
    run.resume()
    assert telegram.sent == sent and provider.reads == ["t1"]


@pytest.mark.parametrize(("values", "message"), [
    ({"max_attempts": 3}, "genau max_attempts - 1"),
    ({"max_attempts": 2, "retry_delays_seconds": [0]}, "zwischen 1 und 3600"),
    ({"max_attempts": 2, "retry_delays_seconds": [400], "max_elapsed_seconds": 300}, "überschreiten"),
])
def test_the_retry_settings_are_validated(values, message):
    with pytest.raises(ValueError, match=message):
        WriteVerificationSettings(**values)
    assert WriteVerificationSettings().retry_delays_seconds == [1, 5, 15, 60]
