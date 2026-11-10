"""5.1 R6: "Aufgabe oder Termin übersehen?" – start, progress, comparison and checked adoption."""
import json

import pytest

from mailhelp.config import ReanalysisSettings
from mailhelp.domain.mail import MailState
from mailhelp.domain.reanalysis import ReanalysisStatus
from mailhelp.runtime.reanalysis_worker import ReanalysisWorker
from mailhelp.web.reanalysis_site import ReanalysisSite
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.reanalysis_fakes import DONE_STEPS, ReanalysisAnalyzer, ReanalysisEngine
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MAIL = mail_id(40)
PATH = f"/mail/{MAIL}"


@pytest.fixture
def setup(web):
    save_mail(web.store, 40, "Schule <schule@example.test>", "Klassenfahrt", [
        proposal(40, "alt", title="Elternabend vorbereiten")], text="Bitte das Formular abgeben.", steps=DONE_STEPS)
    analyzer, sent, authorized = ReanalysisAnalyzer("Formular abgeben"), [], {"ok": True}
    worker = ReanalysisWorker(web.store, ReanalysisSettings(max_jobs_per_day=2), ReanalysisEngine(
        web.store, analyzer, 40), RecordingLogger(), lambda account: None, sent.append,
        lambda actor: authorized["ok"] and web.auth.active(actor.removeprefix("web:")))
    ReanalysisSite(web.site, worker)
    return web, worker, sent, authorized


def page(web):
    html = web.browser.request("GET", PATH).body.decode()
    start = html.index('<section class="card reanalysis"')
    return html[start:html.index("</section>", start)]


def start(web, hint="Bitte die Rückmeldefrist prüfen"):
    form = web.form(PATH, action=f"{PATH}/nachanalyse")
    return web.browser.request("POST", f"{PATH}/nachanalyse", {**form, "hint": hint})


def test_the_offer_names_mail_round_budget_and_the_daily_limit(setup):
    web, worker, _, _ = setup
    html = page(web)
    assert "Aufgabe oder Termin übersehen?" in html and "Analyserunde 1" in html
    assert "höchstens 5 kostenpflichtige Modellaufrufe; heute noch 2 von 2 Nachanalysen" in html
    assert "nichts wird automatisch angelegt" in html and '<textarea id="nachanalyse-hinweis" name="hint"' in html
    worker.jobs.settings = ReanalysisSettings(enabled=False)
    assert "ausgeschaltet" in page(web) and "Erneut analysieren" not in page(web)


def test_start_runs_in_the_background_and_adoption_needs_its_own_click(setup):
    web, worker, sent, _ = setup
    response = start(web)
    assert (response.status, response.headers["Location"]) == (303, f"{PATH}#nachanalyse")
    job = worker.jobs.for_mail(MAIL)[0]
    assert (job.status, job.hint, job.actor.startswith("web:")) == (ReanalysisStatus.QUEUED, "Bitte die "
                                                                    "Rückmeldefrist prüfen", True)
    html = page(web)
    assert "Wartet auf den Start." in html and "Nachanalyse abbrechen" in html and "Erneut analysieren" not in html
    assert worker.run_once() is True and worker.run_once() is False
    html = page(web)
    assert "Abgeschlossen." in html and "2 von 5 Modellaufrufen" in html
    assert "<strong>Formular abgeben</strong> · Neu – wird als unbestätigter Vorschlag übernommen" in html
    assert "<strong>Elternabend vorbereiten</strong> · Nicht mehr erkannt – bleibt erhalten" in html
    assert "Die Übernahme legt nichts an." in html
    # Nothing is adopted until the user asks; the mail still has its one proposal.
    assert [item.id for item in web.store.load_model(f"mail-{MAIL}", MailState).proposals] == ["alt"]
    form = web.form(PATH, action=f"{PATH}/nachanalyse/{job.id}/uebernehmen")
    assert json.loads(form["versions"]) == {"alt": 1} and form["round"] == "1"
    assert web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen", form).status == 303
    assert "Die Übernahme wird ausgeführt" in page(web)
    # A repeated click changes nothing; the background service adopts once.
    assert web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen", form).status == 303
    assert worker.run_once() is True and worker.run_once() is False
    state = web.store.load_model(f"mail-{MAIL}", MailState)
    assert [item.title for item in state.proposals] == ["Elternabend vorbereiten", "Formular abgeben"]
    assert state.proposals[1].status == "pending_confirmation" and [item.title for item in sent] == ["Formular abgeben"]
    assert "Übernommen. Die Vorschläge warten auf deine Bestätigung." in page(web)
    assert web.writer.created == 0


def test_a_result_without_news_offers_nothing_to_adopt_and_a_new_start(setup):
    web, worker, _, _ = setup
    worker.engine.analyzer.titles = ()
    start(web)
    worker.run_once()
    html = page(web)
    assert "es gibt nichts zu übernehmen" in html and "uebernehmen" not in html and "Erneut analysieren" in html


