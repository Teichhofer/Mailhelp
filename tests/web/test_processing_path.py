"""5.1.1 (R2): the mail page explains how the mail was processed, from stored results only."""
from mailhelp.domain.extraction import ActionRoute
from mailhelp.domain.processing import ProcessingError
from mailhelp.domain.relevance import Relevance
from mailhelp.review.archive import AnalysisSnapshot
from tests.scenarios.web_scenario import NOW, mail_id, save_mail

DONE = dict(preparation="completed", relevance="completed", summary="completed", action_detection="completed",
            action_router="completed", task_extraction="completed", event_extraction="completed",
            normalization="completed", proposal_building="completed", duplicate_precheck="completed",
            completion="completed")


def section(web, number):
    page = web.browser.request("GET", f"/mail/{mail_id(number)}").body.decode()
    start = page.index('<section class="card processing-path"')
    return page[start:page.index("</section>", start)]


def test_a_mail_without_a_task_shows_the_stored_reason_and_round(web):
    save_mail(web.store, 80, "Schule <schule@example.test>", "Elternabend", [], text="Info",
              steps={**DONE, "task_extraction": "skipped", "event_extraction": "skipped"}, analysis_round=2,
              relevance=Relevance(decision="relevant", topic_ids=["schule"], reason="Schulthema <b>laut</b> Modell"),
              action_route=ActionRoute(action_state="none", task_count=0, event_count=0,
                                       reason="Reine Information"),
              )
    web.store.save(f"analysis-{mail_id(80)}", AnalysisSnapshot(mail_id=mail_id(80), topics={"schule": "Schule"})
                   .model_dump(mode="json"))
    html = section(web, 80)
    assert '<h2 id="verarbeitung-titel">So wurde diese Mail verarbeitet</h2>' in html
    assert "Analyserunde 2 · aus gespeicherten Ergebnissen, ohne erneute Modellabfrage" in html
    assert html.count('<li class="path-step outcome-done">') == 4
    # The model's reason is labelled as its assessment and escaped like any untrusted text.
    assert ("Modellbewertung, keine geprüfte Tatsache:</span> „Schulthema &lt;b&gt;laut&lt;/b&gt; Modell“"
            in html)
    assert "<p>Themen: Schule</p>" in html and "Reine Information" in html
    assert '<span class="badge ">Ausgelassen</span>' in html  # extraction was not needed
    assert '<div class="path-step path-result outcome-done">' in html and "Keine Aktion erkannt." in html


def test_retention_and_errors_are_named_and_never_reported_as_success(web):
    save_mail(web.store, 81, "Verein <verein@example.test>", "Unterlagen", [], steps=DONE)
    html = section(web, 81)
    assert "Der Mailinhalt wurde nach der Aufbewahrungsregel entfernt." in html
    assert '<span class="badge warn">Nicht mehr aufbewahrt</span>' in html
    assert "Keine Aktion erkannt." not in html
    error = ProcessingError(code="llm_rate_limited", stage="action_router", occurred_at=NOW, retryable=True)
    save_mail(web.store, 82, "Verein <verein@example.test>", "Unterlagen", [], text="x",
              steps={**DONE, "action_router": "failed"}, error=error)
    html = section(web, 82)
    assert '<li class="path-step outcome-failed">' in html and '<span class="badge danger">Fehlgeschlagen</span>' in html
    assert "Das Abfragelimit des Modellanbieters war erreicht. Ein neuer Versuch folgt automatisch." in html


def test_a_damaged_state_or_snapshot_is_reported_without_a_path(web):
    save_mail(web.store, 83, "Verein <verein@example.test>", "Unterlagen", [], text="x", steps=DONE)
    (web.store.directory / f"analysis-{mail_id(83)}.json").write_text("{kaputt", encoding="utf-8")
    page = web.browser.request("GET", f"/mail/{mail_id(83)}").body.decode()
    assert "Verarbeitungsweg beschädigt; bitte Protokolle prüfen." in page
    assert "So wurde diese Mail verarbeitet" not in page
    assert web.site.archive.mail_archive.processing_path(mail_id(84)) == ""
