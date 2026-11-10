"""Real application entry points in a spawned process with hard-kill checkpoints."""
from __future__ import annotations

import traceback
from pathlib import Path

from mailhelp.models import Proposal
from mailhelp.review.inbox import CommandInbox
from mailhelp.storage import JsonStore
from mailhelp.telegram import TelegramDialogController
from mailhelp.web.auth import WebAuth
from tests.fakes.safety_harness import PersistentWriter
from tests.fakes.shared_telegram_dialog import Logger, Telegram


def _writer(provider,checkpoint,mode):
    if mode.startswith('provider:'):
        from tests.fakes.provider_matrix import ProviderMemory
        memory = ProviderMemory(Path(provider), mode.removeprefix('provider:'))
        memory.after_write = lambda: checkpoint('A2')
        return memory.writer()
    return PersistentWriter(Path(provider), checkpoint, mode)


def _verification_checkpoints(checkpoint, name, value, authoritative):
    """5.2: after the receipt and VERIFYING, before the first read; after a passed read."""
    if authoritative and value["status"] == "verifying":
        checkpoint("V1")
    if name.startswith("write-verification-") and value.get("state") == "verified":
        checkpoint("V2")


def run_application(directory, provider, point, connection, mode, coverage_file):
    # Explicit collection also covers processes terminated with kill()/TerminateProcess.
    # Flush at every checkpoint: hard termination cannot run atexit handlers.
    cov = None
    if coverage_file:
        from coverage import Coverage
        active = Coverage.current()
        if active is not None and Path(active.config.data_file).resolve() == Path(coverage_file).resolve():
            cov = active
        else:
            cov = Coverage(data_file=coverage_file, data_suffix=True, branch=True, source=["mailhelp"])
            cov.start()

    def checkpoint(name):
        if name == point:
            if cov is not None:
                cov.save()
            connection.send(("checkpoint", name))
            assert connection.poll(30), "Parent did not terminate or release child"
            connection.recv()

    try:
        with JsonStore(Path(directory)) as store:
            original_save = store.save
            def save(name, value):
                authoritative = name.startswith("proposal-") and "-v" not in name
                if authoritative and value["status"] == "created":
                    checkpoint("A3")
                original_save(name, value)
                if authoritative and value["status"] == "confirmed":
                    checkpoint("A1")
                if authoritative and value["status"] == "created":
                    checkpoint("A4")
                _verification_checkpoints(checkpoint, name, value, authoritative)
                if name.startswith("reconciliation-merge-") and value["status"] == "prepared":
                    checkpoint("A5")
                if authoritative and value["id"] == "target" and value["version"] == 2:
                    checkpoint("A6")
                if authoritative and value["id"] == "source" and value["version"] == 2:
                    checkpoint("A7")
            store.save = save
            writer = _writer(provider,checkpoint,mode)
            commands = CommandInbox(store)
            dialog = TelegramDialogController(store, Telegram(), 1, 2, Logger(),
                {"todoist": writer, "google_calendar": writer}, commands=commands)
            auth = WebAuth(store, "s" * 40, 30, lambda text: None)
            dialog.review.web_authorizer = lambda actor: auth.active(actor.removeprefix("web:"))
            dialog.poll_once()
            proposals = [store.load_model(name, Proposal).model_dump(mode="json")
                         for name in store.names("proposal-") if "-v" not in name]
            connection.send(("done", proposals))
    except BaseException:
        connection.send(("error", traceback.format_exc()))
    finally:
        if cov is not None:
            cov.stop()
            cov.save()
        connection.close()
