from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mailhelp.config import RetentionSettings
from mailhelp.models import MailState, Proposal, ProposalKind, ProposalStatus, RelevanceDialog, Summary
from mailhelp.retention import RetentionService
from mailhelp.storage import JsonStore


class Log:
    def __init__(self): self.events = []
    def event(self, *args, **kwargs): self.events.append((args, kwargs))


NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def state(identifier, age=31, status=ProposalStatus.CREATED):
    proposal = Proposal(id="p" + identifier[0], version=2, kind=ProposalKind.TASK,
                        title="Termin", evidence="Quelle", source_mail_id=identifier,
                        target="inbox", status=status, external_id="external-1",
                        external_link="https://example.invalid/1")
    item = MailState(
        id=identifier, config_fingerprint="0" * 64,
        imap={"account_id": "1" * 24, "folder": "INBOX", "uidvalidity": 7, "uid": 9},
        created_at=NOW - timedelta(days=age + 1), updated_at=NOW - timedelta(days=age),
        mail={"text": "very private"}, relevance={"decision": "relevant", "topic_ids": ["x"], "reason": "private"},
        summary=Summary(sentences=["private one", "private two"]), proposals=[proposal],
        llm_call_ids=["call-secret"], validation_errors=[],
        write_attempts=[{"proposal_id": proposal.id, "proposal_version": 2,
                         "service": "todoist", "idempotency_key": "stable-key"}],
    )
    item.steps.completion = "completed"
    return item


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
    pending = state("c" * 24); pending.steps.completion = "pending"
    dialog = state("d" * 24)
    dialog.awaiting_relevance = True
    dialog.relevance_dialog = RelevanceDialog(mail_id=dialog.id)
    with JsonStore(tmp_path) as store:
        store.save("mail-pending", pending.model_dump(mode="json"))
        store.save("mail-dialog", dialog.model_dump(mode="json"))
        assert RetentionService(store, RetentionSettings(), Log(), lambda: NOW).run().protected == 2
        terminal = state("e" * 24)
        store.save("mail-terminal", terminal.model_dump(mode="json"))
        result = RetentionService(store, RetentionSettings(full_mail_days="unlimited", debug_llm_days="unlimited"), Log(), lambda: NOW).run()
        assert result.mail_scrubbed == result.debug_scrubbed == 0
        mail_only = RetentionService(store, RetentionSettings(full_mail_days="disabled", debug_llm_days="unlimited"), Log(), lambda: NOW).run()
        assert mail_only.mail_scrubbed == 1 and mail_only.debug_scrubbed == 0


def test_retention_boundaries_missing_state_and_clock_validation():
    for bad in (0, 3651, "forever"):
        with pytest.raises(ValidationError): RetentionSettings(full_mail_days=bad)
    assert RetentionSettings(full_mail_days=1).full_mail_days == 1

    class EmptyStore:
        def names(self, prefix): return ["mail-gone"]
        def load_model(self, name, model): return None
    service = RetentionService(EmptyStore(), RetentionSettings(), Log(), lambda: NOW)
    assert service.run().scanned == 1
    service.clock = lambda: datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="Zeitzone"): service.run()