def test_cancel_failure_and_session_end_are_shown(setup):
    web, worker, _, authorized = setup
    start(web)
    job = worker.jobs.for_mail(MAIL)[0]
    form = web.form(PATH, action=f"{PATH}/nachanalyse/{job.id}/abbrechen")
    assert web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/abbrechen", form).status == 303
    assert "Abgebrochen." in page(web) and "Erneut analysieren" in page(web)
    authorized["ok"] = False
    start(web)
    worker.run_once()
    assert "Fehlgeschlagen. Die Sitzung, die die Nachanalyse gestartet hat, wurde beendet." in page(web)


def test_an_adoption_by_an_ended_session_or_a_stale_page_is_refused_and_shown(setup):
    web, worker, sent, authorized = setup
    start(web)
    worker.run_once()
    job = worker.jobs.for_mail(MAIL)[0]
    form = web.form(PATH, action=f"{PATH}/nachanalyse/{job.id}/uebernehmen")
    authorized["ok"] = False
    web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen", form)
    worker.run_once()
    assert "Die Sitzung wurde inzwischen beendet." in page(web) and sent == []
    authorized["ok"] = True
    stale = {**form, "versions": json.dumps({"alt": 7})}
    web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen", stale)
    worker.run_once()
    html = page(web)
    assert "Die Mail wurde inzwischen erneut ausgewertet." in html and sent == []
    assert "Erneut analysieren" in html


@pytest.mark.parametrize(("change", "status", "text"), [
    ({"round": "2"}, 409, "inzwischen erneut ausgewertet"),
    ({"round": "x"}, 409, "Formular ist unvollständig"),
])
def test_a_stale_or_broken_start_is_refused(setup, change, status, text):
    web, worker, _, _ = setup
    form = {**web.form(PATH, action=f"{PATH}/nachanalyse"), **change}
    response = web.browser.request("POST", f"{PATH}/nachanalyse", form)
    assert response.status == status and text in response.body.decode() and worker.jobs.all() == []


def test_forms_of_other_mails_unknown_jobs_and_broken_versions_are_refused(setup):
    web, worker, _, _ = setup
    start(web)
    worker.run_once()
    job = worker.jobs.for_mail(MAIL)[0]
    form = web.form(PATH, action=f"{PATH}/nachanalyse/{job.id}/uebernehmen")
    other = f"/mail/{mail_id(41)}"
    for path in (f"{other}/nachanalyse", f"{other}/nachanalyse/{job.id}/uebernehmen",
                 f"{other}/nachanalyse/{job.id}/abbrechen", f"{PATH}/nachanalyse/{'0' * 32}/uebernehmen"):
        assert web.browser.request("POST", path, form).status == 409
    for versions in ("[]", '{"alt": "1"}', "kaputt"):
        assert web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen",
                                   {**form, "versions": versions}).status == 409
    assert web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen",
                               {key: value for key, value in form.items() if key != "round"}).status == 409
    queued_form = dict(form)
    worker.jobs.save(job.model_copy(update={"status": ReanalysisStatus.CANCELLED}))
    response = web.browser.request("POST", f"{PATH}/nachanalyse/{job.id}/uebernehmen", queued_form)
    assert response.status == 409 and "nicht abgeschlossen" in response.body.decode()
    assert worker.jobs.get(job.id).adoption_round is None


def test_without_csrf_or_session_nothing_starts(setup):
    web, worker, _, _ = setup
    form = web.form(PATH, action=f"{PATH}/nachanalyse")
    assert web.browser.request("POST", f"{PATH}/nachanalyse", {**form, "csrf": "falsch"}).status == 403
    web.browser.cookies.clear()
    assert web.browser.request("POST", f"{PATH}/nachanalyse", form).status in {303, 401, 403}
    assert worker.jobs.all() == []


def test_the_daily_limit_and_unfinished_mails(setup):
    web, worker, _, _ = setup
    for _ in range(2):
        start(web)
        job = worker.jobs.for_mail(MAIL)[-1]
        worker.jobs.cancel(job.id)
    assert "Tageslimit erreicht" in page(web)
    response = start(web)
    assert response.status == 409 and "Tageslimit" in response.body.decode()
    save_mail(web.store, 41, "Schule <schule@example.test>", "Neu", [], text="x",
              steps={**DONE_STEPS, "completion": "pending"})
    html = web.browser.request("GET", f"/mail/{mail_id(41)}").body.decode()
    assert "Aufgabe oder Termin übersehen?" not in html


def test_a_completed_job_whose_comparison_vanished_shows_its_status_only(setup, monkeypatch):
    web, worker, _, _ = setup
    start(web)
    worker.run_once()
    monkeypatch.setattr(worker.adoption, "comparison", lambda job_id: None)
    html = page(web)
    assert "Abgeschlossen." in html and "Vorher und nachher" not in html and "Erneut analysieren" in html
