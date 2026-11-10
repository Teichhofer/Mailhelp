"""5.1.1 (R2): the processing path is readable on every width and without JavaScript."""
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.domain.extraction import ActionRoute, Summary
from mailhelp.domain.relevance import Relevance
from tests.scenarios.web_scenario import mail_id, save_mail

DONE = dict(preparation="completed", relevance="completed", summary="completed", action_detection="completed",
            action_router="completed", task_extraction="skipped", event_extraction="skipped",
            normalization="completed", proposal_building="completed", duplicate_precheck="completed",
            completion="completed")


def seed(mailhelp):
    save_mail(mailhelp.store, 90, "Schule <schule@x.test>", "Elternabend am Donnerstag", [], text="Info",
              steps=DONE, relevance=Relevance(decision="relevant", topic_ids=[], reason="Schulinformation"),
              action_route=ActionRoute(action_state="none", task_count=0, event_count=0,
                                       reason="Die Mail informiert nur über einen Termin der Schule."),
              summary=Summary(sentences=["Elternabend"], deadlines=["Rückmeldung bis Freitag"]))


def test_the_processing_path_explains_a_mail_without_a_task(page, mailhelp):
    seed(mailhelp)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(90)}")
    path = page.get_by_role("region", name="So wurde diese Mail verarbeitet")
    expect(path).to_be_visible()
    expect(path.locator("ol > li")).to_have_count(5)
    expect(path.locator(".path-result")).to_contain_text("Keine Aktion erkannt.")
    expect(path.locator(".model-reason").last).to_contain_text("Modellbewertung, keine geprüfte Tatsache")
    # 5.1.4: a hint names its evidence and stays readable on every width.
    expect(path.locator(".path-hints li")).to_have_count(1)
    expect(path.locator(".path-hints li")).to_contain_text("Beleg: Zusammenfassung: Rückmeldung bis Freitag")
    box = path.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= page.viewport_size["width"] + 1
    assert audit(page, "processing-path-" + page.device, page.mobile) == []
    assert page.errors == []


def test_the_processing_path_needs_no_javascript(browser, mailhelp):
    seed(mailhelp)
    context = browser.new_context(java_script_enabled=False, viewport={"width": 320, "height": 640})
    try:
        page = context.new_page()
        sign_in(page, mailhelp)
        page.goto(f"{mailhelp.url}/mail/{mail_id(90)}")
        path = page.locator("section.processing-path")
        expect(path).to_contain_text("Als relevant eingestuft.")
        expect(path).to_contain_text("Keine Aufgabe und kein Termin erkannt")
    finally:
        context.close()
