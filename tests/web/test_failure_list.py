"""7.3.1: failed mails show cause and actions in /mails?state=failed and return there after an action."""
from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingError, ProcessingErrorCode, ProcessingStage, ValidationIssue
from mailhelp.domain.retry import ProcessingRetry
from mailhelp.review.error_reporting import ADVICE, error_report, error_summary, retry_pending, retry_text
from tests.fakes.shared_web_actions import web as web
from tests.scenarios.web_scenario import mail_id

NOW = datetime(2026, 11, 9, 15, 15, 20, tzinfo=UTC)


def fail(web, number, *, attempts=5, abandoned=True, code="llm_schema_validation_exhausted",
         stage="action_router", retry=True):
    state = web.store.load_model("mail-" + mail_id(number), MailState)
    state.error = ProcessingError(code=code, stage=stage, occurred_at=NOW, retryable=True)
    state.processing_retry = (ProcessingRetry(fingerprint="f", attempts=attempts, first_failed_at=NOW,
                                              last_failed_at=NOW + timedelta(hours=2), abandoned=abandoned)
                              if retry else None)
    # A requested retry clears the counter and leaves its command key (see MailState.retry_requested).
    state.processing_operation = None if retry else "manual-retry-key"
    web.store.save("mail-" + mail_id(number), state.model_dump(mode="json"))
    return state


def test_a_failed_mail_shows_cause_stage_attempts_and_its_actions(web):
    fail(web, 7)
    html = web.browser.request("GET", "/mails?state=failed").body.decode()
    assert "Fehler: KI-Antwort wiederholt ungültig (Stufe: Aktionszuordnung, 5 Fehlversuche)" in html
    assert ">Erneut versuchen</button>" in html and ">Ignorieren</button>" in html
    assert f'href="/mail/{mail_id(7)}#fehlerbericht" data-error-report>Details</a>' in html
    assert 'name="zurueck" value="fehlerliste"' in html


@pytest.mark.parametrize(("kind", "status"), [("retry_mail", "retrying"), ("file_mail", "not_processed")])
def test_an_action_from_the_list_returns_to_the_list_with_its_result(web, kind, status):
    fail(web, 7)
    form = web.form("/mails?state=failed", kind=kind, mail_id=mail_id(7))
    queued = web.browser.request("POST", "/aktion", form)
    assert queued.status == 303 and queued.headers["Location"].endswith("?zurueck=fehlerliste")
    web.run()
    done = web.browser.request("GET", queued.headers["Location"])
    assert done.status == 303 and done.headers["Location"].startswith("/mails?state=failed&ergebnis=")
    page = web.browser.request("GET", done.headers["Location"]).body.decode()
    assert 'class="notice' in page
    state = web.store.load_model("mail-" + mail_id(7), MailState)
    if kind == "retry_mail":
        # Still counted as failed until processed, but marked and without a second retry button.
        assert state.processing_retry is None and "Erneuter Versuch angefordert" in page
        assert ">Erneut versuchen</button>" not in page
    else:
        assert state.processing_filed and f'href="/mail/{mail_id(7)}"' not in page


def test_an_action_from_the_mail_page_still_returns_to_the_mail(web):
    fail(web, 7)
    form = web.form("/mails?state=failed", kind="file_mail", mail_id=mail_id(7))
    form.pop("zurueck")
    queued = web.browser.request("POST", "/aktion", form)
    assert "zurueck" not in queued.headers["Location"]
    web.run()
    assert web.browser.request("GET", queued.headers["Location"]).headers["Location"].startswith(
        f"/mail/{mail_id(7)}?ergebnis=")


def test_a_mail_without_analysis_data_offers_only_ignoring(web, monkeypatch):
    fail(web, 7, code="analysis_data_removed")
    monkeypatch.setattr(MailState, "missing_analysis_steps", property(lambda self: ("analysis",)))
    html = web.browser.request("GET", "/mails?state=failed").body.decode()
    assert ">Ignorieren</button>" in html and ">Erneut versuchen</button>" not in html


def test_a_foreign_or_unknown_result_is_not_shown(web):
    fail(web, 7)
    for value in ("x" * 32, "nicht-hex", "a" * 32):
        page = web.browser.request("GET", f"/mails?state=failed&ergebnis={value}")
        assert page.status == 200 and 'class="notice' not in page.body.decode()


