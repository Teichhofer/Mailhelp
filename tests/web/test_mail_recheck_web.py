"""„Erneut prüfen“ for mails filed as irrelevant in the web (Planung 3.6, Schritt 0.3); synthetic data."""
from __future__ import annotations

from functools import partial

from shared_services import AnalyzerStub, Notify
from shared_web_actions import web as web
from web_scenario import mail_id, save_mail

from mailhelp.domain.processing import ProcessingSteps
from mailhelp.models import MailState
from mailhelp.processing.mail_recheck import RecheckOutcome, request_recheck
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus

FILED = mail_id(7)
IRRELEVANT_STEPS = ProcessingSteps(
    preparation="completed", relevance="completed", summary="skipped", summary_notification="skipped",
    action_detection="skipped", action_router="skipped", task_extraction="skipped", event_extraction="skipped",
    normalization="skipped", proposal_building="skipped", duplicate_precheck="skipped",
    proposal_notification="skipped", completion="completed")


def filed(web) -> None:
    """A mail filed as irrelevant whose relevance result retention already removed."""
    save_mail(web.store, 7, "Amt <amt@example.test>", "Anmeldebestätigung Onlinevortrag", steps=IRRELEVANT_STEPS)
    orchestrator = Orchestrator(AnalyzerStub("relevant"), web.store, Notify(), 1, [], 100_000)
    web.dialog.review.recheck = partial(request_recheck, orchestrator)


def state(web) -> MailState:
    loaded = web.store.load_model(f"mail-{FILED}", MailState)
    assert isinstance(loaded, MailState)
    return loaded


def test_a_mail_filed_as_irrelevant_can_be_rechecked_from_its_page_and_the_archive(web):
    filed(web)
    page = web.browser.request("GET", f"/mail/{FILED}").body.decode()
    assert "Aussortiert" in page and "Erneut prüfen" in page
    archive_form = web.form("/mails", kind="recheck_mail", mail_id=FILED)
    assert archive_form["version"] == "1"
    # Mails with proposals offer no re-check.
    assert 'value="recheck_mail"' not in web.browser.request("GET", f"/mail/{mail_id(1)}").body.decode()
    answer = web.submit(web.form(f"/mail/{FILED}", kind="recheck_mail", mail_id=FILED))
    assert answer.status == 303
    web.run()
    queued = state(web)
    assert (queued.analysis_round, queued.steps.completion, queued.steps.relevance) == (2, "pending", "pending")
    history = web.store.load(f"history-{FILED}")["events"]
    assert [(item["kind"], item["version"], item["status"], item["source"]) for item in history] == [
        ("recheck", 1, "irrelevant", "web")]
    # The result is shown on the mail page, which no longer offers the button.
    result = web.browser.request("GET", answer.headers["Location"])
    assert result.status == 303 and result.headers["Location"].startswith(f"/mail/{FILED}?ergebnis=")
    page = web.browser.request("GET", result.headers["Location"]).body.decode()
    assert "beim nächsten Abruf" in page and 'value="recheck_mail"' not in page
    # The form of the archive names the old round and is refused before it is queued.
    stale = web.submit(archive_form)
    assert stale.status == 409 and "bereits erneut geprüft" in stale.body.decode()


def test_a_recheck_is_checked_again_when_it_runs(web):
    filed(web)
    form = web.form(f"/mail/{FILED}", kind="recheck_mail", mail_id=FILED)
    # Another re-check ran in between: the queued command names an outdated round.
    web.submit(form)
    request_recheck(Orchestrator(AnalyzerStub("relevant"), web.store, Notify(), 1, [], 100_000), FILED)
    web.run()
    (entry,) = web.commands._entries()
    assert entry.result.status == ResultStatus.STALE and "inzwischen geändert" in entry.result.message
    assert state(web).analysis_round == 2 and web.store.load(f"history-{FILED}") is None


def test_a_recheck_needs_a_valid_session_when_it_runs(web):
    filed(web)
    web.submit(web.form(f"/mail/{FILED}", kind="recheck_mail", mail_id=FILED))
    web.auth.revoke_all()
    web.run()
    (entry,) = web.commands._entries()
    assert entry.result.status == ResultStatus.UNAUTHORIZED and state(web).analysis_round == 1


def test_a_recheck_without_the_service_is_refused(web):
    filed(web)
    web.dialog.review.recheck = None
    web.submit(web.form(f"/mail/{FILED}", kind="recheck_mail", mail_id=FILED))
    web.run()
    (entry,) = web.commands._entries()
    assert entry.result.status == ResultStatus.INVALID and "nicht verfügbar" in entry.result.message
    assert state(web).analysis_round == 1


def test_a_recheck_interrupted_by_a_restart_is_judged_from_the_state(web):
    filed(web)
    command = ReviewCommand(kind=CommandKind.RECHECK_MAIL, source=CommandSource.WEB, actor="web:x",
                            mail_id=FILED, version=1, idempotency_key="restart-1")
    assert web.dialog.review.reconcile(command).status == ResultStatus.FAILED
    assert web.dialog.review.recheck(FILED, 1) is RecheckOutcome.QUEUED
    assert web.dialog.review.reconcile(command).status == ResultStatus.DONE
    assert [item["kind"] for item in web.store.load(f"history-{FILED}")["events"]] == ["recheck"]
    web.store.save(f"mail-{FILED}", None)
    assert web.dialog.review.reconcile(command).status == ResultStatus.FAILED
