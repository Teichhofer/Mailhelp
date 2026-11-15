"""Architecture checks for domain and persistence model boundaries."""
import importlib

import pytest

from mailhelp import domain
from mailhelp.activity import models as activity_models
from mailhelp.domain import duplicate, extraction, mail, processing, proposal, relevance, run, temporal
from mailhelp.persistence import schemas


def test_the_legacy_model_facade_is_gone():
    # 7.0.3 (R2): every caller imports from the context module that defines a model.
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mailhelp.models")
    assert run.MailRunState.__module__ == "mailhelp.domain.run"
    assert proposal.Proposal.__module__ == "mailhelp.domain.proposal"
    assert mail.MailState.__module__ == "mailhelp.domain.mail"
    defined = {relevance.Relevance: relevance, temporal.TemporalFact: temporal, extraction.ExtractedTask: extraction,
               processing.ProcessingError: processing, duplicate.DuplicateIndex: duplicate}
    assert all(model.__module__ == module.__name__ for model, module in defined.items())


def test_persistence_boundary_is_explicit_and_preserves_json_schemas():
    expected = {
        "ActionLedger", "DuplicateIndex", "ImapCheckpoint", "IrrelevantSenders",
        "MailRunState", "MailState", "ProposalClarificationState", "RelevanceDialog",
        "TelegramDialogState", "TelegramOffset", "TelegramOutboxState",
    }
    # 2.2: activity reports are persisted as well; their models live in activity.models.
    assert set(schemas.__all__) == expected | {
        "ActivityReport", "ReportMail", "DiagnosticsState", "NotificationQueue", "SetupState",
        "ProposalMatchCache", "ProposalMergeJournal", "ProposalRelation",
        "InitialDraft", "OAuthJobs", "PasswordState", "LearningJob", "ReloadState", "SeriesReceipt", "SeriesOffer",
        "IncomingRecord", "ReanalysisJob", "WriteVerification"}
    # 5.1.2 re-analysis jobs and 5.2.0 write verifications are stored files as well.
    from mailhelp.domain.reanalysis import ReanalysisJob
    from mailhelp.domain.verification import WriteVerification
    assert (schemas.ReanalysisJob, schemas.WriteVerification) == (ReanalysisJob, WriteVerification)
    from mailhelp.review.incoming import IncomingRecord
    assert schemas.IncomingRecord is IncomingRecord
    from mailhelp.review.series import SeriesReceipt
    from mailhelp.review.series_offers import SeriesOffer
    assert schemas.SeriesReceipt is SeriesReceipt and schemas.SeriesOffer is SeriesOffer
    assert all(getattr(schemas, name) is getattr(domain, name) for name in expected)
    assert schemas.ActivityReport is activity_models.ActivityReport
    assert schemas.ReportMail is activity_models.ReportMail
    from mailhelp.runtime.initial_setup import InitialDraft
    from mailhelp.runtime.oauth_web import OAuthJobs
    from mailhelp.runtime.web_password import PasswordState
    assert (schemas.InitialDraft, schemas.OAuthJobs, schemas.PasswordState)==(InitialDraft,OAuthJobs,PasswordState)


@pytest.mark.slow
def test_test_modules_share_helpers_only_through_fakes():
    # Planung 2.1, T1/T2: helpers live in tests/fakes and tests/scenarios, never in another test module.
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in [*root.joinpath("tests").rglob("test_*.py"), *root.joinpath("ui_tests").rglob("test_*.py")]:
        offenders += [f"{path.name}: {name}" for name in imported_modules(path.read_text(encoding="utf-8"))
                      if name.split(".")[-1].startswith("test_")]
    assert offenders == []


def imported_modules(source: str) -> list[str]:
    """Statically imported modules and string literals given to ``__import__``/``import_module``."""
    import ast
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and getattr(node.func, "id", getattr(node.func, "attr", None)) in {"__import__", "import_module"}):
            names.append(node.args[0].value)
    return names


def test_import_scan_sees_dynamic_imports_of_test_modules():
    source = ("import importlib\nfrom tests.fakes.shared_core import x\n"
              "__import__('test_web_auth')\nimportlib.import_module('tests.web.test_web_auth')\nprint('x')")
    assert imported_modules(source) == ["importlib", "tests.fakes.shared_core", "test_web_auth",
                                        "tests.web.test_web_auth"]


def test_helpers_are_imported_through_their_package_only():
    # Planung 4.1, Schritt 9.4: no sys.path hack, so a bare helper name no longer resolves.
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    helpers = {path.stem for folder in ("fakes", "scenarios")
               for path in root.joinpath("tests", folder).glob("*.py") if path.stem != "__init__"}
    offenders = []
    for path in [*root.joinpath("tests").rglob("*.py"), *root.joinpath("ui_tests").rglob("*.py")]:
        offenders += [f"{path.name}: {name}" for name in imported_modules(path.read_text(encoding="utf-8"))
                      if name.split(".")[0] in helpers]
    conftest = root.joinpath("tests", "conftest.py").read_text(encoding="utf-8")
    assert offenders == [] and "sys.path" not in conftest


# Planung 3.3, pillar 1: modules outside the Telegram package that may use it (channel integration).
TELEGRAM_CLIENTS = {"runtime/application.py", "runtime/composition.py", "processing/orchestrator.py", "review/service.py",
                    "runtime/service_coordinator.py"}


def telegram_importers() -> set[str]:
    import ast
    from pathlib import Path

    import mailhelp
    root = Path(mailhelp.__file__).parent
    found = set()
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("telegram/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            level = node.level if isinstance(node, ast.ImportFrom) else 0
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            if (level and module.split(".")[0] == "telegram") or module.startswith("mailhelp.telegram") or any(
                    name.startswith("mailhelp.telegram") for name in names):
                found.add(relative)
    return found


@pytest.mark.slow
def test_only_the_channel_integration_imports_telegram():
    """Domain, analysis, persistence and the remaining services stay free of the Telegram channel."""
    assert telegram_importers() == TELEGRAM_CLIENTS
