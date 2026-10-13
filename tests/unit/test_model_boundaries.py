"""Architecture checks for domain and persistence model boundaries."""
from mailhelp import models
from mailhelp.activity import models as activity_models
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
    assert models.DuplicateSource is proposal.DuplicateSource
    assert models.DuplicateMatchInfo is proposal.DuplicateMatchInfo
    assert models.ExtractedAttachment is extraction.ExtractedAttachment
    assert models.ParsedCalendarEvent is extraction.ParsedCalendarEvent


def test_persistence_boundary_is_explicit_and_preserves_json_schemas():
    expected = {
        "ActionLedger", "DuplicateIndex", "ImapCheckpoint", "IrrelevantSenders",
        "MailRunState", "MailState", "ProposalClarificationState", "RelevanceDialog",
        "TelegramDialogState", "TelegramOffset", "TelegramOutboxState",
    }
    # 2.2: activity reports are persisted as well; their models live in activity.models.
    assert set(schemas.__all__) == expected | {
        "ActivityReport", "ReportMail", "DiagnosticsState", "NotificationQueue", "SetupState"}
    assert all(getattr(schemas, name) is getattr(models, name) for name in expected)
    assert schemas.ActivityReport is activity_models.ActivityReport
    assert schemas.ReportMail is activity_models.ReportMail


def test_test_modules_share_helpers_only_through_fakes():
    # Planung 2.1, T1/T2: helpers live in tests/fakes and tests/scenarios, never in another test module.
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in [*root.joinpath("tests").rglob("test_*.py"), *root.joinpath("ui_tests").rglob("test_*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            offenders += [f"{path.name}: {name}" for name in names if name.split(".")[0].startswith("test_")]
    assert offenders == []
