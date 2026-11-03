from datetime import UTC, datetime
from pathlib import Path

import pytest
from log_fakes import RecordingLogger as Log
from pydantic import ValidationError
from shared_retention import state as state

from mailhelp.config import RetentionSettings
from mailhelp.models import (
    DuplicateIndex,
    DuplicateIndexEntry,
    MailRunCounters,
    MailRunState,
    MailState,
    ProposalStatus,
    RelevanceDialog,
)
from mailhelp.runtime.retention import RetentionService
from mailhelp.storage import JsonStore

NOW = datetime(2026, 9, 16, tzinfo=UTC)




def test_cleanup_expiry_repetition_restart_and_namespace_isolation(tmp_path):
    production = tmp_path / "production"
    test = tmp_path / "test"
    expired = state("a" * 24)
    recent = state("b" * 24, age=3)
    with JsonStore(production) as store:
        store.save("mail-expired", expired.model_dump(mode="json"))
        store.save("mail-recent", recent.model_dump(mode="json"))
    with JsonStore(test) as store:
        store.save("mail-expired", expired.model_dump(mode="json"))

    log = Log()
    with JsonStore(production) as restarted:
        service = RetentionService(restarted, RetentionSettings(full_mail_days=30, debug_llm_days="disabled"), log, lambda: NOW)
        first = service.run()
        assert (first.scanned, first.mail_scrubbed, first.debug_scrubbed) == (2, 1, 2)
        kept = restarted.load_model("mail-expired", MailState)
        assert kept.mail is None and kept.summary is None and kept.relevance is None and kept.llm_call_ids == []
        assert kept.imap.uid == 9 and kept.proposals[0].version == 2
        assert kept.proposals[0].external_id == "external-1" and kept.write_attempts[0].idempotency_key == "stable-key"
        assert service.run().mail_scrubbed == 0
    with JsonStore(test) as isolated:
        assert isolated.load_model("mail-expired", MailState).mail == {"text": "very private"}
    assert all("private" not in str(event) and "stable-key" not in str(event) for event in log.events)


def test_cleanup_ignores_durable_mail_run_state(tmp_path):
    """The overlapping mail-run prefix must never cross the MailState boundary."""
    run = MailRunState(
        run_id="00000000-0000-0000-0000-000000000001", max_mails=100,
        created_at=NOW, entries=[], counters=MailRunCounters(),
    )
    with JsonStore(tmp_path) as store:
        store.save("mail-run-" + "a" * 24, run.model_dump(mode="json"))

        result = RetentionService(store, RetentionSettings(), Log(), lambda: NOW).run()

        assert result.scanned == 0
        assert store.load_model("mail-run-" + "a" * 24, MailRunState) == run
        assert not list(tmp_path.glob("*.invalid"))


@pytest.mark.parametrize("status,letter", [
    (ProposalStatus.NEEDS_CLARIFICATION, "1"), (ProposalStatus.PENDING_CONFIRMATION, "2"),
    (ProposalStatus.CONFIRMED, "3"), (ProposalStatus.WRITING, "4"), (ProposalStatus.UNCERTAIN, "5"),
])
def test_open_writes_and_confirmations_are_protected(tmp_path, status, letter):
    with JsonStore(tmp_path / status.value) as store:
        item = state(letter * 24, status=status)
        store.save("mail-item", item.model_dump(mode="json"))
        result = RetentionService(store, RetentionSettings(full_mail_days="disabled", debug_llm_days="disabled"), Log(), lambda: NOW).run()
        assert result.protected == 1 and store.load_model("mail-item", MailState).mail is not None


def test_pending_and_open_relevance_are_protected_and_unlimited_is_explicit(tmp_path):
    pending = state("c" * 24)
    pending.steps.completion = "pending"
    dialog = state("d" * 24)
    dialog.awaiting_relevance = True
    dialog.relevance_dialog = RelevanceDialog(mail_id=dialog.id)
    with JsonStore(tmp_path) as store:
        store.save("mail-pending", pending.model_dump(mode="json"))
        store.save("mail-dialog", dialog.model_dump(mode="json"))
        assert RetentionService(store, RetentionSettings(), Log(), lambda: NOW).run().protected == 2
        terminal = state("e" * 24)
        store.save("mail-terminal", terminal.model_dump(mode="json"))
        duplicate_index = DuplicateIndex(entries=[DuplicateIndexEntry(
            mail_id=terminal.id, imap=terminal.imap, message_ids=["<x@example.test>"],
            content_fingerprint="f" * 64)])
        store.save("duplicate-index", duplicate_index.model_dump(mode="json"))
        result = RetentionService(store, RetentionSettings(full_mail_days="unlimited", debug_llm_days="unlimited"), Log(), lambda: NOW).run()
        assert result.mail_scrubbed == result.debug_scrubbed == 0
        mail_only = RetentionService(store, RetentionSettings(full_mail_days="disabled", debug_llm_days="unlimited"), Log(), lambda: NOW).run()
        assert mail_only.mail_scrubbed == 1 and mail_only.debug_scrubbed == 0
        assert store.load_model("duplicate-index", DuplicateIndex) == duplicate_index


