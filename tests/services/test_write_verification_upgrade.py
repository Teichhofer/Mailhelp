"""5.2 V10: retention of check records, entries from before 5.2, test mode and the way back."""
import sys
from datetime import UTC, date, datetime, timedelta

import yaml

from mailhelp import cli, state_names
from mailhelp.config import RetentionSettings
from mailhelp.domain.verification import VerificationState, operation_id
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.models import MailState, Proposal, ProposalStatus
from mailhelp.paths import runtime_path
from mailhelp.persistence.proposals import ProposalRepository
from mailhelp.processing.write_verification import WriteVerifications, prepare_rollback
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.inbox import CommandInbox
from mailhelp.review.views import ReviewViews
from mailhelp.runtime.retention import RetentionService
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.shared_application import settings as application_settings
from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)


def task(pid="a", **fields):
    values = dict(status="confirmed", confirmed_web_actor=None, title="Unterlagen senden", due=date(2026, 11, 11))
    values.update(fields)
    return proposal(3, pid, **values)


def written(store, item, script=(), now=NOW):
    """Write *item* through the verifying flow and run its first check."""
    save_mail(store, 3, "Schule <schule@example.test>", "Unterlagen", [item])
    checks, writer = WriteVerifications(store, now=lambda: now), VerifyingWriter(SimulatedProvider(), script=list(script))
    repository = ProposalRepository(store)
    changed, _ = execute_confirmed(item, writer, repository.save_revision, verification=checks)
    return checks.check(changed, writer, repository.save_revision)


def test_check_records_follow_the_mail_content_period_but_a_running_check_keeps_its_record(tmp_path):
    with JsonStore(tmp_path) as store:
        written(store, task("a"))                    # verified, CREATED
        written(store, task("b"), script=[None])     # still VERIFYING
        orphan = WriteVerifications(store, now=lambda: NOW)
        orphan.legacy(task("c", status="created", external_id="x"))  # its proposal no longer exists
        store.save("write-verification-" + "f" * 32, {"schema_version": 1})  # damaged: left to quarantine
        later = NOW + timedelta(days=40)
        expired = RetentionService._expired
        assert WriteVerifications(store).remove_expired(60, later, expired) == 0  # nothing old enough yet
        result = RetentionService(store, RetentionSettings(full_mail_days=30), RecordingLogger(),
                                  lambda: later).run()
        assert result.verification_removed == 2
        names = store.names(state_names.WRITE_VERIFICATION_PREFIX)
        assert names == [state_names.write_verification(operation_id(mail_id(3), "b", 1, "create"))]


def test_an_entry_found_from_before_5_2_stays_visibly_unverified(tmp_path):
    with JsonStore(tmp_path) as store:
        item = task(status="uncertain")
        save_mail(store, 3, "Schule <schule@example.test>", "Unterlagen", [item])
        provider = SimulatedProvider()
        provider.by_key[f"mailhelp:{mail_id(3)}:a:v1"] = {"id": "alt-1"}
        checks = WriteVerifications(store, now=lambda: NOW)
        found, _ = execute_confirmed(item, VerifyingWriter(provider), ProposalRepository(store).save_revision,
                                     verification=checks)
        assert found.status == ProposalStatus.CREATED and provider.reads == []  # no mass reads on upgrade
        assert checks.load(found).state == VerificationState.LEGACY_UNVERIFIED
        view = ReviewViews(store, "Europe/Berlin").proposal(mail_id(3), "a")
        assert view.state == "Angelegt (vor 5.2, nicht nachgeprüft)"


def test_test_mode_neither_writes_nor_reads_nor_invents_a_check(tmp_path):
    with JsonStore(tmp_path) as store:
        provider = SimulatedProvider()
        checks = WriteVerifications(store, now=lambda: NOW)
        simulated, result = execute_confirmed(task(), VerifyingWriter(provider), lambda value: None, True,
                                              verification=checks)
        assert simulated.status == ProposalStatus.SIMULATED and result == {"simulation": True}
        assert (provider.writes, provider.reads, checks.load(simulated)) == ([], [], None)


def test_the_way_back_turns_verifying_entries_into_created_ones(tmp_path):
    with JsonStore(tmp_path) as store:
        written(store, task("b"), script=[None])
        inbox = CommandInbox(store)
        inbox.submit(ReviewCommand(kind=CommandKind.VERIFY_ENTRY, source=CommandSource.TELEGRAM, actor="telegram:1:2",
                                   mail_id=mail_id(3), proposal_id="b", version=1, idempotency_key="k" * 32))
        inbox.drain()
        assert prepare_rollback(store) == (0, 1)
        store.delete("command-inbox")
        assert prepare_rollback(store) == (1, 0)
        current = store.load_model(state_names.proposal(mail_id(3), "b"), Proposal)
        assert current.status == ProposalStatus.CREATED and current.external_id == "t1"
        mail = store.load_model(state_names.mail(mail_id(3)), MailState)
        assert {item.status for item in mail.proposals} == {ProposalStatus.CREATED}
        assert prepare_rollback(store) == (0, 0)


def test_the_command_line_prepares_the_way_back(tmp_path, monkeypatch, capsys):
    config = application_settings(tmp_path)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    namespace = "test" if config.test_mode else "production"
    with JsonStore(runtime_path(config.data_directory, tmp_path) / namespace) as store:
        written(store, task("b"), script=[None])
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--prepare-rollback", "--config-directory", str(tmp_path)])
    assert cli.main() == 0 and "1 Eintrag/Einträge" in capsys.readouterr().out
    with JsonStore(runtime_path(config.data_directory, tmp_path) / namespace) as store:
        CommandInbox(store).submit(ReviewCommand(
            kind=CommandKind.VERIFY_ENTRY, source=CommandSource.TELEGRAM, actor="telegram:1:2",
            mail_id=mail_id(3), proposal_id="b", version=1, idempotency_key="k" * 32))
        CommandInbox(store).drain()
    assert cli.main() == 1 and "warten noch" in capsys.readouterr().err