def test_summary_report_and_retry_texts():
    assert error_summary("invalid_json", "summary", 1) == \
        "Fehler: KI-Antwort war kein gültiges JSON (Stufe: Zusammenfassung, 1 Fehlversuch)"
    assert error_summary("unknown", "other", None) == "Fehler: unknown (Stufe: other)"
    assert set(ADVICE) == set(ProcessingErrorCode)
    state = MailState.model_construct(
        id="a" * 24, error=ProcessingError(code="internal_error", stage="relevance", occurred_at=NOW),
        processing_filed=False, processing_retry=ProcessingRetry(
            fingerprint="f", attempts=2, first_failed_at=NOW, last_failed_at=NOW + timedelta(minutes=5)),
        validation_errors=[ValidationIssue(stage=ProcessingStage.RELEVANCE, code="missing", path=["events", 0, "x"],
                                           occurred_at=NOW),
                           ValidationIssue(stage=ProcessingStage.RELEVANCE, code="other", path=[], occurred_at=NOW)],
        llm_call_ids=[f"call-{number}" for number in range(7)])
    report = error_report(state, "Betreff", "Europe/Berlin")
    assert report.stage_label == "Relevanzprüfung" and report.label == "Interner Fehler"
    assert report.first_failed == "09.11.2026, 16:15:20 Uhr" and report.attempts == "2/5"
    assert report.paths == ("events.0.x",) and report.call_ids == tuple(f"call-{n}" for n in range(2, 7))
    assert "versucht es weiter" in report.retry and not retry_pending(state)
    text = report.text()
    assert text.startswith("=== Mailhelp Fehlerbericht ===") and "Zeitpunkt: 2026-11-09T15:15:20Z" in text
    assert "Feldpfad: events.0.x" in text and "LLM-Calls: call-2" in text
    state.processing_retry.abandoned = True
    assert "pausiert" in retry_text(state) and error_report(state, "B", "UTC").attempts == "5/5 (pausiert)".replace(
        "5/5", "2/5")
    state.processing_retry = None
    assert not retry_pending(state)  # an old error without counter or command is no request
    state.processing_operation = "manual-retry-key"
    pending = error_report(state, "B", "UTC")
    assert pending.attempts == "angefordert" and pending.first_failed == "–" and retry_pending(state)
    assert "LLM-Calls" in pending.text()
    state.llm_call_ids, state.validation_errors = [], []
    assert "LLM-Calls" not in error_report(state, "B", "UTC").text()
    state.processing_filed = True
    assert error_report(state, "B", "UTC") is None and retry_text(state) == "Keine automatischen Versuche."
    state.processing_filed, state.error = False, None
    assert error_report(state, "B", "UTC") is None


def test_the_mail_page_shows_the_error_card_at_the_top_with_the_full_report(web):
    fail(web, 7)
    page = web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    card = page[page.index('id="fehlerbericht"'):]
    assert page.index('id="fehlerbericht"') < page.index('class="mail-text"') if 'class="mail-text"' in page else True
    assert "Verarbeitungsfehler</h2>" in card and "Aktionszuordnung" in card
    assert "Später erneut versuchen" in card and "5 von 5 automatischen Versuchen" in card
    assert "Fehlerbericht anzeigen</summary>" in card and "=== Mailhelp Fehlerbericht ===" in card
    assert "data-copy-report" in card and ">Erneut versuchen</button>" in card and ">Ignorieren</button>" in card
    assert "Ursache und Aktionen stehen oben im Fehlerbericht" in page
    # The form posts from the mail page and leads back to it.
    form = web.form(f"/mail/{mail_id(7)}", kind="file_mail", mail_id=mail_id(7))
    assert "zurueck" not in form


def test_a_requested_retry_offers_no_second_retry_and_a_filed_mail_no_card(web):
    fail(web, 7, retry=False)
    page = web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    assert "Erneuter Versuch angefordert" in page and ">Erneut versuchen</button>" not in page
    state = web.store.load_model("mail-" + mail_id(7), MailState)
    state.processing_filed = True
    web.store.save("mail-" + mail_id(7), state.model_dump(mode="json"))
    assert 'id="fehlerbericht"' not in web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    assert 'id="fehlerbericht"' not in web.browser.request("GET", f"/mail/{mail_id(1)}").body.decode()


def test_the_card_names_validation_paths_and_model_calls(web):
    state = fail(web, 7)
    state.validation_errors = [ValidationIssue(stage=ProcessingStage.ACTION_ROUTER, code="missing",
                                               path=["events", 0, "time"], occurred_at=NOW)]
    state.llm_call_ids = ["call-1"]
    web.store.save("mail-" + mail_id(7), state.model_dump(mode="json"))
    page = web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    assert "<dt>Feldpfade</dt><dd>events.0.time</dd>" in page and "<dt>Modellaufrufe</dt><dd>call-1</dd>" in page


def test_a_damaged_state_never_breaks_the_error_card(web, monkeypatch):
    from mailhelp.persistence.storage import CorruptState
    fail(web, 7)
    original = web.store.peek_model

    def damaged(name, model, *args, **kwargs):
        if name == "mail-" + mail_id(7) and model is MailState:
            raise CorruptState(name)
        return original(name, model, *args, **kwargs)
    monkeypatch.setattr(web.store, "peek_model", damaged)
    # The mail view itself answers 404 then; the card on its own must not fail either.
    assert web.site.archive.mail_archive.failure_card(mail_id(7), "Betreff", "csrf") == ""


def test_an_old_error_without_counter_or_command_still_offers_a_retry(web):
    state = fail(web, 7, retry=False)
    state.processing_operation = None
    web.store.save("mail-" + mail_id(7), state.model_dump(mode="json"))
    assert ">Erneut versuchen</button>" in web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    assert not state.retry_requested
    state.error = state.error.model_copy(update={"code": "llm_rate_limited"})
    assert state.retry_requested  # waits for the rate limit by itself


def test_an_unknown_mail_has_no_error_card(web):
    assert web.site.archive.mail_archive.failure_card("f" * 24, "Betreff", "csrf") == ""