@pytest.mark.parametrize("status", [
    ProposalStatus.REJECTED,
    ProposalStatus.CREATED,
    ProposalStatus.SIMULATED,
    ProposalStatus.FAILED,
])
def test_completed_proposal_is_terminal_but_retained_as_action_result(tmp_path, status):
    completed = state("f" * 24, status=status)
    with JsonStore(tmp_path / status.value) as store:
        store.save("mail-completed", completed.model_dump(mode="json"))
        result = RetentionService(
            store, RetentionSettings(full_mail_days="disabled", debug_llm_days="disabled"),
            Log(), lambda: NOW,
        ).run()
        kept = store.load_model("mail-completed", MailState)
        assert result.protected == 0 and result.mail_scrubbed == 1
        assert kept.proposals[0].status == status
        if status == ProposalStatus.SIMULATED:
            assert kept.proposals[0].simulation_notified
            assert kept.proposals[0].external_id is None
        else:
            assert kept.proposals[0].external_id == "external-1"
            assert kept.proposals[0].external_link == "https://example.invalid/1"


def test_retention_boundaries_missing_state_and_clock_validation():
    for bad in (0, 3651, "forever"):
        with pytest.raises(ValidationError): RetentionSettings(full_mail_days=bad)
    assert RetentionSettings(full_mail_days=1).full_mail_days == 1

    class EmptyStore:
        directory = Path("nicht-vorhanden")
        def names(self, prefix): return ["mail-gone"]
        def load_model(self, name, model): return None
    service = RetentionService(EmptyStore(), RetentionSettings(), Log(), lambda: NOW)
    assert service.run().scanned == 1
    service.clock = lambda: datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="Zeitzone"): service.run()


def test_a_repeated_cleanup_rewrites_nothing(tmp_path):
    """Regression: every cleanup rewrote all removed analyses (580 fsyncs, several seconds per cycle)."""
    class RecordingStore(JsonStore):
        saved: list[str] = []

        def save(self, name, value):
            self.saved.append(name)
            super().save(name, value)

    expired = state("a" * 24)
    with RecordingStore(tmp_path) as store:
        store.save(f"mail-{expired.id}", expired.model_dump(mode="json"))
        store.save(f"analysis-{expired.id}", {"schema_version": 1, "mail_id": expired.id})
        store.save(f"history-{expired.id}", {"schema_version": 1, "events": []})
        settings = RetentionSettings(full_mail_days=30, debug_llm_days="disabled", history_days=1)
        service = RetentionService(store, settings, Log(), lambda: NOW)
        store.saved.clear()
        service.run()
        assert {f"analysis-{expired.id}", f"history-{expired.id}"} <= set(store.saved)
        store.saved.clear()
        revision = store.revision
        service.run()
        assert store.saved == [] and store.revision == revision


@pytest.mark.parametrize(("interval", "runs"), [(60, [0.0, 3600.0, 7300.0]), (0, [0.0, 10.0, 3600.0, 7300.0])])
def test_maintenance_runs_at_the_configured_interval(monkeypatch, tmp_path, interval, runs):
    from types import SimpleNamespace

    from mailhelp.logging import NullLogger
    from mailhelp.runtime.application import Application

    clock = iter([0.0, 10.0, 3600.0, 7300.0])
    done = []
    monkeypatch.setattr("mailhelp.runtime.application.time.monotonic", lambda: next(clock))

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def run(self):
            done.append(now[0])

    monkeypatch.setattr("mailhelp.runtime.application.RetentionService", Service)
    settings = SimpleNamespace(retention=RetentionSettings(cleanup_interval_minutes=interval))
    app = SimpleNamespace(settings=settings, store=None, logger=NullLogger(), _maintained_at=None, orchestrator=None)
    now = [0.0]
    for moment in (0.0, 10.0, 3600.0, 7300.0):
        now[0] = moment
        Application._maintain(app)
    assert done == runs
    with pytest.raises(ValidationError):
        RetentionSettings(cleanup_interval_minutes=1441)
    assert RetentionSettings().cleanup_interval_minutes == 60
