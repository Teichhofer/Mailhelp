"""Genuine state files of every former release keep working (Planung 2.1, T5).

``states/<release>/<scenario>/`` was written by the release itself: its own
``tests/test_e2e_simulated.py`` ran from a checkout of the release commit
(1.1 ``5c865f0``, 1.2 ``154fdb4``, 1.3 ``7a89071``, 1.4 ``d8f81d5``,
1.5 ``d88d316``, 1.6 ``b36d094``, 2.0 ``a24a010``) and its temporary state
directories were kept.  The scenarios cover a created proposal (``complete``),
an open clarification with a revised version (``incomplete``), web sessions
and the command inbox (``web``) and IMAP checkpoints (``state``).

The current release must read every file without quarantine or loss, and a
restart must neither repeat an external write nor analyse a finished mail again.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from shared_application import Imap, Orch, Telegram, app
from shared_telegram_dialog import Writer, controller

from mailhelp.domain.duplicate import DuplicateIndex
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProposalClarificationState, TelegramDialogState, TelegramOutboxState
from mailhelp.domain.proposal import ActionLedger
from mailhelp.domain.run import ImapCheckpoint, MailRunState, TelegramOffset
from mailhelp.models import Proposal
from mailhelp.storage import JsonStore

STATES = Path(__file__).parent / "states"
CASES = sorted((release.name, scenario.name) for release in STATES.iterdir() for scenario in release.iterdir())
# Most specific prefix first: "mail-run-" before "mail-".
MODELS = (("mail-run-", MailRunState), ("mail-", MailState), ("proposal-", Proposal),
          ("clarification-", ProposalClarificationState), ("telegram-dialog", TelegramDialogState),
          ("telegram-outbox", TelegramOutboxState), ("telegram-offset", TelegramOffset),
          ("duplicate-index", DuplicateIndex), ("action-ledger", ActionLedger), ("imap-", ImapCheckpoint))


def model_for(name: str):
    return next((model for prefix, model in MODELS if name.startswith(prefix)), None)


def test_every_release_and_scenario_is_present():
    assert sorted({release for release, _ in CASES}) == ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "2.0"]
    assert all(len([case for case in CASES if case[0] == release]) == 4 for release, _ in CASES)


@pytest.mark.parametrize(("release", "scenario"), CASES)
def test_former_state_loads_without_loss(tmp_path, release, scenario):
    directory = tmp_path / "state"
    shutil.copytree(STATES / release / scenario, directory)
    original = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")}
    with JsonStore(directory) as store:
        for name, value in original.items():
            model = model_for(name)
            loaded = store.load(name) if model is None else store.load_model(name, model)
            assert loaded is not None, name
            if model is Proposal:
                # Decisions and external references survive every migration.
                assert (loaded.status.value, loaded.version, loaded.external_id, loaded.external_link) == (
                    value["status"], value["version"], value.get("external_id"), value.get("external_link")), name
            if model is MailState:
                assert (loaded.id, loaded.config_fingerprint) == (value["id"], value["config_fingerprint"]), name
        assert sorted(store.names()) == sorted(original)
    # Nothing was quarantined as unreadable.
    assert sorted(path.name for path in directory.iterdir() if path.suffix != ".json") == [".lock"]


@pytest.mark.parametrize(("release", "scenario"), CASES)
def test_restart_on_former_state_repeats_no_external_write_or_analysis(tmp_path, release, scenario):
    directory = tmp_path / "state"
    shutil.copytree(STATES / release / scenario, directory)
    with JsonStore(directory) as store:
        finished = {name for name in store.names("mail-") if not name.startswith("mail-run-")
                    if store.load_model(name, MailState).steps.completion == "completed"}
        writer = Writer(found={"id": "external-reconciled", "url": "https://example.test/item"})
        dialog, _, _ = controller(store, (), {"todoist": writer, "google_calendar": writer})
        dialog.poll_once()
        assert writer.created == 0
        orchestrator = Orch()
        app(tmp_path, Imap([]), Telegram([]), orchestrator, store=store).mailbox.resume_pending()
        assert orchestrator.seen == []
        assert finished == {name for name in store.names("mail-") if not name.startswith("mail-run-")
                            if store.load_model(name, MailState).steps.completion == "completed"}
