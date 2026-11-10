"""5.1 R6 in a real browser: start a re-analysis, see the comparison and adopt it."""
import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.config import ReanalysisSettings
from mailhelp.runtime.reanalysis_worker import ReanalysisWorker
from mailhelp.web.reanalysis_site import ReanalysisSite
from tests.fakes.reanalysis_fakes import DONE_STEPS, ReanalysisAnalyzer, ReanalysisEngine
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MAIL = mail_id(60)


@pytest.fixture
def worker(mailhelp):
    save_mail(mailhelp.store, 60, "Schule <schule@x.test>", "Klassenfahrt", [
        proposal(60, "alt", title="Elternabend vorbereiten")], text="Bitte das Formular abgeben.", steps=DONE_STEPS)
    sent = []
    worker = ReanalysisWorker(mailhelp.store, ReanalysisSettings(), ReanalysisEngine(
        mailhelp.store, ReanalysisAnalyzer("Formular abgeben"), 60), _Logger(), lambda account: None, sent.append,
        lambda actor: mailhelp.auth.active(actor.removeprefix("web:")))
    ReanalysisSite(mailhelp.site, worker)
    worker.sent = sent
    return worker


class _Logger:
    def event(self, *args, **fields):
        pass


def test_a_missed_task_is_found_compared_and_adopted_unconfirmed(page, mailhelp, worker):
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{MAIL}")
    section = page.get_by_role("region", name="Aufgabe oder Termin übersehen?")
    expect(section).to_contain_text("höchstens 5 kostenpflichtige Modellaufrufe")
    section.get_by_label("Hinweis für die Analyse (optional)").fill("Bitte die Abgabefrist prüfen")
    assert audit(page, "reanalysis-offer-" + page.device, page.mobile) == []
    section.get_by_role("button", name="Erneut analysieren").click()
    expect(section).to_contain_text("Wartet auf den Start.")
    assert worker.run_once()
    page.reload()
    expect(section).to_contain_text("Formular abgeben")
    expect(section).to_contain_text("Neu – wird als unbestätigter Vorschlag übernommen")
    expect(section).to_contain_text("Nicht mehr erkannt – bleibt erhalten")
    assert audit(page, "reanalysis-compare-" + page.device, page.mobile) == []
    section.get_by_role("button", name="Ergebnis übernehmen").click()
    expect(section).to_contain_text("Die Übernahme wird ausgeführt")
    assert worker.run_once()
    page.reload()
    expect(section).to_contain_text("Übernommen. Die Vorschläge warten auf deine Bestätigung.")
    assert [item.title for item in worker.sent] == ["Formular abgeben"]
    assert mailhelp.writer.created == []
    assert page.errors == []


def test_the_re_analysis_needs_no_javascript(browser, mailhelp, worker):
    context = browser.new_context(java_script_enabled=False, viewport={"width": 320, "height": 640})
    try:
        page = context.new_page()
        sign_in(page, mailhelp)
        page.goto(f"{mailhelp.url}/mail/{MAIL}")
        page.get_by_role("button", name="Erneut analysieren").click()
        expect(page.locator("section.reanalysis")).to_contain_text("Wartet auf den Start.")
        page.get_by_role("button", name="Nachanalyse abbrechen").click()
        expect(page.locator("section.reanalysis")).to_contain_text("Abgebrochen.")
    finally:
        context.close()
