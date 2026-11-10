"""5.1 R6: the background service runs jobs, opens one IMAP session per bound mailbox and survives errors."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from mailhelp.config import ReanalysisSettings
from mailhelp.domain.mail import MailState
from mailhelp.domain.reanalysis import ReanalysisJob, ReanalysisStatus
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.runtime import reanalysis_worker
from mailhelp.runtime.reanalysis_worker import ReanalysisWorker, mailbox_readers
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.reanalysis_fakes import DONE_STEPS, ReanalysisAnalyzer, ReanalysisEngine
from tests.scenarios.web_scenario import mail_id

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
MAIL = mail_id(9)


def raw():
    message = EmailMessage()
    message["From"], message["Subject"] = "schule@example.test", "Formular"
    message.set_content("Bitte das Formular bis Freitag abgeben.")
    return message.as_bytes()


class Reader:
    def __init__(self):
        self.calls, self.closed = [], False

    def fetch_uid(self, folder, uid, expected_uidvalidity):
        self.calls.append((folder, uid, expected_uidvalidity))
        return FetchedMail(folder, expected_uidvalidity, uid, raw(), "0" * 24, NOW - timedelta(days=1))


def worker_for(store, opened=None, authorized=lambda actor: True):
    readers = []

    @contextmanager
    def open_reader(account_id):
        reader = Reader()
        readers.append(reader)
        try:
            yield reader
        finally:
            reader.closed = True
    worker = ReanalysisWorker(store, ReanalysisSettings(), ReanalysisEngine(store, ReanalysisAnalyzer("Formular"), 9),
                              RecordingLogger(), opened or open_reader, [].append, authorized)
    return worker, readers


def seed(store, **fields):
    state = MailState(id=MAIL, config_fingerprint="f" * 64, created_at=NOW - timedelta(days=1), steps=DONE_STEPS,
                      imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 4, "uid": 12}, **fields)
    store.save(f"mail-{MAIL}", state.model_dump(mode="json"))
    return state


def test_removed_content_is_read_in_one_session_that_is_closed_afterwards(tmp_path):
    store = JsonStore(tmp_path)
    state = seed(store, mail=None)
    worker, readers = worker_for(store)
    job, _ = worker.jobs.start(state, expected_round=1, hint=None, key="k")
    assert worker.run_once() is True
    done = worker.jobs.get(job.id)
    assert done.status == ReanalysisStatus.COMPLETED and [item.title for item in done.proposals] == ["Formular"]
    assert len(readers) == 1 and readers[0].calls == [("INBOX", 12, 4)] and readers[0].closed


def test_a_mailbox_without_session_ends_the_job_with_a_reason(tmp_path):
    store = JsonStore(tmp_path)
    state = seed(store, mail=None)
    worker, _ = worker_for(store, opened=lambda account_id: None)
    job, _ = worker.jobs.start(state, expected_round=1, hint=None, key="k")
    worker.run_once()
    assert worker.jobs.get(job.id).error == "mailbox_unavailable"


def test_the_thread_recovers_runs_and_stops_and_a_damaged_job_does_not_stop_it(tmp_path, monkeypatch):
    monkeypatch.setattr(reanalysis_worker, "IDLE_SECONDS", 0.01)
    store = JsonStore(tmp_path)
    state = seed(store, mail={"text": "Bitte das Formular abgeben.", "headers": {}})
    worker, _ = worker_for(store)
    job, _ = worker.jobs.start(state, expected_round=1, hint=None, key="k")
    worker.jobs.save(job.model_copy(update={"status": ReanalysisStatus.RUNNING}))
    calls = []
    original = worker.run_once

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("beschädigte Auftragsdatei")
        return original()
    worker.run_once = flaky
    worker.start()
    for _ in range(500):
        if worker.jobs.get(job.id).status == ReanalysisStatus.COMPLETED:
            break
        worker.woken.wait(0.01)
    worker.wake()
    worker.stop()
    assert worker.jobs.get(job.id).status == ReanalysisStatus.COMPLETED and worker.jobs.get(job.id).attempts == 1
    assert not worker.thread.is_alive()
    errors = [fields for (level, _, event), fields in worker.jobs.logger.events if event == "reanalysis_worker_failed"]
    assert errors == [{"error": "RuntimeError"}]
    ReanalysisWorker(store, ReanalysisSettings(), None, RecordingLogger(), lambda a: None, [].append,
                     lambda a: True).stop()


def test_mailbox_readers_open_only_the_bound_enabled_mailbox(monkeypatch):
    mailboxes = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    settings = SimpleNamespace(imap=SimpleNamespace(enabled_mailboxes=lambda: mailboxes))
    secrets = SimpleNamespace(imap_credentials=lambda number: f"zugang-{number}")
    monkeypatch.setattr(reanalysis_worker, "mailbox_account_id", lambda mailbox, credentials: f"konto-{mailbox.id}")
    opened = []
    open_reader = mailbox_readers(settings, secrets, lambda s, k, mailbox: opened.append(mailbox.id) or "sitzung")
    assert open_reader("konto-2") == "sitzung" and opened == [2]
    assert open_reader("fremd") is None


def test_an_adoption_request_names_round_versions_and_session_together():
    base = dict(id="a" * 32, mail_id=MAIL, source_round=1, config_fingerprint="f" * 64,
                imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1}, key_hash="b" * 64,
                max_attempts=2, max_llm_calls=5, created_at=NOW, updated_at=NOW)
    with pytest.raises(ValueError, match="Runde, Versionen und Sitzung"):
        ReanalysisJob(**base, adoption_round=1)
    with pytest.raises(ValueError, match="kann übernommen werden"):
        ReanalysisJob(**base, adoption_round=1, adoption_versions={}, adoption_actor="web:x")
