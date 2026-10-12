"""Shared synthetic fixtures and doubles; no test-module dependencies."""
from datetime import UTC, datetime, timedelta

from log_fakes import RecordingLogger as Log

from mailhelp.models import MailState, Proposal, ProposalKind, ProposalStatus, Summary

NOW = datetime(2026, 9, 16, tzinfo=UTC)

def state(identifier, age=31, status=ProposalStatus.CREATED):
    simulated = status == ProposalStatus.SIMULATED
    proposal = Proposal(id="p" + identifier[0], version=2, kind=ProposalKind.TASK, responsibility="user", certainty="certain", classification="new",
                        title="Termin", evidence="Quelle", source_mail_id=identifier,
                        target="inbox", status=status,
                        external_id=None if simulated else "external-1",
                        external_link=None if simulated else "https://example.invalid/1",
                        simulation_notified=simulated)
    item = MailState(
        id=identifier, config_fingerprint="0" * 64,
        imap={"account_id": "1" * 24, "folder": "INBOX", "uidvalidity": 7, "uid": 9},
        created_at=NOW - timedelta(days=age + 1), updated_at=NOW - timedelta(days=age),
        mail={"text": "very private"}, relevance={"decision": "relevant", "topic_ids": ["x"], "reason": "private"},
        summary=Summary(sentences=["private one", "private two"]), proposals=[proposal],
        llm_call_ids=["call-secret"], validation_errors=[],
        write_attempts=[{"mail_id": identifier, "proposal_id": proposal.id, "proposal_version": 2,
                         "service": "todoist", "idempotency_key": "stable-key"}],
    )
    item.steps.completion = "completed"
    return item
