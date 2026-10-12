"""Upgrade from 1.1 and read-only Docker mounts."""
from __future__ import annotations

import os
import stat
from datetime import UTC, datetime

import pytest
import yaml
from shared_web_actions import web  # noqa: F401  (fixture)
from shared_web_v12 import configure
from web_scenario import mail_id

from mailhelp.configuration import AdminCommand, AdminKind, file_hash
from mailhelp.review.inbox import COMMAND_INBOX, CommandInbox, CommandStatus
from mailhelp.review.results import ResultStatus


def test_a_1_1_command_inbox_with_an_open_command_is_processed_after_the_upgrade(web):
    """A queued 1.1 command (no patch field, no admin commands) loads and runs once."""
    session = web.auth.sessions()[0].id
    web.store.save(COMMAND_INBOX, {"schema_version": 1, "entries": [{
        "id": "a" * 32, "status": "queued", "received_at": datetime(2026, 10, 10, tzinfo=UTC).isoformat(),
        "result": None, "finished_at": None,
        "command": {"kind": "reject", "source": "web", "actor": f"web:{session}", "mail_id": mail_id(1),
                    "proposal_id": "formular", "version": 1, "idempotency_key": "key-from-1-1",
                    "text": None, "decision": None, "replay_offset": None}}]})
    upgraded = CommandInbox(web.store)
    web.dialog.commands = upgraded
    web.run()
    assert upgraded.get("a" * 32).status == CommandStatus.DONE
    assert web.store.load(f"proposal-{mail_id(1)}-formular")["status"] == "rejected"


def test_old_proposals_without_history_are_marked_as_incomplete(web):
    page = web.browser.request("GET", "/verlauf").body.decode()
    assert "Altbestand / Ablauf nicht vollständig erfasst" in page
    assert "unbekannt" in page


def test_a_read_only_config_mount_gives_a_clear_result_and_changes_nothing(web, tmp_path):
    """Docker mounts config.yaml read-only (compose.yaml); saving must fail cleanly."""
    service, *_ = configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    before = path.read_text(encoding="utf-8")
    command = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{web.auth.sessions()[0].id}",
                           idempotency_key="key-readonly-1", expected_hash=file_hash(path),
                           patch={"poll_interval_seconds": 10}, acknowledged=True)
    # Windows refuses to replace a read-only file; on Linux the directory decides.
    path.chmod(stat.S_IREAD)
    if os.name != "nt":
        tmp_path.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        result = service.execute(command)
    finally:
        tmp_path.chmod(stat.S_IRWXU)
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert result.status == ResultStatus.INVALID
    assert "nicht schreibbar" in result.message
    assert path.read_text(encoding="utf-8") == before
    assert yaml.safe_load(before)["poll_interval_seconds"] == 5


@pytest.mark.parametrize("mount", ["compose.yaml"])
def test_compose_documents_the_read_only_configuration(mount):
    from pathlib import Path
    assert "./config.yaml:/config/config.yaml:ro" in Path(mount).read_text(encoding="utf-8")
