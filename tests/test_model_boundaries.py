"""Architecture checks for domain and persistence model boundaries."""
from mailhelp import models
from mailhelp.domain import duplicate, extraction, mail, processing, proposal, relevance, run, temporal
from mailhelp.persistence import schemas


def test_context_modules_and_legacy_facade_share_model_types():
    assert models.MailRunState is run.MailRunState
    assert models.Relevance is relevance.Relevance
    assert models.TemporalFact is temporal.TemporalFact
    assert models.ExtractedTask is extraction.ExtractedTask
    assert models.Proposal is proposal.Proposal
    assert models.ProcessingError is processing.ProcessingError
    assert models.DuplicateIndex is duplicate.DuplicateIndex
    assert models.MailState is mail.MailState


def test_persistence_boundary_is_explicit_and_preserves_json_schemas():
    expected = {
        "ActionLedger", "DuplicateIndex", "ImapCheckpoint", "IrrelevantSenders",
        "MailRunState", "MailState", "ProposalClarificationState", "RelevanceDialog",
        "TelegramDialogState", "TelegramOffset",
    }
    assert set(schemas.__all__) == expected
    assert all(getattr(schemas, name) is getattr(models, name) for name in expected)
